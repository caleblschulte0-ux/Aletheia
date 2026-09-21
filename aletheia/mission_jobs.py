"""The job hunt, as one mission type plugged into mission control.

Operator direction, 2026-09-16: *"jobs should be the current test case, not
the architecture."* `mission_control` is the generic screen: the state
word, the mission cards, what needs him, the ribbon, eyes. This module is
the job hunt's PROVIDER for it, registered in `mission_control.registry()`.
It contributes what any provider contributes (a mission card, needs,
liveness signals, ribbon lines, screenshot candidates, a detail view) and
keeps what only applications have:

- the pipeline DISCOVERED -> REVIEWED -> APPLYING -> NEEDS YOU -> SENT ->
  REPLIED -> INTERVIEW, counted from the records, with a card per
  application answering "why this one?" and "why didn't this send?"
- today's discovery summary and its outlier / best-fit queues
- whether the apply loop is demonstrably alive, from what it leaves behind

`read` is the only impure function and reads each store once; `build` and
every helper below it are pure, so the tests hold the derivation.

Read-only throughout: nothing here approves, submits, halts or launches.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any, Callable, Iterable

from aletheia.mission_control import (Provider, _age_s, _parse, _plural, _stamp,
                                      _words, duration_words, mission_card)

TYPE = "job_hunt"
MISSION_ID = "job-hunt"

#: The pipeline, in the brief's words and order.
STAGES = ("DISCOVERED", "REVIEWED", "APPLYING", "NEEDS YOU", "SENT", "REPLIED", "INTERVIEW")
#: Where an application leaves the pipeline without going further.
OFF_RAMPS = ("STOPPED", "SET ASIDE")

#: `apply_forever` waits five minutes between turns and journals every batch
#: it starts; a running batch holds the campaign lock. Quiet for longer than
#: this, with no batch running, and the loop is not demonstrably alive.
LOOP_QUIET_S = 20 * 60.0
#: A campaign lock older than this is the stale-lock shape (2026-09-13: a
#: three-hour lock held the hunt still).
LOCK_OLD_S = 3 * 3600.0
#: The hunt counts as something she is pursuing while it has left a mark
#: this recently. Older than that it is history, not a mission.
PURSUED_S = 7 * 86400.0
#: A loop that died within this window is news worth a banner; one that
#: stopped days ago is simply not running, and the card says so.
BANNER_S = 24 * 3600.0

CARDS_PER_STAGE = 12
NEEDS_LISTED = 8

LOOP_SUBJECTS = ("apply:forever", "campaign")


# ---- small pure helpers ----------------------------------------------------------

def _site(url: object) -> str:
    from urllib.parse import urlparse
    try:
        return urlparse(str(url or "")).netloc
    except ValueError:
        return ""


def describe(record: dict) -> str:
    """The job, then the employer; pure (no job_fit lookup)."""
    title = " ".join(str(record.get("job_title") or "").split())
    company = " ".join(str(record.get("company") or "").split())
    if title and company and company.casefold() not in title.casefold():
        return f"{title} at {company}"
    return (title or company or " ".join(str(record.get("page_title") or "").split())
            or _site(record.get("url")) or str(record.get("id") or "an application"))


def _last_moved(record: dict) -> str:
    stamps = [str(record.get(k) or "") for k in
              ("submitted_at", "pressed_at", "closed_at", "reopened_at", "staged_at")]
    stamps += [str(o.get("at") or "") for o in (record.get("outcomes") or []) if isinstance(o, dict)]
    return max(stamps) if stamps else ""


# ---- is the apply loop alive? -------------------------------------------------------

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
        if subject in LOOP_SUBJECTS or entry.get("actor") == "aletheia-apply-forever":
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


# ---- the pipeline --------------------------------------------------------------------

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


def card(record: dict, *, stage: str, approval_state: str = "", his_ok: str = "",
         grant_live: bool = False, has_screenshot: bool = False) -> dict:
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
        "captcha": str(record.get("captcha") or ""),
        "outcome": record.get("outcome") or "",
        "screenshot": bool(has_screenshot),
    }


def pipeline(records: list[dict], *, facts: dict | None = None, grant_live: bool = False,
             discovery_today: dict | None = None, today_floor: str = "",
             has_screenshot: Callable[[dict], bool] | None = None,
             per_stage: int = CARDS_PER_STAGE) -> dict:
    """Counts and cards per stage, from the records. Pure.

    `facts` maps application id -> {"approval_state", "his_ok"} (read by
    `read`); `discovery_today` is `job_discovery.today()`.
    """
    facts = facts or {}
    has_screenshot = has_screenshot or (lambda r: False)
    lanes: dict[str, list[tuple]] = {s: [] for s in STAGES + OFF_RAMPS}
    for record in records:
        if not isinstance(record, dict) or "state" not in record:
            continue
        f = facts.get(record.get("id")) or {}
        stage = stage_of(record, approval_state=f.get("approval_state", ""),
                         his_ok=f.get("his_ok", ""), grant_live=grant_live)
        lanes[stage].append((record, f, stage))

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

    def cards_of(rows):
        return [card(r, stage=s, approval_state=f.get("approval_state", ""), his_ok=f.get("his_ok", ""),
                     grant_live=grant_live, has_screenshot=has_screenshot(r))
                for r, f, s in rows[:per_stage]]

    stages = []
    summary = discovery_today or {}
    for stage in STAGES:
        rows = sorted(lanes[stage], key=lambda t: _last_moved(t[0]), reverse=True)
        entry = {"stage": stage, "count": len(rows), "today": today(stage, rows), "source": "records",
                 "cards": cards_of(rows)}
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
                    "cards": cards_of(rows)})
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


# ---- what the job hunt adds to the generic screen ---------------------------------------

def activity(records: Iterable[dict]) -> list[dict]:
    """Ribbon lines from the application records, each with its receipt. Pure."""
    items: list[dict] = []
    for record in records:
        if not isinstance(record, dict) or not record.get("id"):
            continue
        receipt = {"kind": "application", "id": record["id"]}
        named = describe(record).rstrip(".")
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
    return items


def screenshots(browser: dict, *, records_by_id: dict, shots: set, newest_first: list | None = None) -> list[dict]:
    """Screenshot candidates for Eyes, best first: the application she is on
    now, the last one she worked, then the newest on record. Pure."""
    browser = browser or {}
    out: list[dict] = []
    seen: set = set()

    def add(record: dict | None, of: str) -> None:
        if not record or record.get("id") not in shots or record.get("id") in seen:
            return
        seen.add(record["id"])
        out.append({"id": record["id"], "of": of, "title": describe(record),
                    "src": f"/api/mission/screenshot?id={record['id']}", "at": _last_moved(record)})

    last = browser.get("last") if isinstance(browser.get("last"), dict) else {}
    add(records_by_id.get(browser.get("application")), "the application she is on now")
    add(records_by_id.get((last or {}).get("application")), "the last application she worked")
    ordered = newest_first if newest_first is not None else sorted(
        records_by_id.values(), key=_last_moved, reverse=True)
    for record in ordered[:40]:
        if out:
            break
        add(record, "the latest screenshot on record")
    return out


def _next(state: str, *, hunt: dict, loop: dict, say_time: Callable) -> str:
    lock = hunt.get("campaign") or {}
    minds = hunt.get("thinking") or {}
    if hunt.get("blocked"):
        until = _parse((minds.get("claude") or {}).get("resting_until"))
        return (f"The job hunt picks up at {say_time(until)}, when the big "
                "models are back." if until
                else "The job hunt picks up when something can think again.")
    if hunt.get("running"):
        size = lock.get("count") or lock.get("limit")
        if str(lock.get("kind") or "") == "retry":
            batch = (f"re-reading up to {size} waiting applications" if size
                     else "re-reading the waiting applications")
        else:
            batch = f"this batch of {size}" if size else "this batch"
        return (f"Finish {batch}; the apply loop starts another within 5 minutes."
                if loop.get("alive") else
                f"Finish {batch}. {str(loop.get('said') or '').capitalize()}, so nothing may follow it.")
    if loop.get("alive"):
        return "The apply loop starts another batch within 5 minutes."
    if state == "NEEDS YOU":
        return "Nothing moves on these until you answer them."
    if loop.get("alive") is False:
        return f"Nothing is scheduled: {loop.get('said')}."
    return "Nothing is scheduled."


def build(reading: dict, ctx: dict) -> dict:
    """The job hunt's contribution to the mission screen. Pure.

    `reading` is what `read` returned; `ctx` is the generic context
    (`now`, `entries`, `halted`, `browser`, `say_time`, `today_floor`).
    """
    now = ctx["now"]
    say_time = ctx.get("say_time") or _stamp
    hunt = reading.get("hunt") or {}
    records = [r for r in reading.get("records") or [] if isinstance(r, dict)]
    by_id = {r.get("id"): r for r in records if r.get("id")}
    shots = set(reading.get("shots") or ())
    loop = apply_loop(hunt.get("campaign"), ctx.get("entries") or [], now,
                      halted=bool(ctx.get("halted")), resting=bool(hunt.get("blocked")))
    piped = pipeline(records, facts=reading.get("facts"), grant_live=bool(reading.get("grant_live")),
                     discovery_today=reading.get("summary"), today_floor=ctx.get("today_floor") or "",
                     has_screenshot=lambda r: r.get("id") in shots)
    lanes = {s["stage"]: s for s in piped["stages"] + piped["off_ramps"]}
    waiting = lanes.get("NEEDS YOU") or {"count": 0, "cards": []}

    newest = max((_last_moved(r) for r in records), default="")
    marks = [a for a in (_age_s(newest, now), _age_s(loop.get("last_seen"), now)) if a is not None]
    pursued = bool(hunt.get("running") or loop.get("alive") or waiting["count"]
                   or (marks and min(marks) <= PURSUED_S))
    out: dict[str, Any] = {"missions": [], "claims": sorted(
        {str(r.get("approval")) for r in records if r.get("approval")}),
        "signals": [], "activity": activity(records),
        "screenshots": screenshots(ctx.get("browser") or {}, records_by_id=by_id, shots=shots),
        "details": {}}
    if not pursued:
        return out

    blockers: list[dict] = []
    if ctx.get("halted"):
        status = "STOPPED"
        blockers.append({"said": "everything is halted", "since": None, "source": "the kill switch"})
    elif hunt.get("readable") is False:
        status = "BLOCKED"
        blockers.append({"said": str(hunt.get("note") or "the application records could not be read"),
                         "since": None, "source": "application records"})
    elif hunt.get("blocked"):
        status = "BLOCKED"
        minds = hunt.get("thinking") or {}
        blockers.append({"said": "nobody can think: the big models are out and hers "
                                 + str((minds.get("local") or {}).get("why") or "cannot run"),
                         "since": (minds.get("claude") or {}).get("resting_until"), "source": "the minds"})
    elif hunt.get("running") or loop.get("alive"):
        status = "RUNNING"
    elif waiting["count"]:
        status = "NEEDS YOU"
    elif loop.get("alive") is False:
        status = "STOPPED"
    else:
        status = "OPEN"
    if loop.get("stale") and loop.get("alive") is not False:
        blockers.append({"said": str(loop.get("said")), "since": loop.get("last_seen"), "source": "campaign lock"})
    elif loop.get("alive") is False and not ctx.get("halted"):
        blockers.append({"said": str(loop.get("said")), "since": loop.get("last_seen"), "source": "journal"})

    browser = ctx.get("browser") or {}
    # The browser is this mission's only when the browser section says it
    # came from the application records: a browser goal for anything else
    # (`browser_mission`) is its own card, and the job hunt must not claim it.
    ours = browser.get("active") and browser.get("source", "applications") == "applications"
    if ours:
        step = (str(browser.get("purpose") or "") + (f" - {browser['stage']}" if browser.get("stage") else "")
                + (f" at {browser['site']}" if browser.get("site") else ""))
    elif hunt.get("running"):
        step = "a batch is running"
    elif loop.get("alive"):
        step = "between batches"
    else:
        step = ""

    needs = [{"said": f"{c['title']}: {c['why_not_sent'] or 'waiting on you'}",
              "receipt": {"kind": "application", "id": c["id"]}, "blocking": True}
             for c in waiting["cards"][:NEEDS_LISTED]]
    today = hunt.get("today") or {}
    counts = [{"label": label, "n": today.get(key)} for key, label in
              (("sent", "sent today"), ("ready", "ready today"), ("blocked", "didn't send today"),
               ("replies", "replies today")) if today.get(key) is not None]
    now_counts = hunt.get("now") or {}
    if now_counts.get("sent_total") is not None:
        counts.append({"label": "sent, all time", "n": now_counts["sent_total"]})
    receipts = [{"kind": "application", "id": r["id"], "label": describe(r)}
                for r in sorted(records, key=_last_moved, reverse=True)[:3] if r.get("id")]
    out["missions"].append(mission_card(
        id=MISSION_ID, type=TYPE, title="Job hunt",
        goal="Find openings that fit his resume and apply, one approval each",
        status=status, step=_words(step, 180), next=_next(status, hunt=hunt, loop=loop, say_time=say_time),
        blockers=blockers, needs=needs, needs_count=int(waiting["count"] or 0), counts=counts,
        receipts=receipts, updated=newest or loop.get("last_seen"), detail=True,
        in_browser=bool(ours), source="application records, campaign lock, journal"))

    loop_age = _age_s(loop.get("last_seen"), now)
    loop_ok = loop.get("alive") is not False and not loop.get("stale")
    signal = {"what": "apply loop", "ok": loop_ok, "said": str(loop.get("said") or "")}
    if not loop_ok and not ctx.get("halted") and (loop.get("stale") and loop.get("alive") is None
                                                  or (loop_age is not None and loop_age <= BANNER_S)):
        signal["banner"] = f"The job hunt looks stopped: {loop.get('said')}."
    out["signals"].append(signal)
    out["details"][MISSION_ID] = {
        "type": TYPE, "pipeline": piped, "discovery": discovery(reading.get("summary")), "loop": loop,
        "hunt": {"running": hunt.get("running"), "today": hunt.get("today"), "now": hunt.get("now"),
                 "readable": hunt.get("readable"), "note": hunt.get("note")},
    }
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


def read(ctx: dict) -> dict:
    """Every store the job hunt needs, read once. Never raises."""
    from aletheia import apply_run
    now = ctx["now"]
    notes: list[str] = []
    hunt = (ctx.get("sections") or {}).get("job_hunt") or {}
    try:
        records = apply_run.all_runs()
    except Exception as exc:  # noqa: BLE001
        records = []
        notes.append(f"the application records could not be read ({type(exc).__name__})")
    facts = {}
    for r in records:
        if r.get("state") != "AWAITING_YOU":
            continue
        try:
            his_ok = apply_run.waits_for_his_ok(r)
        except Exception:
            his_ok = ""
        facts[r.get("id")] = {"approval_state": _approval_state(str(r.get("approval") or "")), "his_ok": his_ok}
    try:
        from aletheia import job_discovery
        summary = job_discovery.today(now)
    except Exception:
        summary = None
        notes.append("today's discovery summary could not be read")
    shots = {str(r.get("id")) for r in records if r.get("id") and screenshot_path(r) is not None}
    return {"hunt": hunt, "records": records, "facts": facts, "summary": summary,
            "grant_live": _grant_live(now), "shots": sorted(shots), "notes": notes}


#: Fields of an application record the receipt leaves out: the resume path
#: and the full step list say nothing he needs and can be long.
_RECEIPT_DROP = ("resume", "steps")


def receipt(kind: str, ident: str) -> dict | None:
    """An application's receipt, with the two questions answered."""
    from aletheia import apply_run
    if kind != "application":
        return None
    try:
        record = apply_run.load_run(ident)
    except (OSError, ValueError, KeyError):
        return None
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
    fit = record.get("fit") if isinstance(record.get("fit"), dict) else {}
    return {"kind": kind, "id": ident, "record": shown,
            # who judged the fit, said as what it is: a receipt field
            "provenance": {"model": str(fit.get("by") or ""), "basis": "fit judgement" if fit else ""}}


def screenshot_for(app_id: str) -> Path | None:
    from aletheia import apply_run
    try:
        return screenshot_path(apply_run.load_run(app_id))
    except (OSError, ValueError, KeyError):
        return None


PROVIDER = Provider(
    type=TYPE, label="Job hunt", read=read, build=build,
    journal_subjects=frozenset({"apply"}),
    subject_labels={"apply:forever": "Job hunt", "campaign": "Job hunt", "jobs": "Job search",
                    "job-discovery": "Discovery", "apply": "Applications"},
    receipt_kinds=("application",), receipt=receipt, screenshot=screenshot_for,
)
