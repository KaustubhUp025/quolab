"""Vector stores.

The pipeline depends only on the :class:`VectorStore` interface.

- :class:`SqliteVecStore` — zero-infra default. Stores vectors in SQLite and ranks
  with a NumPy cosine scan over the rows for one ``(project_id, ref)``. Always works
  (no native extension required); fine for repo-sized corpora.
- :class:`PgVectorStore` — Postgres + pgvector for production / multi-tenant use.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Protocol

import numpy as np
import structlog

from quolab.config import Settings
from quolab.models import Chunk, SearchResult

log = structlog.get_logger(__name__)


def _cosine_topk(
    query: np.ndarray, matrix: np.ndarray, k: int
) -> list[tuple[int, float]]:
    """Return (row_index, score) for the top-k rows by cosine similarity."""
    if matrix.shape[0] == 0:
        return []
    qn = query / (np.linalg.norm(query) + 1e-12)
    mn = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-12)
    scores = mn @ qn
    k = min(k, scores.shape[0])
    idx = np.argpartition(-scores, k - 1)[:k]
    idx = idx[np.argsort(-scores[idx])]
    return [(int(i), float(scores[i])) for i in idx]


class VectorStore(Protocol):
    def has_index(self, project_id: str, ref: str) -> bool: ...
    def clear(self, project_id: str, ref: str) -> None: ...
    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...
    def search(
        self, project_id: str, ref: str, query_vec: list[float], k: int
    ) -> list[SearchResult]: ...


class SqliteVecStore:
    """SQLite-backed store with a NumPy cosine scan per project/ref."""

    def __init__(self, db_path: str) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                project_id TEXT NOT NULL,
                ref        TEXT NOT NULL,
                path       TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                end_line   INTEGER NOT NULL,
                symbol     TEXT NOT NULL,
                text       TEXT NOT NULL,
                vector     TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_proj_ref ON chunks(project_id, ref)"
        )
        self._conn.commit()

    def has_index(self, project_id: str, ref: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM chunks WHERE project_id=? AND ref=? LIMIT 1", (project_id, ref)
        )
        return cur.fetchone() is not None

    def clear(self, project_id: str, ref: str) -> None:
        self._conn.execute(
            "DELETE FROM chunks WHERE project_id=? AND ref=?", (project_id, ref)
        )
        self._conn.commit()

    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        rows = [
            (
                c.project_id, c.ref, c.path, c.start_line, c.end_line, c.symbol, c.text,
                json.dumps(v),
            )
            for c, v in zip(chunks, vectors, strict=True)
        ]
        self._conn.executemany(
            "INSERT INTO chunks(project_id,ref,path,start_line,end_line,symbol,text,vector)"
            " VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
        self._conn.commit()

    def search(
        self, project_id: str, ref: str, query_vec: list[float], k: int
    ) -> list[SearchResult]:
        cur = self._conn.execute(
            "SELECT path,start_line,end_line,symbol,text,vector FROM chunks"
            " WHERE project_id=? AND ref=?",
            (project_id, ref),
        )
        rows = cur.fetchall()
        if not rows:
            return []
        matrix = np.array([json.loads(r[5]) for r in rows], dtype=np.float32)
        ranked = _cosine_topk(np.array(query_vec, dtype=np.float32), matrix, k)
        out: list[SearchResult] = []
        for i, score in ranked:
            path, start, end, symbol, text, _ = rows[i]
            out.append(
                SearchResult(
                    chunk=Chunk(project_id, ref, path, start, end, symbol, text),
                    score=score,
                )
            )
        return out


class PgVectorStore:
    """Postgres + pgvector store (production)."""

    def __init__(self, dsn: str, dim: int) -> None:
        if not dsn:
            raise ValueError("QUOLAB_PG_DSN is required for the pgvector store")
        try:
            import psycopg
            from pgvector.psycopg import register_vector
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("pgvector store needs the 'pg' extra: pip install 'quolab[pg]'") from exc
        self._psycopg = psycopg
        self._dim = dim
        self._conn = psycopg.connect(dsn, autocommit=True)
        self._conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(self._conn)
        self._conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS chunks (
                id BIGSERIAL PRIMARY KEY,
                project_id TEXT, ref TEXT, path TEXT,
                start_line INT, end_line INT, symbol TEXT, text TEXT,
                vector vector({dim})
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pg_proj_ref ON chunks(project_id, ref)"
        )

    def has_index(self, project_id: str, ref: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM chunks WHERE project_id=%s AND ref=%s LIMIT 1", (project_id, ref)
        )
        return cur.fetchone() is not None

    def clear(self, project_id: str, ref: str) -> None:
        self._conn.execute(
            "DELETE FROM chunks WHERE project_id=%s AND ref=%s", (project_id, ref)
        )

    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        import numpy as _np

        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunks(project_id,ref,path,start_line,end_line,symbol,text,vector)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                [
                    (c.project_id, c.ref, c.path, c.start_line, c.end_line, c.symbol, c.text,
                     _np.array(v, dtype=_np.float32))
                    for c, v in zip(chunks, vectors, strict=True)
                ],
            )

    def search(
        self, project_id: str, ref: str, query_vec: list[float], k: int
    ) -> list[SearchResult]:
        import numpy as _np

        cur = self._conn.execute(
            "SELECT path,start_line,end_line,symbol,text, 1 - (vector <=> %s) AS score"
            " FROM chunks WHERE project_id=%s AND ref=%s ORDER BY vector <=> %s LIMIT %s",
            (_np.array(query_vec, dtype=_np.float32), project_id, ref,
             _np.array(query_vec, dtype=_np.float32), k),
        )
        return [
            SearchResult(
                chunk=Chunk(project_id, ref, r[0], r[1], r[2], r[3], r[4]),
                score=float(r[5]),
            )
            for r in cur.fetchall()
        ]


def make_store(settings: Settings) -> VectorStore:
    if settings.store == "sqlite":
        log.info("store_selected", backend="sqlite", path=settings.sqlite_path)
        return SqliteVecStore(settings.sqlite_path)
    if settings.store == "pgvector":
        log.info("store_selected", backend="pgvector")
        return PgVectorStore(settings.pg_dsn, settings.embed_dim)
    raise ValueError(f"Unknown store: {settings.store!r} (expected 'sqlite' or 'pgvector')")
