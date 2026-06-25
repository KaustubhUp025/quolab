<p align="center">
  <img src="src/quolab/static/logo.svg" alt="quolab" height="56">
</p>

<p align="center">
  <a href="https://github.com/KaustubhUp025/quolab/actions/workflows/ci.yml"><img src="https://github.com/KaustubhUp025/quolab/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.10%E2%80%933.12-blue" alt="python">
  <img src="https://img.shields.io/badge/license-Apache--2.0-green" alt="license">
  <img src="https://img.shields.io/badge/search-hybrid%20(BM25%2Bvector%2BRRF)-purple" alt="hybrid search">
  <img src="https://img.shields.io/badge/MCP-FastMCP-purple" alt="mcp">
</p>

# quolab

> The logo reuses [Quorum](../quorum)'s consensus ring as the **lens of a magnifying
> glass** — quolab is Quorum's lab: the same consensus motif, now powering code search.

**An open-source slice of GitLab Ultimate.** `quolab` is a small, self-hostable
service that gives you the two GitLab Ultimate features that actually matter for an
automated code reviewer — without a paid tier:

1. **Semantic code search** — AI-powered, cross-file code search built from scratch
   (git clone → tree-sitter chunking → embeddings → vector search). Runs **fully
   on-device by default (no API key, no rate limit)** via a local embedding model.
   A drop-in replacement for GitLab Ultimate's *Advanced / GitLab Duo code search*.
2. **A merge-gate policy engine** — consumes SARIF findings and gates merges via
   free-tier commit statuses. A lightweight stand-in for Ultimate's *Merge Request
   Approval / Scan-Result Policies*.
3. **A findings dashboard** — aggregates SARIF findings across projects over time, a
   minimal stand-in for Ultimate's *Security Dashboard*.

## Why this exists

It was built to keep the [Quorum](../quorum) coordination-bug reviewer fully
functional after a GitLab Ultimate trial ends. Quorum's one load-bearing Ultimate
dependency is **semantic code search**; everything else it does runs on the free
tier. `quolab` restores that capability as an independent open-source project so
Quorum (or any tool) can plug into it via one HTTP endpoint or MCP tool — no paid
GitLab plan required.

`quolab` is intentionally **separate from Quorum**: its own repo, its own roadmap.
Quorum consumes it through a thin adapter; nothing here depends on Quorum.

## Quickstart

```bash
pip install -e ".[dev,treesitter,local]"  # add ",pg" for Postgres, ",mcp" for the MCP shim
cp .env.example .env             # defaults to the local embedder — no API key needed
uvicorn quolab.app:app --port 8080

# index + search a public repo
curl -X POST localhost:8080/index  -d '{"project_id":"https://gitlab.com/group/repo"}'
curl -X POST localhost:8080/search -d '{"project_id":"https://gitlab.com/group/repo","query":"saga compensation handler"}'
```

## Architecture

```
repo (git clone / GitLab REST / local)
      │
      ▼
 tree-sitter chunking ─► embeddings (local | gemini | hash) ─► store (sqlite+FTS5 | pgvector)
                                                                   │
                            ┌──────────────── hybrid retrieval ────┘
                            │   lexical (BM25)  ⊕  vector  →  Reciprocal Rank Fusion
                            ▼
              REST  /search    ·    MCP  semantic_code_search    ·    CLI  quolab search
```

### Search modes (`mode=`)
- **`auto`** (default) — picks per query: code-shaped queries → `hybrid`, natural language → `semantic`.
- **`hybrid`** — BM25 ⊕ vector fused with RRF (best recall for code; exact identifiers + intent).
- **`semantic`** — vector only. **`lexical`** — BM25/FTS5 only.

### Three ways to run it
- **CLI:** `quolab search <repo> "where is the lock acquired" --mode auto`
- **REST:** `POST /search` (returns Quorum's REST-search text shape — drop-in)
- **MCP:** `quolab mcp` → FastMCP streamable-HTTP `semantic_code_search` tool for agents

### Embeddings & store
- **Embeddings:** `local` by default — `Qwen/Qwen3-Embedding-0.6B` via sentence-transformers,
  on-device (auto GPU/fp16, CPU fallback), **no API key, no rate limit**. Also `gemini`
  (opt-in hosted API; `pip install 'quolab[gemini]'`) and `hash` (deterministic, offline for CI/dev).
- **Store:** SQLite (numpy cosine + FTS5) for zero-infra local; `pgvector` for production.
- **Indexing:** incremental by commit SHA — only changed files are re-embedded.

> **Local model note:** the default embedder downloads ~1.2 GB on first use (cached in
> `~/.cache/huggingface`) and runs entirely on your machine — fp16 fits a 4 GB GPU, and it
> falls back to CPU automatically. No key, no per-request network call, no rate limit.
> The `hash` embedder needs no model at all (lexical/hybrid still work; only pure-semantic
> quality drops). The hosted `gemini` path remains available but is subject to the AI Studio
> free-tier cap of ~100 `embed_content` requests/min.

### Measured quality (dogfooding quolab on its own `src/`, 6 natural-language queries)

| embedder | mode | found@5 | precision@1 |
|---|---|---|---|
| `hash` (offline) | semantic | 0.67 (chance) | **0.00** |
| `local` (Qwen3-0.6B, **default**) | semantic | **0.83** | **0.50** |
| `gemini` (hosted) | semantic | **0.83** | **0.67** |

On conceptual queries that don't contain the code's identifiers, real embeddings rank the
right file first far more often than the offline baseline. The default **local** Qwen3 model
matches hosted Gemini on found@5 (0.83) with no API key or rate limit, at a small
precision@1 cost. Reproduce the default (local) row with
`python bench/run_bench.py src/quolab --embedder local --mode semantic --fixtures bench/fixtures/queries_semantic.json`.

## Use it with Quorum (no GitLab Ultimate)

Quorum's only Ultimate dependency is semantic search. Point it at quolab:

```bash
quolab serve --port 8080                 # or deploy to Cloud Run
# in Quorum's environment:
export QUORUM_MCP_MODE=semantic
export QUORUM_SEARCH_URL=http://localhost:8080
quorum review <merge-request-url>        # uses quolab; falls back to REST if it's down
```

Also ships a **GitHub Action** (`action.yml`) and a **GitLab CI template** (`ci/`) for
one-step "index → search → merge-gate" in any pipeline.

## License

Apache-2.0. See [LICENSE](LICENSE).
