"""M5 — findings dashboard: /gate persists a SARIF decision; /dashboard renders it."""

from __future__ import annotations

from fastapi.testclient import TestClient

from quolab.app import app
from quolab.config import Settings
from quolab.policy import recent_decisions

_SARIF_FAIL = {
    "runs": [{
        "tool": {"driver": {"rules": [{"id": "R1", "defaultConfiguration": {"level": "error"}}]}},
        "results": [
            {"ruleId": "R1", "level": "error"},
            {"ruleId": "R2", "level": "warning"},
        ],
    }]
}


def _patch_settings(monkeypatch, tmp_path):
    s = Settings(sqlite_path=str(tmp_path / "i.db"))
    monkeypatch.setattr("quolab.app.get_settings", lambda: s)
    return s


def test_gate_persists_and_blocks(tmp_path, monkeypatch):
    s = _patch_settings(monkeypatch, tmp_path)
    client = TestClient(app)
    resp = client.post("/gate", json={
        "project_id": "group/repo", "sha": "deadbeefcafe", "sarif": _SARIF_FAIL,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "failed" and body["passed"] is False
    assert body["blocking"] == 1 and body["warnings"] == 1 and body["total"] == 2
    # persisted
    rows = recent_decisions(s.sqlite_path)
    assert len(rows) == 1 and rows[0]["project_id"] == "group/repo"


def test_dashboard_data_returns_records(tmp_path, monkeypatch):
    _patch_settings(monkeypatch, tmp_path)
    client = TestClient(app)
    client.post("/gate", json={"project_id": "a/b", "sha": "1", "sarif": _SARIF_FAIL})
    resp = client.get("/dashboard/data")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["decisions"][0]["state"] == "failed"


def test_dashboard_data_empty_when_no_gate(tmp_path, monkeypatch):
    _patch_settings(monkeypatch, tmp_path)
    client = TestClient(app)
    resp = client.get("/dashboard/data")
    assert resp.status_code == 200
    assert resp.json() == {"decisions": [], "count": 0}


def test_dashboard_page_served():
    client = TestClient(app)
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "Findings Dashboard" in resp.text


def test_policy_override_applied(tmp_path, monkeypatch):
    _patch_settings(monkeypatch, tmp_path)
    client = TestClient(app)
    # Treat 'error' as non-blocking via an override → gate passes.
    resp = client.post("/gate", json={
        "project_id": "a/b", "sha": "1", "sarif": _SARIF_FAIL,
        "policy": {"block_on": ["critical"], "warn_on": ["error", "warning"]},
    })
    assert resp.json()["state"] == "success"
