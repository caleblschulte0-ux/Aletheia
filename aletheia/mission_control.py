"""Mission control: the one screen he reads after hours away.

The brief (docs/JARVIS_BRIEF.md section 5, milestone 5): *come back after
hours away and, from one screen in ten seconds, know: is she running, what
is she doing, what did she accomplish, what failed, what needs me, what
happens next.*

`current_state` is the single root of what is true now (agent, job_hunt,
browser, code). This module does not add a second one. It turns that root,
plus the stores it already reads (the application records, today's
discovery summary, the journal, the AgentSession receipts), into the shapes
the Command Center renders:

- `header`       the state word, one "doing" sentence, one "next" sentence,
                 and whether what it says is stale (the Core's heartbeat,
                 the apply loop's last sign of life)
- `pipeline`     DISCOVERED -> REVIEWED -> APPLYING -> NEEDS YOU -> SENT ->
                 REPLIED -> INTERVIEW, counted from the records, with a card
                 per application that answers "why this one?" and "why
                 didn't this send?"
- `discovery`    today's discovery summary and its outlier / best-fit queues
- `ribbon`       what she did, newest first, in sentences, each with the
                 receipt it came from one click away
- `eyes`         the browser's site, purpose and stage, and the screenshot
                 already on the record (never a new one: reading must not act)

THE BUILDERS ARE PURE. Every one takes plain dicts and a `now`, and touches
no store, so the tests hold the derivation rather than a fixture directory.
`gather` is the only function that reads, and it reads each store once.

MODEL PROVENANCE IS A RECEIPT FIELD. A session answered by `ollama:qwen3`
or a fit judged by `model:codex` says so inside the receipt; the sentence on
the ribbon is hers. The model is who she hired, not who she is.

Read-only throughout: nothing here approves, submits, halts or launches.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Iterable

#: The pipeline, in the brief's words and order.
STAGES = ("DISCOVERED", "REVIEWED", "APPLYING", "NEEDS YOU", "SENT", "REPLIED", "INTERVIEW")
#: Where an application leaves the pipeline without going further.
OFF_RAMPS = ("STOPPED", "SET ASIDE")

#: The Core writes a heartbeat every sync beat (60s). Past this it is not
#: "running", whatever the page last said.
CORE_STALE_S = 300.0
#: `apply_forever` waits five minutes between turns and journals every batch
#: it starts; a running batch holds the campaign lock. Quiet for longer than
#: this, with no batch running, and the loop is not demonstrably alive.
LOOP_QUIET_S = 20 * 60.0
#: A campaign lock older than this is the stale-lock shape (2026-09-13: a
#: three-hour lock held the hunt still).
LOCK_OLD_S = 3 * 3600.0

CARDS_PER_STAGE = 12
RIBBON_LIMIT = 40
GATHER_CACHE_S = 5.0
_GATHERED: dict[str, Any] = {"at": 0.0, "value": None}

#: Journal subjects that are plumbing, not something she did for him.
NOISE_SUBJECTS = frozenset({"formfill", "workspace:read", "calendar:refresh", "quick"})
#: Journal subjects whose application-level lines the records say better.
RECORD_SUBJECTS = frozenset({"apply"})

#: What the ribbon calls each part of her, in words.
SUBJECT_LABELS = {
    "apply:forever": "Job hunt", "campaign": "Job hunt", "jobs": "Job search",
    "job-discovery": "Discovery", "apply": "Applications", "core": "Core",
    "core:sync": "Core", "supervisor": "Core", "access": "Access",
    "followup": "Conversation", "code": "Code", "project": "Projects",
}


# ---- small pure helpers ----------------------------------------------------------

def _parse(stamp: object) -> dt.datetime | None:
    if not stamp:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _age_s(stamp: object, now: dt.datetime) -> float | None:
    when = _parse(stamp)
    return None if when is None else max(0.0, (now - when).total_seconds())


def _stamp(when: dt.datetime) -> str:
    return when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _words(text: object, limit: int = 240) -> str:
    said = " ".join(str(text or "").split())
    if len(said) <= limit:
        return said
    cut = said[:limit].rsplit(" ", 1)[0]
    return (cut or said[:limit]).rstrip(",;:-") + "..."


def duration_words(seconds: float | None) -> str:
    """"40 seconds", "12 minutes", "3 hours", "2 days"."""
    if seconds is None:
        return "an unknown time"
    s = max(0, int(seconds))
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if s >= size * (2 if unit == "day" else 1):
            n = round(s / size)
            return f"{n} {unit}{'s' if n != 1 else ''}"
    return f"{s} second{'s' if s != 1 else ''}"


def _plural(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def describe(record: dict) -> str:
    """The job, then the employer; pure (no job_fit lookup)."""
    title = " ".join(str(record.get("job_title") or "").split())
    company = " ".join(str(record.get("company") or "").split())
    if title and company and company.casefold() not in title.casefold():
        return f"{title} at {company}"
    return (title or company or " ".join(str(record.get("page_title") or "").split())
            or _site(record.get("url")) or str(record.get("id") or "an application"))


def _site(url: object) -> str:
    from urllib.parse import urlparse
    try:
        return urlparse(str(url or "")).netloc
    except ValueError:
        return ""


# ---- is she running? --------------------------------------------------------------

def apply_loop(lock: dict | None, entries: Iterable[dict], now: dt.datetime, *,
               halted: bool = False, resting: bool = False) -> dict:
    """Whether the apply loop is demonstrably alive, from what it leaves behind.

    It has no heartbeat of its own. What it does leave: the campaign lock
    while a batch runs, and a journal line each time it starts one (every
    five minutes when nothing is running). `alive` is True, False, or None
    when quiet is expected (halted, or nobody can think and it is waiting).
    """
    if lock and lock.get("running"):
        age = _age_s(lock.get("started_at"), now)
        if age is not None and age > LOCK_OLD_S:
            return {"alive": None, "stale": True, "last_seen": lock.get("started_at"),
                    "said": f"a batch has held the campaign lock for {duration_words(age)}, "
                            "longer than any batch should take"}
        return {"alive": True, "stale": False, "last_seen": lock.get("started_at"),
                "said": "a batch is running"
                        + (f" (started {duration_words(age)} ago)" if age is not None else "")}
    last = None
    for entry in entries:
        subject = str(entry.get("subject") or "")
        if subject in ("apply:forever", "campaign") or entry.get("actor") == "aletheia-apply-forever":
            if last is None or str(entry.get("ts") or "") > str(last.get("ts") or ""):
                last = entry
    seen = last.get("ts") if last else None
    age = _age_s(seen, now)
    if halted:
        return {"alive": None, "stale": False, "last_seen": seen,
                "said": "halted with everything else"}
    if age is not None and age <= LOOP_QUIET_S:
        return {"alive": True, "stale": False, "last_seen": seen,
                "said": f"last started work {duration_words(age)} ago"}
    if resting:
        return {"alive": None, "stale": False, "last_seen": seen,
                "said": "waiting until someone can think"}
    return {"alive": False, "stale": True, "last_seen": seen,
            "said": ("no sign of the apply loop in the journal" if age is None
                     else f"the apply loop has not started anything for {duration_words(age)}")}


def header(agent: dict, *, now: dt.datetime, core: dict, loop: dict, hunt: dict | None = None,
           browser: dict | None = None, pending_approvals: int = 0, applications_waiting: int | None = None,
           say_time: Callable | None = None) -> dict:
    """"What is Thea doing right now?" - the state word, doing, next, stale.

    `agent` is `current_state.agent`'s block; `core` is {"heartbeat_age_s",
    "alive"}; `loop` is `apply_loop`'s answer. `pending_approvals` counts the
    approvals that are NOT an application's (those are counted once, as
    `applications_waiting`, the pipeline's NEEDS YOU). Pure.
    """
    from aletheia.current_state import AGENT_STATES
    hunt = hunt or {}
    browser = browser or {}
    state = str(agent.get("state") or "IDLE")
    if state not in AGENT_STATES:
        state = "IDLE"
    step = _words(agent.get("step"), 180)
    mission = _words(agent.get("mission"), 80)
    say_time = say_time or (lambda when: _stamp(when))

    what = (step or mission).rstrip(". ")
    doing = {
        "HALTED": "Halted" + (f": {step.rstrip('. ')}" if step else "") + ". Nothing acts until you resume her.",
        "IDLE": "Nothing in flight right now.",
        "ACTING": f"Working: {what}.",
        "LOOKING": f"Looking: {what}.",
        "THINKING": f"Thinking: {what}.",
        "BLOCKED": f"Stuck: {what}.",
        "NEEDS YOU": f"Waiting on you: {what}.",
        "WAITING": f"Waiting on the world: {what}.",
        "LISTENING": "Listening: the microphone is open.",
    }[state]

    waiting = list(hunt.get("waiting_on_him") or [])
    if applications_waiting is None:
        applications_waiting = len(waiting)
    minds = hunt.get("thinking") or {}
    lock = hunt.get("campaign") or {}
    if state == "HALTED":
        nxt = "Nothing, until you resume her."
    elif state == "BLOCKED":
        until = _parse((minds.get("claude") or {}).get("resting_until"))
        nxt = (f"The job hunt picks up when Claude is back at {say_time(until)}." if until
               else "The job hunt picks up when a model can think again.")
    elif state == "NEEDS YOU" and waiting:
        first = waiting[0]
        who = first.get("company") or first.get("job") or "an application"
        more = (f" (and {applications_waiting - 1} more)" if applications_waiting > 1 else "")
        nxt = f"{who} is waiting on you: {first.get('why') or 'your answer'}{more}."
    elif state == "NEEDS YOU" and pending_approvals:
        nxt = f"{_plural(pending_approvals, 'approval')} waiting for your yes or no."
    elif state in ("ACTING", "LOOKING"):
        size = lock.get("count") or lock.get("limit")
        batch = f"this batch of {size}" if size else "this batch"
        nxt = (f"Finish {batch}; the apply loop starts another within 5 minutes."
               if loop.get("alive") else
               f"Finish {batch}. {str(loop.get('said') or '').capitalize()}, so nothing may follow it.")
    elif state == "THINKING":
        nxt = "Your answer appears in the conversation when it is ready."
    elif loop.get("alive") and not hunt.get("running"):
        nxt = "The apply loop starts another batch within 5 minutes."
    elif loop.get("alive"):
        nxt = "Keep applying until you say stop."
    elif loop.get("alive") is False:
        nxt = f"Nothing is scheduled: {loop.get('said')}."
    else:
        nxt = "Nothing is scheduled."

    age = core.get("heartbeat_age_s")
    core_ok = bool(core.get("alive")) and age is not None and age <= CORE_STALE_S
    signals = [{
        "what": "core", "ok": core_ok,
        "said": (f"Core heartbeat {duration_words(age)} old" if age is not None
                 else "the Core has never recorded a heartbeat"),
    }, {
        "what": "apply loop", "ok": loop.get("alive") is not False and not loop.get("stale"),
        "said": str(loop.get("said") or ""),
    }]
    stale = not core_ok
    banner = ""
    if not core_ok:
        banner = ("The Core's heartbeat is " + (f"{duration_words(age)} old" if age is not None else "missing")
                  + ": this screen may be out of date and nothing may be running.")
    elif loop.get("alive") is False or loop.get("stale"):
        banner = f"The job hunt looks stopped: {loop.get('said')}."
    return {"state": state, "doing": doing, "next": nxt, "since": agent.get("since"),
            "mission": mission, "stale": stale, "banner": banner, "signals": signals,
            "needs_you": pending_approvals + applications_waiting,
            "needs_you_parts": {"applications": applications_waiting, "approvals": pending_approvals},
            "as_of": _stamp(now)}


# ---- the job hunt control room -----------------------------------------------------

def stage_of(record: dict, *, approval_state: str = "", his_ok: str = "",
             grant_live: bool = False) -> str:
    """Where one application record sits in the pipeline."""
    state = str(record.get("state") or "")
    if state == "SUBMITTED":
        outcome = str(record.get("outcome") or "")
        if outcome in ("interview", "offer"):
            return "INTERVIEW"
        if outcome in ("replied", "rejected", "closed"):
            return "REPLIED"
        return "SENT"
    if state in ("SUBMITTING", "APPROVED"):
        return "APPLYING"
    if state in ("NEEDS_YOU", "NEEDS_ACCOUNT"):
        return "NEEDS YOU"
    if state == "AWAITING_YOU":
        if his_ok:
            return "NEEDS YOU"
        if approval_state == "APPROVED" or grant_live:
            return "APPLYING"
        return "NEEDS YOU"
    if state in ("FAILED", "REJECTED"):
        return "STOPPED"
    if state == "CLOSED":
        return "SET ASIDE"
    return "REVIEWED"


_EXCEPTION_PREFIX = re.compile(r"^(?:[A-Z][A-Za-z]+(?:Error|Exception)):\s*")


def plain_failure(text: object) -> str:
    """A recorded failure in plain words: the exception class is not a reason."""
    said = _words(text, 400)
    if not said:
        return ""
    if said.startswith("TargetClosedError") or "Target page, context or browser has been closed" in said:
        return "the browser closed while she was on the form, so nothing was sent"
    if said.startswith("TimeoutError"):
        return "the page took too long to answer, so nothing was sent"
    said = _EXCEPTION_PREFIX.sub("", said)
    return said[:1].upper() + said[1:]


def why_not_sent(record: dict, *, stage: str, approval_state: str = "", his_ok: str = "",
                 grant_live: bool = False) -> str:
    """"Why didn't this send?" from the blocker the record holds. "" when it did."""
    state = str(record.get("state") or "")
    if stage in ("SENT", "REPLIED", "INTERVIEW"):
        return ""
    if state == "SUBMITTING":
        return "Submit was pressed and its answer was never recorded; it is not pressed again without proof."
    if state == "NEEDS_YOU":
        labels = [_words(q.get("label"), 80) for q in (record.get("questions") or [])
                  if isinstance(q, dict) and q.get("label")]
        if labels:
            shown = "; ".join(labels[:3]) + (f"; and {len(labels) - 3} more" if len(labels) > 3 else "")
            return f"The form asks what only you can answer: {shown}."
        return _words(record.get("say"), 300) or "The form asks something only you can answer."
    if state == "NEEDS_ACCOUNT":
        return "The employer wants an account first. " + plain_failure(record.get("failure"))
    if state == "AWAITING_YOU":
        if his_ok == "judged-locally":
            return ("Filled, but only her own model judged it realistic, so it waits for your OK "
                    "rather than the standing grant.")
        if his_ok:
            return f"Filled, but it is {his_ok} work, so it waits for your own OK rather than the standing grant."
        if approval_state == "APPROVED":
            return "Approved; it sends on the Core's next beat."
        if grant_live:
            return "Filled; your standing grant sends it on the Core's next beat."
        if approval_state == "EXPIRED":
            return "Filled, but its approval expired and no standing grant covers sending, so it waits for your OK."
        return "Filled and ready; no standing grant covers sending, so it waits for your OK."
    if state in ("FAILED", "REJECTED"):
        said = plain_failure(record.get("failure"))
        if not said:
            evidence = record.get("click_evidence")
            if isinstance(evidence, dict) and evidence.get("captcha"):
                said = "A CAPTCHA challenge was in front of the Submit button"
            elif state == "REJECTED":
                said = "The site handed the form back instead of accepting it"
            else:
                said = "It failed without recording why"
        return said.rstrip(".") + "."
    if state == "CLOSED":
        return "Set aside: " + (_words(record.get("closed_because"), 300) or "closed without a reason recorded").rstrip(".") + "."
    return ""


def why_this_one(record: dict) -> dict | None:
    """"Why this one?" from `job_value`'s reasons, else the fit judgement."""
    liked = [str(x) for x in (record.get("why_she_liked_it") or []) if str(x).strip()]
    against = [str(x) for x in (record.get("why_not") or []) if str(x).strip()]
    if liked or against:
        from aletheia import job_value
        return {"said": job_value.why(record), "liked": liked[:6], "against": against[:4],
                "value": record.get("value"), "queue": record.get("queue") or "",
                "source": "job_value"}
    fit = record.get("fit")
    if isinstance(fit, dict) and str(fit.get("why") or "").strip():
        return {"said": _words(fit.get("why"), 400), "liked": [], "against": [],
                "value": None, "queue": "", "source": "fit"}
    return None


