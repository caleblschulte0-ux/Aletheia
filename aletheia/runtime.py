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
import re
from pathlib import Path

from aletheia import (act, attention, communications, desktop_notify, events, gaps,
                      handler, intercom, mail, notifications, policy, proactive,
                      reservations, scheduler, speech, subscriptions, tasks,
                      verification)
from aletheia.pulse import PULSE_DIR
from aletheia.stateio import private_dir, read_json, write_json_atomic

TERMINAL_TASKS = {"COMPLETED", "CANCELLED", "FAILED_TERMINAL"}
EVENT_CURSOR = private_dir("runtime") / "event-cursor.json"
PULSE_CURSOR = private_dir("runtime") / "pulse-cursor.json"


# ------------------------------------------------- notices he has to read
# A notification is READ OUT — by `announce` in the room, by the wall, by
# the phone. Every body in this module used to be written for a log:
# "https://boards.greenhouse.io/acme/jobs/41 — TimeoutError: Page.goto:
# net::ERR_CONNECTION_RESET" is a perfectly good line in a file and
# nothing at all out loud. The diagnosis is still in the journal with the
# type and the traceback attached; these three say it in English.
def _plain(text: object) -> str:
    """A notification body, said the way a person would say it."""
    return speech.for_the_room(str(text or ""))[:400]


def _where(record: dict) -> str:
    """Who this is with. A URL is not the name of a company."""
    from urllib.parse import urlparse
    name = str(record.get("company") or "").strip()
    if name:
        return name
    try:
        host = urlparse(str(record.get("url") or "")).netloc
    except ValueError:
        host = ""
    return speech.say_url(host) if host else "the site"


