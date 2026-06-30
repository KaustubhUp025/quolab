#!/usr/bin/env python3
"""Evaluate quolab's embedder on the CoIR benchmark (NDCG@10) — the leaderboard-comparable
number for a release.

This is intentionally OUTSIDE the CI gate: it needs network access and downloads multi-GB
datasets + a real embedding model. The fast, offline ranking signal lives in
``bench/run_bench.py`` (dogfood NDCG@10). Run this manually before cutting a release:

    pip install -e '.[local,bench]'
    QUOLAB_EMBEDDER=local python bench/coir_eval.py --tasks codesearchnet

It wraps quolab's configured :class:`~quolab.embedder.Embedder` in the lightweight
encode_queries/encode_corpus interface CoIR expects, so the exact model quolab serves is
the model that gets scored — no separate eval path to drift out of sync.
"""

from __future__ import annotations

import argparse
import sys

from quolab.config import Settings
from quolab.embedder import make_embedder


class _QuolabCoIRModel:
    """Adapt quolab's Embedder to CoIR's encode_queries / encode_corpus contract."""

    def __init__(self, settings: Settings) -> None:
        self._embedder = make_embedder(settings)

    def encode_queries(self, queries: list[str], batch_size: int = 64, **_) -> list[list[float]]:
        return [self._embedder.embed_query(q) for q in queries]

    def encode_corpus(self, corpus: list, batch_size: int = 64, **_) -> list[list[float]]:
        # CoIR corpus entries are dicts {"title": ..., "text": ...} (or plain strings).
        def _text(item) -> str:
            if isinstance(item, dict):
                return (item.get("title", "") + "\n" + item.get("text", "")).strip()
            return str(item)

        texts = [_text(it) for it in corpus]
        out: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            out.extend(self._embedder.embed_documents(texts[i:i + batch_size]))
        return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate quolab's embedder on CoIR")
    ap.add_argument("--tasks", nargs="+", default=["codesearchnet"],
                    help="CoIR task names (e.g. codesearchnet, cosqa, codetrans-dl)")
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--output", default="bench/coir_results")
    args = ap.parse_args(argv)

    try:
        from coir.data_loader import get_tasks
        from coir.evaluation import COIR
    except ImportError:
        print("CoIR is not installed. Run: pip install -e '.[bench]'", file=sys.stderr)
        return 2

    model = _QuolabCoIRModel(Settings())
    tasks = get_tasks(tasks=args.tasks)
    evaluation = COIR(tasks=tasks, batch_size=args.batch_size)
    results = evaluation.run(model, output_folder=args.output)
    print("CoIR results (NDCG@10 per task):")
    for task, metrics in results.items():
        ndcg10 = metrics.get("NDCG@10") or metrics.get("ndcg_at_10")
        print(f"  {task}: NDCG@10 = {ndcg10}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