def _last_moved(record: dict) -> str:
    stamps = [str(record.get(k) or "") for k in
              ("submitted_at", "pressed_at", "closed_at", "reopened_at", "staged_at")]
    stamps += [str(o.get("at") or "") for o in (record.get("outcomes") or []) if isinstance(o, dict)]
    return max(stamps) if stamps else ""


def card(record: dict, *, stage: str, approval_state: str = "", his_ok: str = "",
         grant_live: bool = False, has_screenshot: bool = False) -> dict:
    captcha = str(record.get("captcha") or "")
    return {
        "id": record.get("id"),
        "title": describe(record),
        "company": " ".join(str(record.get("company") or "").split()),
        "site": _site(record.get("url")),
        "url": str(record.get("url") or ""),
        "state": record.get("state"),
        "stage": stage,
        "when": _last_moved(record),
        "why_this_one": why_this_one(record),
        "why_not_sent": why_not_sent(record, stage=stage, approval_state=approval_state,
                                     his_ok=his_ok, grant_live=grant_live),
        "captcha": captcha,
        "outcome": record.get("outcome") or "",
        "screenshot": bool(has_screenshot),
    }


def pipeline(records: list[dict], *, facts: dict | None = None, grant_live: bool = False,
             discovery_today: dict | None = None, today_floor: str = "",
             has_screenshot: Callable[[dict], bool] | None = None,
             per_stage: int = CARDS_PER_STAGE) -> dict:
    """Counts and cards per stage, from the records. Pure.

    `facts` maps application id -> {"approval_state", "his_ok"} (read by
    `gather`); `discovery_today` is `job_discovery.today()`.
    """
    facts = facts or {}
    has_screenshot = has_screenshot or (lambda r: False)
    lanes: dict[str, list[dict]] = {s: [] for s in STAGES + OFF_RAMPS}
    for record in records:
        if not isinstance(record, dict) or "state" not in record:
            continue
        f = facts.get(record.get("id")) or {}
        stage = stage_of(record, approval_state=f.get("approval_state", ""),
                         his_ok=f.get("his_ok", ""), grant_live=grant_live)
        lanes[stage].append((record, f, stage))  # type: ignore[arg-type]

    def today(stage: str, rows) -> int | None:
        if not today_floor:
            return None
        key = {"SENT": "submitted_at", "REPLIED": None, "INTERVIEW": None}.get(stage, "staged_at")
        n = 0
        for record, _f, _s in rows:
            if key is None:
                n += any(str(o.get("at") or "") >= today_floor for o in (record.get("outcomes") or [])
                         if isinstance(o, dict))
            else:
                n += str(record.get(key) or record.get("staged_at") or "") >= today_floor
        return n

    stages = []
    summary = discovery_today or {}
    for stage in STAGES:
        rows = sorted(lanes[stage], key=lambda t: _last_moved(t[0]), reverse=True)
        entry = {"stage": stage, "count": len(rows), "today": today(stage, rows), "source": "records",
                 "cards": [card(r, stage=s, approval_state=f.get("approval_state", ""),
                                his_ok=f.get("his_ok", ""), grant_live=grant_live,
                                has_screenshot=has_screenshot(r))
                           for r, f, s in rows[:per_stage]]}
        if stage in ("DISCOVERED", "REVIEWED"):
            # Openings exist before a record does. These two come from the
            # day's discovery summary; a day with none says so, not zero.
            field = "discovered" if stage == "DISCOVERED" else "qualified"
            if summary:
                entry.update({"count": int(summary.get(field) or 0), "today": int(summary.get(field) or 0),
                              "source": "today's discovery summary"})
            else:
                entry.update({"count": None, "today": None,
                              "source": "no discovery summary recorded today"})
            entry["cards"] = []
        stages.append(entry)
    off = []
    for ramp in OFF_RAMPS:
        rows = sorted(lanes[ramp], key=lambda t: _last_moved(t[0]), reverse=True)
        off.append({"stage": ramp, "count": len(rows), "today": today(ramp, rows), "source": "records",
                    "cards": [card(r, stage=s, approval_state=f.get("approval_state", ""),
                                   his_ok=f.get("his_ok", ""), grant_live=grant_live,
                                   has_screenshot=has_screenshot(r))
                              for r, f, s in rows[:per_stage]]})
    return {"stages": stages, "off_ramps": off, "records": sum(len(v) for v in lanes.values()),
            "grant_live": bool(grant_live)}


