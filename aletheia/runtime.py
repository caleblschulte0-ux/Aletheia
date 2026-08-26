"""Local runtime tick for schedules, reply monitoring, proactivity and gaps.

This runs inside the loopback Core and operates on gitignored private state.
Every executable scheduled command is revalidated through the intercom grammar
and existing policy gates at execution time. The runtime never expands authority.
"""
from __future__ import annotations

import datetime as dt

from aletheia import act, communications, gaps, intercom, notifications, policy, scheduler, tasks

TERMINAL_TASKS = {"COMPLETED", "CANCELLED", "FAILED_TERMINAL"}


def run_due_schedules(fleet: dict, *, now: dt.datetime | None = None, request=None) -> list[dict]:
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    results = []
    for spec in scheduler.all_schedules():
        occurrence = scheduler.occurrence_at_or_before(spec, now)
        if occurrence is None:
            continue
        # Validate before claiming so a malformed schedule can be repaired and
        # is not permanently swallowed by a receipt.
        problems = intercom.validate_kind_args(spec["command"], fleet)
        if problems:
            results.append({"schedule": spec["id"], "outcome": "invalid",
                            "detail": "; ".join(problems)})
            continue
        if policy.halted() and spec["command"]["kind"] != "resume":
            results.append({"schedule": spec["id"], "outcome": "halted",
                            "detail": "kill switch is on"})
            continue
        receipt = scheduler.claim_due(spec, now=now)
        if receipt is None:
            continue
        try:
            kwargs = {"quote": f"private schedule {spec['id']}"}
            if request is not None:
                kwargs["request"] = request
            detail = intercom.execute_command(spec["command"], fleet, **kwargs)
            results.append({"schedule": spec["id"], "occurrence": receipt["occurrence"],
                            "outcome": "done", "detail": detail})
        except act.Refused as exc:
            results.append({"schedule": spec["id"], "occurrence": receipt["occurrence"],
                            "outcome": "refused", "detail": str(exc)})
        except Exception as exc:
            results.append({"schedule": spec["id"], "occurrence": receipt["occurrence"],
                            "outcome": "error", "detail": f"{type(exc).__name__}: {exc}"})
    return results


def evaluate_replies(*, now: dt.datetime | None = None) -> list[dict]:
    """Evaluate reply expectations and surface only state transitions."""
    before = {e["id"]: e.get("status") for e in communications.all_expectations()}
    after = communications.evaluate_all(now=now)
    transitions = []
    for value in after:
        old, new = before.get(value["id"]), value.get("status")
        if old == new:
            continue
        transitions.append({"expectation": value["id"], "from": old, "to": new})
        if new == "REPLIED":
            notifications.publish("Reply received", f"Tracked conversation {value['thread_id']} has a reply.",
                                  priority="IMPORTANT", source="communications",
                                  dedupe_key=f"reply:{value['id']}", related={"expectation": value["id"]})
        elif new == "OVERDUE":
            notifications.publish("Reply overdue", f"No tracked reply arrived before the deadline for {value['thread_id']}.",
                                  priority="IMPORTANT", source="communications",
                                  dedupe_key=f"overdue:{value['id']}", related={"expectation": value["id"]})
    return transitions


def reconcile_task_gaps(*, registry: dict | None = None) -> list[dict]:
    """Phase 20: turn capability gaps into work and resume when they close."""
    actions = []
    for task in tasks.all_tasks():
        if task.get("status") in TERMINAL_TASKS:
            continue
        required = task.get("required_capabilities") or []
        if not required:
            continue
        report = gaps.assess(required, registry=registry)
        if report["satisfied"]:
            if task["status"] in {"WAITING_DEPENDENCY", "WAITING_OPERATOR", "BLOCKED"} and \
               str(task.get("result", "")).startswith("capability gap:"):
                resumed = tasks.set_status(task["id"], "QUEUED", "capability gap: closed; original work resumed")
                actions.append({"task": task["id"], "action": "resumed", "status": resumed["status"]})
            continue
        gap_tasks = gaps.materialize(required, registry=registry)
        statuses = {item["status"] for item in report["blocked"]}
        wait_state = "WAITING_OPERATOR" if statuses and statuses <= {"NEEDS_CONFIGURATION"} else "WAITING_DEPENDENCY"
        note = "capability gap: " + ", ".join(
            [f"{item['id']}={item['status']}" for item in report["blocked"]] +
            [f"{cid}=UNKNOWN" for cid in report["unknown"]])
        if task["status"] not in {wait_state, "RUNNING"}:
            tasks.set_status(task["id"], wait_state, note)
        actions.append({"task": task["id"], "action": "gap_materialized",
                        "gap_tasks": [g["id"] for g in gap_tasks], "waiting": wait_state})
    return actions


def tick(fleet: dict, *, now: dt.datetime | None = None, registry: dict | None = None,
         request=None) -> dict:
    return {
        "schedules": run_due_schedules(fleet, now=now, request=request),
        "reply_transitions": evaluate_replies(now=now),
        "capability_gaps": reconcile_task_gaps(registry=registry),
    }
