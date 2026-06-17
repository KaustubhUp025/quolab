"""Embedder retry + REST fetch path."""

from __future__ import annotations

import httpx

from quolab.config import Settings
from quolab.embedder import _embed_retry
from quolab.indexer import fetch_repo


def test_embed_retry_recovers(monkeypatch):
    # don't actually sleep between retries
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda *_: None)
    calls = {"n": 0}

    @_embed_retry
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("429 rate limited")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3


def test_embed_retry_gives_up(monkeypatch):
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda *_: None)

    @_embed_retry
    def always_fail():
        raise RuntimeError("nope")

    import pytest
    with pytest.raises(RuntimeError):
        always_fail()


def test_rest_fetch_downloads_matching_files(tmp_path, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/repository/tree"):
            return httpx.Response(200, json=[
                {"type": "blob", "path": "pkg/a.py"},
                {"type": "blob", "path": "README.md"},   # filtered out (not a code suffix)
                {"type": "tree", "path": "pkg"},
            ])
        if request.url.path.endswith("/raw"):
            return httpx.Response(200, content=b"def a():\n    return 1\n")
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=transport, **kw)
    )

    settings = Settings(
        fetch="rest", repo_cache=str(tmp_path / "repos"),
        gitlab_url="https://gitlab.com", gitlab_token="x",
    )
    cache = fetch_repo(settings, "group/repo", "HEAD")
    assert (cache / "pkg" / "a.py").exists()
    assert not (cache / "README.md").exists()   # suffix filtered