def discovery(summary: dict | None) -> dict:
    """Today's discovery summary as the control room shows it. Pure."""
    from aletheia import job_discovery
    if not summary:
        return {"day": None, "said": job_discovery.spoken(None), "discovered": None, "qualified": None,
                "crawled": None, "outliers": [], "best": [], "employers_new": [], "sources": {}}

    def by_value(rows):
        return sorted([r for r in rows or [] if isinstance(r, dict)],
                      key=lambda r: -int(r.get("value") or 0))
    return {"day": summary.get("day"), "said": job_discovery.spoken(summary),
            "discovered": summary.get("discovered", 0), "qualified": summary.get("qualified", 0),
            "crawled": summary.get("crawled", 0), "outliers": by_value(summary.get("outliers"))[:12],
            "best": by_value(summary.get("best"))[:12],
            "employers_new": list(summary.get("employers_new") or [])[:20],
            "sources": dict(summary.get("sources") or {}), "updated": summary.get("updated")}


# ---- the activity ribbon -------------------------------------------------------------

def journal_id(entry: dict) -> str:
    raw = json.dumps([entry.get("ts"), entry.get("subject"), entry.get("text")], ensure_ascii=False)
    return "j-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _sentence(text: str) -> str:
    said = _words(text, 220)
    return (said[:1].upper() + said[1:]) if said else ""


