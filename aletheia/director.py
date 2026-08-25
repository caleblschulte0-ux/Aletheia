"""The Agent Director V1 (Playbook §§64–68, 123; Phase 9).

Turns a READY task with an assigned worker into a **work order** — a
GitHub issue on this repo carrying the full §67 delegation contract
(goal, context, authority, constraints, expected output, success
criteria, reporting) — and parks the task WAITING_EXTERNAL until the
worker reports back through the task engine. The dependency chain lives
on disk, so it survives every restart (§123's acceptance).

Policy is enforced here, not assumed: `agent.delegate` is declared
`operator_once` in the capability registry, so each work order needs an
APPROVED approval first. No approval → the director REQUESTS one
(published as a 🔐 issue the operator can decide from a phone or through
Thea) and waits. Ability, then permission — never both in one step
(§70). Halted ⇒ nothing dispatches.

How a worker completes the loop today: a Claude session opens the work
order, does the work, records evidence via
`python -m aletheia.tasks status <id> COMPLETED --note "<evidence>"`,
and closes the issue. The orchestrator then folds the verified result
back into the goal. Programmatic worker WAKE-UP (no human starting the
session) is the remaining gap — tracked honestly in the registry notes.
"""
from __future__ import annotations

import argparse
import sys

from aletheia import gh, journal, plans, policy, tasks

WORK_ORDER_PREFIX = "🛠 Work order:"
DELEGATE_CAPABILITY = "agent.delegate"


def _approval_id(tid: str) -> str:
    return f"delegate-{tid}"


def render_work_order(task: dict) -> str:
    """The §67 delegation contract, rendered from durable state."""
    goal_line = "standalone task (no parent goal)"
    context = ""
    if task.get("goal"):
        try:
            plan = plans.load(task["goal"])
            goal_line = f"{plan['title']} (`{plan['slug']}`) — {plan['goal']}"
            done, total = plans.progress(plan)
            context = f"Goal progress: {done}/{total} steps done.\n"
        except FileNotFoundError:
            goal_line = f"`{task['goal']}` (plan file missing)"
    deps = ", ".join(f"`{d}`" for d in task.get("dependencies", [])) or "none"
    return (
        f"**GOAL:** {goal_line}\n\n"
        f"**TASK:** `{task['id']}` — {task['description']}\n\n"
        f"**CONTEXT:** {context}Dependencies (all COMPLETED): {deps}. "
        f"Attempt #{task.get('attempts', 0) + 1}.\n\n"
        f"**AUTHORITY:** Work on a `claude/*` branch of the relevant repo; "
        "capabilities per this repo's registries; nothing beyond them.\n\n"
        "**CONSTRAINTS:** The constitution (`CLAUDE.md`) and playbook apply. "
        "Never weaken a gate; never fake a capability.\n\n"
        "**EXPECTED OUTPUT:** The work itself, pushed/committed where it belongs.\n\n"
        "**SUCCESS CRITERIA:** Verifiable evidence — tests, CI, files, receipts. "
        "'Done' without evidence does not count (§68).\n\n"
        "**REPORTING:** `python -m aletheia.tasks status "
        f"{task['id']} COMPLETED --note \"<evidence>\"` (or FAILED_RETRYABLE / "
        "BLOCKED with a note), then close this issue.\n"
    )


def dispatch_ready(repo_full: str, request=gh.request) -> list[dict]:
    """One director pass. For each READY task with a worker:
    approval APPROVED → file the work order; no approval → request it
    (idempotently); DENIED → mark the task BLOCKED. Returns actions taken."""
    policy.ensure_not_halted()
    actions = []
    for task in tasks.ready():
        if not task.get("assigned_worker"):
            continue
        tid = task["id"]
        aid = _approval_id(tid)
        try:
            approval = policy.load(aid)
        except FileNotFoundError:
            policy.request(
                aid,
                requested_action=f"delegate task {tid} to {task['assigned_worker']}",
                reason=task["description"],
                consequence="a work-order issue is filed; the worker acts within "
                            "registry-granted authority",
                reversible=True, task=tid)
            policy.publish(aid, repo_full, request_fn=request)
            actions.append({"task": tid, "action": "approval_requested", "approval": aid})
            continue
        if approval["state"] == "PENDING":
            continue  # asked already — waiting on the operator, silently
        if approval["state"] == "DENIED":
            tasks.set_status(tid, "BLOCKED", f"delegation denied (approval {aid})")
            actions.append({"task": tid, "action": "blocked_by_denial"})
            continue
        issue = request("POST", f"/repos/{repo_full}/issues", {
            "title": f"{WORK_ORDER_PREFIX} {tid} — {task['description'][:70]}",
            "body": render_work_order(task),
        })
        number = (issue or {}).get("number", "?")
        tasks.set_status(tid, "WAITING_EXTERNAL",
                         f"work order issue #{number} filed for {task['assigned_worker']}")
        journal.append("action", f"director:{tid}",
                       f"work order #{number} -> {task['assigned_worker']}")
        actions.append({"task": tid, "action": "work_order_filed", "issue": number})
    return actions


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Delegate ready tasks to workers.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--repo", required=True, help="owner/name of this repo")
    args = ap.parse_args(argv)

    if not gh.token():
        print("no token — the director cannot file work orders; skipping honestly",
              file=sys.stderr)
        return 0
    try:
        actions = dispatch_ready(args.repo)
    except policy.Halted as exc:
        print(f"halted: {exc}")
        return 0
    for a in actions:
        print(a)
    if not actions:
        print("nothing to dispatch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
