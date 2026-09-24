"""Checkpoints for any browser goal, so a crash resumes instead of restarting.

The brief (docs/JARVIS_BRIEF.md §4): "mission checkpoints ... so a crash
resumes rather than restarts", and one invariant, which this module exists
to enforce rather than describe:

    RETRYING OBSERVATION IS FINE. RETRYING A SUBMISSION WITHOUT PROOF THE
    PRIOR ATTEMPT FAILED IS NOT.

The checkpoints are goal-agnostic - the same six for a job application, a
library-card signup and an appointment request:

    observed          she looked at a page of it
    filled            she put his answers into a page of it
    review_reached    the final button is in front of her
    submit_clicked    written BEFORE the press, so a crash mid-press is known
    receipt_verified  the site said it went through
    done              the goal is finished

`submit_clicked` is written to disk before the button is pressed. That is
the whole mechanism: after a crash, a record whose last submit attempt has
no verdict is a submission that MAY have happened, and "may have happened"
is not proof it failed. The only proofs of failure are a site that handed
the form back with its own refusal (`rejected`) and a press that provably
never reached the page (`not_pressed`). Anything else - confirmed,
unconfirmed, a 5xx after the press, a crash - refuses a second press.

Verification codes arrive here as EVENTS (`post_event`), so the loop can
wait on a code without knowing whether it came from his mailbox, a text he
read out, or the Command Center.

Private state, one JSON file per mission. Inputs are his answers and live
beside the route that uses them, never in the journal.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re

from aletheia import journal, stateio

RUNNING = "RUNNING"
NEEDS_YOU = "NEEDS_YOU"              # a boundary only he can pass: named exactly
AWAITING_APPROVAL = "AWAITING_APPROVAL"  # the committing press waits for his yes
SUBMITTING = "SUBMITTING"           # pressed or pressing; verdict not yet read
SUBMITTED_UNCONFIRMED = "SUBMITTED_UNCONFIRMED"
DONE = "DONE"
REFUSED = "REFUSED"                 # spending, or something never allowed
MANUAL_ONLY = "MANUAL_ONLY"         # the site's terms forbid automation
REJECTED = "REJECTED"               # the site handed it back: proof it failed
LEFT = "LEFT"                       # she left it: nothing more she could do, or he never came
STATES = (RUNNING, NEEDS_YOU, AWAITING_APPROVAL, SUBMITTING, SUBMITTED_UNCONFIRMED,
          DONE, REFUSED, MANUAL_ONLY, REJECTED, LEFT)

#: Boundaries that are HERS, not his: nothing he does from a phone changes
#: them. Live 2026-09-23 his page carried 72 "waiting for you" cards from
#: the general browser - 30 with no way forward, 16 where he had already
#: said no, 3 whose posting had closed, 11 where she ran out of steps, went
#: in circles or hit an error - each saying "it carries on when you do your
#: part", with nothing to press. A wall she cannot pass is a wall she leaves.
NOT_HIS = ("NO_WAY_FORWARD", "APPROVAL_DENIED", "POSTING_CLOSED", "OUT_OF_STEPS",
           "GOING_IN_CIRCLES", "ERROR", "UNKNOWN")
#: Boundaries that ARE his - a human check, a sign-in, a question, a code -
#: wait this long for him and are then left too, said as such.
HIS_KINDS = ("CAPTCHA", "SIGN_IN", "QUESTIONS", "WAITING_FOR_CODE", "NO_VAULT",
             "ACCOUNT_CREATION_APPROVAL")
LEAVE_AFTER_S = 48 * 3600
#: Of his kinds, the ones that on a JOB application are not his after all: a
#: human check and a sign-in are walls she cannot pass, and he is not
#: going to pass them for her one job at a time (2026-09-23).
NOT_HIS_ON_A_JOB = ("CAPTCHA", "SIGN_IN")
_KIND_WORDS = {"NO_WAY_FORWARD": "no way forward on the page", "APPROVAL_DENIED": "you said no",
               "POSTING_CLOSED": "the posting closed", "OUT_OF_STEPS": "she ran out of steps",
               "GOING_IN_CIRCLES": "she was going in circles", "ERROR": "the page broke",
               "UNKNOWN": "it stopped without saying why", "CAPTCHA": "a human check",
               "SIGN_IN": "a sign-in", "QUESTIONS": "questions only you can answer",
               "WAITING_FOR_CODE": "a verification code", "NO_VAULT": "an account she has no way into",
               "ACCOUNT_CREATION_APPROVAL": "an account to create first"}


def kind_words(kind: str) -> str:
    return _KIND_WORDS.get(str(kind or ""), str(kind or "").replace("_", " ").casefold() or "a boundary")


def _is_job(record: dict) -> bool:
    try:
        from aletheia import jobs_grant
        return jobs_grant.is_job_mission(record)
    except Exception:
        return str(record.get("id") or "").startswith("bm-apply-for-this-job")


def leave(mid: str, because: str, *, via: str = "operator") -> dict:
    """His "Clear" on one mission: left, said, and never pressed again.
    Raises KeyError when there is no such mission."""
    if not exists(mid):
        raise KeyError(mid)
    record = load(mid)
    if record.get("state") in (LEFT, DONE):
        return record
    record["state"] = LEFT
    record["left_because"] = because
    record["left_at"] = stateio.utcnow()
    save(record)
    goal = " ".join(str(record.get("goal") or mid).split())[:80]
    journal.append("action", "browser", f"cleared: {goal} - {because}", actor=via)
    return record


def leave_walls(now: dt.datetime | None = None) -> list[dict]:
    """Leave every NEEDS_YOU mission that is not his to pass, and every one
    of his that has waited LEAVE_AFTER_S. Returns what was left. One journal
    line for the sweep, never one per mission; nothing is pressed."""
    from collections import Counter
    now = now or dt.datetime.now(dt.timezone.utc)
    left, why_counts = [], Counter()
    for record in all_missions(NEEDS_YOU):
        boundary = record.get("boundary") or {}
        kind = str(boundary.get("kind") or "UNKNOWN")
        if kind in NOT_HIS:
            because = f"nothing more she could do here: {kind_words(kind)}"
        elif kind in NOT_HIS_ON_A_JOB and _is_job(record):
            # His words, 2026-09-23 evening, about a page of "needs you" cards
            # stopped at CAPTCHAs on job applications: "If I wanted a bot to
            # take me to websites where the jobs are and not actually apply
            # to them for me, I wouldn't be here." A human check or a sign-in
            # on a job application is not his to do; it is left now and the
            # next opening is tried.
            because = f"{kind_words(kind)} on a job application, which is not yours to do"
        else:
            age = _age_s(boundary.get("at") or record.get("beat"), now)
            if age is None or age < LEAVE_AFTER_S:
                continue
            because = f"waited two days for {kind_words(kind)} and you did not come"
        record["state"] = LEFT
        record["left_because"] = because
        record["left_at"] = stateio.utcnow()
        save(record)
        why_counts[kind_words(kind)] += 1
        left.append(record)
    if left:
        said = ", ".join(f"{n} where {w}" if not w.startswith(("she", "you", "it")) else f"{n} where {w}"
                         for w, n in why_counts.most_common())
        journal.append("action", "browser",
                       f"left {len(left)} application{'s' if len(left) != 1 else ''} the general browser "
                       f"could not finish ({said})", actor="aletheia-browser")
    return left


def _age_s(stamp, now: dt.datetime) -> float | None:
    try:
        when = dt.datetime.fromisoformat(str(stamp or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return (now - when).total_seconds()

OBSERVED = "observed"
FILLED = "filled"
REVIEW_REACHED = "review_reached"
SUBMIT_CLICKED = "submit_clicked"
RECEIPT_VERIFIED = "receipt_verified"
FINISHED = "done"
CHECKPOINTS = (OBSERVED, FILLED, REVIEW_REACHED, SUBMIT_CLICKED, RECEIPT_VERIFIED, FINISHED)

#: Verdicts that PROVE a submission did not take.
PROVEN_FAILED = frozenset({"rejected", "not_pressed"})
#: The press was answered with the site's sign-in door (Workday, 2026-09-24):
#: nothing was sent, so the button may be pressed again once she is in -
#: but it is not a refusal, so the mission is not REJECTED for it.
SIGN_IN_AFTER_PRESS = "sign_in_after_press"
NOTHING_WAS_SENT = PROVEN_FAILED | frozenset({SIGN_IN_AFTER_PRESS})
STALE_AFTER_MIN = 20
MAX_CHECKPOINTS = 120
MAX_EVENTS = 20


class DuplicateSubmission(PermissionError):
    """A second press with no proof the first one failed."""


def missions_dir():
    return stateio.private_dir("browser-missions")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]


def mission_id(goal: str, start_url: str) -> str:
    """The same goal on the same page is the same mission, deliberately: a
    second `pursue` of it resumes (or refuses to submit twice) instead of
    starting a fresh one that has forgotten the first press."""
    goal = " ".join(str(goal or "").split())
    slug = re.sub(r"[^a-z0-9]+", "-", goal.casefold())[:24].strip("-") or "goal"
    return f"bm-{slug}-{_digest(goal.casefold() + '|' + str(start_url or '').strip())}"


def _path(mid: str):
    return missions_dir() / f"{stateio.safe_id(mid, name='browser mission id')}.json"


def load(mid: str) -> dict:
    return stateio.read_json(_path(mid))


def exists(mid: str) -> bool:
    return _path(mid).is_file()


def save(record: dict) -> dict:
    record["beat"] = stateio.utcnow()
    path = _path(record["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    stateio.write_json_atomic(path, record)
    return record


def all_missions(state: str | None = None) -> list[dict]:
    folder = missions_dir()
    out = []
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.json")):
        try:
            value = stateio.read_json(path)
        except (OSError, ValueError):
            continue
        if isinstance(value, dict) and (state is None or value.get("state") == state):
            out.append(value)
    return out


def open_mission(goal: str, start_url: str, *, inputs: dict | None = None,
                 mode: str = "autonomous", skill: str = "general") -> dict:
    """The mission for this goal: the existing record if there is one (its
    checkpoints and submissions are the point), else a new one."""
    mid = mission_id(goal, start_url)
    if exists(mid):
        record = load(mid)
        if inputs:
            record["inputs"] = {**(record.get("inputs") or {}), **dict(inputs)}
        return record
    record = {"id": mid, "goal": " ".join(str(goal).split()), "start_url": start_url,
              "inputs": dict(inputs or {}), "mode": mode, "skill": skill, "state": RUNNING,
              "checkpoints": [], "route": [], "attached": [], "submits": [], "events": [],
              "history": [], "boundary": None, "created": stateio.utcnow(), "attempt": 1}
    return save(record)


# ---- checkpoints -------------------------------------------------------------

def checkpoint(record: dict, name: str, *, url: str = "", **detail) -> dict:
    if name not in CHECKPOINTS:
        raise ValueError(f"unknown checkpoint {name!r}")
    rows = record.setdefault("checkpoints", [])
    rows.append({"name": name, "at": stateio.utcnow(), "url": str(url)[:300],
                 **{k: v for k, v in detail.items() if v not in (None, "")}})
    record["checkpoints"] = rows[-MAX_CHECKPOINTS:]
    record["last_checkpoint"] = name
    return save(record)


def reached(record: dict, name: str) -> bool:
    return any(row.get("name") == name for row in record.get("checkpoints") or [])


def stale(record: dict, *, minutes: int = STALE_AFTER_MIN) -> bool:
    """A RUNNING record nobody has touched lately is a crash, not a live run."""
    try:
        beat = dt.datetime.fromisoformat(str(record.get("beat") or "").replace("Z", "+00:00"))
    except ValueError:
        return True
    return dt.datetime.now(dt.timezone.utc) - beat > dt.timedelta(minutes=minutes)


# ---- the invariant -----------------------------------------------------------

def submit_key(button: str, url: str) -> str:
    """Which submission a press is: the page shape and the button's words.
    Making an account and then sending the application are two different
    submissions of one mission; pressing either one twice is a duplicate."""
    from aletheia import site_skills
    words = " ".join(re.sub(r"[^a-z0-9 ]+", " ", str(button or "").casefold()).split())
    return f"{site_skills.path_of(url)}|{words}"


def may_submit(record: dict, *, button: str | None = None, url: str = "") -> tuple[bool, str]:
    """(allowed, why). Every earlier attempt at THIS submission (all of them,
    when no button is named) must be PROVEN to have failed."""
    key = submit_key(button, url) if button is not None else None
    for attempt in record.get("submits") or []:
        if key is not None and attempt.get("key") not in (None, key):
            continue
        verdict = str(attempt.get("verdict") or "pending")
        if verdict in NOTHING_WAS_SENT:
            continue
        said = {"confirmed": "and the site confirmed it",
                "pending": "and no verdict was ever recorded (it may have gone through)",
                "submitted, unconfirmed": "and the site did not say whether it went through",
                "error": "and the site errored after the press, which is not proof it failed",
                "verification_required": "and the site asked for a code before accepting it, which "
                                         "is not proof it failed"}
        return False, (f"'{attempt.get('button') or 'the final button'}' was already pressed at "
                       f"{attempt.get('at')} {said.get(verdict, f'({verdict})')}; pressing it again "
                       "could send it twice, so it needs proof the first press failed")
    return True, ""


def may_submit_here(record: dict, *, button: str, url: str) -> tuple[bool, str]:
    return may_submit(record, button=button, url=url)


def refuse_duplicate(record: dict, *, button: str | None = None, url: str = "") -> None:
    ok, why = may_submit(record, button=button, url=url)
    if not ok:
        raise DuplicateSubmission(why)


def begin_submit(record: dict, *, button: str, approval: str = "", url: str = "") -> dict:
    """Written BEFORE the press. Raises if the invariant forbids the press."""
    refuse_duplicate(record, button=button, url=url)
    record.setdefault("submits", []).append({"at": stateio.utcnow(), "button": button,
                                             "key": submit_key(button, url),
                                             "approval": approval, "verdict": "pending"})
    record["state"] = SUBMITTING
    return checkpoint(record, SUBMIT_CLICKED, url=url, button=button)


def end_submit(record: dict, *, verdict: str, evidence: str = "", url: str = "",
               note: str = "") -> dict:
    """What the page said after the press, folded into the mission."""
    attempts = record.setdefault("submits", [])
    if not attempts:
        attempts.append({"at": stateio.utcnow(), "button": "", "verdict": "pending"})
    attempts[-1].update({"verdict": verdict, "evidence": str(evidence)[:600],
                         "decided_at": stateio.utcnow()})
    if verdict == "confirmed":
        record["state"] = DONE
        record["boundary"] = None
        checkpoint(record, RECEIPT_VERIFIED, url=url, note=note)
        return checkpoint(record, FINISHED, url=url)
    if verdict in PROVEN_FAILED:
        record["state"] = REJECTED
        record["boundary"] = {"kind": "REJECTED", "url": url,
                              "say": note or "The site handed it back; nothing was accepted.",
                              "evidence": str(evidence)[:600]}
        return save(record)
    record["state"] = SUBMITTED_UNCONFIRMED
    record["boundary"] = {"kind": "UNCONFIRMED", "url": url,
                          "say": note or ("The button was pressed and the site did not say it "
                                          "went through. I will not press it again without "
                                          "proof it failed.")}
    return save(record)


def stop_at(record: dict, state: str, boundary: dict) -> dict:
    """Stop at a precisely named boundary: which kind, which page, which
    step, and what exactly remains."""
    if state not in STATES:
        raise ValueError(f"unknown mission state {state!r}")
    record["state"] = state
    record["boundary"] = {**boundary, "at": stateio.utcnow()}
    return save(record)


# ---- events ------------------------------------------------------------------

def post_event(mid: str, kind: str, value: str, *, source: str = "operator") -> dict:
    """A verification code (or any value the loop is waiting on) arriving."""
    record = load(mid)
    events = record.setdefault("events", [])
    events.append({"kind": str(kind), "value": str(value)[:200], "source": source,
                   "at": stateio.utcnow(), "used": False})
    record["events"] = events[-MAX_EVENTS:]
    return save(record)


def take_event(record: dict, kind: str) -> str:
    """The oldest unused event of this kind, marked used. "" if none."""
    for event in record.get("events") or []:
        if event.get("kind") == kind and not event.get("used"):
            event["used"] = True
            save(record)
            return str(event.get("value") or "")
    return ""


def describe(record: dict) -> str:
    """One sentence: where this goal stands and what, exactly, is left."""
    state = record.get("state")
    goal = str(record.get("goal") or "")[:90]
    boundary = record.get("boundary") or {}
    last = record.get("last_checkpoint") or "nothing yet"
    if state == DONE:
        from aletheia import page_answer
        said = page_answer.spoken(record.get("result") or {})
        return f"Done: {goal}. {said}".strip() if said else f"Done: {goal}."
    if boundary.get("say"):
        return f"{goal}: {boundary['say']} (last checkpoint: {last})"
    return f"{goal}: {str(state).lower().replace('_', ' ')} (last checkpoint: {last})"
