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
import time
import hashlib
import json
from pathlib import Path

from aletheia import (act, attention, communications, desktop_notify, events, gaps,
                      handler, intercom, mail, notifications, policy, proactive,
                      reservations, scheduler, subscriptions, tasks,
                      verification)
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
    # Deliberately NOT caught here. This used to publish its own
    # never-clearing notification and return [{"action": "error"}], which
    # the summary renders with len() — so a transient IMAP blip read as
    # "one mail event" and left an IMPORTANT alarm on the wall for hours
    # after the network healed. The beat's own `guarded` handles it now:
    # counted as a failure rather than as work, notified only once it
    # persists, and acknowledged when it starts working again.
    return mail.poll_events(limit=50)


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


# How long one beat may spend on subsystems before deferring the rest.
# The Core's sync interval is 60s and this thread also pulls commands and
# stamps the liveness heartbeat, so the work has to fit inside the gap.
TICK_BUDGET_S = 25.0


# How far ahead a deadline starts being worth saying out loud.
DUE_SOON_HOURS = 24.0


def surface_due_tasks(*, now: dt.datetime | None = None) -> list[dict]:
    """Nudge once a day, per task, while a deadline is near or past.

    Once a DAY rather than once, because a deadline that spoke once at
    3 a.m. and never again has not reminded him of anything; and once a day
    rather than every beat, because a notification every sixty seconds is a
    notification he turns off. The dedupe key carries HIS local date, so
    the nudge lands again each morning until the task is done or cancelled
    — which are the two things that stop it, and both are his to do.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        from aletheia import localtime
        today = now.astimezone(localtime.operator_tz()).date().isoformat()
    except Exception:
        today = now.date().isoformat()
    out = []
    for row in tasks.due(now=now, within_hours=DUE_SOON_HOURS):
        task, when, overdue = row["task"], row["when"], row["overdue"]
        try:
            local = when.astimezone(localtime.operator_tz())
        except Exception:
            local = when
        title = ("Overdue: " if overdue else "Due soon: ") + task["description"][:70]
        body = (("was due " if overdue else "due ")
                + local.strftime("%a %d %b %H:%M")
                + f" · task {task['id']}")
        notifications.publish(
            title, body, priority="IMPORTANT", source="tasks",
            dedupe_key=f"task-due:{task['id']}:{today}",
            related={"task": task["id"]})
        out.append({"task": task["id"], "overdue": overdue})
    return out


def send_approved_applications() -> list[dict]:
    """Send what he confirmed, once each.

    The whole loop he asked for ends here: she fills the application, it
    waits as a normal approval, he taps Approve on his phone, and the next
    beat presses submit. A failure is recorded on the run and surfaced —
    never retried, because the failure mode of a retry loop on this
    particular button is several copies of his application in somebody's
    inbox.
    """
    from aletheia import apply_run
    sent = []
    for record in apply_run.all_runs("AWAITING_YOU"):
        try:
            approval = policy.load(record["approval"])
        except Exception:
            continue
        if approval.get("state") != "APPROVED":
            continue
        try:
            # accept, NOT confirm: he has already decided. `confirm` GRANTS
            # the approval, which would mean the check for his approval was
            # the thing granting it.
            apply_run.accept(record["id"])
            done = apply_run.submit(record["id"])
        except Exception as exc:
            notifications.publish(
                "An application could not be sent",
                f"{record['url']} — {type(exc).__name__}: {exc}"[:400],
                priority="IMPORTANT", source="apply",
                dedupe_key=f"apply-failed:{record['id']}")
            continue
        result = done.get("result", {})
        notifications.publish(
            "Application sent", f"{record['url']} — {result.get('note', '')}"[:400],
            priority="IMPORTANT", source="apply",
            dedupe_key=f"apply-sent:{record['id']}",
            related={"application": record["id"]})
        sent.append({"application": record["id"], "url": record["url"],
                     "verdict": result.get("verdict")})
    return sent


def press_approved_web_tasks() -> list[dict]:
    """Press what he confirmed on a web task, once each.

    Without this the whole capability ended in a question nobody could
    answer: she drives the site, stops at Submit, says "confirm it and I
    will press it", he taps Approve on his phone — and nothing pressed it,
    ever, because `webtask.commit` only existed on the command line. The
    same shape as `send_approved_applications`, and the same rule: a
    failure is surfaced and never retried, because the failure mode of a
    retry loop on this particular button is several copies of whatever he
    was doing.
    """
    from aletheia import webtask
    pressed = []
    for record in webtask.all_runs(webtask.COMMIT):
        try:
            approval = policy.load(record["approval"])
        except Exception:
            continue
        if approval.get("state") != "APPROVED":
            continue
        try:
            done = webtask.commit(record["id"])
        except Exception as exc:
            notifications.publish(
                "I could not press it",
                f"{record.get('button', '')} on {record.get('url', '')} — "
                f"{type(exc).__name__}: {exc}"[:400],
                priority="IMPORTANT", source="webtask",
                dedupe_key=f"webtask-failed:{record['id']}")
            continue
        result = done.get("result", {})
        verdict = str(result.get("verdict") or "submitted, unconfirmed")
        # WHAT THE SITE SAID, in the title. "Pressed 'Submit application'"
        # read as success on a run the site had refused outright.
        title = {"confirmed": "Done",
                 "rejected": "It would not go through"}.get(verdict, "Pressed it")
        notifications.publish(
            f"{title}: {record.get('button', 'it')}",
            (f"{record.get('goal', '')[:120]} — {result.get('note', '')} "
             f"{result.get('evidence', '')[:160]}").strip(),
            priority="IMPORTANT", source="webtask",
            dedupe_key=f"webtask-pressed:{record['id']}",
            related={"web_task": record["id"]})
        pressed.append({"web_task": record["id"], "button": record.get("button"),
                        "verdict": verdict,
                        "url": result.get("url", record.get("url"))})
    return pressed


def run_approved_scripts() -> list[dict]:
    """Run the file-deleting programs he confirmed, once each.

    Same shape as everything else that waits on him: he taps Approve on
    his phone and the next beat does it. A failure is surfaced and never
    retried — a delete that half-happened is not a thing to attempt twice
    on its own initiative.
    """
    from aletheia import script
    done = []
    for approval in policy.all_approvals():
        if approval.get("state") != "APPROVED":
            continue
        if not str(approval.get("requested_action", "")).startswith(
                "script.destructive:"):
            continue
        try:
            result = script.confirmed(approval["id"])
        except script.ScriptRefused:
            continue                     # already run, or its source is gone
        except Exception as exc:
            notifications.publish(
                "That program would not run",
                f"{approval.get('reason', '')[:160]} — "
                f"{type(exc).__name__}: {exc}"[:400],
                priority="IMPORTANT", source="script",
                dedupe_key=f"script-failed:{approval['id']}")
            continue
        notifications.publish(
            "Done", f"{approval.get('reason', '')[:160]} — "
                    f"{result.get('output', '')[:200]}",
            priority="IMPORTANT", source="script",
            dedupe_key=f"script-ran:{approval['id']}")
        done.append({"approval": approval["id"],
                     "program": result.get("program", "")})
    return done


def tick(fleet: dict, *, now: dt.datetime | None = None,
         registry: dict | None = None, request=None,
         budget_s: float = TICK_BUDGET_S) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    # The budget covers the WHOLE beat, so it has to start before the first
    # subsystem rather than after it.
    failures: list[dict] = []
    skipped: list[str] = []
    deadline = time.monotonic() + budget_s
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
        """Run one subsystem; a failure must not stop the beat — but it must
        also not read as work.

        This used to return the exception as a one-element list, and the
        summary is rendered with len(), so a permanently broken mail poller
        showed up as "1 mail event" every minute: indistinguishable from
        success, and nothing ever told the operator. A failure now returns
        NOTHING for the count and is collected separately, where the caller
        surfaces it.
        """
        # A beat is also allowed to run out of time. The sync loop that
        # pulls commands and stamps the heartbeat is this same thread, so a
        # subsystem that takes a browser-shaped minute must not be able to
        # hold the rest of the beat hostage: once the budget is spent, the
        # remaining subsystems are SKIPPED to the next beat rather than run
        # late. Skipping is not a failure and is not counted as one.
        if time.monotonic() >= deadline:
            skipped.append(name)
            return []
        try:
            return fn()
        except Exception as exc:
            failures.append({"producer": name,
                             "error": f"{type(exc).__name__}: {exc}"[:300]})
            return []

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
    # AFTER attention, because attention is what decides a notice is loud.
    # This is the inch that was missing: "remind me at three to call the
    # dentist" produced a correct, on-time notification that appeared
    # NOWHERE — not on his screen, not audibly, and not on a phone in his
    # pocket that was not polling. Everything upstream was right, which is
    # exactly why nothing caught it.
    # A deadline he set has to come BACK to him. `tasks.create` stored one
    # and nothing in the system ever compared it to the clock, so "renew the
    # registration by Friday" was a sentence in a file — the difference
    # between a task list and a graveyard.
    due_tasks = guarded("due", lambda: surface_due_tasks(now=now))
    # An application he APPROVED gets sent, here, on a later beat. The
    # approval he taps on his phone is an ordinary policy approval, so the
    # existing Approve button is the confirm — there is no second UI to
    # build and no second thing to remember. Nothing is sent that is not
    # APPROVED, and each is sent exactly once.
    applications_sent = guarded("applications", send_approved_applications)
    web_tasks_pressed = guarded("web_tasks", press_approved_web_tasks)
    # A subscription is CANCELLED when the merchant says so, not when we
    # pressed a button — and believing otherwise costs him a charge a
    # month for as long as he believes it.
    # A question nobody answered in a week, and a yes to something
    # irreversible that has sat unpressed for a day, both stop counting.
    approvals_expired = guarded(
        "approvals", lambda: [a["id"] for a in policy.expire_stale()])
    scripts_run = guarded("scripts", run_approved_scripts)
    bookings_settled = guarded(
        "reservations", lambda: [r["id"] for r in reservations.reconcile()])
    subscriptions_settled = guarded(
        "subscriptions", lambda: [s["id"] for s in subscriptions.reconcile()])
    delivered = guarded("desktop", desktop_notify.deliver_pending)
    return {
        "failures": failures,
        "skipped": skipped,
        "schedules": schedules,
        "mail_events": mail_events,
        "pulse_events": pulse_events,
        "action_records": action_records,
        "reply_transitions": reply_transitions,
        "events_processed": events_processed,
        "capability_gaps": capability_gaps,
        "approved_intents": approved_intents,
        "web_tasks_pressed": web_tasks_pressed,
        "subscriptions_settled": subscriptions_settled,
        "bookings_settled": bookings_settled,
        "scripts_run": scripts_run,
        "approvals_expired": approvals_expired,
        "authorized_errands": authorized_errands,
        "room_devices": room_devices,
        "meetings": meetings_progress,
        "calendar": calendar_updates,
        "handle_requests": handle_requests,
        "attention": attention_records,
        "due_tasks": due_tasks,
        "applications_sent": applications_sent,
        "delivered": delivered,
    }
