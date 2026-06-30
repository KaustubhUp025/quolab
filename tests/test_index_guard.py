"""R1 — index metadata guard: an index built by one embedder is rebuilt, not reused, by another."""

from __future__ import annotations

import numpy as np

from quolab.engine import SearchEngine
from quolab.store import make_store


class _Embedder:
    """Deterministic embedder of a fixed dimension; distinct dims => distinct vectors."""

    def __init__(self, dim: int, tag: str) -> None:
        self.dim = dim
        self._tag = tag

    def _vec(self, text: str) -> list[float]:
        import hashlib

        seed = int(hashlib.sha1((self._tag + text).encode()).hexdigest()[:8], 16)
        v = np.random.default_rng(seed).standard_normal(self.dim)
        return (v / (np.linalg.norm(v) + 1e-12)).tolist()

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


def _seed_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text("def alpha():\n    return 1\n")
    return repo


def test_signature_recorded_on_index(settings, monkeypatch, tmp_path):
    repo = _seed_repo(tmp_path)
    monkeypatch.setattr("quolab.engine.fetch_repo", lambda s, p, r: repo)

    store = make_store(settings)
    eng = SearchEngine(settings, embedder=_Embedder(8, "A"), store=store)
    eng.index("proj", "HEAD")
    assert store.get_embed_sig("proj", "HEAD") == eng._embed_sig()
    assert store.get_embed_sig("proj", "HEAD").endswith(":8")


def test_changing_embedder_dim_triggers_rebuild_not_crash(settings, monkeypatch, tmp_path):
    repo = _seed_repo(tmp_path)
    monkeypatch.setattr("quolab.engine.fetch_repo", lambda s, p, r: repo)

    store = make_store(settings)

    # Index with an 8-dim embedder.
    eng_a = SearchEngine(settings, embedder=_Embedder(8, "A"), store=store)
    eng_a.index("proj", "HEAD")
    sig_a = store.get_embed_sig("proj", "HEAD")

    # Query with a DIFFERENT-dim (16) embedder sharing the same store. Without the guard
    # this mixes 16-dim query vectors against 8-dim stored vectors → shape error. The guard
    # must rebuild the index under the new signature and return results cleanly.
    eng_b = SearchEngine(settings, embedder=_Embedder(16, "B"), store=store)
    results = eng_b.search("proj", "alpha", mode="semantic")

    assert results, "search should return results after an automatic rebuild"
    assert store.get_embed_sig("proj", "HEAD") != sig_a
    assert store.get_embed_sig("proj", "HEAD").endswith(":16")


def test_legacy_index_without_signature_is_rebuilt(settings, monkeypatch, tmp_path):
    repo = _seed_repo(tmp_path)
    monkeypatch.setattr("quolab.engine.fetch_repo", lambda s, p, r: repo)

    store = make_store(settings)
    eng = SearchEngine(settings, embedder=_Embedder(8, "A"), store=store)
    eng.index("proj", "HEAD")

    # Simulate a pre-R1 index: clear the recorded signature but keep the chunks.
    store._conn.execute("UPDATE index_meta SET embed_sig=NULL")
    store._conn.commit()
    assert store.get_embed_sig("proj", "HEAD") is None

    results = eng.search("proj", "alpha", mode="semantic")
    assert results
    assert store.get_embed_sig("proj", "HEAD") == eng._embed_sig()
