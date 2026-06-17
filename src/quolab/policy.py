"""Merge-gate policy engine — an OSS stand-in for GitLab Ultimate's
*Merge Request Approval / Scan-Result Policies*.

It consumes SARIF (the format Quorum already emits) plus a small YAML policy, decides
whether a merge should be blocked, and (optionally) reports the decision as a
free-tier **commit status** via the GitLab REST API — no paid tier required.

Policy YAML example::

    block_on: [error]          # SARIF levels that block the merge
    warn_on: [warning]         # levels reported but not blocking
    max_findings: 50           # block if more than this many findings total
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

log = structlog.get_logger(__name__)

# SARIF level → severity bucket (mirrors Quorum's mapping).
_DEFAULT_BLOCK = ("error",)
_DEFAULT_WARN = ("warning",)


@dataclass
class Policy:
    block_on: tuple[str, ...] = _DEFAULT_BLOCK
    warn_on: tuple[str, ...] = _DEFAULT_WARN
    max_findings: int | None = None

    @classmethod
    def from_yaml(cls, text: str) -> "Policy":
        import yaml

        data = yaml.safe_load(text) or {}
        return cls(
            block_on=tuple(data.get("block_on", _DEFAULT_BLOCK)),
            warn_on=tuple(data.get("warn_on", _DEFAULT_WARN)),
            max_findings=data.get("max_findings"),
        )


@dataclass
class GateDecision:
    state: str  # "success" | "failed"
    blocking: int = 0
    warnings: int = 0
    total: int = 0
    reasons: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.state == "success"


def _iter_levels(sarif: dict):
    """Yield the SARIF ``level`` for every result across all runs."""
    for run in sarif.get("runs", []):
        # rule-id → default level (from the rule's defaultConfiguration)
        rule_levels = {
            r.get("id"): r.get("defaultConfiguration", {}).get("level")
            for r in run.get("tool", {}).get("driver", {}).get("rules", [])
        }
        for res in run.get("results", []):
            level = res.get("level") or rule_levels.get(res.get("ruleId")) or "warning"
            yield level


def evaluate(sarif: dict, policy: Policy) -> GateDecision:
    """Evaluate a SARIF report against a policy and return the gate decision."""
    levels = list(_iter_levels(sarif))
    blocking = sum(1 for lvl in levels if lvl in policy.block_on)
    warnings = sum(1 for lvl in levels if lvl in policy.warn_on)
    total = len(levels)

    reasons: list[str] = []
    if blocking:
        reasons.append(f"{blocking} finding(s) at blocking level {list(policy.block_on)}")
    if policy.max_findings is not None and total > policy.max_findings:
        reasons.append(f"{total} findings exceeds max_findings={policy.max_findings}")

    state = "failed" if reasons else "success"
    decision = GateDecision(
        state=state, blocking=blocking, warnings=warnings, total=total, reasons=reasons
    )
    log.info("gate_evaluated", state=state, blocking=blocking, warnings=warnings, total=total)
    return decision


async def post_commit_status(
    *,
    gitlab_url: str,
    token: str,
    project_id: str,
    sha: str,
    decision: GateDecision,
    name: str = "quolab/merge-gate",
    target_url: str | None = None,
) -> int:
    """Report the gate decision as a GitLab commit status (free-tier API).

    Returns the HTTP status code. Uses ``POST /projects/:id/statuses/:sha``.
    """
    import httpx
    from urllib.parse import quote

    pid = quote(project_id, safe="") if "/" in project_id else project_id
    desc = "; ".join(decision.reasons) if decision.reasons else "all coordination checks passed"
    payload = {
        "state": decision.state,
        "name": name,
        "description": desc[:255],
    }
    if target_url:
        payload["target_url"] = target_url

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{gitlab_url.rstrip('/')}/api/v4/projects/{pid}/statuses/{sha}",
            headers={"PRIVATE-TOKEN": token},
            params=payload,
        )
    log.info("commit_status_posted", code=resp.status_code, state=decision.state)
    return resp.status_code