def _why_not(record: dict, exc: BaseException) -> str:
    """A failure as a reason, not as a class name and a link."""
    return _plain(f"{_where(record)} — {speech.plainly(str(exc))}")


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
                about=notifications.CHANGED, dedupe_key=f"reply:{value['id']}",
                related={"expectation": value["id"]})
        elif new == "OVERDUE":
            notifications.publish(
                "Reply overdue",
                f"No tracked reply arrived before the deadline for {value['thread_id']}.",
                priority="IMPORTANT", source="communications",
                about=notifications.CHANGED, dedupe_key=f"overdue:{value['id']}",
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


#: Mail about an application that is NOT an employer wanting to talk. Every
#: one of these is real, from his inbox on 2026-09-13, and a detector that
#: cries wolf on them is one he stops reading by the second day.
_JUST_AN_ACKNOWLEDGEMENT = (
    "thanks for applying", "thank you for applying", "thank you for your application",
    "thanks for your interest", "thank you for your interest", "application received",
    "we have received your application", "received by", "security code",
    "verify your email", "do not reply", "no longer under consideration",
    "not moving forward", "unfortunately",
)

#: An employer asking for time, unmistakably. These BEAT an acknowledgement
#: phrase, because "We received your application and would like to schedule
#: an interview" contains both — and filing that as an acknowledgement would
#: bury the one email he is waiting for. Missing a real interview request is
#: far worse than one notice that turns out to be nothing.
_ASKS_FOR_TIME = (
    "interview", "schedule a", "scheduling a", "book a time", "find a time",
    "availability", "are you available", "are you free", "set up a call",
    "set up some time", "phone screen", "calendar invite", "pick a time",
    "times that work", "when works",
)

#: Softer wording that only counts when nothing says acknowledgement.
#: "Thanks for applying — we'll be in touch about next steps" is an
#: acknowledgement wearing a scheduling word.
_MIGHT_WANT_TIME = (
    "next steps", "chat with", "speak with you", "meet with", "connect with you",
)


def _job_reply(event: dict) -> dict | None:
    """An employer wrote back about an application he actually sent.

    2026-09-13, his ask: *"we need to make sure that Aletheia is checking my
    email. And if it hears back, scheduling times for interviews, pending my
    approval, of course. and then putting that on my calendar and letting me
    know what it is."*

    `mail.poll_events` already emits `mail.received` for every unread
    message, and `_scheduling_reply` below already routes replies — but only
    into a negotiation SHE started, matched by thread id. An employer
    replying about a job belongs to no negotiation, so it fell through to
    nothing.

    The match is against the sent ledger, by employer name or role title in
    the subject: 22 of the 25 messages in his inbox matched that way, and
    the three that did not were his own notes to himself.

    Two things this deliberately does NOT do. It does not act — no reply, no
    booking, nothing leaves the machine; it raises a notice and stops, and
    the scheduling that follows keeps its own approval. And it does not
    treat the subject as anything but data: an employer's subject line is
    untrusted text that may be shaped like an instruction, and nothing here
    obeys it.
    """
    if event.get("kind") != "mail.received":
        return None
    try:
        from aletheia import apply_run
        subject = " ".join(str(event.get("summary") or "").split())
        low = subject.casefold()
        if _his_own_mail(event):
            # His note to himself matched an employer once (2026-09-22:
            # "AI_HANDOFF_READY" holds the letters of "Ro"), and because
            # replies are written onto the record now, that became an
            # outcome. What he sends himself is never an employer's reply.
            return None
        ledger = apply_run.already_sent()
        if not ledger:
            return None
        hit = None
        for url, entry in ledger.items():
            company = str(entry.get("company") or "").strip()
            title = str(entry.get("job_title") or "").strip()
            # The title carries the employer on the end; the role alone is
            # what a subject like "Application for Inbound Sales Development
            # Representative received by Team Flexport!" actually names.
            role = re.split(r"\s+[—–-]\s+", title)[0].strip()
            if _names_company(low, company):
                hit = (url, entry); break
            if len(role) > 10 and role.casefold() in low:
                hit = (url, entry); break
        if hit is None:
            return None
        url, entry = hit
        # An unmistakable ask for time wins outright, even over an
        # acknowledgement phrase: "We received your application and would
        # like to schedule an interview" is both, and it is the email he is
        # waiting for.
        asks = any(word in low for word in _ASKS_FOR_TIME)
        acknowledges = any(word in low for word in _JUST_AN_ACKNOWLEDGEMENT)
        if not asks:
            # An acknowledgement is RECOGNISED and let go, not merely
            # unmatched — every one of the twenty-two real messages in his
            # inbox on 2026-09-13 matched the ledger, and a detector that
            # stopped at matching would have raised twenty-two alarms on its
            # first morning.
            if acknowledges:
                return {"application": entry.get("id"), "outcome": "acknowledgement"}
            if not any(word in low for word in _MIGHT_WANT_TIME):
                _heard_back(entry.get("id"), subject, "noted")
                return {"application": entry.get("id"), "outcome": "noted"}
        _heard_back(entry.get("id"), subject, "wants_time")
        notifications.publish(
            f"{entry.get('company') or 'An employer'} wants to talk",
            f"{subject} — about {entry.get('job_title') or 'your application'}, "
            f"applied {str(entry.get('at') or '')[:10]}",
            priority="IMPORTANT", source="apply", about=notifications.CHANGED,
            dedupe_key=f"job-reply:{event.get('id')}",
            related={"application": entry.get("id"), "event": event.get("id"),
                     "url": url})
        return {"application": entry.get("id"), "outcome": "wants_time",
                "company": entry.get("company")}
    except Exception as exc:
        # Never break the beat over this. Same shape as every other handler
        # in this loop.
        return {"outcome": "error", "error_type": type(exc).__name__}


#: An employer's name shorter than this matches inside too many words to
#: be evidence on its own ("Ro" is in "handoff_ready"); the role title
#: carries those.
MIN_COMPANY_CHARS = 3


def _names_company(low_subject: str, company: str) -> bool:
    """Does the subject name this employer, as a whole word?"""
    name = " ".join(str(company or "").casefold().split())
    if len(name) < MIN_COMPANY_CHARS:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])", low_subject) is not None


