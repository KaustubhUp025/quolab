# Contributing to quolab

Thanks for your interest! quolab is an open-source slice of GitLab Ultimate —
semantic code search + a merge-gate policy engine — built so tools like
[Quorum](https://github.com/KaustubhUp025/quorum) keep working without a paid tier.

## Dev setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,treesitter,mcp]"
pytest -q                 # 38+ tests, fully offline
ruff check src tests      # lint
python bench/run_bench.py .   # retrieval benchmark (offline, hash embedder)
```

No API key is needed for development: tests and the benchmark use the deterministic
`hash` embedder. For real semantic results, set `QUOLAB_GEMINI_API_KEY` and use the
default `gemini` embedder.

## Architecture (where things live)

- `indexer.py` — fetch (git clone / GitLab REST / local path) + tree-sitter chunking
- `embedder.py` — `Embedder` interface: `gemini` (default), `local`, `hash` (offline)
- `store.py` — `SqliteVecStore` (FTS5 + numpy cosine) / `PgVectorStore`
- `retrieval.py` — RRF fusion + adaptive `mode` selection
- `engine.py` — orchestration: incremental index + hybrid search
- `app.py` / `mcp_server.py` / `cli.py` — REST, MCP, and CLI front-ends
- `policy.py` / `policy_cli.py` — SARIF-driven merge-gate

## Ground rules

- Keep it dependency-light; heavy backends (tree-sitter, pgvector, local models, mcp)
  stay optional extras with graceful fallbacks.
- Every change keeps `pytest` green and `ruff` clean; the dogfood benchmark must stay
  above its threshold.
- New retrieval behaviour needs a test; new config needs a `.env.example` line.

## Submitting

Open a PR against `main`. CI runs lint + types + tests (3.10–3.12) + the dogfood
benchmark. By contributing you agree your work is licensed under Apache-2.0.
