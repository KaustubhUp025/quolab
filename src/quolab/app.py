"""FastAPI service exposing quolab's semantic search (+ health).

Endpoints
---------
- ``POST /search`` — semantic code search; returns both structured hits and a
  ``formatted`` string in Quorum's REST-search text shape (drop-in contract).
- ``POST /index``  — pre-warm a project's index.
- ``GET  /healthz`` — liveness.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from quolab import __version__
from quolab.config import get_settings
from quolab.engine import SearchEngine, format_results
from quolab.policy import Policy, evaluate, recent_decisions, record_decision

log = structlog.get_logger(__name__)

app = FastAPI(title="quolab", version=__version__, description="OSS semantic code search")

_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@lru_cache(maxsize=1)
def get_engine() -> SearchEngine:
    return SearchEngine()


class SearchRequest(BaseModel):
    project_id: str = Field(..., description="Clone URL or group/repo path")
    query: str
    ref: str = "HEAD"
    max_results: int = Field(default=5, ge=1, le=50)
    mode: str = Field(default="auto", description="auto | semantic | lexical | hybrid")


class Hit(BaseModel):
    path: str
    start_line: int
    end_line: int
    symbol: str
    score: float
    snippet: str


class SearchResponse(BaseModel):
    project_id: str
    ref: str
    query: str
    hits: list[Hit]
    formatted: str


class IndexRequest(BaseModel):
    project_id: str
    ref: str = "HEAD"
    force: bool = False


class GateRequest(BaseModel):
    project_id: str
    sha: str = ""
    sarif: dict = Field(..., description="A SARIF report (the format Quorum emits)")
    policy: dict | None = Field(default=None, description="Optional policy override")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "version": __version__}


@app.post("/search", response_model=SearchResponse)
def search(req: SearchRequest) -> SearchResponse:
    try:
        results = get_engine().search(
            req.project_id, req.query, req.ref, req.max_results, req.mode
        )
    except ValueError as exc:  # bad input / not-indexed precondition
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log.error("search_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"search failed: {exc}") from exc
    hits = [
        Hit(
            path=r.chunk.path, start_line=r.chunk.start_line, end_line=r.chunk.end_line,
            symbol=r.chunk.symbol, score=r.score, snippet=r.chunk.text,
        )
        for r in results
    ]
    return SearchResponse(
        project_id=req.project_id, ref=req.ref, query=req.query,
        hits=hits, formatted=format_results(req.query, results),
    )


@app.get("/status")
def status(project_id: str, ref: str = "HEAD") -> dict:
    return get_engine().status(project_id, ref)


@app.post("/index")
def index(req: IndexRequest) -> dict:
    try:
        stats = get_engine().index(req.project_id, req.ref, force=req.force)
    except ValueError as exc:  # bad input (e.g. disallowed host, control chars)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log.error("index_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"index failed: {exc}") from exc
    return {
        "project_id": stats.project_id, "ref": stats.ref,
        "files": stats.files, "chunks": stats.chunks, "skipped": stats.skipped,
    }


@app.post("/gate")
def gate(req: GateRequest) -> dict:
    """Evaluate a SARIF report against the merge-gate policy and record the decision.

    Powers the findings dashboard (replaces GitLab Ultimate's Security Dashboard /
    Scan-Result Policies) — same SARIF, no paid tier.
    """
    policy = Policy(**req.policy) if req.policy else Policy()
    decision = evaluate(req.sarif, policy)
    record_decision(get_settings().sqlite_path, req.project_id, req.sha, decision)
    return {
        "state": decision.state, "passed": decision.passed, "blocking": decision.blocking,
        "warnings": decision.warnings, "total": decision.total, "reasons": decision.reasons,
    }


@app.get("/dashboard/data")
def dashboard_data(limit: int = 100) -> dict:
    decisions = recent_decisions(get_settings().sqlite_path, limit=max(1, min(limit, 500)))
    return {"decisions": decisions, "count": len(decisions)}


@app.get("/dashboard")
def dashboard() -> FileResponse:
    return FileResponse(str(_STATIC_DIR / "dashboard.html"))


def main() -> None:  # pragma: no cover - thin entrypoint
    import uvicorn

    s = get_settings()
    uvicorn.run("quolab.app:app", host=s.host, port=s.port, log_level=s.log_level)


if __name__ == "__main__":  # pragma: no cover
    main()
