# Changelog

All notable changes to quolab are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versioning is [SemVer](https://semver.org/).

## [Unreleased]

### Changed
- **Default embedder is now `local`** (`Qwen/Qwen3-Embedding-0.6B` via sentence-transformers)
  — runs on-device (auto GPU/fp16 with CPU fallback), needs **no API key and has no rate
  limit**. The hosted `gemini` embedder is now opt-in behind the `[gemini]` extra
  (`pip install 'quolab[gemini]'`); `google-genai` is no longer a required dependency.
  Default embedding dimension changed 768 → 1024 (Qwen3 native), so re-index with `--force`
  when migrating an existing index. Measured quality on the dogfood benchmark: local matches
  hosted Gemini on found@5 (0.83).

### Added
- **Hybrid + adaptive retrieval**: FTS5/BM25 lexical search fused with vector search via
  Reciprocal Rank Fusion; `mode = auto | semantic | lexical | hybrid` with a query-shape
  heuristic for `auto`.
- **Incremental indexing**: index keyed by commit SHA; only changed/added files are
  re-embedded, removed files are dropped; `/status` endpoint + `engine.status()`.
- **MCP server** (FastMCP, streamable-HTTP): `semantic_code_search`, `get_symbol`,
  `index`, `status` tools; `quolab mcp` CLI command.
- **Embedders**: `local` (default, on-device via sentence-transformers), `gemini` (opt-in
  hosted API, with tenacity retry), and `hash` (deterministic, offline — for CI/dev).
  Concurrent batch embedding during indexing.
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
