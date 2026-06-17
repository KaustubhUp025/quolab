"""CLI for the merge-gate policy engine: evaluate a SARIF report against a policy.

    python -m quolab.policy_cli quorum.sarif --policy .quolab-policy.yml

Exits 0 when the gate passes, 1 when it blocks — so it can gate a CI pipeline.
Optionally posts a GitLab commit status when --project/--sha/--token are given.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from quolab.policy import Policy, evaluate, post_commit_status


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="quolab merge-gate policy")
    ap.add_argument("sarif", help="path to a SARIF report")
    ap.add_argument("--policy", default="", help="path to a YAML policy (defaults applied if omitted)")
    ap.add_argument("--gitlab-url", default="https://gitlab.com")
    ap.add_argument("--project", default="", help="project id/path (to post a commit status)")
    ap.add_argument("--sha", default="", help="commit sha (to post a commit status)")
    ap.add_argument("--token", default="", help="GitLab token (to post a commit status)")
    args = ap.parse_args(argv)

    sarif = json.loads(Path(args.sarif).read_text())
    policy = (
        Policy.from_yaml(Path(args.policy).read_text())
        if args.policy and Path(args.policy).exists()
        else Policy()
    )
    decision = evaluate(sarif, policy)
    print(f"gate: {decision.state}  blocking={decision.blocking}  warnings={decision.warnings}  "
          f"total={decision.total}")
    for reason in decision.reasons:
        print(f"  - {reason}")

    if args.project and args.sha and args.token:
        code = asyncio.run(post_commit_status(
            gitlab_url=args.gitlab_url, token=args.token, project_id=args.project,
            sha=args.sha, decision=decision,
        ))
        print(f"posted commit status (HTTP {code})")

    return 0 if decision.passed else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