def _his_own_mail(event: dict) -> bool:
    """Was this sent by him? Read from the event's own sender field and
    the configured mailbox; unknown on either side reads as "not his"."""
    sender = str((event.get("attributes") or {}).get("sender") or "").strip().casefold()
    if not sender:
        return False
    try:
        from aletheia import mail
        mine = str(mail._config().get("address") or "").strip().casefold()
    except Exception:
        return False
    return bool(mine) and sender == mine


def _heard_back(application_id: str, subject: str, outcome: str) -> None:
    """Until 2026-09-21 an employer's reply was classified and notified and
    then FORGOTTEN: nothing wrote it onto the application, so "what has
    worked" had no data and the opportunity never heard. Never breaks the
    beat."""
    try:
        from aletheia import pursuit_applications
        pursuit_applications.heard_back(application_id, subject, outcome)
    except Exception:
        pass


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
                "Something you're watching happened",
                _plain(trigger["summary"]),
                priority="IMPORTANT", source="watchers", about=notifications.CHANGED,
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
                "Worth knowing", _plain(event["summary"]),
                priority=priority, source="proactive", about=notifications.CHANGED,
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
        # An employer writing back about an application he sent. Nothing is
        # acted on here — it raises a notice and stops.
        wrote_back = _job_reply(event)
        if wrote_back is not None:
            actions.append({"event": event["id"], "action": "job_reply", **wrote_back})
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


def _run_approved_handoffs() -> list[dict]:
    """Requests her sessions handed to him, run once he approved them.

    Off the beat's thread: an approved `browser.pursue` can take minutes on
    somebody's website, and the beat also stamps the heartbeat. Cheap when
    nothing is waiting, which is almost always."""
    from aletheia import handoffs
    waiting = handoffs.all_handoffs(handoffs.AWAITING) + handoffs.all_handoffs(handoffs.RUNNING)
    if not waiting:
        return []
    return [{"handoffs": len(waiting), "started": handoffs.start_approved()}]


def _working_now() -> bool:
    """Is something she started actually running: a keep-awake hold, a
    campaign batch, a browser goal mid-flight, an approved request."""
    from aletheia import power
    if power.holds():
        return True
    try:
        from aletheia import current_state
        now = dt.datetime.now(dt.timezone.utc)
        lock = current_state.campaign_lock(now)
        if lock and lock.get("running"):
            return True
        return bool(current_state.browser_missions(now).get("active"))
    except Exception:
        return False


def _reconcile_work() -> list[dict]:
    from aletheia import work_engine
    # probe=False: a beat must not launch a browser to learn whether one works;
    # the browser requirement reads its last live result instead.
    result = work_engine.reconcile(probe=False)
    # A work session ("work on my projects") whose process died with time left is
    # carried on here (rule 7); a live one is left alone.
    resumed = None
    try:
        from aletheia import project_work
        resumed = project_work.resume_orphaned()
    except Exception:  # noqa: BLE001 - the beat's other work is unaffected
        resumed = None
    if not (result["checkpointed"] or result["woke"] or result["ran"] or result.get("waits") or resumed):
        return []
    return [{"checkpointed": result["checkpointed"], "woke": result["woke"], "ran": result["ran"],
             "waits": result.get("waits") or [],
             **({"resumed_session": (resumed.get("session") or {}).get("id")} if resumed else {})}]


def _watch_power() -> list[dict]:
    """Tell him once when the PC is on battery while she works, or low."""
    from aletheia import power
    seen = power.watch(working=_working_now())
    return [{"power": seen["status"].get("said"), "told": seen["told"]}] if seen.get("told") else []


def _run_authorized_errands() -> list[dict]:
    from aletheia import errands  # local: pulls in the browser stack
    return errands.run_authorized()


