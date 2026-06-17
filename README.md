<p align="center">
  <img src="src/quolab/static/logo.svg" alt="quolab" height="56">
</p>

# quolab

> The logo reuses [Quorum](../quorum)'s consensus ring as the **lens of a magnifying
> glass** — quolab is Quorum's lab: the same consensus motif, now powering code search.

**An open-source slice of GitLab Ultimate.** `quolab` is a small, self-hostable
service that gives you the two GitLab Ultimate features that actually matter for an
automated code reviewer — without a paid tier:

1. **Semantic code search** — AI-powered, cross-file code search built from scratch
   (git clone → tree-sitter chunking → embeddings → vector search). A drop-in
   replacement for GitLab Ultimate's *Advanced / GitLab Duo code search*.
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
pip install -e ".[dev,treesitter]"  # add ",pg" for Postgres, ",mcp" for the MCP shim
cp .env.example .env             # set QUOLAB_GEMINI_API_KEY
uvicorn quolab.app:app --port 8080

# index + search a public repo
curl -X POST localhost:8080/index  -d '{"project_id":"https://gitlab.com/group/repo"}'
curl -X POST localhost:8080/search -d '{"project_id":"https://gitlab.com/group/repo","query":"saga compensation handler"}'
```

## Architecture

```
repo (git clone / GitLab REST, free)
      │
      ▼
 tree-sitter chunking  ──►  Gemini embeddings  ──►  vector store (sqlite-vec | pgvector)
                                                            │
                          POST /search  ◄────────  cosine top-k
                          MCP semantic_code_search tool (optional)
```

- **Embeddings:** Gemini embedding API by default (free, no GPU). Pluggable — a local
  OSS model (Qwen3-Embedding / nomic-embed-code) can be swapped via `QUOLAB_EMBEDDER=local`.
- **Store:** `sqlite-vec` for zero-infra local use; `pgvector` for production.
- **Output:** `/search` returns results in the same text shape Quorum's REST search
  produces, so integration is a drop-in.

## License

Apache-2.0. See [LICENSE](LICENSE).