def ribbon(*, journal_entries: Iterable[dict], records: Iterable[dict], sessions: Iterable[dict],
           limit: int = RIBBON_LIMIT) -> list[dict]:
    """What she did, newest first, one sentence each, receipt attached. Pure."""
    items: list[dict] = []
    for entry in journal_entries:
        subject = str(entry.get("subject") or "")
        kind = str(entry.get("kind") or "")
        if subject in NOISE_SUBJECTS or (subject == "access" and kind != "alert"):
            continue
        if subject in RECORD_SUBJECTS and kind != "alert":
            continue
        said = _sentence(entry.get("text") or "")
        if not said or not entry.get("ts"):
            continue
        items.append({"at": entry["ts"], "tone": "alert" if kind == "alert" else "info",
                      "what": SUBJECT_LABELS.get(subject, subject.split(":")[0].capitalize() or "Journal"),
                      "said": said, "receipt": {"kind": "journal", "id": journal_id(entry)}})
    for record in records:
        if not isinstance(record, dict) or not record.get("id"):
            continue
        receipt = {"kind": "application", "id": record["id"]}
        named = describe(record)
        state = record.get("state")
        if state == "SUBMITTED" and (record.get("submitted_at") or record.get("pressed_at")):
            items.append({"at": record.get("submitted_at") or record.get("pressed_at"), "tone": "good",
                          "what": "Applications", "said": f"Sent {named}.", "receipt": receipt})
        elif state in ("FAILED", "REJECTED") and record.get("staged_at"):
            items.append({"at": record.get("pressed_at") or record["staged_at"], "tone": "alert",
                          "what": "Applications",
                          "said": f"Couldn't send {named}: " + why_not_sent(record, stage="STOPPED"),
                          "receipt": receipt})
        elif state in ("NEEDS_YOU", "NEEDS_ACCOUNT") and record.get("staged_at"):
            items.append({"at": record["staged_at"], "tone": "needs", "what": "Applications",
                          "said": f"{named} needs you. " + why_not_sent(record, stage="NEEDS YOU"),
                          "receipt": receipt})
        elif state == "AWAITING_YOU" and record.get("staged_at"):
            items.append({"at": record["staged_at"], "tone": "info", "what": "Applications",
                          "said": f"Filled the application for {named}.", "receipt": receipt})
        elif state == "CLOSED" and record.get("closed_at"):
            items.append({"at": record["closed_at"], "tone": "info", "what": "Applications",
                          "said": f"Set aside {named}: " + _words(record.get("closed_because"), 160),
                          "receipt": receipt})
        for outcome in record.get("outcomes") or []:
            if isinstance(outcome, dict) and outcome.get("at"):
                note = _words(outcome.get("note"), 120)
                items.append({"at": outcome["at"], "tone": "good", "what": "Applications",
                              "said": f"{record.get('company') or named}: {outcome.get('outcome')}"
                                      + (f" - {note}" if note else "") + ".",
                              "receipt": receipt})
    for session in sessions:
        if not isinstance(session, dict) or not session.get("id"):
            continue
        at = session.get("saved_at")
        if not at:
            continue
        question = _words(session.get("question"), 120)
        looked = [s.get("tool") for s in (session.get("sources") or []) if isinstance(s, dict)]
        outcome = str(session.get("outcome") or "")
        if outcome == "answered":
            said = f"Answered “{question}”" + (f" after looking at {', '.join(looked[:3])}" if looked
                                                          else " without looking anything up")
        elif outcome == "handed_off":
            said = f"Handed “{question}” to you: it needs your decision"
        elif outcome == "refused_at_door":
            said = f"Refused “{question}”: it asks to spend money"
        else:
            said = f"Couldn't finish “{question}” ({outcome.replace('_', ' ') or 'no outcome'})"
        items.append({"at": at, "tone": "alert" if outcome not in ("answered", "handed_off", "refused_at_door")
                      else "info", "what": "Conversation", "said": said + ".",
                      "receipt": {"kind": "session", "id": session["id"]}})
    items.sort(key=lambda i: str(i.get("at") or ""), reverse=True)
    return items[:max(0, int(limit))]


