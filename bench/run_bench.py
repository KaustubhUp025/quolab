#!/usr/bin/env python3
"""quolab retrieval benchmark — the CI quality gate (dogfoods quolab on itself).

Indexes a target repo and checks that each fixture query retrieves the expected file.
Runs fully offline with the deterministic ``hash`` embedder, so it needs no Gemini key;
fixtures use lexical mode (the key-free, deterministic signal). Reports found@k and
precision@1 and exits non-zero if found@k drops below the threshold — so a search-quality
regression blocks the merge.

Usage:
    python bench/run_bench.py [TARGET_DIR] [-k N] [--min 0.8]
Env:
    QUOLAB_BENCH_MIN   override the found@k threshold (default 0.8)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from quolab.config import Settings
from quolab.embedder import HashEmbedder
from quolab.engine import SearchEngine
from quolab.store import SqliteVecStore

_FIXTURES = Path(__file__).parent / "fixtures" / "queries.json"


def run(target: str, k: int, threshold: float) -> int:
    fixtures = json.loads(_FIXTURES.read_text())
    tmp = tempfile.mkdtemp(prefix="quolab-bench-")
    settings = Settings(
        embedder="hash", store="sqlite", sqlite_path=str(Path(tmp) / "bench.db")
    )
    engine = SearchEngine(
        settings=settings, embedder=HashEmbedder(settings.embed_dim),
        store=SqliteVecStore(settings.sqlite_path),
    )
    stats = engine.index(target)
    print(f"indexed {stats.files} files, {stats.chunks} chunks from {target!r}")

    found = 0
    p1 = 0
    for fx in fixtures:
        results = engine.search(
            target, fx["query"], max_results=k, mode=fx.get("mode", "lexical")
        )
        paths = [r.chunk.path for r in results]
        hit_rank = next((i for i, p in enumerate(paths) if fx["expect"] in p), None)
        if hit_rank is not None:
            found += 1
            if hit_rank == 0:
                p1 += 1
        flag = "ok " if hit_rank is not None else "MISS"
        print(f"  [{flag}] {fx['query']!r} → expect {fx['expect']} "
              f"(rank={hit_rank if hit_rank is not None else '-'})")

    n = len(fixtures)
    found_at_k = found / n
    prec_at_1 = p1 / n
    print(f"\nfound@{k} = {found_at_k:.2f}   precision@1 = {prec_at_1:.2f}   (threshold {threshold:.2f})")
    if found_at_k < threshold:
        print("BENCH FAILED: retrieval quality below threshold", file=sys.stderr)
        return 1
    print("BENCH PASSED")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="quolab retrieval benchmark")
    ap.add_argument("target", nargs="?", default=".", help="repo dir or clone URL")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--min", type=float, default=float(os.environ.get("QUOLAB_BENCH_MIN", "0.8")))
    args = ap.parse_args(argv)
    return run(args.target, args.k, args.min)


if __name__ == "__main__":
    sys.exit(main())
