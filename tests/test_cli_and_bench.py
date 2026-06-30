"""Tests for the hash embedder, policy CLI, and benchmark harness."""

from __future__ import annotations

import json

from quolab.embedder import HashEmbedder


def test_hash_embedder_is_deterministic_and_normalized():
    e = HashEmbedder(dim=64)
    v1 = e.embed_query("acquire_lock")
    v2 = e.embed_query("acquire_lock")
    assert v1 == v2                       # deterministic
    assert len(v1) == 64
    import math
    assert abs(math.sqrt(sum(x * x for x in v1)) - 1.0) < 1e-6   # unit norm


def test_policy_cli_blocks_on_critical(tmp_path, capsys):
    from quolab.policy_cli import main

    sarif = tmp_path / "r.sarif"
    sarif.write_text(json.dumps({
        "runs": [{"tool": {"driver": {"name": "quorum", "rules": []}},
                  "results": [{"ruleId": "R1", "level": "error"}]}]
    }))
    rc = main([str(sarif)])
    assert rc == 1
    assert "blocking=1" in capsys.readouterr().out


def test_policy_cli_passes_clean(tmp_path):
    from quolab.policy_cli import main

    sarif = tmp_path / "r.sarif"
    sarif.write_text(json.dumps({
        "runs": [{"tool": {"driver": {"name": "quorum", "rules": []}}, "results": []}]
    }))
    assert main([str(sarif)]) == 0


def test_bench_runs_on_self():
    # point the bench at this repo; offline hash embedder, lexical fixtures
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    import bench.run_bench as bench

    found_at_k, prec_at_1, ndcg = bench.run(".", k=5, embedder="hash")  # offline, lexical
    assert found_at_k >= 0.8     # lexical retrieval on identifiers is strong & deterministic
    assert 0.0 <= prec_at_1 <= 1.0
    assert 0.0 <= ndcg <= 1.0    # NDCG@10 graded-ranking metric
