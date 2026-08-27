"""Local runtime tick for schedules, external observations, proactivity and gaps.

This runs inside the loopback Core and operates on gitignored private state.
Every executable scheduled command is revalidated through the intercom grammar
and existing policy gates at execution time. External observations (mail and the
Git-backed fleet pulse) become private bus events before watcher/proactive
consumption. Durable receipts from existing acting capabilities are folded into
private ActionRecords. Attention reconciliation runs after notification-producing
work so quiet hours/escalation apply without changing action authority.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

from aletheia import (act, attention, communications, events, gaps, handler, intercom, mail,
                      notifications, policy, proactive, scheduler, tasks, verification)
from aletheia.pulse import PULSE_DIR
from aletheia.stateio import private_dir, read_json, write_json_atomic

TERMINAL_TASKS = {"COMPLETED", "CANCELLED", "FAILED_TERMINAL"}
EVENT_CURSOR = private_dir("runtime") / "event-cursor.json"
PULSE_CURSOR = private_dir("runtime") / "pulse-cursor.json"


def _schedule_verification(spec: dict, receipt: dict) -> tuple[str | None, str | None]:
    plan = {"schedule": spec["id"], "occurrence": receipt["occurrence"], "command": spec["command"]}
    action_id = verification.new_action_id("automation.execute", seed=plan)
    try:
        verification.begin("automation.execute", provider="aletheia.local", intent=f"scheduled {spec['command']['kind']}", plan=plan,
                           requested_by="scheduler", action_id=action_id, inputs_summary=f"schedule {spec['id']}")
        return action_id, None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _finish_schedule_verification(action_id: str | None, *, succeeded: bool,
                                  result_summary: str, receipt: dict) -> str | None:
    if not action_id:
        return None
    try:
        value = verification.record_execution(
            action_id, succeeded=succeeded, result_summary=result_summary,
            evidence=([{"id": "occurrence-receipt", "kind": "truthy",
                        "observed": bool(receipt.get("occurrence")), "source": "scheduler"}]
                      if succeeded else []), auto_verify=False)
        return value["status"]
    except Exception as exc:
        return f"verification-error:{type(exc).__name__}:{exc}"


def run_due_schedules(fleet: dict, *, now: dt.datetime | None = None, request=None) -> list[dict]:
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    results = []
    for spec in scheduler.all_schedules():
        occurrence = scheduler.occurrence_at_or_before(spec, now)
        if occurrence is None:
            continue
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
        action_id, verification_error = _schedule_verification(spec, receipt)
        try:
            kwargs = {"quote": f"private schedule {spec['id']}"}
            if request is not None:
                kwargs["request"] = request
            detail = intercom.execute_command(spec["command"], fleet, **kwargs)
            result = {"schedule": spec["id"], "occurrence": receipt["occurrence"],
                      "outcome": "done", "detail": detail, "action_record": action_id}
            result["verification_status"] = _finish_schedule_verification(
                action_id, succeeded=True, result_summary=detail, receipt=receipt)
        except act.Refused as exc:
            result = {"schedule": spec["id"], "occurrence": receipt["occurrence"],
                      "outcome": "refused", "detail": str(exc), "action_record": action_id}
            result["verification_status"] = _finish_schedule_verification(
                action_id, succeeded=False, result_summary=str(exc), receipt=receipt)
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            result = {"schedule": spec["id"], "occurrence": receipt["occurrence"],
                      "outcome": "error", "detail": detail, "action_record": action_id}
            result["verification_status"] = _finish_schedule_verification(
                action_id, succeeded=False, result_summary=detail, receipt=receipt)
        if verification_error:
            result["verification_error"] = verification_error
        results.append(result)
    return results


def poll_mail_events() -> list[dict]:
    ok, _ = mail.available()
    if not ok:
        return []
    try:
        return mail.poll_events(limit=50)
    except Exception as exc:
        notifications.publish(
            "Mail polling failed", f"{type(exc).__name__}: {exc}",
            priority="IMPORTANT", source="mail",
            dedupe_key=f"mail-poll-error:{type(exc).__name__}",
            related={"capability": "email.read"})
        return [{"action": "error", "detail": f"{type(exc).__name__}: {exc}"}]


def _event_id_for_pulse(generated: str, material: dict) -> str:
    try:
        when = dt.datetime.fromisoformat(generated.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("pulse generated_at must be an ISO timestamp") from exc
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("pulse generated_at must be timezone-aware")
    stamp = when.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    digest = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()[:10]
    return f"evt-{stamp}-{digest}"


def mirror_pulse_events(*, pulse_path: Path | None = None,
                        cursor_path: Path | None = None) -> list[dict]:
    pulse_path = pulse_path or (PULSE_DIR / "latest.json")
    cursor_path = cursor_path or PULSE_CURSOR
    if not pulse_path.is_file():
        return []
    try:
        pulse = json.loads(pulse_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"pulse is unreadable: {exc}") from exc
    generated = str(pulse.get("generated_at", ""))
    if not generated:
        raise ValueError("pulse missing generated_at")
    try:
        cursor = read_json(cursor_path).get("generated_at", "")
    except ValueError:
        cursor = ""
    if generated == cursor:
        return []
    actions = []
    for transition in pulse.get("transitions", []):
        required = {"repo", "from", "to"}
        if not isinstance(transition, dict) or required - transition.keys():
            continue
        material = {"generated_at": generated,
                    **{k: transition.get(k) for k in ("repo", "github", "from", "to")}}
        event_id = _event_id_for_pulse(generated, material)
        try:
            emitted = events.emit(
                "fleet.health_changed", f"repo:{transition['repo']}",
                f"{transition.get('github', transition['repo'])} health {transition['from']} -> {transition['to']}",
                source="pulse",
                attributes={"repo": transition["repo"], "from": transition["from"],
                            "to": transition["to"], "github": transition.get("github", "")},
                event_id=event_id, occurred_at=generated)
            actions.append({"action": "emitted", "event": emitted["event"]["id"],
                            "repo": transition["repo"]})
        except FileExistsError:
            actions.append({"action": "already_emitted", "event": event_id,
                            "repo": transition["repo"]})
    write_json_atomic(cursor_path, {
        "version": 1, "generated_at": generated,
        "updated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    return actions


def evaluate_replies(*, now: dt.datetime | None = None) -> list[dict]:
    before = {e["id"]: e.get("status") for e in communications.all_expectations()}
    after = communications.evaluate_all(now=now)
    transitions = []
    for value in after:
        old, new = before.get(value["id"]), value.get("status")
        if old == new:
            continue
        transitions.append({"expectation": value["id"], "from": old, "to": new})
        if new == "REPLIED":
            notifications.publish(
                "Reply received", f"Tracked conversation {value['thread_id']} has a reply.",
                priority="IMPORTANT", source="communications",
                dedupe_key=f"reply:{value['id']}",
                related={"expectation": value["id"]})
        elif new == "OVERDUE":
            notifications.publish(
                "Reply overdue",
                f"No tracked reply arrived before the deadline for {value['thread_id']}.",
                priority="IMPORTANT", source="communications",
                dedupe_key=f"overdue:{value['id']}",
                related={"expectation": value["id"]})
    return transitions


def reconcile_task_gaps(*, registry: dict | None = None) -> list[dict]:
    actions = []
    for task in tasks.all_tasks():
        if task.get("status") in TERMINAL_TASKS:
            continue
        required = task.get("required_capabilities") or []
        if not required:
            continue
        report = gaps.assess(required, registry=registry)
        if report["satisfied"]:
            if (task["status"] in {"WAITING_DEPENDENCY", "WAITING_OPERATOR", "BLOCKED"}
                    and str(task.get("result", "")).startswith("capability gap:")):
                resumed = tasks.set_status(
                    task["id"], "QUEUED", "capability gap: closed; original work resumed")
                actions.append({"task": task["id"], "action": "resumed",
                                "status": resumed["status"]})
            continue
        gap_tasks = gaps.materialize(required, registry=registry)
        statuses = {item["status"] for item in report["blocked"]}
        wait_state = ("WAITING_OPERATOR" if statuses and statuses <= {"NEEDS_CONFIGURATION"}
                      else "WAITING_DEPENDENCY")
        note = "capability gap: " + ", ".join(
            [f"{item['id']}={item['status']}" for item in report["blocked"]]
            + [f"{cid}=UNKNOWN" for cid in report["unknown"]])
        if task["status"] not in {wait_state, "RUNNING"}:
            tasks.set_status(task["id"], wait_state, note)
        actions.append({"task": task["id"], "action": "gap_materialized",
                        "gap_tasks": [g["id"] for g in gap_tasks], "waiting": wait_state})
    return actions


def _scheduling_reply(event: dict) -> dict | None:
    """Route a correlated mail reply to the meeting negotiation waiting on it."""
    if event.get("kind") != "mail.reply":
        return None
    try:
        from aletheia import scheduling
        thread = (event.get("attributes") or {}).get("thread_id", "")
        negotiation_id = scheduling.negotiation_for_thread(thread)
        if not negotiation_id:
            return None
        noted = scheduling.note_reply(negotiation_id)
        return {"negotiation": negotiation_id} if noted else None
    except Exception as exc:
        return {"outcome": "error", "error_type": type(exc).__name__}


def _advisor_judgment(event: dict, now: dt.datetime) -> dict | None:
    """Optional model triage. Failure never blocks deterministic event handling."""
    try:
        from aletheia import advisor
        return advisor.evaluate_event(event, now=now)
    except Exception as exc:
        # Never echo provider/config exception text into runtime results: an
        # external dependency error may contain data we did not intend to surface.
        return {"event": event.get("id", "?"), "outcome": "error",
                "error_type": type(exc).__name__}


def process_new_events(*, now: dt.datetime | None = None,
                       cursor_path: Path | None = None,
                       events_dir: Path | None = None,
                       watchers_dir: Path | None = None) -> list[dict]:
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
    fresh = sorted(
        (e for e in events.list_events(events_dir=events_dir, limit=500)
         if e["id"] > cursor), key=lambda e: e["id"])
    actions: list[dict] = []
    rules = proactive.all_rules()
    for event in fresh:
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
                "Watched event",
                f"{trigger['summary']} ({event['kind']}, {event['subject']})",
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
            priority = receipt["proposal"].get("priority", "NORMAL")
            notifications.publish(
                "Proactive: " + rule["id"],
                f"{event['summary']} ({event['kind']}, {event['subject']})",
                priority=priority, source="proactive",
                dedupe_key=f"proactive:{rule['id']}:{event['id']}",
                related={"rule": rule["id"], "event": event["id"]})
            if kind == "enqueue":
                task_id = f"proact-{rule['id']}-{event['id']}"[:60].rstrip("-").lower()
                try:
                    tasks.create(
                        task_id,
                        f"Proactive rule {rule['id']}: follow up on {event['kind']}",
                        goal=event["summary"])
                except (FileExistsError, ValueError):
                    pass
            actions.append({"event": event["id"], "action": f"rule_{kind}",
                            "rule": rule["id"], "priority": priority})
        routed = _scheduling_reply(event)
        if routed is not None:
            actions.append({"event": event["id"], "action": "meeting_reply", **routed})
        judged = _advisor_judgment(event, now)
        if judged is not None:
            actions.append({"event": event["id"],
                            "action": "advisor_" + judged.get("outcome", "unknown"),
                            **({"error_type": judged["error_type"]}
                               if judged.get("error_type") else {})})
    if fresh:
        write_json_atomic(cursor_path, {
            "version": 1, "last_event_id": fresh[-1]["id"],
            "updated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")})
    return actions


def _run_approved_intents(fleet: dict) -> list[dict]:
    from aletheia import intents  # local: planner pulls in the reasoner
    return intents.run_approved(fleet)


def _run_authorized_errands() -> list[dict]:
    from aletheia import errands  # local: pulls in the browser stack
    return errands.run_authorized()


def _reconcile_scheduling(now: dt.datetime) -> list[dict]:
    from aletheia import scheduling
    return scheduling.reconcile(now=now)


def _observe_room() -> list[dict]:
    """Refresh device reachability when a hub is configured; honest no-op
    when it is not, so an unconfigured room costs nothing per beat."""
    from aletheia import hass
    if not hass.available()[0]:
        return []
    return hass.observe()


def _refresh_calendar(now: dt.datetime) -> list[dict]:
    """Prefer one official OAuth provider; fall back to ICS, never both.

    Both mechanisms mirror into the same local availability store. Running both
    against the same upstream account would double-count busy time, so an
    official provider config is authoritative whenever present.
    """
    from aletheia import calendar_live, ics
    if calendar_live.available()[0]:
        result = calendar_live.refresh_if_due(now=now)
        if result is None:
            return []
        return [{"action": "refreshed", "provider": result["provider"],
                 "remote_count": result["remote_count"],
                 "conflicts": len(result["conflicts"])}]
    if ics.available()[0]:
        result = ics.refresh_if_due(now=now)
        if result is None:
            return []
        return [{"action": "refreshed", "provider": "ics", **result}]
    return []


def tick(fleet: dict, *, now: dt.datetime | None = None,
         registry: dict | None = None, request=None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    schedules = run_due_schedules(fleet, now=now, request=request)
    for result in schedules:
        if result["outcome"] in {"refused", "error", "invalid"}:
            notifications.publish(
                f"Schedule {result['schedule']} {result['outcome']}", result["detail"],
                priority="IMPORTANT", source="scheduler",
                dedupe_key=(f"schedule:{result['schedule']}:"
                            f"{result.get('occurrence', 'invalid')}:{result['outcome']}"),
                related={"schedule": result["schedule"]})

    def guarded(name, fn):
        try:
            return fn()
        except Exception as exc:
            return [{"action": "error", "producer": name,
                     "detail": f"{type(exc).__name__}: {exc}"}]

    mail_events = guarded("mail", poll_mail_events)
    pulse_events = guarded("pulse", mirror_pulse_events)
    action_records = guarded("receipts", verification.reconcile_durable_receipts)
    reply_transitions = evaluate_replies(now=now)
    events_processed = process_new_events(now=now)
    capability_gaps = reconcile_task_gaps(registry=registry)
    handle_requests = guarded(
        "handler", lambda: handler.reconcile_all(registry=registry, now=now))
    # Approved arbitrary asks (aletheia.intents): the plan the operator
    # okayed runs HERE, on a later beat, through the ordinary gates — not
    # inside the conversation that produced it.
    approved_intents = guarded(
        "intents", lambda: _run_approved_intents(fleet))
    # Errands he authorized: the last mile into the world, run here rather
    # than inside the sentence that asked for it.
    authorized_errands = guarded("errands", _run_authorized_errands)
    room_devices = guarded("room", _observe_room)
    # Meetings arranging themselves across days (Phase 15): offers that have
    # really been delivered start waiting for a reply, accepted slots ask for
    # their calendar-write approval, stale offers are abandoned.
    meetings_progress = guarded(
        "scheduling", lambda: _reconcile_scheduling(now))
    calendar_updates = guarded("calendar", lambda: _refresh_calendar(now))
    # LAST: everything above may create notifications. Attention never executes
    # them; it only classifies READY vs DEFERRED and escalates eligible priority.
    attention_records = guarded("attention", lambda: attention.reconcile(now=now))
    return {
        "schedules": schedules,
        "mail_events": mail_events,
        "pulse_events": pulse_events,
        "action_records": action_records,
        "reply_transitions": reply_transitions,
        "events_processed": events_processed,
        "capability_gaps": capability_gaps,
        "approved_intents": approved_intents,
        "authorized_errands": authorized_errands,
        "room_devices": room_devices,
        "meetings": meetings_progress,
        "calendar": calendar_updates,
        "handle_requests": handle_requests,
        "attention": attention_records,
    }
