"""MCP server exposing quolab over streamable-HTTP (FastMCP).

This is the "no GitLab Ultimate" path for agents: a Gemini/ADK agent (e.g. Quorum's
Agent Engine Playground) points an MCPToolset at this server and calls
``semantic_code_search`` live — same shape as GitLab's MCP search tool, no paid tier.

The tool logic lives in plain ``_do_*`` functions so it is unit-testable without a
running MCP transport; the FastMCP ``@tool`` wrappers just delegate to them.
"""

from __future__ import annotations

from functools import lru_cache

import structlog

from quolab.engine import SearchEngine, format_results

log = structlog.get_logger(__name__)


@lru_cache(maxsize=1)
def get_engine() -> SearchEngine:
    return SearchEngine()


# --- testable core ---------------------------------------------------------

def _do_search(project_id: str, query: str, ref: str = "HEAD",
               max_results: int = 5, mode: str = "auto") -> str:
    results = get_engine().search(project_id, query, ref, max_results, mode)
    return format_results(query, results)


def _do_get_symbol(project_id: str, symbol: str, ref: str = "HEAD") -> str:
    results = get_engine().search(project_id, symbol, ref, max_results=5, mode="lexical")
    return format_results(symbol, results)


def _do_index(project_id: str, ref: str = "HEAD", force: bool = False) -> dict:
    s = get_engine().index(project_id, ref, force=force)
    return {"project_id": s.project_id, "ref": s.ref, "files": s.files,
            "embedded_chunks": s.chunks, "skipped": s.skipped}


def _do_status(project_id: str, ref: str = "HEAD") -> dict:
    return get_engine().status(project_id, ref)


# --- MCP wiring ------------------------------------------------------------

def build_server():
    """Construct the FastMCP server with quolab's tools registered."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("quolab")

    @mcp.tool()
    def semantic_code_search(
        project_id: str, query: str, ref: str = "HEAD",
        max_results: int = 5, mode: str = "auto",
    ) -> str:
        """Hybrid semantic + lexical code search across a repository.

        project_id: clone URL or 'group/repo' path. mode: auto|semantic|lexical|hybrid.
        Returns path-tagged code snippets ranked by relevance.
        """
        return _do_search(project_id, query, ref, max_results, mode)

    @mcp.tool()
    def get_symbol(project_id: str, symbol: str, ref: str = "HEAD") -> str:
        """Find the definition(s) of a named symbol (function/class/method)."""
        return _do_get_symbol(project_id, symbol, ref)

    @mcp.tool()
    def index(project_id: str, ref: str = "HEAD", force: bool = False) -> dict:
        """Index (or incrementally refresh) a repository for search."""
        return _do_index(project_id, ref, force)

    @mcp.tool()
    def status(project_id: str, ref: str = "HEAD") -> dict:
        """Report what is currently indexed for a repository."""
        return _do_status(project_id, ref)

    return mcp


def main() -> None:  # pragma: no cover - transport entrypoint
    build_server().run(transport="streamable-http")


if __name__ == "__main__":  # pragma: no cover
    main()
