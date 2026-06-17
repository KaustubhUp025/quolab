"""The search engine: orchestrates fetch → chunk → embed → store → query.

This is the heart of quolab. :meth:`SearchEngine.search` returns results formatted to
match Quorum's ``GitLabRESTClient.semantic_code_search`` text shape, so Quorum can use
quolab as a drop-in replacement for GitLab Ultimate's semantic search.
"""

from __future__ import annotations

import structlog

from quolab.config import Settings, get_settings
from quolab.embedder import Embedder, make_embedder
from quolab.indexer import chunk_text, fetch_repo, iter_source_files
from quolab.models import IndexStats, SearchResult
from quolab.store import VectorStore, make_store

log = structlog.get_logger(__name__)

_DEFAULT_REF = "HEAD"
_EMBED_BATCH = 64


class SearchEngine:
    def __init__(
        self,
        settings: Settings | None = None,
        embedder: Embedder | None = None,
        store: VectorStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.embedder = embedder or make_embedder(self.settings)
        self.store = store or make_store(self.settings)

    def index(self, project_id: str, ref: str = _DEFAULT_REF, *, force: bool = False) -> IndexStats:
        """Fetch, chunk, embed and store a project. Idempotent unless ``force``."""
        ref = ref or _DEFAULT_REF
        stats = IndexStats(project_id=project_id, ref=ref)
        if self.store.has_index(project_id, ref) and not force:
            log.info("index_cached", project_id=project_id, ref=ref)
            return stats
        if force:
            self.store.clear(project_id, ref)

        root = fetch_repo(self.settings, project_id, ref)
        all_chunks = []
        for rel_path, text in iter_source_files(root, self.settings):
            stats.files += 1
            try:
                all_chunks.extend(chunk_text(project_id, ref, rel_path, text, self.settings))
            except Exception as exc:  # pragma: no cover - defensive
                stats.skipped += 1
                stats.errors.append(f"{rel_path}: {exc}")

        for i in range(0, len(all_chunks), _EMBED_BATCH):
            batch = all_chunks[i:i + _EMBED_BATCH]
            vectors = self.embedder.embed_documents([c.text for c in batch])
            self.store.add(batch, vectors)
            stats.chunks += len(batch)

        log.info("index_complete", project_id=project_id, ref=ref,
                 files=stats.files, chunks=stats.chunks)
        return stats

    def search(
        self, project_id: str, query: str, ref: str = _DEFAULT_REF, max_results: int = 5
    ) -> list[SearchResult]:
        """Semantic search; lazily indexes the project on first use."""
        ref = ref or _DEFAULT_REF
        if not self.store.has_index(project_id, ref):
            self.index(project_id, ref)
        query_vec = self.embedder.embed_query(query)
        return self.store.search(project_id, ref, query_vec, max_results)


def format_results(query: str, results: list[SearchResult]) -> str:
    """Render results in Quorum's REST ``semantic_code_search`` text shape.

    Quorum's agent prompt expects a human-readable block of path-tagged snippets.
    Matching that shape keeps the Quorum adapter a true drop-in.
    """
    if not results:
        return f"[No code matches for query {query!r}.]"
    blocks = [f"Semantic search results for {query!r}:\n"]
    for i, r in enumerate(results, 1):
        c = r.chunk
        header = f"{i}. {c.path}:{c.start_line}-{c.end_line}"
        if c.symbol:
            header += f"  ({c.symbol})"
        header += f"  [score={r.score:.3f}]"
        snippet = c.text if len(c.text) <= 1500 else c.text[:1500] + "\n…(truncated)"
        blocks.append(f"{header}\n```\n{snippet}\n```")
    return "\n\n".join(blocks)