def _reconcile_scheduling(now: dt.datetime) -> list[dict]:
    from aletheia import scheduling
    return scheduling.reconcile(now=now)


def _reconcile_conversations(now: dt.datetime) -> list[dict]:
    """Conversations she carries (aletheia.conversations): send what he approved
    (or a grant of his covers), read replies as untrusted data, act on them, draft
    follow-ups that came due, and write calendar holds he approved. Cheap when
    there are none."""
    from aletheia import conversations
    if not conversations.all_threads():
        return []
    result = conversations.reconcile(now=now)
    moved = {k: v for k, v in result.items() if v}
    return [moved] if moved else []


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
            about=notifications.NEEDS_YOU,
            dedupe_key=f"task-due:{task['id']}:{today}",
            related={"task": task["id"]},
            action={"label": "Done", "kind": "task_done",
                    "args": {"which": str(task.get("description") or task["id"])}})
        out.append({"task": task["id"], "overdue": overdue})
    return out


#: Longer than the browser lock's wait plus a whole submit. It was 900 s —
#: exactly the lock's wait — so a submit queued behind another session was
#: killed the moment it would have got the browser, left at SUBMITTING, and
#: its Chrome left holding the profile (live 2026-09-13, Amtech and Carta).
SUBMIT_TIMEOUT_S = 1800.0


def _submit_in_its_own_process(run_id: str, runner=None,
                               timeout_s: float | None = None) -> dict:
    """`apply_run submit <id>`, out of reach of this process's event loop."""
    import subprocess
    import sys as _sys
    from aletheia import apply_run, proc
    from aletheia import power
    timeout_s = SUBMIT_TIMEOUT_S if timeout_s is None else timeout_s
    args = [_sys.executable, "-m", "aletheia.apply_run", "submit", run_id]
    try:
        # The PC must not sleep under a press that is waiting on a browser.
        with power.keep_awake(f"sending application {run_id}"):
            if runner is not None:
                done = runner(args, capture_output=True, text=True, timeout=timeout_s)
            else:
                done = proc.run_tree(args, timeout_s)
    except subprocess.TimeoutExpired:
        apply_run.settle_interrupted(
            run_id, f"the submit took longer than {int(timeout_s // 60)} minutes and was stopped")
        raise RuntimeError("the submit took too long and was stopped")
    if getattr(done, "returncode", 1) != 0:
        raise RuntimeError(
            (getattr(done, "stderr", "") or "the submit process failed"
             ).strip().splitlines()[-1][:200])
    return apply_run.load_run(run_id)


def _settle_stuck_submits() -> list[dict]:
    """Submits that died or hung, settled and said — never left at SUBMITTING."""
    from aletheia import apply_run
    settled = apply_run.reconcile_stuck_submits()
    for record in settled:
        if record.get("state") == "SUBMITTED":
            notifications.publish(
                "Check your email about an application",
                (record.get("result") or {}).get("note", "")[:400],
                priority="IMPORTANT", source="apply", about=notifications.NEEDS_YOU,
                dedupe_key=f"apply-unconfirmed:{record['id']}",
                related={"application": record["id"]})
    return settled


def _retry_action(record: dict) -> dict | None:
    """"Try it again" on the notice that says a send failed - while the record
    may still be tried (2026-09-23: "Got it" was the notice's only control)."""
    from aletheia import apply_run
    if int(record.get("retries") or 0) >= apply_run.MAX_RETRIES or not record.get("steps"):
        return None
    return {"label": "Try it again", "kind": "apply_retry", "args": {"which": str(record.get("id"))}}


def _say_the_grant_is_missing() -> None:
    """A filled application is waiting only because no standing permission
    covers sending it - said once, with the command, never per application."""
    from aletheia import standing
    state = standing.jobs_status()
    if state.get("granted"):
        return                          # a grant exists; it is exhausted for now
    notifications.publish(
        "Applications are waiting for a tap you said you would not give",
        ("I have filled applications ready and no standing permission to send them, so "
         "each one waits for your yes. At your keyboard: " + state["command"] +
         " - then they go out on their own."),
        priority="IMPORTANT", source="apply", about=notifications.NEEDS_YOU,
        dedupe_key="apply-grant-missing")


