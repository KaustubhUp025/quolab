"""Shared test fixtures: deterministic fakes so the suite needs no network or GPU."""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from quolab.config import Settings


class FakeEmbedder:
    """Deterministic hash-based embedder — no API calls, stable vectors.

    Same text → same vector, so query/doc similarity is meaningful in tests.
    """

    def __init__(self, dim: int = 32) -> None:
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        rng = np.random.default_rng(int(hashlib.sha1(text.encode()).hexdigest()[:8], 16))
        v = rng.standard_normal(self.dim)
        return (v / (np.linalg.norm(v) + 1e-12)).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        embedder="hash",  # overridden by injected FakeEmbedder in engine tests; no model load
        store="sqlite",
        sqlite_path=str(tmp_path / "index.db"),
        repo_cache=str(tmp_path / "repos"),
    )


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()