# ---- eyes ------------------------------------------------------------------------------

def eyes(browser: dict, *, records_by_id: dict, has_screenshot: Callable[[dict], bool]) -> dict:
    """The browser's site, purpose and stage, and the screenshot on record. Pure."""
    browser = browser or {}
    out = {"active": bool(browser.get("active")), "site": browser.get("site") or "",
           "purpose": browser.get("purpose") or "", "stage": browser.get("stage") or "",
           "since": browser.get("since"), "application": browser.get("application"),
           "readable": browser.get("readable", True), "screenshot": None, "last": None}
    last = browser.get("last") if isinstance(browser.get("last"), dict) else None
    if last:
        record = records_by_id.get(last.get("application")) or {}
        out["last"] = {"application": last.get("application"), "site": last.get("site") or "",
                       "what": last.get("what") or "", "state": last.get("state"), "at": last.get("at"),
                       "title": describe(record) if record else (last.get("what") or "")}
    for app_id, why in ((browser.get("application"), "the application she is on now"),
                        ((last or {}).get("application"), "the last application she worked")):
        record = records_by_id.get(app_id) if app_id else None
        if record and has_screenshot(record):
            out["screenshot"] = {"application": app_id, "of": why, "title": describe(record),
                                 "src": f"/api/mission/screenshot?id={app_id}",
                                 "at": _last_moved(record)}
            break
    return out


