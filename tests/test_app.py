from fastapi.testclient import TestClient

from quolab.app import app, get_engine
from quolab.config import Settings
from quolab.engine import SearchEngine
from quolab.store import SqliteVecStore

from conftest import FakeEmbedder


def _engine(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "saga.py").write_text("class Saga:\n    def compensate(self):\n        rollback()\n")
    monkeypatch.setattr("quolab.engine.fetch_repo", lambda s, p, r: repo)
    settings = Settings(sqlite_path=str(tmp_path / "i.db"), repo_cache=str(tmp_path / "r"))
    return SearchEngine(
        settings=settings, embedder=FakeEmbedder(),
        store=SqliteVecStore(settings.sqlite_path),
    )


def test_healthz():
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_search_endpoint(tmp_path, monkeypatch):
    app.dependency_overrides = {}
    get_engine.cache_clear()
    eng = _engine(tmp_path, monkeypatch)
    monkeypatch.setattr("quolab.app.get_engine", lambda: eng)

    client = TestClient(app)
    resp = client.post("/search", json={"project_id": "proj", "query": "compensate"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "compensate"
    assert "formatted" in body
    assert isinstance(body["hits"], list)