def leave_walls() -> int:
    """Walls the general browser cannot pass are left, and their records
    closed, on every beat (2026-09-23: 72 "waiting for you" cards)."""
    from aletheia import apply_run, browser_mission
    left = browser_mission.leave_walls()
    return apply_run.close_left_missions(left) if left else 0


def send_approved_applications() -> list[dict]:
    """Send what he authorized, once each.

    A failure is recorded on the run and surfaced — never retried, because
    the failure mode of a retry loop on this particular button is several
    copies of his application in somebody's inbox.

    Two things authorize a send, and the second one is the whole point:

    - the application's own approval is APPROVED (he tapped it), or
    - a standing grant covers `application.submit`.

    It was the first one alone until 2026-09-12, and his ruling retired
    that: *"No one approval per application. I want this thing just to be
    applying to jobs, nonstop."* Requiring a tap per application is exactly
    the shape that fails him, because it fails at the moment he has gone
    away — which is the moment he built this for. Two fully answered
    applications (GitLab, Figma) sat at AWAITING_YOU with zero blocking
    questions and no tap coming, and would have sat there forever.

    The grant is not a bypass. `authority.satisfy` re-reads the registry,
    checks expiry and the use count, and writes a claim receipt naming the
    application — so every unattended send is still attributable to a
    specific authorization he gave, and the grant runs out rather than
    being permanent. A high-risk capability could not be delegated this
    way at all; `application.submit` is `registry_grant` precisely because
    he decided it should be.
    """
    from aletheia import apply_run, authority
    sent = []
    for record in apply_run.all_runs("AWAITING_YOU"):
        if record.get("engine") == apply_run.ENGINE_LOOP:
            # Filled by the general browser loop: its press is its browser
            # mission's own approval (press_approved_web_tasks), never this
            # path and never on the standing grant.
            continue
        try:
            approval = policy.load(record["approval"])
        except Exception:
            approval = {}
        # NOT A FULL-TIME JOB, NOT ON THE GRANT - asked of EVERY record, not only
        # the ones whose approval is still open. `stage` spends the grant when
        # a form is filled, so live 2026-09-13 Bluevine's "(part-time)" job
        # reached this loop already APPROVED by the grant and went out unseen.
        # Only his own yes sends it; he is told why it is waiting.
        kind = apply_run.waits_for_his_ok(record)
        if kind:
            # Part-time work, or a job only her own model judged realistic.
            title, body, key = apply_run.his_ok_notice(record, kind)
            notifications.publish(
                title, body,
                priority="IMPORTANT", source="apply", about=notifications.NEEDS_YOU,
                dedupe_key=key,
                related={"application": record["id"]},
                # "Approve it if you want it" - with the button that does.
                action=({"label": "Approve it", "kind": "approve",
                         "args": {"id": str(record.get("approval"))}}
                        if record.get("approval") else None))
            continue
        if approval.get("state") == "EXPIRED":
            # A YES THAT WENT COLD IS ASKED AGAIN, not spent on. The grant was
            # claimed every beat for an application whose approval had
            # expired, and `confirm` then failed on it: eleven claims,
            # nothing sent (2026-09-23). Renew first; then the grant.
            try:
                apply_run.renew_approval(record["id"])
                record = apply_run.load_run(record["id"])
                approval = policy.load(record["approval"])
            except Exception as exc:
                notifications.publish(
                    "An application could not be sent",
                    _why_not(record, exc),
                    priority="IMPORTANT", source="apply", about=notifications.FAILED,
                    dedupe_key=f"apply-renew-failed:{record['id']}")
                continue
        if approval.get("state") == "DENIED":
            continue                      # he said no; the grant never overrides him
        if approval.get("state") != "APPROVED":
            # His standing grant. The action id names THIS application, so
            # the receipt says what the use was spent on — a probe with a
            # made-up id would spend a use and record a fiction.
            # The approval id, which is already a safe id. "apply:<id>" was
            # refused by `safe_id` (no colon), so `satisfy` returned None
            # on EVERY application even with a live grant - the second
            # silent way this path never sent anything (found 2026-09-23).
            claim = authority.satisfy(
                "application.submit", str(record.get("approval") or f"{record['id']}-submit"))
            if claim is None:
                # NOT QUIETLY. Nothing had ever created this grant, so from
                # 2026-09-12 to 2026-09-23 every filled application fell
                # through here in silence and waited for a tap he had said
                # he would not be giving - 82 of them the night he noticed.
                # One notice, once, naming the one command that fixes it.
                _say_the_grant_is_missing()
                continue
            # And then GRANT the approval, in his name, citing the grant.
            # Not because the gate is inconvenient: `accept` and `submit`
            # both re-check `policy.usable(record["approval"])`, so a run
            # carrying a standing grant and an ungranted approval would
            # have died two functions later with "it needs your
            # confirmation" — the same stall, moved somewhere harder to
            # see. Deciding the approval here keeps both of those checks
            # exactly as strict as they were and leaves one auditable
            # record of WHY it was sent without him.
            try:
                apply_run.confirm(
                    record["id"], via="standing-grant",
                    because=f"{claim}: he said send stuff, nonstop")
            except Exception as exc:
                notifications.publish(
                    "An application could not be sent",
                    _why_not(record, exc),
                    priority="IMPORTANT", source="apply", about=notifications.FAILED,
                    dedupe_key=f"apply-grant-failed:{record['id']}",
                    action=_retry_action(record))
                continue
        try:
            # accept, NOT confirm: he has already decided. `confirm` GRANTS
            # the approval, which would mean the check for his approval was
            # the thing granting it.
            apply_run.accept(record["id"])
            # IN ITS OWN PROCESS. This runs on the Core's beat, which is an
            # asyncio loop, and Playwright's sync API refuses to run inside
            # one: live 2026-09-12 every unattended send since his standing
            # grant went live died with "Playwright Sync API inside the
            # asyncio loop" — his grant was decorative and the failures were
            # only visible in the records. `campaign` has spawned its own
            # process for exactly this reason since it was written.
            done = _submit_in_its_own_process(record["id"])
        except Exception as exc:
            try:
                back = apply_run.load_run(record["id"]).get("state") == "AWAITING_YOU"
            except Exception:
                back = False
            if back:
                continue            # nothing was pressed; the next beat tries again
            notifications.publish(
                "An application could not be sent",
                _why_not(record, exc),
                priority="IMPORTANT", source="apply", about=notifications.FAILED,
                dedupe_key=f"apply-failed:{record['id']}",
                action=_retry_action(record))
            continue
        result = done.get("result", {})
        notifications.publish(
            "Application sent", _plain(f"{_where(record)} — {result.get('note', '')}"),
            priority="IMPORTANT", source="apply", about=notifications.ROUTINE,
            dedupe_key=f"apply-sent:{record['id']}",
            related={"application": record["id"]})
        sent.append({"application": record["id"], "url": record["url"],
                     "verdict": result.get("verdict")})
    return sent


