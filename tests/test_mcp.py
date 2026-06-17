"""MCP server: tool logic is testable without a running transport."""

from __future__ import annotations

import pathlib

import quolab.mcp_server as mcp_server
from quolab.engine import SearchEngine
from quolab.store import SqliteVecStore

from conftest import FakeEmbedder


def _wire_engine(settings, monkeypatch):
    repo = pathlib.Path(settings.repo_cache).parent / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "saga.py").write_text("class Saga:\n    def compensate(self):\n        rollback()\n")
    monkeypatch.setattr("quolab.engine.fetch_repo", lambda s, p, r: repo)
    eng = SearchEngine(
        settings=settings, embedder=FakeEmbedder(), store=SqliteVecStore(settings.sqlite_path)
    )
    monkeypatch.setattr(mcp_server, "get_engine", lambda: eng)
    return eng


def test_do_search_returns_formatted(settings, monkeypatch):
    _wire_engine(settings, monkeypatch)
    out = mcp_server._do_search("proj", "compensate", "HEAD")
    assert "saga.py" in out


def test_do_get_symbol(settings, monkeypatch):
    _wire_engine(settings, monkeypatch)
    out = mcp_server._do_get_symbol("proj", "compensate", "HEAD")
    assert "saga.py" in out


def test_do_index_and_status(settings, monkeypatch):
    _wire_engine(settings, monkeypatch)
    idx = mcp_server._do_index("proj", "HEAD")
    assert idx["files"] == 1
    st = mcp_server._do_status("proj", "HEAD")
    assert st["indexed"] is True


def test_build_server_registers_tools():
    server = mcp_server.build_server()
    assert server is not None  # FastMCP constructed without error
