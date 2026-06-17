"""Incremental indexing: only changed/added files are re-embedded."""

from __future__ import annotations

import pathlib

from quolab.engine import SearchEngine
from quolab.store import SqliteVecStore


def _engine(settings, fake_embedder):
    return SearchEngine(
        settings=settings, embedder=fake_embedder, store=SqliteVecStore(settings.sqlite_path)
    )


def _repo(settings):
    repo = pathlib.Path(settings.repo_cache).parent / "repo"
    (repo / "pkg").mkdir(parents=True, exist_ok=True)
    (repo / "pkg" / "a.py").write_text("def alpha_widget():\n    return 1\n")
    (repo / "pkg" / "b.py").write_text("def beta_gadget():\n    return 2\n")
    return repo


def test_reindex_unchanged_embeds_nothing(settings, fake_embedder, monkeypatch):
    repo = _repo(settings)
    monkeypatch.setattr("quolab.engine.fetch_repo", lambda s, p, r: repo)
    eng = _engine(settings, fake_embedder)

    first = eng.index("proj", "HEAD")
    assert first.chunks > 0 and first.files == 2

    second = eng.index("proj", "HEAD")
    assert second.chunks == 0           # nothing re-embedded
    assert second.files == 2


def test_changed_file_reembeds_only_that_file(settings, fake_embedder, monkeypatch):
    repo = _repo(settings)
    monkeypatch.setattr("quolab.engine.fetch_repo", lambda s, p, r: repo)
    eng = _engine(settings, fake_embedder)
    eng.index("proj", "HEAD")

    (repo / "pkg" / "a.py").write_text("def alpha_widget():\n    return 999  # changed\n")
    stats = eng.index("proj", "HEAD")
    assert stats.chunks >= 1            # a.py re-embedded
    # b.py chunk still present (untouched)
    results = eng.search("proj", "beta_gadget", "HEAD", mode="lexical")
    assert any("b.py" in r.chunk.path for r in results)


def test_removed_file_is_dropped(settings, fake_embedder, monkeypatch):
    repo = _repo(settings)
    monkeypatch.setattr("quolab.engine.fetch_repo", lambda s, p, r: repo)
    eng = _engine(settings, fake_embedder)
    eng.index("proj", "HEAD")
    before = eng.status("proj", "HEAD")

    (repo / "pkg" / "b.py").unlink()
    eng.index("proj", "HEAD")
    after = eng.status("proj", "HEAD")

    assert after["files"] == 1
    assert after["chunks"] < before["chunks"]
    # b.py no longer searchable
    assert not eng.search("proj", "beta_gadget", "HEAD", mode="lexical")


def test_status_shape(settings, fake_embedder, monkeypatch):
    repo = _repo(settings)
    monkeypatch.setattr("quolab.engine.fetch_repo", lambda s, p, r: repo)
    eng = _engine(settings, fake_embedder)
    eng.index("proj", "HEAD")
    st = eng.status("proj", "HEAD")
    assert st["indexed"] is True
    assert st["files"] == 2
    assert "commit" in st
