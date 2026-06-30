"""B5 — cross-encoder rerank stage (wiring tested with a fake reranker; no model download)."""

from __future__ import annotations

from quolab import retrieval
from quolab.engine import SearchEngine
from quolab.models import Chunk, SearchResult
from quolab.store import make_store


class FakeReranker:
    """Scores a doc by how many query terms it contains — deterministic, no model."""

    def __init__(self) -> None:
        self.calls = 0

    def rerank(self, query: str, docs: list[str]) -> list[float]:
        self.calls += 1
        terms = set(query.lower().split())
        return [float(sum(t in d.lower() for t in terms)) for d in docs]


def _r(path: str, text: str, score: float) -> SearchResult:
    chunk = Chunk(project_id="p", ref="HEAD", path=path, start_line=1, end_line=2,
                  symbol="", text=text)
    return SearchResult(chunk=chunk, score=score)


def test_rerank_none_is_noop():
    results = [_r("a", "x", 0.9), _r("b", "y", 0.1)]
    assert retrieval.rerank(None, "q", results, 10) is results


def test_rerank_promotes_best_match():
    # First-stage order puts the weak match first; the reranker should flip them.
    results = [_r("a.py", "totally unrelated", 0.9), _r("b.py", "parse the auth token", 0.1)]
    out = retrieval.rerank(FakeReranker(), "auth token", results, 10)
    assert out[0].chunk.path == "b.py"


def test_rerank_only_touches_top_k():
    results = [_r("a", "auth", 0.9), _r("b", "auth", 0.8), _r("c", "tail", 0.1)]
    out = retrieval.rerank(FakeReranker(), "auth", results, top_k=2)
    # The tail item beyond top_k keeps its position at the end.
    assert out[-1].chunk.path == "c"


def test_engine_applies_reranker(settings, fake_embedder, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    # Both files mention "token" so both are first-stage candidates, but only auth.py is
    # the real match — the reranker must promote it.
    (repo / "weak.py").write_text("def store_token_count():\n    return 0\n")
    (repo / "auth.py").write_text("def verify_auth_token(t):\n    return check(t)\n")
    monkeypatch.setattr("quolab.engine.fetch_repo", lambda s, p, r: repo)

    fake = FakeReranker()
    eng = SearchEngine(settings, embedder=fake_embedder, store=make_store(settings), reranker=fake)
    results = eng.search("proj", "verify auth token", mode="lexical", max_results=5)
    assert fake.calls >= 1  # reranker was invoked
    assert results and "auth" in results[0].chunk.path
