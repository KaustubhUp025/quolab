"""Embedding backends.

The pipeline depends only on the :class:`Embedder` interface so the provider can be
swapped by config (``QUOLAB_EMBEDDER``) without touching the indexer or store.

Default: :class:`LocalEmbedder` — a local OSS model (``Qwen/Qwen3-Embedding-0.6B``) via
         sentence-transformers. Runs fully on-device (GPU if available, else CPU); no API
         key, no rate limit, no per-request network round-trip.
Opt-in:  :class:`GeminiEmbedder` — the hosted Gemini embedding API (needs a key and the
         ``gemini`` extra). Subject to the free-tier 100 req/min cap.
Offline: :class:`HashEmbedder` — deterministic, dependency-free; for CI/bench only.
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
# max wait 65s so the free-tier "100 embed requests/minute" 429 (≈60s reset) self-heals.
_embed_retry = retry(
    reraise=True,
    stop=stop_after_attempt(6),
    wait=wait_exponential(multiplier=2, min=2, max=65),
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
    """Local OSS embedding model via sentence-transformers — the default embedder.

    Runs on-device with no API key or rate limit. Uses the GPU when available — in fp16
    to fit small VRAM — and **falls back to CPU automatically on CUDA out-of-memory** (a
    real risk on a 4 GB laptop GPU shared with the display). Code-retrieval models such as
    ``Qwen/Qwen3-Embedding-0.6B`` distinguish documents from queries via an instruction
    prompt: documents are embedded plain, queries with the model's ``query`` prompt — the
    local analogue of Gemini's ``RETRIEVAL_DOCUMENT`` / ``RETRIEVAL_QUERY`` task types.
    """

    # Code chunks are functions/classes — 1024 tokens is ample and caps activation memory.
    _MAX_SEQ_LEN = 1024

    def __init__(
        self, model: str, dim: int, device: str = "auto", batch_size: int = 16
    ) -> None:
        try:
            import torch
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "LocalEmbedder needs the 'local' extra: pip install 'quolab[local]'"
            ) from exc

        self._torch = torch
        self._batch_size = batch_size
        resolved = (
            "cuda" if (device == "auto" and torch.cuda.is_available())
            else device if device in ("cuda", "cpu")
            else "cpu"
        )
        self._model = SentenceTransformer(model, device=resolved)
        self._device = resolved
        if resolved == "cuda":
            self._model.half()  # force fp16 (kwarg dtype names differ across transformers versions)
        # Cap sequence length to bound activation memory (model defaults can be 32k).
        if (self._model.max_seq_length or 0) > self._MAX_SEQ_LEN:
            self._model.max_seq_length = self._MAX_SEQ_LEN
        # Some code models define a "query" instruction prompt; use it when present.
        self._query_prompt = "query" if "query" in getattr(self._model, "prompts", {}) else None

        # method renamed get_sentence_embedding_dimension -> get_embedding_dimension in ST 5.x
        get_dim = getattr(self._model, "get_embedding_dimension", None) or \
            self._model.get_sentence_embedding_dimension
        actual = get_dim()
        if actual and actual != dim:
            log.warning("embed_dim_mismatch", configured=dim, model_dim=actual, model=model,
                        hint="set QUOLAB_EMBED_DIM to the model's native dim and reindex")
        self.dim = actual or dim
        log.info("local_embedder_ready", model=model, device=resolved, dim=self.dim,
                 query_prompt=bool(self._query_prompt))

    def _encode(self, texts: list[str], **kwargs) -> list[list[float]]:
        """Encode with normalized vectors; retry on CPU if the GPU runs out of memory."""
        try:
            vecs = self._model.encode(
                texts, normalize_embeddings=True, batch_size=self._batch_size, **kwargs
            )
        except self._torch.cuda.OutOfMemoryError:
            if self._device != "cuda":
                raise
            log.warning("cuda_oom_fallback_cpu", note="moving local embedder to CPU for the rest of this run")
            self._torch.cuda.empty_cache()
            self._model = self._model.to("cpu").float()
            self._device = "cpu"
            vecs = self._model.encode(
                texts, normalize_embeddings=True, batch_size=self._batch_size, **kwargs
            )
        return [v.tolist() for v in vecs]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._encode(texts)

    def embed_query(self, text: str) -> list[float]:
        kwargs = {"prompt_name": self._query_prompt} if self._query_prompt else {}
        return self._encode([text], **kwargs)[0]


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
        return LocalEmbedder(
            settings.embed_model, settings.embed_dim,
            device=settings.embed_device, batch_size=settings.embed_batch_size,
        )
    if settings.embedder == "hash":
        log.info("embedder_selected", backend="hash")
        return HashEmbedder(settings.embed_dim)
    raise ValueError(
        f"Unknown embedder: {settings.embedder!r} (expected 'gemini', 'local' or 'hash')"
    )