def _held_live(record: dict) -> bool:
    import datetime as _dt
    until = str(record.get("held_live_until") or "")
    if not until:
        return False
    try:
        when = _dt.datetime.fromisoformat(until.replace("Z", "+00:00"))
    except ValueError:
        return False
    return when > _dt.datetime.now(_dt.timezone.utc)


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
        if _held_live(record):
            # A browser mission is still holding its live session open for this
            # yes, and presses it there (an expiring code survives). If that
            # process dies the hold lapses and this beat presses by replay.
            continue
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
                _plain(f"{record.get('button', 'the button')} at "
                       f"{_where(record)} — {speech.plainly(str(exc))}"),
                priority="IMPORTANT", source="webtask", about=notifications.FAILED,
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
            _plain(f"{record.get('goal', '')[:120]}. "
                   f"{result.get('note', '')}"),
            priority="IMPORTANT", source="webtask",
            about=(notifications.FAILED if verdict == "rejected"
                   else notifications.FINISHED),
            dedupe_key=f"webtask-pressed:{record['id']}",
            related={"web_task": record["id"]})
        pressed.append({"web_task": record["id"], "button": record.get("button"),
                        "verdict": verdict,
                        "url": result.get("url", record.get("url"))})
    if any(row.get("web_task", "").startswith("bm-apply-for-this-job") for row in pressed):
        # An application the general loop filled: its record follows its mission.
        from aletheia import apply_run
        apply_run.sync_loop_applications()
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
                _plain(f"{approval.get('reason', '')[:160]} — "
                       f"{speech.plainly(str(exc))}"),
                priority="IMPORTANT", source="script", about=notifications.FAILED,
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


