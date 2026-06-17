"""Embedding backends.

The pipeline depends only on the :class:`Embedder` interface so the provider can be
swapped by config (``QUOLAB_EMBEDDER``) without touching the indexer or store.

Default: :class:`GeminiEmbedder` — the free hosted Gemini embedding API (no GPU).
Stub:    :class:`LocalEmbedder` — a local OSS model (Qwen3-Embedding / nomic-embed-code)
         via sentence-transformers, for full self-containment later.
"""

from __future__ import annotations

from typing import Protocol

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from quolab.config import Settings

log = structlog.get_logger(__name__)

# Gemini distinguishes document vs query embeddings via task_type.
_TASK_DOCUMENT = "RETRIEVAL_DOCUMENT"
_TASK_QUERY = "RETRIEVAL_QUERY"

# Retry transient embedding-API failures (rate limit / 5xx / network) with backoff.
_embed_retry = retry(
    reraise=True,
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=30),
)


class Embedder(Protocol):
    """Maps text to fixed-length float vectors."""

    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed code chunks for storage."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a search query."""
        ...


class GeminiEmbedder:
    """Embeds via the hosted Gemini embedding API (``google-genai``)."""

    def __init__(self, api_key: str, model: str, dim: int) -> None:
        if not api_key:
            raise ValueError("QUOLAB_GEMINI_API_KEY is required for the gemini embedder")
        from google import genai  # imported lazily so the package installs without it

        self._client = genai.Client(api_key=api_key)
        self._genai = genai
        self.model = model
        self.dim = dim

    @_embed_retry
    def _embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        from google.genai import types

        resp = self._client.models.embed_content(
            model=self.model,
            contents=texts,
            config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=self.dim),
        )
        return [list(e.values) for e in resp.embeddings]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embed(texts, _TASK_DOCUMENT)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], _TASK_QUERY)[0]


class LocalEmbedder:
    """Local OSS embedding model via sentence-transformers (stub, opt-in extra)."""

    def __init__(self, model: str, dim: int) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "LocalEmbedder needs the 'local' extra: pip install 'quolab[local]'"
            ) from exc
        self._model = SentenceTransformer(model)
        self.dim = dim

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return [v.tolist() for v in self._model.encode(texts, normalize_embeddings=True)]

    def embed_query(self, text: str) -> list[float]:
        return self._model.encode([text], normalize_embeddings=True)[0].tolist()


class HashEmbedder:
    """Deterministic, dependency-free embedder (no network, no model download).

    Hashes text to a stable pseudo-random unit vector. Semantic quality is nil — it is
    for **offline/CI** use, local smoke tests, and the dogfood benchmark where only the
    pipeline and lexical/RRF paths need to run without a Gemini key.
    """

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        import hashlib

        import numpy as np

        seed = int(hashlib.sha1(text.encode("utf-8")).hexdigest()[:8], 16)
        v = np.random.default_rng(seed).standard_normal(self.dim)
        return (v / (np.linalg.norm(v) + 1e-12)).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def make_embedder(settings: Settings) -> Embedder:
    """Build the configured embedder."""
    if settings.embedder == "gemini":
        log.info("embedder_selected", backend="gemini", model=settings.embed_model)
        return GeminiEmbedder(settings.gemini_api_key, settings.embed_model, settings.embed_dim)
    if settings.embedder == "local":
        log.info("embedder_selected", backend="local", model=settings.embed_model)
        return LocalEmbedder(settings.embed_model, settings.embed_dim)
    if settings.embedder == "hash":
        log.info("embedder_selected", backend="hash")
        return HashEmbedder(settings.embed_dim)
    raise ValueError(
        f"Unknown embedder: {settings.embedder!r} (expected 'gemini', 'local' or 'hash')"
    )
