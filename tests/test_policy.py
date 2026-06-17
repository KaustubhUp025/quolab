from quolab.policy import Policy, evaluate


def _sarif(levels):
    return {
        "runs": [
            {
                "tool": {"driver": {"name": "quorum", "rules": []}},
                "results": [{"ruleId": f"R{i}", "level": lvl} for i, lvl in enumerate(levels)],
            }
        ]
    }


def test_blocks_on_error():
    decision = evaluate(_sarif(["error", "warning"]), Policy())
    assert decision.state == "failed"
    assert decision.blocking == 1
    assert decision.warnings == 1
    assert not decision.passed


def test_passes_when_only_warnings():
    decision = evaluate(_sarif(["warning", "warning"]), Policy())
    assert decision.passed
    assert decision.state == "success"


def test_max_findings_blocks():
    decision = evaluate(_sarif(["note"] * 5), Policy(block_on=("error",), max_findings=3))
    assert decision.state == "failed"
    assert any("exceeds max_findings" in r for r in decision.reasons)


def test_rule_default_level_used_when_result_has_no_level():
    sarif = {
        "runs": [
            {
                "tool": {"driver": {"name": "quorum", "rules": [
                    {"id": "R1", "defaultConfiguration": {"level": "error"}},
                ]}},
                "results": [{"ruleId": "R1"}],
            }
        ]
    }
    assert evaluate(sarif, Policy()).blocking == 1


def test_policy_from_yaml():
    p = Policy.from_yaml("block_on: [error, warning]\nmax_findings: 10\n")
    assert p.block_on == ("error", "warning")
    assert p.max_findings == 10
