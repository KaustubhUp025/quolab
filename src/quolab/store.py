"""Vector stores.

The pipeline depends only on the :class:`VectorStore` interface.

- :class:`SqliteVecStore` — zero-infra default. Stores vectors in SQLite and ranks
  with a NumPy cosine scan over the rows for one ``(project_id, ref)``. Always works
  (no native extension required); fine for repo-sized corpora.
- :class:`PgVectorStore` — Postgres + pgvector for production / multi-tenant use.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Protocol

import numpy as np
import structlog

from quolab.config import Settings
from quolab.models import Chunk, SearchResult

log = structlog.get_logger(__name__)


_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")


def _fts_match_query(query: str) -> str:
    """Turn a free-text query into a safe FTS5 MATCH expression (OR of terms).

    Splits camelCase/underscore identifiers into their parts so 'acquireLock' and
    'acquire_lock' both match 'acquire' / 'lock'. Returns '' when there's nothing usable.
    """
    terms: set[str] = set()
    for tok in _WORD.findall(query):
        terms.add(tok.lower())
        # split snake_case and camelCase into sub-terms
        for part in re.split(r"_|(?<=[a-z0-9])(?=[A-Z])", tok):
            if len(part) > 1:
                terms.add(part.lower())
    return " OR ".join(f'"{t}"' for t in sorted(terms))


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
    def lexical_search(
        self, project_id: str, ref: str, query: str, k: int
    ) -> list[SearchResult]: ...
    def get_file_shas(self, project_id: str, ref: str) -> dict[str, str]: ...
    def set_file_shas(self, project_id: str, ref: str, mapping: dict[str, str]) -> None: ...
    def delete_paths(self, project_id: str, ref: str, paths: list[str]) -> None: ...
    def forget_files(self, project_id: str, ref: str, paths: list[str]) -> None: ...
    def get_commit(self, project_id: str, ref: str) -> str | None: ...
    def set_commit(self, project_id: str, ref: str, commit_sha: str) -> None: ...
    def counts(self, project_id: str, ref: str) -> tuple[int, int]: ...


class SqliteVecStore:
    """SQLite-backed store with a NumPy cosine scan per project/ref."""

    def __init__(self, db_path: str) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
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
        # incremental-indexing bookkeeping
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS files ("
            "project_id TEXT, ref TEXT, path TEXT, sha TEXT, "
            "PRIMARY KEY(project_id, ref, path))"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS index_meta ("
            "project_id TEXT, ref TEXT, commit_sha TEXT, "
            "PRIMARY KEY(project_id, ref))"
        )
        self._has_fts = self._init_fts()
        self._conn.commit()

    def _init_fts(self) -> bool:
        """Create an FTS5 lexical index kept in sync via triggers.

        Returns False (and falls back to a LIKE scan) if FTS5 isn't compiled in.
        """
        try:
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts "
                "USING fts5(text, symbol, content='chunks', content_rowid='id')"
            )
            self._conn.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
                  INSERT INTO chunks_fts(rowid, text, symbol) VALUES (new.id, new.text, new.symbol);
                END;
                CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
                  INSERT INTO chunks_fts(chunks_fts, rowid, text, symbol)
                  VALUES ('delete', old.id, old.text, old.symbol);
                END;
                """
            )
            return True
        except sqlite3.OperationalError as exc:  # pragma: no cover - depends on build
            log.warning("fts5_unavailable_lexical_fallback", error=str(exc)[:120])
            return False

    def has_index(self, project_id: str, ref: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM chunks WHERE project_id=? AND ref=? LIMIT 1", (project_id, ref)
        )
        return cur.fetchone() is not None

    def clear(self, project_id: str, ref: str) -> None:
        for tbl in ("chunks", "files", "index_meta"):
            self._conn.execute(
                f"DELETE FROM {tbl} WHERE project_id=? AND ref=?", (project_id, ref)
            )
        self._conn.commit()

    # --- incremental indexing bookkeeping ---

    def get_file_shas(self, project_id: str, ref: str) -> dict[str, str]:
        cur = self._conn.execute(
            "SELECT path, sha FROM files WHERE project_id=? AND ref=?", (project_id, ref)
        )
        return {p: s for p, s in cur.fetchall()}

    def set_file_shas(self, project_id: str, ref: str, mapping: dict[str, str]) -> None:
        self._conn.executemany(
            "INSERT OR REPLACE INTO files(project_id, ref, path, sha) VALUES (?,?,?,?)",
            [(project_id, ref, p, s) for p, s in mapping.items()],
        )
        self._conn.commit()

    def delete_paths(self, project_id: str, ref: str, paths: list[str]) -> None:
        """Delete the chunks for the given file paths (FTS stays in sync via trigger)."""
        self._conn.executemany(
            "DELETE FROM chunks WHERE project_id=? AND ref=? AND path=?",
            [(project_id, ref, p) for p in paths],
        )
        self._conn.commit()

    def forget_files(self, project_id: str, ref: str, paths: list[str]) -> None:
        self._conn.executemany(
            "DELETE FROM files WHERE project_id=? AND ref=? AND path=?",
            [(project_id, ref, p) for p in paths],
        )
        self._conn.commit()

    def get_commit(self, project_id: str, ref: str) -> str | None:
        cur = self._conn.execute(
            "SELECT commit_sha FROM index_meta WHERE project_id=? AND ref=?", (project_id, ref)
        )
        row = cur.fetchone()
        return row[0] if row else None

    def set_commit(self, project_id: str, ref: str, commit_sha: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO index_meta(project_id, ref, commit_sha) VALUES (?,?,?)",
            (project_id, ref, commit_sha),
        )
        self._conn.commit()

    def counts(self, project_id: str, ref: str) -> tuple[int, int]:
        c = self._conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE project_id=? AND ref=?", (project_id, ref)
        ).fetchone()[0]
        f = self._conn.execute(
            "SELECT COUNT(*) FROM files WHERE project_id=? AND ref=?", (project_id, ref)
        ).fetchone()[0]
        return int(c), int(f)

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

    def lexical_search(
        self, project_id: str, ref: str, query: str, k: int
    ) -> list[SearchResult]:
        """BM25-ranked full-text search over chunk text (FTS5), best-first."""
        if self._has_fts:
            match = _fts_match_query(query)
            if not match:
                return []
            cur = self._conn.execute(
                "SELECT c.path,c.start_line,c.end_line,c.symbol,c.text, bm25(chunks_fts) AS rank "
                "FROM chunks_fts f JOIN chunks c ON c.id = f.rowid "
                "WHERE chunks_fts MATCH ? AND c.project_id=? AND c.ref=? "
                "ORDER BY rank LIMIT ?",
                (match, project_id, ref, k),
            )
            rows = cur.fetchall()
            # bm25 is lower-is-better; expose a higher-is-better score for fusion display.
            return [
                SearchResult(
                    chunk=Chunk(project_id, ref, r[0], r[1], r[2], r[3], r[4]),
                    score=-float(r[5]),
                )
                for r in rows
            ]
        # FTS5 absent: naive LIKE scan over the first query term.
        terms = _WORD.findall(query.lower())
        if not terms:
            return []
        like = f"%{terms[0]}%"
        cur = self._conn.execute(
            "SELECT path,start_line,end_line,symbol,text FROM chunks "
            "WHERE project_id=? AND ref=? AND lower(text) LIKE ? LIMIT ?",
            (project_id, ref, like, k),
        )
        return [
            SearchResult(chunk=Chunk(project_id, ref, r[0], r[1], r[2], r[3], r[4]), score=1.0)
            for r in cur.fetchall()
        ]


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
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS files (project_id TEXT, ref TEXT, path TEXT, sha TEXT, "
            "PRIMARY KEY(project_id, ref, path))"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS index_meta (project_id TEXT, ref TEXT, commit_sha TEXT, "
            "PRIMARY KEY(project_id, ref))"
        )

    def has_index(self, project_id: str, ref: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM chunks WHERE project_id=%s AND ref=%s LIMIT 1", (project_id, ref)
        )
        return cur.fetchone() is not None

    def clear(self, project_id: str, ref: str) -> None:
        for tbl in ("chunks", "files", "index_meta"):
            self._conn.execute(
                f"DELETE FROM {tbl} WHERE project_id=%s AND ref=%s", (project_id, ref)
            )

    def get_file_shas(self, project_id: str, ref: str) -> dict[str, str]:
        cur = self._conn.execute(
            "SELECT path, sha FROM files WHERE project_id=%s AND ref=%s", (project_id, ref)
        )
        return {p: s for p, s in cur.fetchall()}

    def set_file_shas(self, project_id: str, ref: str, mapping: dict[str, str]) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO files(project_id, ref, path, sha) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (project_id, ref, path) DO UPDATE SET sha=EXCLUDED.sha",
                [(project_id, ref, p, s) for p, s in mapping.items()],
            )

    def delete_paths(self, project_id: str, ref: str, paths: list[str]) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(
                "DELETE FROM chunks WHERE project_id=%s AND ref=%s AND path=%s",
                [(project_id, ref, p) for p in paths],
            )

    def forget_files(self, project_id: str, ref: str, paths: list[str]) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(
                "DELETE FROM files WHERE project_id=%s AND ref=%s AND path=%s",
                [(project_id, ref, p) for p in paths],
            )

    def get_commit(self, project_id: str, ref: str) -> str | None:
        row = self._conn.execute(
            "SELECT commit_sha FROM index_meta WHERE project_id=%s AND ref=%s", (project_id, ref)
        ).fetchone()
        return row[0] if row else None

    def set_commit(self, project_id: str, ref: str, commit_sha: str) -> None:
        self._conn.execute(
            "INSERT INTO index_meta(project_id, ref, commit_sha) VALUES (%s,%s,%s) "
            "ON CONFLICT (project_id, ref) DO UPDATE SET commit_sha=EXCLUDED.commit_sha",
            (project_id, ref, commit_sha),
        )

    def counts(self, project_id: str, ref: str) -> tuple[int, int]:
        c = self._conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE project_id=%s AND ref=%s", (project_id, ref)
        ).fetchone()[0]
        f = self._conn.execute(
            "SELECT COUNT(*) FROM files WHERE project_id=%s AND ref=%s", (project_id, ref)
        ).fetchone()[0]
        return int(c), int(f)

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

    def lexical_search(
        self, project_id: str, ref: str, query: str, k: int
    ) -> list[SearchResult]:
        """Postgres full-text search (ts_rank over to_tsvector of chunk text)."""
        terms = " | ".join(t.lower() for t in _WORD.findall(query))
        if not terms:
            return []
        cur = self._conn.execute(
            "SELECT path,start_line,end_line,symbol,text, "
            "ts_rank(to_tsvector('simple', text), to_tsquery('simple', %s)) AS rank "
            "FROM chunks WHERE project_id=%s AND ref=%s "
            "AND to_tsvector('simple', text) @@ to_tsquery('simple', %s) "
            "ORDER BY rank DESC LIMIT %s",
            (terms, project_id, ref, terms, k),
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
