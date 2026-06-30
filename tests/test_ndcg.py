"""E1 — NDCG@10 metric correctness (boundary matching, graded gains) + CoIR runner guard."""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bench.run_bench as bench  # noqa: E402


def test_perfect_ranking_is_one():
    paths = ["src/quolab/store.py", "a.py", "b.py"]
    assert bench._ndcg_at_k(paths, {"store.py": 1.0}, 10) == 1.0


def test_relevant_at_rank_two_is_discounted():
    paths = ["a.py", "src/quolab/store.py", "b.py"]
    expected = (1.0 / math.log2(3)) / 1.0  # gain at 0-based rank 1
    assert bench._ndcg_at_k(paths, {"store.py": 1.0}, 10) == expected


def test_boundary_match_excludes_test_file():
    # 'retrieval.py' must NOT match 'tests/test_retrieval.py' (would push NDCG > 1).
    paths = ["tests/test_retrieval.py", "src/quolab/retrieval.py"]
    ndcg = bench._ndcg_at_k(paths, {"retrieval.py": 1.0}, 10)
    assert 0.0 <= ndcg <= 1.0
    assert ndcg == (1.0 / math.log2(3))  # the real file sits at rank 1, test file ignored


def test_missing_relevant_is_zero():
    assert bench._ndcg_at_k(["a.py", "b.py"], {"store.py": 1.0}, 10) == 0.0


def test_graded_relevance_orders_by_gain():
    # Two relevant files with different gains; ideal puts the higher gain first.
    paths = ["src/quolab/engine.py", "src/quolab/store.py"]
    rel = {"engine.py": 3.0, "store.py": 1.0}
    dcg = 3.0 / math.log2(2) + 1.0 / math.log2(3)
    idcg = 3.0 / math.log2(2) + 1.0 / math.log2(3)
    assert bench._ndcg_at_k(paths, rel, 10) == dcg / idcg == 1.0


def test_coir_runner_reports_missing_dependency(capsys):
    # Without coir-eval installed, the runner exits 2 with a clear message (no crash).
    import bench.coir_eval as ce

    if "coir.evaluation" in sys.modules:
        return  # coir actually installed; nothing to assert
    rc = ce.main(["--tasks", "codesearchnet"])
    assert rc == 2
    assert "pip install" in capsys.readouterr().err
