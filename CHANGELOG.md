# Changelog

All notable changes to quolab are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versioning is [SemVer](https://semver.org/).

## [Unreleased]

### Added
- **Hybrid + adaptive retrieval**: FTS5/BM25 lexical search fused with vector search via
  Reciprocal Rank Fusion; `mode = auto | semantic | lexical | hybrid` with a query-shape
  heuristic for `auto`.
- **Incremental indexing**: index keyed by commit SHA; only changed/added files are
  re-embedded, removed files are dropped; `/status` endpoint + `engine.status()`.
- **MCP server** (FastMCP, streamable-HTTP): `semantic_code_search`, `get_symbol`,
  `index`, `status` tools; `quolab mcp` CLI command.
- **Embedders**: `gemini` (default, with tenacity retry), `local` (stub), and `hash`
  (deterministic, offline — for CI/dev). Concurrent batch embedding during indexing.
- **Fetch paths**: shallow git clone, GitLab REST (read-only), and local-directory
  passthrough; vendored/build/cache dirs excluded from indexing.
- **Merge-gate policy CLI** (`python -m quolab.policy_cli`) over the SARIF policy engine.
- **OSS infra**: GitHub Actions CI (lint/type/test 3.10–3.12, build, PyPI + GHCR on
  release), a dogfood retrieval benchmark gate (`bench/`), a composite GitHub Action
  (`action.yml`), and a GitLab CI template (`ci/`).
- **Quorum integration** (in the quorum repo, on a feature branch): `GitLabSemanticClient`
  + `QUORUM_MCP_MODE=semantic` so Quorum uses quolab when GitLab Ultimate is absent.

## [0.1.0] — 2026-06-17

### Added
- Initial bootstrap: from-scratch semantic code search service (git clone → tree-sitter
  → Gemini embeddings → SQLite/pgvector → FastAPI `/search` + CLI) and a SARIF
  merge-gate policy engine. Apache-2.0.
