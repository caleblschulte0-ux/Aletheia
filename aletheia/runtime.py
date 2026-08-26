"""Local runtime tick for schedules, reply monitoring, proactivity and gaps.

This runs inside the loopback Core and operates on gitignored private state.
Every executable scheduled command is revalidated through the intercom grammar
and existing policy gates at execution time. The runtime never expands authority.
"""
from __future__ import annotations

import datetime as dt

from pathlib import Path

from aletheia import act, communications, events, gaps, intercom, notifications, policy, proactive, scheduler, tasks
from aletheia.stateio import private_dir, read_json, write_json_atomic

TERMINAL_TASKS = {"COMPLETED", "CANCELLED", "FAILED_TERMINAL"}
EVENT_CURSOR = private_dir("runtime") / "event-cursor.json"


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


def process_new_events(*, now: dt.datetime | None = None,
                       cursor_path: Path | None = None,
                       events_dir: Path | None = None,
                       watchers_dir: Path | None = None) -> list[dict]:
    """Consume bus events emitted since the last tick.

    For each new event: watcher triggers become operator notifications
    ("tell me when X" actually tells him), and proactive rules produce
    their bounded proposals — notify/surface publish a notification,
    enqueue additionally persists an ordinary QUEUED task. Rules never
    execute anything; the cursor makes consumption idempotent.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    cursor_path = cursor_path or EVENT_CURSOR
    events_dir = Path(events_dir) if events_dir else events.EVENTS_DIR
    watchers_dir = Path(watchers_dir) if watchers_dir else events.WATCHERS_DIR
    try:
        cursor = read_json(cursor_path).get("last_event_id", "")
    except ValueError:
        cursor = ""
    fresh = sorted((e for e in events.list_events(events_dir=events_dir, limit=500)
                    if e["id"] > cursor), key=lambda e: e["id"])
    actions: list[dict] = []
    rules = proactive.all_rules()
    for event in fresh:
        # emit() already evaluated watchers; the trigger receipts on disk are
        # the durable record (re-evaluating would skip a once-watcher that is
        # now TRIGGERED). evaluate_watchers covers events emitted before the
        # watcher existed or with a different watchers_dir.
        events.evaluate_watchers(event, watchers_dir=watchers_dir)
        triggers = []
        triggers_root = watchers_dir / "triggers"
        if triggers_root.is_dir():
            for receipt_path in sorted(triggers_root.glob(f"*/{event['id']}.json")):
                try:
                    triggers.append(read_json(receipt_path))
                except ValueError:
                    continue
        for trigger in triggers:
            notifications.publish(
                "Watched event", f"{trigger['summary']} ({event['kind']}, {event['subject']})",
                priority="IMPORTANT", source="watchers",
                dedupe_key=f"trigger:{trigger['watcher_id']}:{event['id']}",
                related={"watcher": trigger["watcher_id"], "event": event["id"]})
            actions.append({"event": event["id"], "action": "watcher_notified",
                            "watcher": trigger["watcher_id"]})
        for rule in rules:
            receipt = proactive.evaluate(rule, event, now=now)
            if receipt is None:
                continue
            kind = receipt["proposal"]["kind"]
            notifications.publish(
                "Proactive: " + rule["id"],
                f"{event['summary']} ({event['kind']}, {event['subject']})",
                priority="NORMAL", source="proactive",
                dedupe_key=f"proactive:{rule['id']}:{event['id']}",
                related={"rule": rule["id"], "event": event["id"]})
            if kind == "enqueue":
                task_id = f"proact-{rule['id']}-{event['id']}"[:60].rstrip("-").lower()
                try:
                    tasks.create(task_id, f"Proactive rule {rule['id']}: follow up on {event['kind']}",
                                 goal=event["summary"])
                except (FileExistsError, ValueError):
                    pass  # idempotent, or an id the task engine refuses — the notification stands
            actions.append({"event": event["id"], "action": f"rule_{kind}", "rule": rule["id"]})
    if fresh:
        write_json_atomic(cursor_path, {"version": 1, "last_event_id": fresh[-1]["id"],
                                        "updated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")})
    return actions


def tick(fleet: dict, *, now: dt.datetime | None = None, registry: dict | None = None,
         request=None) -> dict:
    schedules = run_due_schedules(fleet, now=now, request=request)
    for result in schedules:  # a failing schedule must reach the operator
        if result["outcome"] in {"refused", "error", "invalid"}:
            notifications.publish(
                f"Schedule {result['schedule']} {result['outcome']}", result["detail"],
                priority="IMPORTANT", source="scheduler",
                dedupe_key=f"schedule:{result['schedule']}:{result.get('occurrence', 'invalid')}:{result['outcome']}",
                related={"schedule": result["schedule"]})
    return {
        "schedules": schedules,
        "reply_transitions": evaluate_replies(now=now),
        "events_processed": process_new_events(now=now),
        "capability_gaps": reconcile_task_gaps(registry=registry),
    }