def _heal_local_ai() -> dict:
    from aletheia import local_model_pool
    return local_model_pool.ensure()


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

    # Her own model stays reachable without him: Ollama stopped is started,
    # a missing model is fetched, once, in the background (the rung that
    # never runs out has to be there). Rate-limited inside; a reachable pool
    # costs one cached probe. FIRST, not last: it sat at the end of this
    # beat behind a 25 s budget, and on a loaded night (2026-09-22) the beat
    # ran out of time before it every time, so the smaller model was never
    # fetched and the rung under the fast one never existed.
    local_ai_heal = guarded("local_ai", _heal_local_ai)
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
    # What her sessions handed to him and he approved: exactly that request,
    # once, through every gate again (aletheia.handoffs).
    approved_handoffs = guarded("handoffs", _run_approved_handoffs)
    # Everything unfinished, read as one non-blocking queue (aletheia.work_engine):
    # blocked items are checkpointed with why and when, cleared ones wake, and
    # its own gap items take their next action. Inside the beat, never a second loop.
    work = guarded("work", _reconcile_work)
    power_watch = guarded("power", _watch_power)
    room_devices = guarded("room", _observe_room)
    # Meetings arranging themselves across days (Phase 15): offers that have
    # really been delivered start waiting for a reply, accepted slots ask for
    # their calendar-write approval, stale offers are abandoned.
    meetings_progress = guarded(
        "scheduling", lambda: _reconcile_scheduling(now))
    calendar_updates = guarded("calendar", lambda: _refresh_calendar(now))
    conversations_progress = guarded("conversations", lambda: _reconcile_conversations(now))
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
    stuck_submits = guarded("stuck_submits", _settle_stuck_submits)
    applications_sent = guarded("applications", send_approved_applications)
    guarded("walls", leave_walls)
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
        "local_ai": local_ai_heal,
        "skipped": skipped,
        "schedules": schedules,
        "mail_events": mail_events,
        "pulse_events": pulse_events,
        "action_records": action_records,
        "reply_transitions": reply_transitions,
        "events_processed": events_processed,
        "capability_gaps": capability_gaps,
        "approved_intents": approved_intents,
        "approved_handoffs": approved_handoffs,
        "work": work,
        "power": power_watch,
        "web_tasks_pressed": web_tasks_pressed,
        "subscriptions_settled": subscriptions_settled,
        "bookings_settled": bookings_settled,
        "scripts_run": scripts_run,
        "approvals_expired": approvals_expired,
        "authorized_errands": authorized_errands,
        "room_devices": room_devices,
        "meetings": meetings_progress,
        "calendar": calendar_updates,
        "conversations": conversations_progress,
        "handle_requests": handle_requests,
        "attention": attention_records,
        "due_tasks": due_tasks,
        "applications_sent": applications_sent,
        "delivered": delivered,
    }