# ---- reading the stores (the only impure part) ----------------------------------------

def screenshot_path(record: dict) -> Path | None:
    """The newest screenshot the record already points at, inside the
    applications directory, if it exists. Never takes one."""
    from aletheia import apply_run
    try:
        home = apply_run.staged_dir().resolve()
    except Exception:
        return None
    candidates = []
    result = record.get("result")
    if isinstance(result, dict) and result.get("screenshot"):
        candidates.append(result["screenshot"])
    if record.get("screenshot"):
        candidates.append(record["screenshot"])
    for raw in candidates:
        try:
            path = Path(str(raw)).resolve()
        except (OSError, ValueError):
            continue
        if path.suffix.lower() == ".png" and path.parent == home and path.is_file():
            return path
    return None


def _sessions(limit: int = 30) -> list[dict]:
    from aletheia import stateio
    try:
        directory = stateio.private_dir("agent-sessions")
        paths = sorted(directory.glob("agent-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return []
    out = []
    for path in paths[:limit]:
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def _approval_state(approval_id: str) -> str:
    from aletheia import policy
    if not approval_id:
        return ""
    try:
        return str(policy.load(approval_id).get("state") or "")
    except Exception:
        return ""


def _grant_live(now: dt.datetime) -> bool:
    from aletheia import authority
    try:
        return any(authority.allows(g, "application.submit", now=now) for g in authority.active_grants(now=now))
    except Exception:
        return False


def gather(now: dt.datetime | None = None, *, fresh: bool = False) -> dict:
    """Everything the mission screen shows, read once. Never raises."""
    clock = time.monotonic()
    if not fresh and _GATHERED["value"] is not None and clock - _GATHERED["at"] < GATHER_CACHE_S:
        return json.loads(json.dumps(_GATHERED["value"]))
    from aletheia import apply_run, current_state, journal, liveness, policy
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    notes: list[str] = []
    derived = current_state.sections(now)
    hunt = derived.get("job_hunt") or {}
    try:
        records = apply_run.all_runs()
    except Exception as exc:  # noqa: BLE001
        records = []
        notes.append(f"the application records could not be read ({type(exc).__name__})")
    by_id = {r.get("id"): r for r in records if r.get("id")}
    facts = {}
    for r in records:
        if r.get("state") != "AWAITING_YOU":
            continue
        try:
            his_ok = apply_run.waits_for_his_ok(r)
        except Exception:
            his_ok = ""
        facts[r.get("id")] = {"approval_state": _approval_state(str(r.get("approval") or "")),
                              "his_ok": his_ok}
    try:
        entries = journal.entries()[-600:]
    except Exception as exc:  # noqa: BLE001
        entries = []
        notes.append(f"the journal could not be read ({type(exc).__name__})")
    try:
        pending = [a for a in policy.all_approvals() if a.get("state") == "PENDING"]
    except Exception:
        pending = []
    halt = None
    try:
        halt = policy.halted()
    except Exception:
        pass
    agent = derived.get("agent") or {}
    try:
        agent = current_state.agent(now, hunt=hunt, browsing=derived.get("browser") or {},
                                    pending_approvals=pending)
    except Exception:
        pass
    age = None
    try:
        age = liveness.age_seconds()
    except Exception:
        pass
    core = {"heartbeat_age_s": None if age is None else round(age, 1),
            "alive": bool(age is not None and age <= CORE_STALE_S)}
    try:
        from aletheia import job_discovery
        summary = job_discovery.today(now)
    except Exception:
        summary = None
        notes.append("today's discovery summary could not be read")
    shots: dict[str, bool] = {}

    def has_shot(record: dict) -> bool:
        key = str(record.get("id") or "")
        if key not in shots:
            shots[key] = screenshot_path(record) is not None
        return shots[key]

    try:
        from aletheia import reasoner
        say_time = reasoner.spoken_time
    except Exception:
        say_time = None
    referenced = {str(r.get("approval") or "") for r in records if r.get("approval")}
    other_approvals = [a for a in pending if a.get("id") not in referenced]
    loop = apply_loop(hunt.get("campaign"), entries, now, halted=bool(halt),
                      resting=bool(hunt.get("blocked")))
    piped = pipeline(records, facts=facts, grant_live=_grant_live(now),
                     discovery_today=summary, today_floor=current_state.today_started(now),
                     has_screenshot=has_shot)
    waiting_count = next((st["count"] for st in piped["stages"] if st["stage"] == "NEEDS YOU"), 0) or 0
    value = {
        "version": 1,
        "as_of": _stamp(now),
        "header": header(agent, now=now, core=core, loop=loop, hunt=hunt,
                         browser=derived.get("browser"), pending_approvals=len(other_approvals),
                         applications_waiting=waiting_count, say_time=say_time),
        "apply_loop": loop,
        "job_hunt": {"running": hunt.get("running"), "today": hunt.get("today"), "now": hunt.get("now"),
                     "readable": hunt.get("readable"), "note": hunt.get("note")},
        "pipeline": piped,
        "discovery": discovery(summary),
        "ribbon": ribbon(journal_entries=entries, records=records, sessions=_sessions()),
        "eyes": eyes(derived.get("browser") or {}, records_by_id=by_id, has_screenshot=has_shot),
        "code": derived.get("code"),
        "notes": notes,
    }
    value = json.loads(json.dumps(value, default=str))
    _GATHERED.update({"at": clock, "value": value})
    return json.loads(json.dumps(value))


def forget_cache() -> None:
    _GATHERED.update({"at": 0.0, "value": None})


#: Fields of an application record the receipt leaves out: the resume path
#: and the full step list say nothing he needs and can be long.
_RECEIPT_DROP = ("resume", "steps")


def receipt(kind: str, ident: str) -> dict | None:
    """The record a ribbon line or a card came from. None when there is none."""
    from aletheia import stateio
    kind = str(kind or "")
    ident = str(ident or "")
    try:
        if kind == "application":
            from aletheia import apply_run
            record = apply_run.load_run(ident)
            shown = {k: v for k, v in record.items() if k not in _RECEIPT_DROP}
            approval_state = _approval_state(str(record.get("approval") or ""))
            try:
                his_ok = apply_run.waits_for_his_ok(record) if record.get("state") == "AWAITING_YOU" else ""
            except Exception:
                his_ok = ""
            live = _grant_live(dt.datetime.now(dt.timezone.utc))
            stage = stage_of(record, approval_state=approval_state, his_ok=his_ok, grant_live=live)
            shown["_explained"] = {
                "stage": stage,
                "why_this_one": why_this_one(record),
                "why_not_sent": why_not_sent(record, stage=stage, approval_state=approval_state,
                                             his_ok=his_ok, grant_live=live),
                "screenshot": screenshot_path(record) is not None,
            }
            return {"kind": kind, "id": ident, "record": shown}
        if kind == "session":
            path = stateio.private_dir("agent-sessions") / f"{stateio.safe_id(ident, name='session id')}.json"
            record = json.loads(path.read_text(encoding="utf-8"))
            return {"kind": kind, "id": ident, "record": record,
                    # who she hired to think, said as what it is
                    "provenance": {"model": record.get("model") or "", "basis": record.get("basis") or "",
                                   "sources": record.get("sources") or []}}
        if kind == "journal":
            from aletheia import journal
            for entry in reversed(journal.entries()[-3000:]):
                if journal_id(entry) == ident:
                    return {"kind": kind, "id": ident, "record": entry}
            return None
    except (OSError, ValueError, KeyError):
        return None
    return None


def screenshot_for(app_id: str) -> Path | None:
    from aletheia import apply_run
    try:
        return screenshot_path(apply_run.load_run(app_id))
    except (OSError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="What the mission screen shows, as JSON.")
    ap.add_argument("part", nargs="?", help="header, pipeline, discovery, ribbon, eyes; omit for all")
    args = ap.parse_args(argv)
    value = gather(fresh=True)
    if args.part:
        value = value.get(args.part, {"error": f"no part {args.part!r}"})
    print(json.dumps(value, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
