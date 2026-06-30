"""S2/S3 — input validation, result-count cap, and opt-out auto-index at the engine chokepoint."""

from __future__ import annotations

import pytest

from quolab.engine import SearchEngine
from quolab.store import make_store


class _Embedder:
    dim = 8

    def _vec(self, text):
        import hashlib

        import numpy as np

        seed = int(hashlib.sha1(text.encode()).hexdigest()[:8], 16)
        v = np.random.default_rng(seed).standard_normal(self.dim)
        return (v / (np.linalg.norm(v) + 1e-12)).tolist()

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


def _engine(settings, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text("def alpha():\n    return 1\n")
    monkeypatch.setattr("quolab.engine.fetch_repo", lambda s, p, r: repo)
    return SearchEngine(settings, embedder=_Embedder(), store=make_store(settings))


# --- S3: input validation ---------------------------------------------------

@pytest.mark.parametrize("bad", ["", "   ", "x" * 3000, "has\x00null", "ctrl\x07char"])
def test_invalid_query_rejected(settings, monkeypatch, tmp_path, bad):
    eng = _engine(settings, monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        eng.search("proj", bad)


@pytest.mark.parametrize("bad", ["", "  ", "p" * 600, "evil\nproject", "x\x00y"])
def test_invalid_project_id_rejected(settings, monkeypatch, tmp_path, bad):
    eng = _engine(settings, monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        eng.search(bad, "alpha")


def test_valid_query_with_whitespace_ok(settings, monkeypatch, tmp_path):
    eng = _engine(settings, monkeypatch, tmp_path)
    # tabs/newlines inside an otherwise valid query are allowed
    assert eng.search("proj", "find the alpha\tfunction\n", mode="semantic") is not None


# --- S2: result-count cap ---------------------------------------------------

def test_max_results_capped(settings, monkeypatch, tmp_path):
    settings = settings.model_copy(update={"max_results_cap": 2})
    eng = _engine(settings, monkeypatch, tmp_path)
    eng.index("proj", "HEAD")
    results = eng.search("proj", "alpha", max_results=999, mode="lexical")
    assert len(results) <= 2


# --- S2: opt-out auto-index -------------------------------------------------

def test_auto_index_disabled_refuses_unindexed(settings, monkeypatch, tmp_path):
    settings = settings.model_copy(update={"allow_auto_index": False})
    eng = _engine(settings, monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="not indexed"):
        eng.search("proj", "alpha")


def test_auto_index_disabled_serves_prewarmed(settings, monkeypatch, tmp_path):
    settings = settings.model_copy(update={"allow_auto_index": False})
    eng = _engine(settings, monkeypatch, tmp_path)
    eng.index("proj", "HEAD")  # explicit pre-warm is still allowed
    assert eng.search("proj", "alpha", mode="lexical") is not None
