#!/usr/bin/env python3
"""quolab retrieval benchmark — the CI quality gate (dogfoods quolab on itself).

Indexes a target repo and checks that each fixture query retrieves the expected file.
Runs fully offline with the deterministic ``hash`` embedder, so it needs no Gemini key;
fixtures use lexical mode (the key-free, deterministic signal). Reports found@k,
precision@1 and **NDCG@10** (the CoIR-standard graded-ranking metric, see bench/coir_eval.py
for the full leaderboard-comparable eval) and exits non-zero if found@k drops below the
threshold — so a search-quality regression blocks the merge.

Fixtures carry ``expect`` (a path substring of the single relevant file). They may also
carry ``relevant``: a {path-substring: gain} map for graded NDCG; absent → {expect: 1}.

Usage:
    python bench/run_bench.py [TARGET_DIR] [-k N] [--min 0.8]
Env:
    QUOLAB_BENCH_MIN   override the found@k threshold (default 0.8)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from pathlib import Path

from quolab.config import Settings
from quolab.embedder import make_embedder
from quolab.engine import SearchEngine
from quolab.store import SqliteVecStore

_FIXTURE_DIR = Path(__file__).parent / "fixtures"
_NDCG_K = 10


def _relevance(fx: dict) -> dict[str, float]:
    """Graded relevance map for a fixture: {path-substring: gain}."""
    rel = fx.get("relevant")
    if isinstance(rel, dict) and rel:
        return {str(k): float(v) for k, v in rel.items()}
    return {fx["expect"]: 1.0}


def _ndcg_at_k(paths: list[str], relevant: dict[str, float], k: int) -> float:
    """NDCG@k with graded gains. A relevance key matches a result at a path boundary
    (exact path or ``/``-prefixed suffix) so e.g. ``retrieval.py`` does not also match
    ``tests/test_retrieval.py`` — which would let DCG exceed IDCG."""
    def gain(path: str) -> float:
        return max(
            (g for sub, g in relevant.items() if path == sub or path.endswith("/" + sub)),
            default=0.0,
        )

    dcg = sum(gain(p) / math.log2(i + 2) for i, p in enumerate(paths[:k]) if gain(p))
    ideal = sorted(relevant.values(), reverse=True)[:k]
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def run(
    target: str,
    k: int = 5,
    threshold: float = 0.8,
    embedder: str = "hash",
    mode: str | None = None,
    fixtures_path: str | None = None,
) -> tuple[float, float, float]:
    """Index ``target`` and score fixture queries. Returns (found@k, precision@1, ndcg@10)."""
    path = Path(fixtures_path) if fixtures_path else _FIXTURE_DIR / "queries.json"
    fixtures = json.loads(path.read_text())
    tmp = tempfile.mkdtemp(prefix="quolab-bench-")
    settings = Settings(
        embedder=embedder, store="sqlite", sqlite_path=str(Path(tmp) / "bench.db")
    )
    engine = SearchEngine(
        settings=settings, embedder=make_embedder(settings),
        store=SqliteVecStore(settings.sqlite_path),
    )
    stats = engine.index(target)
    print(f"[embedder={embedder} mode={mode or 'fixture'}] "
          f"indexed {stats.files} files, {stats.chunks} chunks from {target!r}")

    topn = max(k, _NDCG_K)
    found = p1 = 0
    ndcg_total = 0.0
    for fx in fixtures:
        run_mode = mode or fx.get("mode", "lexical")
        results = engine.search(target, fx["query"], max_results=topn, mode=run_mode)
        # Relevance is file-level but results are chunks; collapse to unique files in rank
        # order so the file is the retrievable unit (and NDCG stays in [0, 1]).
        seen: set[str] = set()
        paths = [p for r in results if (p := r.chunk.path) not in seen and not seen.add(p)]
        rank = next((i for i, p in enumerate(paths[:k]) if fx["expect"] in p), None)
        if rank is not None:
            found += 1
            p1 += rank == 0
        ndcg_total += _ndcg_at_k(paths, _relevance(fx), _NDCG_K)
        flag = "ok " if rank is not None else "MISS"
        print(f"  [{flag}] {fx['query']!r} → {fx['expect']} (rank={rank if rank is not None else '-'})")

    n = len(fixtures)
    found_at_k, prec_at_1, ndcg = found / n, p1 / n, ndcg_total / n
    print(f"  → found@{k} = {found_at_k:.2f}   precision@1 = {prec_at_1:.2f}   "
          f"NDCG@{_NDCG_K} = {ndcg:.3f}")
    return found_at_k, prec_at_1, ndcg


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="quolab retrieval benchmark")
    ap.add_argument("target", nargs="?", default=".", help="repo dir or clone URL")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--min", type=float, default=float(os.environ.get("QUOLAB_BENCH_MIN", "0.8")))
    ap.add_argument("--embedder", default=os.environ.get("QUOLAB_EMBEDDER", "hash"))
    ap.add_argument("--mode", default=None, help="override fixture mode (auto|semantic|lexical|hybrid)")
    ap.add_argument("--fixtures", default=None, help="path to a fixtures json")
    args = ap.parse_args(argv)
    found_at_k, _, _ = run(args.target, args.k, args.min, args.embedder, args.mode, args.fixtures)
    if found_at_k < args.min:
        print("BENCH FAILED: retrieval quality below threshold", file=sys.stderr)
        return 1
    print("BENCH PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
