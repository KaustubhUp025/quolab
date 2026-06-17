from quolab.engine import SearchEngine, format_results
from quolab.models import Chunk, SearchResult
from quolab.store import SqliteVecStore


def _seed_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "lock.py").write_text(
        'def acquire(key):\n    return redis.set(key, "locked", nx=True)\n'
    )
    (repo / "pkg" / "saga.py").write_text(
        "class Saga:\n    def compensate(self):\n        rollback()\n"
    )
    return repo


def test_index_and_search_end_to_end(settings, fake_embedder, monkeypatch):
    repo = _seed_repo(__import__("pathlib").Path(settings.repo_cache).parent)
    # Point fetch_repo at the seeded local dir instead of cloning.
    monkeypatch.setattr("quolab.engine.fetch_repo", lambda s, p, r: repo)

    store = SqliteVecStore(settings.sqlite_path)
    engine = SearchEngine(settings=settings, embedder=fake_embedder, store=store)

    stats = engine.index("proj", "HEAD")
    assert stats.files == 2
    assert stats.chunks >= 2

    results = engine.search("proj", "compensate rollback", "HEAD", max_results=3)
    assert results
    paths = [r.chunk.path for r in results]
    assert any("saga.py" in p for p in paths)


def test_hybrid_and_lexical_modes(settings, fake_embedder, monkeypatch):
    repo = _seed_repo(__import__("pathlib").Path(settings.repo_cache).parent)
    monkeypatch.setattr("quolab.engine.fetch_repo", lambda s, p, r: repo)
    engine = SearchEngine(
        settings=settings, embedder=fake_embedder, store=SqliteVecStore(settings.sqlite_path)
    )
    engine.index("proj", "HEAD")

    # lexical: exact identifier 'acquire' lands the lock file
    lex = engine.search("proj", "acquire", "HEAD", mode="lexical")
    assert any("lock.py" in r.chunk.path for r in lex)

    # hybrid: fuses both arms, returns results
    hyb = engine.search("proj", "compensate", "HEAD", mode="hybrid")
    assert hyb


def test_invalid_mode_raises(settings, fake_embedder):
    import pytest
    engine = SearchEngine(
        settings=settings, embedder=fake_embedder, store=SqliteVecStore(settings.sqlite_path)
    )
    with pytest.raises(ValueError):  # validated before any indexing
        engine.search("proj", "x", "HEAD", mode="bogus")


def test_search_lazily_indexes(settings, fake_embedder, monkeypatch):
    repo = _seed_repo(__import__("pathlib").Path(settings.repo_cache).parent)
    monkeypatch.setattr("quolab.engine.fetch_repo", lambda s, p, r: repo)
    engine = SearchEngine(
        settings=settings, embedder=fake_embedder, store=SqliteVecStore(settings.sqlite_path)
    )
    # No explicit index() call — search must trigger it.
    results = engine.search("proj", "acquire lock", "HEAD")
    assert results


def test_format_results_shape():
    r = SearchResult(Chunk("p", "HEAD", "a.py", 3, 9, "acquire", "code here"), 0.87)
    out = format_results("lock", [r])
    assert "a.py:3-9" in out
    assert "(acquire)" in out
    assert "score=0.870" in out
    assert "```" in out


def test_format_results_empty():
    assert "No code matches" in format_results("nothing", [])
