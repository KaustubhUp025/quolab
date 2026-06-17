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
from quolab.embedder import make_embedder
from quolab.engine import SearchEngine
from quolab.store import SqliteVecStore

_FIXTURE_DIR = Path(__file__).parent / "fixtures"


def run(
    target: str,
    k: int = 5,
    threshold: float = 0.8,
    embedder: str = "hash",
    mode: str | None = None,
    fixtures_path: str | None = None,
) -> tuple[float, float]:
    """Index ``target`` and score fixture queries. Returns (found@k, precision@1)."""
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

    found = p1 = 0
    for fx in fixtures:
        run_mode = mode or fx.get("mode", "lexical")
        results = engine.search(target, fx["query"], max_results=k, mode=run_mode)
        paths = [r.chunk.path for r in results]
        rank = next((i for i, p in enumerate(paths) if fx["expect"] in p), None)
        if rank is not None:
            found += 1
            p1 += rank == 0
        flag = "ok " if rank is not None else "MISS"
        print(f"  [{flag}] {fx['query']!r} → {fx['expect']} (rank={rank if rank is not None else '-'})")

    n = len(fixtures)
    found_at_k, prec_at_1 = found / n, p1 / n
    print(f"  → found@{k} = {found_at_k:.2f}   precision@1 = {prec_at_1:.2f}")
    return found_at_k, prec_at_1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="quolab retrieval benchmark")
    ap.add_argument("target", nargs="?", default=".", help="repo dir or clone URL")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--min", type=float, default=float(os.environ.get("QUOLAB_BENCH_MIN", "0.8")))
    ap.add_argument("--embedder", default=os.environ.get("QUOLAB_EMBEDDER", "hash"))
    ap.add_argument("--mode", default=None, help="override fixture mode (auto|semantic|lexical|hybrid)")
    ap.add_argument("--fixtures", default=None, help="path to a fixtures json")
    args = ap.parse_args(argv)
    found_at_k, _ = run(args.target, args.k, args.min, args.embedder, args.mode, args.fixtures)
    if found_at_k < args.min:
        print("BENCH FAILED: retrieval quality below threshold", file=sys.stderr)
        return 1
    print("BENCH PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
