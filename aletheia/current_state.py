"""Canonical model of NOW for every Aletheia interface.

This aggregates durable truth; it does not invent live activity. Missing or
unconfigured stores degrade to empty/error sections rather than fake status.

Version 2 (the brief, docs/JARVIS_BRIEF.md §2) makes this the single root
of situational awareness by adding what it omitted:

- `agent`: her own state in the tiny vocabulary the interface speaks
  (IDLE, LISTENING, THINKING, LOOKING, ACTING, WAITING, NEEDS YOU, BLOCKED,
  HALTED), the mission, the step and since when.
- `job_hunt`: whether it is running, today's counts (discovered,
  qualified, attempted, ready, sent, blocked, replies), the blockers by
  employer and reason, what is waiting on him, the campaign lock, and
  which minds can think (Claude's rest, Codex's rest, her own model).
- `browser`: active, site, purpose, stage - from ANY browser goal
  (`browser_mission`), not only job applications, plus the goals stopped at
  a named boundary waiting on him.
- `agent_sessions`: her tool-using sessions running now, and the requests
  they handed to him (`aletheia.handoffs`): waiting, running, finished.
- `code`: repo, branch, dirty, latest commit, and whether the running Core
  predates the code on disk.
- `power`: AC or battery, how much, and whether something holds the PC
  awake (`aletheia.power`).
- `usage`: what is genuinely known about the subscriptions' limits - the
  last limit Claude or Codex reported and when it said it resets. Nothing
  records how much of a window is used, and this says "unknown" rather
  than guess.

EVERY COUNT IS DERIVED, NEVER GUESSED. The application records
(`apply_run.all_runs`, `apply_run.already_sent`), the campaign lock, the
rest markers (`reasoner.resting_until`, `reasoner.codex_resting`) and
`running.version` are the sources; a store that cannot be read says so in
the section (`readable: False` and a note), because an interface that
renders a zero for an unreadable store is lying exactly where he is
trusting it.

READING MUST NOT ACT. `campaign.running()` kills a batch it judges hung;
this reads the lock file and asks the operating system whether the pid is
alive, and touches nothing.
"""
from __future__ import annotations

import datetime as dt
import json
import time
from typing import Any, Callable

from aletheia import capabilities, communications, notifications, policy, projects, scheduler, tasks

TERMINAL_TASKS = {"COMPLETED", "CANCELLED", "FAILED_TERMINAL"}

#: The vocabulary the top of the screen speaks (brief §5).
AGENT_STATES = ("IDLE", "LISTENING", "THINKING", "LOOKING", "ACTING", "WAITING",
                "NEEDS YOU", "BLOCKED", "HALTED")

#: Application states, by what they mean for the counts.
PRESSED = ("SUBMITTED", "SUBMITTING")
BLOCKED_STATES = ("FAILED", "REJECTED", "NEEDS_ACCOUNT")
WORKED_STATES = ("AWAITING_YOU", "NEEDS_YOU", "NEEDS_ACCOUNT", "SUBMITTED", "SUBMITTING",
                 "FAILED", "REJECTED", "APPROVED")
MAX_LISTED = 8

#: The derived sections are read by the Command Center every fifteen
#: seconds and by the supervisor; the application directory holds a few
#: hundred files. A short cache keeps a status read cheap without letting
#: it go stale for longer than a beat.
SECTIONS_CACHE_S = 3.0
_SECTIONS: dict[str, Any] = {"at": 0.0, "value": None}
#: `git status` is a subprocess; the answer changes when he edits, not
#: between two polls.
DIRTY_CACHE_S = 30.0
_DIRTY: dict[str, Any] = {"at": 0.0, "value": None}


def _utc(now: dt.datetime | None) -> dt.datetime:
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(dt.timezone.utc)


def _stamp(when: dt.datetime) -> str:
    return when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp: object) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def today_started(now: dt.datetime) -> str:
    """Midnight this morning on HIS clock, as a UTC stamp the records compare
    against. A calendar day, not a rolling window: asked at nine in the
    morning, "today" is not mostly yesterday evening."""
    try:
        from aletheia import localtime
        zone = localtime.operator_tz()
    except Exception:
        zone = dt.timezone.utc
    local = now.astimezone(zone)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return _stamp(start)


def _since(stamp: object, floor: str) -> bool:
    return bool(stamp) and str(stamp) >= floor


def _safe(fn: Callable[[], Any], fallback: Any) -> Any:
    try:
        return fn()
    except Exception:
        return fallback


# ---- the job hunt --------------------------------------------------------

def campaign_lock(now: dt.datetime) -> dict | None:
    """The campaign lock as it stands, with whether its process is alive.

    Read-only: `campaign.running()` stops a batch it judges hung, and a
    status read must not be the thing that stops a batch.
    """
    from aletheia import campaign, proc
    try:
        value = json.loads(campaign.LOCK_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    started = _parse(value.get("started_at"))
    pid = value.get("pid")
    alive = proc.pid_alive(pid, needle="aletheia.campaign") if pid else None
    fresh = started is not None and now - started < campaign.STALE_LOCK
    return {"kind": str(value.get("kind") or "apply"), "pid": pid,
            "started_at": value.get("started_at"), "alive": alive,
            # The same rule `campaign.running` applies, minus the kill: a
            # dead pid is not running; a live one is; an unknowable one is
            # trusted while the lock is fresh.
            "running": alive is True or (alive is None and fresh),
            "limit": value.get("limit"), "count": value.get("count")}


def _reason_for(record: dict) -> str:
    for key in ("failure", "why", "closed_because"):
        said = " ".join(str(record.get(key) or "").split())
        if said:
            return said[:200]
    evidence = record.get("click_evidence")
    if isinstance(evidence, dict) and evidence.get("captcha"):
        return "a CAPTCHA challenge was in front of the Submit button"
    if record.get("captcha"):
        return f"the form loads a {record['captcha']} check"
    return str(record.get("state") or "")


def _name(record: dict) -> tuple[str, str]:
    from aletheia import apply_run
    company = " ".join(str(record.get("company") or "").split())
    return company, apply_run.describe(record)


def thinking(now: dt.datetime | None = None) -> dict:
    """Which minds can think right now: Claude, Codex, her own model."""
    from aletheia import reasoner
    now = _utc(now)
    claude = _safe(lambda: reasoner.resting_until(now), None)
    codex = _safe(lambda: reasoner.codex_resting(now), None)
    local_ok, local_why = _safe(reasoner.local_allowed, (False, "could not be checked"))
    out = {
        "claude": {"resting_until": _stamp(claude) if claude else None},
        "codex": ({"resting_until": _stamp(codex[0]), "why": codex[1]} if codex
                  else {"resting_until": None}),
        "local": {"allowed": bool(local_ok), "why": str(local_why)},
    }
    # WHAT HER OWN MODEL IS DOING, and how it has been doing: the call
    # running now (what, how long so far) and the ring of recent ones
    # (answers today, typical time). This is what lets him SEE it working
    # when it is the only mind left and everything takes a minute.
    try:
        from aletheia import local_model_pool
        out["local"]["busy"] = local_model_pool.busy()
        out["local"]["recent"] = local_model_pool.recent(now=now)
    except Exception:  # noqa: BLE001
        out["local"]["busy"] = None
        out["local"]["recent"] = {}
    out["anyone"] = claude is None or codex is None or bool(local_ok)
    return out


def brains_words(minds: dict | None = None) -> str:
    """One sentence about who is thinking: the big models, or her own,
    slower, and how that has been going. On the page under "Right now"
    and in "what are you doing" when nothing else is happening."""
    from aletheia import reasoner, speech
    minds = minds if minds is not None else thinking()
    local = minds.get("local") or {}
    recent = local.get("recent") or {}
    busy = local.get("busy") or None
    claude_until = (minds.get("claude") or {}).get("resting_until")
    codex_until = (minds.get("codex") or {}).get("resting_until")
    frontier = claude_until is None or codex_until is None
    typical = recent.get("typical_s")
    pace = f", usually {speech.about_seconds(typical)} an answer" if typical else ""
    today = recent.get("today_ok") or 0
    tally = f" {speech.count_phrase(int(today), 'answer')} from it today." if today else ""
    if frontier:
        if local.get("allowed"):
            said = "Thinking with the big models; my own model is ready as backup" + pace + "."
        else:
            return "Thinking with the big models. My own model is " + _local_state_words(local) + "."
        return said + tally
    until = _parse(claude_until) if claude_until else None
    out = reasoner.big_models_out(until) if until else reasoner.big_models_out()
    if local.get("allowed"):
        said = f"{out}, so I'm thinking with my own model: slower{pace}."
        if busy:
            said += (f" Working on “{speech.shorten(str(busy.get('what') or ''), 60)}” now, "
                     f"{speech.count_phrase(int(busy.get('elapsed_s') or 0), 'second')} in.")
        return said + tally
    return f"{out}, and my own model is {_local_state_words(local)}. Nobody can think until one is back."


def _local_state_words(local: dict) -> str:
    why = str(local.get("why") or "")
    if "switched off" in why:
        return "switched off"
    if "not running" in why:
        return "not running; I start it myself and try again every few minutes"
    if "memory" in why:
        return "waiting for memory to free up"
    return why or "not available"


def job_hunt(now: dt.datetime | None = None) -> dict:
    """The job hunt, counted from the records. Never raises."""
    from aletheia import apply_run
    now = _utc(now)
    floor = today_started(now)
    lock = _safe(lambda: campaign_lock(now), None)
    minds = thinking(now)
    try:
        rows = apply_run.all_runs()
    except Exception as exc:  # noqa: BLE001
        return {"readable": False, "running": bool(lock and lock["running"]),
                "campaign": lock, "thinking": minds,
                "note": f"the application records could not be read ({type(exc).__name__})"}
    try:
        sent_total = len(apply_run.already_sent())
    except Exception:
        sent_total = None

    staged_today = [r for r in rows if _since(r.get("staged_at"), floor)]
    sent_today = [r for r in rows if r.get("state") in PRESSED
                  and _since(r.get("submitted_at") or r.get("pressed_at"), floor)]
    blocked_today = [r for r in staged_today if r.get("state") in BLOCKED_STATES]
    blocked_today += [r for r in rows if r.get("state") in BLOCKED_STATES
                      and r not in blocked_today
                      and _since(r.get("submitted_at") or r.get("pressed_at"), floor)]

    def unfit(record: dict) -> bool:
        return record.get("state") == apply_run.CLOSED and \
            _safe(lambda: apply_run.closure_kind(record), "unfit") == "unfit"

    replies_today = []
    for r in rows:
        for entry in (r.get("outcomes") or []):
            if isinstance(entry, dict) and _since(entry.get("at"), floor):
                replies_today.append({"company": _name(r)[0], "job": _name(r)[1],
                                      "outcome": entry.get("outcome"),
                                      "note": str(entry.get("note") or "")[:120]})
    today = {
        "discovered": len(staged_today),
        "qualified": sum(1 for r in staged_today if not unfit(r)),
        "attempted": sum(1 for r in staged_today if r.get("state") in WORKED_STATES),
        "ready": sum(1 for r in staged_today if r.get("state") == "AWAITING_YOU"),
        "sent": len(sent_today),
        "blocked": len(blocked_today),
        "replies": len(replies_today),
    }
    blockers = []
    for r in sorted(blocked_today, key=lambda r: str(r.get("staged_at") or ""), reverse=True)[:MAX_LISTED]:
        company, job = _name(r)
        blockers.append({"id": r.get("id"), "company": company, "job": job,
                         "state": r.get("state"), "reason": _reason_for(r)})
    waiting: list[dict] = []
    for r in rows:
        if r.get("state") == "NEEDS_YOU":
            company, job = _name(r)
            labels = [" ".join(str(q.get("label") or "").split())[:240] for q in (r.get("questions") or [])
                      if isinstance(q, dict)]
            waiting.append({"id": r.get("id"), "company": company, "job": job,
                            "why": "questions only you can answer",
                            "questions": labels[:4]})
        elif r.get("state") == "AWAITING_YOU":
            kind = _safe(lambda r=r: apply_run.waits_for_his_ok(r), "")
            if kind:
                company, job = _name(r)
                waiting.append({"id": r.get("id"), "company": company, "job": job,
                                "why": ("only your own model judged it realistic"
                                        if kind == apply_run.JUDGED_LOCALLY
                                        else f"it is {kind} work, which waits for your OK")})
    waiting.sort(key=lambda w: str(w.get("id") or ""))
    running = bool(lock and lock["running"])
    return {
        "readable": True,
        "running": running,
        "campaign": lock,
        "today": today,
        "now": {"ready": sum(1 for r in rows if r.get("state") == "AWAITING_YOU"),
                "needs_you": sum(1 for r in rows if r.get("state") == "NEEDS_YOU"),
                "in_flight": sum(1 for r in rows if r.get("state") == "SUBMITTING"),
                "sent_total": sent_total, "records": len(rows)},
        "blockers": blockers,
        "waiting_on_him": waiting[:MAX_LISTED],
        "replies": replies_today[:MAX_LISTED],
        "thinking": minds,
        # Blocked as a whole only when nobody can think: then batches cannot
        # judge a job and `apply_forever` waits (its own rule, read here).
        "blocked": not minds["anyone"],
    }


# ---- the browser ---------------------------------------------------------

def _site(url: object) -> str:
    from urllib.parse import urlparse
    try:
        return urlparse(str(url or "")).netloc
    except ValueError:
        return ""


#: Browser mission states that are a boundary waiting on him.
MISSION_WAITING = ("NEEDS_YOU", "AWAITING_APPROVAL", "SUBMITTED_UNCONFIRMED")
#: How the checkpoint names read as a stage.
CHECKPOINT_STAGE = {"observed": "reading the page", "filled": "filling the form",
                    "review_reached": "at the final button", "submit_clicked": "pressing submit",
                    "receipt_verified": "confirmed by the site", "done": "done"}


def boundary_words(record: dict) -> str:
    """"stopped at CAPTCHA on example.com" - the named stop, short."""
    boundary = record.get("boundary") or {}
    kind = str(boundary.get("kind") or record.get("state") or "").replace("_", " ")
    site = _site(boundary.get("url") or record.get("start_url"))
    said = f"stopped at {kind}" if kind else "stopped"
    return said + (f" on {site}" if site else "")


def browser_missions(now: dt.datetime | None = None) -> dict:
    """Every browser goal, whatever it is for: which one is being driven now,
    and which ones stopped at a boundary that waits on him. Never raises;
    reading never resumes, expires or deletes anything."""
    from aletheia import browser_mission as bm
    now = _utc(now)
    try:
        rows = bm.all_missions()
    except Exception as exc:  # noqa: BLE001
        return {"readable": False, "active": None, "waiting": [], "counts": {},
                "note": f"the browser missions could not be read ({type(exc).__name__})"}
    active = None
    waiting = []
    counts: dict[str, int] = {}
    for r in rows:
        state = str(r.get("state") or "")
        counts[state] = counts.get(state, 0) + 1
        fresh = not _safe(lambda r=r: bm.stale(r), True)
        if state in (bm.RUNNING, bm.SUBMITTING) and fresh:
            if active is None or str(r.get("beat") or "") > str(active.get("beat") or ""):
                active = r
        elif state in MISSION_WAITING:
            boundary = r.get("boundary") or {}
            waiting.append({"mission": r.get("id"), "goal": " ".join(str(r.get("goal") or "").split())[:160],
                            "site": _site(boundary.get("url") or r.get("start_url")),
                            "kind": boundary.get("kind") or state, "state": state,
                            "said": boundary_words(r), "say": str(boundary.get("say") or "")[:300],
                            "since": boundary.get("at") or r.get("beat")})
    waiting.sort(key=lambda w: str(w.get("since") or ""), reverse=True)
    out: dict = {"readable": True, "active": None, "waiting": waiting[:MAX_LISTED],
                 "waiting_count": len(waiting), "counts": counts}
    if active is not None:
        checkpoints = active.get("checkpoints") or []
        last = checkpoints[-1] if checkpoints else {}
        stage = ("pressing submit" if active.get("state") == bm.SUBMITTING
                 else CHECKPOINT_STAGE.get(str(active.get("last_checkpoint") or ""), "starting"))
        out["active"] = {"mission": active.get("id"),
                         "goal": " ".join(str(active.get("goal") or "").split())[:160],
                         "site": _site(last.get("url") or active.get("resume_url") or active.get("start_url")),
                         "stage": stage, "since": active.get("created"), "beat": active.get("beat"),
                         "skill": active.get("skill")}
    newest = max(rows, key=lambda r: str(r.get("beat") or ""), default=None)
    if newest is not None:
        out["last"] = {"mission": newest.get("id"), "goal": str(newest.get("goal") or "")[:160],
                       "state": newest.get("state"), "at": newest.get("beat"),
                       "site": _site(newest.get("start_url")), "said": _safe(lambda: bm.describe(newest), "")}
    return out


def agent_sessions(now: dt.datetime | None = None) -> dict:
    """Her tool-using sessions and the requests they handed to him. Never
    raises. A session record still marked running whose process is gone, or
    that started too long ago, is reported as `abandoned`, not running."""
    from aletheia import handoffs, proc, stateio
    from aletheia.agent_session import LIVE_S
    now = _utc(now)
    running, abandoned = [], 0
    try:
        folder = stateio.private_dir("agent-sessions")
        paths = sorted(folder.glob("agent-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:40] \
            if folder.is_dir() else []
        readable = True
    except Exception:
        paths, readable = [], False
    for path in paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if record.get("outcome") != "running":
            continue
        started = _parse(record.get("started_at") or record.get("saved_at"))
        alive = proc.pid_alive(record.get("pid")) if record.get("pid") else None
        if alive is False or started is None or (now - started).total_seconds() > LIVE_S:
            abandoned += 1
            continue
        running.append({"session": record.get("id"), "question": str(record.get("question") or "")[:160],
                        "since": record.get("started_at")})
    try:
        rows = handoffs.all_handoffs()
    except Exception:
        rows, readable = [], False

    def row(h: dict) -> dict:
        return {"handoff": h.get("id"), "approval": h.get("approval"), "tool": h.get("tool"),
                "state": h.get("state"), "said": str(h.get("consequence") or "")[:200],
                "session": h.get("session"), "outcome": str(h.get("outcome") or "")[:200],
                "at": h.get("finished_at") or h.get("started_at") or h.get("created_at")}
    waiting = [row(h) for h in rows if h.get("state") == handoffs.AWAITING]
    doing = [row(h) for h in rows if h.get("state") == handoffs.RUNNING]
    floor = today_started(now)
    finished = sorted((row(h) for h in rows if h.get("state") in handoffs.FINISHED
                       and str(h.get("finished_at") or "") >= floor),
                      key=lambda h: str(h.get("at") or ""), reverse=True)
    return {"readable": readable, "running": running, "abandoned": abandoned,
            "handoffs": {"waiting": waiting[:MAX_LISTED], "running": doing,
                         "finished_today": finished[:MAX_LISTED],
                         "counts": {"waiting": len(waiting), "running": len(doing),
                                    "finished_today": len(finished)}}}


def power_state() -> dict:
    from aletheia import power
    return power.section()


def _rest_record(path_fn) -> dict:
    try:
        value = json.loads(path_fn().read_text(encoding="utf-8"))
    except (OSError, ValueError, AttributeError):
        return {}
    return value if isinstance(value, dict) else {}


def usage(now: dt.datetime | None = None) -> dict:
    """What is genuinely known about the subscriptions' usage. Never raises.

    Known: the last time Claude or Codex REPORTED a spent limit in an error,
    what it said, and when it said the window comes back (`reasoner` keeps
    both). Not known, and said so: how much of a window is used, or any
    weekly total - neither CLI reports that to her.
    """
    from aletheia import reasoner, sensitivity
    now = _utc(now)

    def one(record: dict, resting) -> dict:
        until = _parse(record.get("until"))
        said = " ".join(str(record.get("said") or "").split())
        return {"resting_now": resting is not None,
                "last_limit_hit": record.get("noted_at") or None,
                "resets_at": _stamp(until) if until else None,
                "why": record.get("why") or ("limit" if record else None),
                "said": sensitivity.clean(said)[:160] if said else ""}
    claude = one(_rest_record(reasoner._rest_path), _safe(lambda: reasoner.resting_until(now), None))
    codex = one(_rest_record(reasoner._codex_rest_path), _safe(lambda: reasoner.codex_resting(now), None))
    if not claude["last_limit_hit"]:
        claude["note"] = "no limit has been recorded for Claude"
    if not codex["last_limit_hit"]:
        codex["note"] = "no limit is on record for Codex (a Codex that answers again clears its record)"
    return {"claude": claude, "codex": codex, "window_used": "unknown", "weekly": "unknown",
            "note": ("Only a limit a CLI reported, and the reset it named, is recorded. How much of a "
                     "window is used, and weekly totals, are not reported to her: unknown.")}


def browser(now: dt.datetime | None = None, *, hunt: dict | None = None,
            missions: dict | None = None) -> dict:
    """Active, site, purpose, stage — derived from any browser goal being
    driven (`browser_mission`), the submit processes, the campaign lock and
    the newest application record being worked. Never raises.

    `source` says which store the answer came from, so a job-specific view
    does not claim a browser that is doing something else, and `waiting`
    lists the goals stopped at a boundary that needs him."""
    from aletheia import apply_run, proc
    now = _utc(now)
    hunt = hunt if hunt is not None else job_hunt(now)
    lock = hunt.get("campaign") or None
    missions = missions if missions is not None else browser_missions(now)
    goal = missions.get("active") if missions.get("readable") else None
    waiting = list(missions.get("waiting") or [])

    def with_missions(out: dict) -> dict:
        out["waiting"] = waiting
        out["waiting_count"] = int(missions.get("waiting_count") or 0)
        if missions.get("readable") is False:
            out["missions_note"] = missions.get("note")
        return out

    def from_goal() -> dict:
        return with_missions({"active": True, "site": goal["site"], "purpose": goal["goal"],
                              "stage": goal["stage"], "since": goal.get("since"),
                              "application": None, "mission": goal["mission"],
                              "source": "browser_mission"})
    try:
        rows = apply_run.all_runs()
    except Exception as exc:  # noqa: BLE001
        if goal:
            return from_goal()
        return with_missions({"active": bool(lock and lock.get("running")), "site": "", "purpose": "",
                              "stage": "unknown", "readable": False, "source": "applications",
                              "note": f"the application records could not be read ({type(exc).__name__})"})

    def newest(records: list[dict], *keys: str) -> dict | None:
        best, best_at = None, ""
        for r in records:
            at = max(str(r.get(k) or "") for k in keys) if keys else ""
            if at > best_at:
                best, best_at = r, at
        return best

    # A submit in its own process is the browser pressing a button.
    pressing = [r for r in rows if r.get("state") == "SUBMITTING"
                and proc.pid_alive(r.get("submit_pid")) is not False]
    if pressing:
        record = newest(pressing, "pressed_at", "staged_at") or pressing[0]
        company, job = _name(record)
        return with_missions({"active": True, "site": _site(record.get("url")),
                              "purpose": f"sending the application for {job}",
                              "stage": "pressing submit", "since": record.get("pressed_at"),
                              "application": record.get("id"), "source": "applications"})
    # A goal being driven right now names the page it is on, which beats the
    # campaign lock's guess from the newest record.
    if goal:
        return from_goal()
    if lock and lock.get("running"):
        started = str(lock.get("started_at") or "")
        worked = [r for r in rows if str(r.get("staged_at") or "") >= started]
        record = newest(worked, "staged_at")
        kind = lock.get("kind") or "apply"
        purpose = {"retry": "re-reading the applications that were waiting on questions",
                   "answer": "putting your answer into the forms that asked for it"
                   }.get(kind, "finding openings and filling their forms")
        if record is None:
            return with_missions({"active": True, "site": "", "purpose": purpose,
                                  "stage": "looking for openings" if kind == "apply" else "reading records",
                                  "since": lock.get("started_at"), "application": None,
                                  "source": "applications"})
        stage = {"AWAITING_YOU": "form filled, waiting for confirmation",
                 "NEEDS_YOU": "stopped on questions only you can answer",
                 "NEEDS_ACCOUNT": "stopped at an account wall",
                 "FAILED": "the form would not go", "REJECTED": "the site refused the form",
                 "SUBMITTED": "sent", "CLOSED": "closed without applying"
                 }.get(str(record.get("state")), str(record.get("state") or "")).lower()
        return with_missions({"active": True, "site": _site(record.get("url")), "purpose": purpose,
                              "stage": stage, "since": lock.get("started_at"),
                              "application": record.get("id"), "source": "applications"})
    last = newest([r for r in rows if r.get("state") in WORKED_STATES],
                  "pressed_at", "submitted_at", "staged_at")
    out = {"active": False, "site": "", "purpose": "", "stage": "idle", "since": None,
           "application": None, "source": ""}
    if last is not None:
        out["last"] = {"application": last.get("id"), "site": _site(last.get("url")),
                       "what": _name(last)[1], "state": last.get("state"),
                       "at": last.get("submitted_at") or last.get("pressed_at") or last.get("staged_at")}
    goal_last = missions.get("last") if missions.get("readable") else None
    if goal_last and str(goal_last.get("at") or "") > str((out.get("last") or {}).get("at") or ""):
        out["last"] = {"mission": goal_last.get("mission"), "site": goal_last.get("site"),
                       "what": goal_last.get("goal"), "state": goal_last.get("state"),
                       "at": goal_last.get("at")}
    return with_missions(out)


# ---- the code ------------------------------------------------------------

def _dirty(now_s: float | None = None) -> dict:
    """Modified tracked files, from git, cached. Never raises."""
    import subprocess
    from aletheia.fleet import REPO_ROOT
    from aletheia.proc import hidden_flags
    now_s = time.monotonic() if now_s is None else now_s
    if _DIRTY["value"] is not None and now_s - _DIRTY["at"] < DIRTY_CACHE_S:
        return dict(_DIRTY["value"])
    try:
        done = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                              capture_output=True, text=True, cwd=str(REPO_ROOT),
                              timeout=15, creationflags=hidden_flags())
        if done.returncode != 0:
            value = {"known": False, "dirty": None, "files": []}
        else:
            files = [line[3:].strip() for line in done.stdout.splitlines() if line.strip()]
            value = {"known": True, "dirty": bool(files), "count": len(files),
                     "files": files[:5]}
    except Exception:
        value = {"known": False, "dirty": None, "files": []}
    _DIRTY.update({"at": now_s, "value": dict(value)})
    return value


def code() -> dict:
    """Repo, branch, dirty, latest commit, and whether she started before
    the code on disk was written. Never raises."""
    from aletheia import running
    from aletheia.fleet import REPO_ROOT
    facts = _safe(running.version, {})
    dirty = _dirty()
    return {
        "repo": str(REPO_ROOT),
        "branch": facts.get("branch") or "",
        "commit": facts.get("commit") or "",
        "subject": facts.get("subject") or "",
        "behind": facts.get("behind") or "",
        "dirty": dirty.get("dirty"),
        "dirty_files": dirty.get("files") or [],
        "running_old_code": facts.get("running_old_code"),
        "newest_code": facts.get("newest_code") or "",
        "started_at": facts.get("started_at"),
        "readable": bool(facts) and dirty.get("known", False),
    }


# ---- the agent -----------------------------------------------------------

def agent(now: dt.datetime | None = None, *, hunt: dict | None = None,
          browsing: dict | None = None, pending_approvals: list | None = None,
          waiting_operator: list | None = None, waiting_replies: list | None = None,
          sessions: dict | None = None) -> dict:
    """Her state in the tiny vocabulary, with the evidence it came from.

    The order is the order of what he needs to know: halted beats
    everything; something in flight beats something waiting; something
    waiting on him beats something waiting on the world; quiet is last.
    """
    from aletheia import closed, ears, followups
    now = _utc(now)
    hunt = hunt if hunt is not None else job_hunt(now)
    browsing = browsing if browsing is not None else browser(now, hunt=hunt)
    sessions = sessions if sessions is not None else _safe(lambda: agent_sessions(now), {})
    handed = (sessions or {}).get("handoffs") or {}

    halt = _safe(policy.halted, None)
    if halt:
        return {"state": "HALTED", "mission": "nothing acts until you resume",
                "step": str(halt.get("reason") or ""), "since": halt.get("halted_at")}
    if _safe(closed.is_closed, False):
        return {"state": "HALTED", "mission": "closed - staying shut until you open me",
                "step": _safe(closed.why, "") or "", "since": None}
    doing = list(handed.get("running") or [])
    if doing and not browsing.get("active"):
        return {"state": "ACTING", "mission": "what you approved",
                "step": "doing what you approved: " + str(doing[0].get("said") or doing[0].get("tool") or ""),
                "since": doing[0].get("at")}
    if browsing.get("active") and browsing.get("source") == "browser_mission":
        return {"state": "ACTING", "mission": str(browsing.get("purpose") or "a browser goal"),
                "step": str(browsing.get("stage") or "working") +
                        (f" at {browsing['site']}" if browsing.get("site") else ""),
                "since": browsing.get("since")}
    if browsing.get("active"):
        state = "LOOKING" if browsing.get("stage") == "looking for openings" else "ACTING"
        return {"state": state, "mission": "job hunt",
                "step": (browsing.get("purpose") or "") +
                        (f" - {browsing['stage']}" if browsing.get("stage") else "")
                        + (f" at {browsing['site']}" if browsing.get("site") else ""),
                "since": browsing.get("since")}
    busy = _safe(lambda: (hunt.get("thinking") or {}).get("local", {}).get("busy"), None) \
        or _safe(lambda: __import__("aletheia.local_model_pool", fromlist=["busy"]).busy(), None)
    if busy:
        from aletheia import speech
        typical = ((hunt.get("thinking") or {}).get("local", {}).get("recent") or {}).get("typical_s")
        return {"state": "THINKING", "mission": "thinking with my own model",
                "step": (f"thinking with my own model about “{speech.shorten(str(busy.get('what') or ''), 70)}”"
                         f" - {speech.count_phrase(int(busy.get('elapsed_s') or 0), 'second')} so far"
                         + (f", usually {speech.about_seconds(typical)}" if typical else "")),
                "since": busy.get("started_at")}
    if _safe(followups.pending_count, 0):
        return {"state": "THINKING", "mission": "answering you", "step": "a reply is on its way",
                "since": None}
    thinking_now = list((sessions or {}).get("running") or [])
    if thinking_now:
        asked = str(thinking_now[0].get("question") or "").strip()
        return {"state": "THINKING", "mission": "answering you",
                "step": f"looking things up to answer “{asked}”" if asked else "looking things up",
                "since": thinking_now[0].get("since")}
    if hunt.get("readable") and hunt.get("blocked"):
        minds = hunt.get("thinking") or {}
        until = (minds.get("claude") or {}).get("resting_until")
        return {"state": "BLOCKED", "mission": "job hunt",
                "step": "nobody can think: the big models are out and mine "
                        + str((minds.get("local") or {}).get("why") or "cannot run"),
                "since": until}
    pending = pending_approvals if pending_approvals is not None else \
        [a for a in _safe(policy.all_approvals, []) if a.get("state") == "PENDING"]
    waiting_him = list(hunt.get("waiting_on_him") or []) if hunt.get("readable") else []
    stopped_goals = int(browsing.get("waiting_count") or len(browsing.get("waiting") or []))
    if pending or waiting_him or waiting_operator or stopped_goals:
        parts = []
        if pending:
            parts.append(f"{len(pending)} approval{'s' if len(pending) != 1 else ''}")
        if waiting_him:
            parts.append(f"{len(waiting_him)} application{'s' if len(waiting_him) != 1 else ''}")
        if stopped_goals:
            first = (browsing.get("waiting") or [{}])[0]
            parts.append(f"{stopped_goals} browser goal{'s' if stopped_goals != 1 else ''}"
                         + (f" ({first['said']})" if first.get("said") else ""))
        if waiting_operator:
            parts.append(f"{len(waiting_operator)} task{'s' if len(waiting_operator) != 1 else ''}")
        since = min((str(a.get("created_at") or "") for a in pending), default="") or None
        return {"state": "NEEDS YOU", "mission": "waiting on you",
                "step": " and ".join(parts) + " waiting on you", "since": since}
    if waiting_replies:
        return {"state": "WAITING", "mission": "waiting on the world",
                "step": f"{len(waiting_replies)} repl{'ies' if len(waiting_replies) != 1 else 'y'} expected",
                "since": None}
    if _safe(ears.listening, False):
        return {"state": "LISTENING", "mission": "the room", "step": "microphone open",
                "since": None}
    from aletheia import liveness
    started = (_safe(liveness.last, None) or {}).get("started_at")
    return {"state": "IDLE", "mission": "", "step": "", "since": started}


# ---- the snapshot --------------------------------------------------------

def work(now: dt.datetime | None = None) -> dict:
    """Every unfinished item across her queues as one inventory (`aletheia.work_engine`):
    counts per state, what can run now, and each blocked item with why and when it
    wakes. Read-only; no live probes."""
    from aletheia import work_engine
    return work_engine.summary(_utc(now))


def work_session_section(now: dt.datetime | None = None) -> dict:
    """The work session he started ("work on my projects"): running, done, waiting and why."""
    from aletheia import project_work
    return project_work.summary(_utc(now))


def unattended(now: dt.datetime | None = None) -> dict:
    """What she did WITHOUT asking him (`aletheia.autonomy`): every reversible,
    local action she took on her own, with the command that undoes each one and
    how much of her daily allowance is left. Empty says so."""
    from aletheia import autonomy
    return autonomy.summary(hours=24.0, now=_utc(now))


def studies_section(now: dt.datetime | None = None) -> dict:
    """His studies (`aletheia.studies`): evidence, proposals awaiting him, changes being measured."""
    from aletheia import studies
    return studies.section(_utc(now))


def programs_section(now: dt.datetime | None = None) -> dict:
    """His long missions (`aletheia.programs`): each one's progress, what waits, what is his."""
    from aletheia import programs
    return programs.section(_utc(now))


def conversations(now: dt.datetime | None = None) -> dict:
    """The conversations she carries (`aletheia.conversations`): what waits for his
    approval, who she is waiting to hear from, which follow-ups are due, what needs
    his answer, and the calendar holds and clashes. An empty store says so."""
    from aletheia import conversations as store
    return store.summary(_utc(now))


def sections(now: dt.datetime | None = None, *, fresh: bool = False) -> dict:
    """The derived sections, cached for a few seconds. Never raises."""
    now = _utc(now)
    clock = time.monotonic()
    if not fresh and _SECTIONS["value"] is not None and clock - _SECTIONS["at"] < SECTIONS_CACHE_S:
        return json.loads(json.dumps(_SECTIONS["value"]))
    hunt = _safe(lambda: job_hunt(now), {"readable": False, "note": "the job hunt could not be read"})
    missions = _safe(lambda: browser_missions(now), {"readable": False, "active": None, "waiting": []})
    browsing = _safe(lambda: browser(now, hunt=hunt, missions=missions),
                     {"active": False, "site": "", "purpose": "", "stage": "unknown",
                      "readable": False})
    sessions = _safe(lambda: agent_sessions(now), {"readable": False})
    value = {
        "agent": _safe(lambda: agent(now, hunt=hunt, browsing=browsing, sessions=sessions),
                       {"state": "IDLE", "mission": "", "step": "", "since": None,
                        "readable": False}),
        "job_hunt": hunt,
        "browser": browsing,
        "agent_sessions": sessions,
        "code": _safe(code, {"readable": False}),
        "power": _safe(power_state, {"known": False, "said": "the power state could not be read"}),
        "usage": _safe(lambda: usage(now), {"window_used": "unknown", "weekly": "unknown",
                                            "note": "the usage records could not be read"}),
        "work": _safe(lambda: work(now), {"readable": False, "note": "the work inventory could not be read"}),
        "work_session": _safe(lambda: work_session_section(now),
                              {"readable": False, "note": "the work sessions could not be read"}),
        "programs": _safe(lambda: programs_section(now),
                          {"readable": False, "note": "the long missions could not be read"}),
        "studies": _safe(lambda: studies_section(now),
                         {"readable": False, "note": "the studies could not be read"}),
        "conversations": _safe(lambda: conversations(now),
                               {"readable": False, "note": "the conversations could not be read"}),
        "unattended": _safe(lambda: unattended(now),
                            {"readable": False, "note": "the unattended ledger could not be read"}),
        "brains": _safe(lambda: {"minds": hunt.get("thinking") or thinking(now),
                                 "said": brains_words(hunt.get("thinking") or thinking(now))},
                        {"minds": {}, "said": ""}),
    }
    _SECTIONS.update({"at": clock, "value": json.loads(json.dumps(value, default=str))})
    return json.loads(json.dumps(value, default=str))


def forget_cache() -> None:
    _SECTIONS.update({"at": 0.0, "value": None})
    _DIRTY.update({"at": 0.0, "value": None})


def snapshot(*, now: dt.datetime | None = None) -> dict:
    now = _utc(now)
    all_tasks = tasks.all_tasks()
    all_projects = projects.all_projects()
    approvals = policy.all_approvals()
    expectations = communications.all_expectations()
    schedules = scheduler.all_schedules()
    registry = capabilities.load_registry()

    waiting_replies = [e for e in expectations if e.get("status") == "WAITING"]
    overdue_replies = [e for e in expectations if e.get("status") == "OVERDUE"]
    active_projects = [p for p in all_projects if p.get("status") not in {"COMPLETED", "CANCELLED"}]
    active_tasks = [t for t in all_tasks if t.get("status") not in TERMINAL_TASKS]
    blocked_tasks = [t for t in active_tasks if t.get("status") in {"BLOCKED", "FAILED_RETRYABLE"}]
    waiting_operator = [t for t in active_tasks if t.get("status") == "WAITING_OPERATOR"]
    pending_approvals = [a for a in approvals if a.get("state") == "PENDING"]

    upcoming = []
    for spec in schedules:
        try:
            occurrence = scheduler.next_occurrence(spec, now)
        except ValueError:
            continue
        if occurrence is not None:
            upcoming.append({"schedule_id": spec["id"], "at": occurrence.isoformat(),
                             "command_kind": spec["command"].get("kind")})
    upcoming.sort(key=lambda item: item["at"])

    unavailable = [c for c in registry.get("capabilities", []) if c.get("status") != "AVAILABLE"]
    derived = sections(now)
    # The agent line is recomputed with what THIS snapshot already read, so
    # NEEDS YOU and WAITING agree with the lists beside them.
    derived["agent"] = _safe(
        lambda: agent(now, hunt=derived["job_hunt"], browsing=derived["browser"],
                      pending_approvals=pending_approvals, waiting_operator=waiting_operator,
                      waiting_replies=waiting_replies, sessions=derived.get("agent_sessions")),
        derived["agent"])
    return {
        "version": 2,
        "as_of": _stamp(now),
        "halted": bool(policy.halted()),
        "agent": derived["agent"],
        "focus": {
            "active_projects": [{"id": p["id"], "title": p["title"], "status": p["status"]}
                                for p in active_projects],
            "active_tasks": [{"id": t["id"], "description": t["description"], "status": t["status"]}
                             for t in active_tasks],
        },
        "needs_attention": {
            "pending_approvals": [a["id"] for a in pending_approvals],
            "waiting_operator": [t["id"] for t in waiting_operator],
            "blocked_tasks": [t["id"] for t in blocked_tasks],
            "overdue_replies": [e["id"] for e in overdue_replies],
            "unread_notifications": notifications.unread_count(),
        },
        "waiting": {"replies": [e["id"] for e in waiting_replies]},
        "upcoming": upcoming[:20],
        "capability_gaps": [{"id": c["id"], "status": c["status"]} for c in unavailable],
        "job_hunt": derived["job_hunt"],
        "browser": derived["browser"],
        "agent_sessions": derived.get("agent_sessions"),
        "code": derived["code"],
        "power": derived.get("power"),
        "usage": derived.get("usage"),
        "work": derived.get("work"),
        "work_session": derived.get("work_session"),
        "programs": derived.get("programs"),
        "studies": derived.get("studies"),
        "unattended": derived.get("unattended"),
    }


# ---- said out loud ------------------------------------------------------

def _plural(count: int, word: str) -> str:
    from aletheia import speech
    return speech.count_phrase(count, word)


def job_hunt_words(hunt: dict | None = None) -> str:
    """How the applications went today, as a sentence. From the counts."""
    from aletheia import speech
    hunt = hunt if hunt is not None else job_hunt()
    if not hunt.get("readable"):
        return ("I can't read my application records right now, so I can't say how "
                "the applications went. " + str(hunt.get("note") or "")).strip()
    today = hunt["today"]
    if not today["discovered"] and not today["sent"] and not today["blocked"]:
        said = "No applications today: nothing was found, sent or blocked."
    else:
        bits = [f"{_plural(today['discovered'], 'opening')} found"]
        if today["qualified"] != today["discovered"]:
            bits.append(f"{today['qualified']} worth trying")
        bits.append(f"{_plural(today['attempted'], 'form')} filled")
        bits.append(f"{today['sent']} sent")
        if today["ready"]:
            bits.append(f"{today['ready']} ready for you")
        if today["blocked"]:
            bits.append(f"{today['blocked']} blocked")
        said = "Today: " + ", ".join(bits) + "."
        if hunt.get("blockers"):
            named = [f"{said_name(b['company'], b['job'])} - {said_clause(b['reason'], 110)}"
                     for b in hunt["blockers"][:3]]
            said += " Blocked: " + "; ".join(named) + "."
        if today["replies"]:
            said += f" {_plural(today['replies'], 'reply', 'replies')} from employers."
    now = hunt.get("now") or {}
    if now.get("needs_you"):
        said += f" {_plural(now['needs_you'], 'application')} waiting on questions only you can answer."
    if hunt.get("running"):
        said += " The hunt is running now."
    elif hunt.get("blocked"):
        said += " The hunt is stopped: nobody can think just now."
    minds = hunt.get("thinking") or {}
    claude = (minds.get("claude") or {}).get("resting_until")
    if claude:
        from aletheia import reasoner
        when = _parse(claude)
        said += (f" {reasoner.big_models_out(when)}, so it is thinking with "
                 + ("my own model." if (minds.get('local') or {}).get('allowed')
                    else "the other one." if not (minds.get('codex') or {}).get('resting_until')
                    else "nobody, until then."))
    return said


def last_application(rows: list | None = None) -> dict | None:
    """The newest application she pressed Submit on, or None. Never raises."""
    from aletheia import apply_run
    try:
        rows = rows if rows is not None else apply_run.all_runs()
    except Exception:  # noqa: BLE001
        return None
    pressed = [r for r in rows if r.get("state") in PRESSED]
    if not pressed:
        return None
    pressed.sort(key=lambda r: str(r.get("submitted_at") or r.get("pressed_at") or ""))
    return pressed[-1]


def _said_application(record: dict) -> str:
    """"Operations Analyst at Stripe" - or, when the record has no names,
    what `said_name` makes of its URL."""
    company, job = _name(record)
    return said_name(company, job) if job.startswith("http") or not job else job


def still_applying_words(hunt: dict | None = None) -> str:
    """"Are you still applying?" - from whether the batch's PROCESS is alive."""
    from aletheia import speech
    hunt = hunt if hunt is not None else job_hunt()
    lock = hunt.get("campaign") or {}
    if hunt.get("running"):
        since = speech.ago(lock.get("started_at"))
        said = "Yes, a batch of applications is running now"
        said += f", started {since}" if since and since != "just now" else ""
        if lock.get("limit"):
            said += f", making {speech.count_phrase(int(lock['limit']), 'application')} ready"
        return said + "."
    said = "No, nothing is running right now."
    if hunt.get("readable") and hunt.get("blocked"):
        said += " The hunt is stopped because nobody can think just now."
    last = last_application()
    if last:
        when = speech.ago(last.get("submitted_at") or last.get("pressed_at"))
        said += f" The last one I sent was {_said_application(last)}"
        said += f", {when}." if when else "."
    elif hunt.get("readable"):
        said += " I have not sent an application yet."
    return said


def how_many_words(hunt: dict | None = None, *, total: bool = False) -> str:
    """"How many jobs have you applied to?" - a count of records, nothing else."""
    from aletheia import speech
    hunt = hunt if hunt is not None else job_hunt()
    if not hunt.get("readable"):
        return ("I can't read my application records right now, so I can't count them. "
                + str(hunt.get("note") or "")).strip()
    now = hunt.get("now") or {}
    today = hunt.get("today") or {}
    sent_total = now.get("sent_total")
    if total and sent_total is not None:
        said = f"{speech.count_phrase(int(sent_total), 'application')} sent in total"
        said += f", {today.get('sent', 0)} of them today." if today.get("sent") else "."
    else:
        said = f"{speech.count_phrase(int(today.get('sent', 0)), 'application')} sent today"
        said += f", {sent_total} in total." if sent_total else "."
    if today.get("ready"):
        said += f" {speech.count_phrase(int(today['ready']), 'more')} ready for you to approve."
    if not sent_total and not today.get("sent"):
        said = "None so far: I have no record of an application sent"
        said += (f", though {speech.count_phrase(int(today['ready']), 'application')} "
                 "waiting for you to approve." if today.get("ready") else ".")
    return said


def last_application_words(*, what: bool) -> str:
    """"When was the last application?" / "What was the last job you applied to?" """
    from aletheia import speech
    hunt = job_hunt()
    if not hunt.get("readable"):
        return "I can't read my application records right now, so I can't say."
    last = last_application()
    if not last:
        return "I have not sent an application yet, so there is no last one."
    who = _said_application(last)
    when = speech.ago(last.get("submitted_at") or last.get("pressed_at"))
    if what:
        return f"The last one was {who}" + (f", sent {when}." if when else ".")
    return (f"The last application went {when}, to {who}." if when
            else f"The last application was {who}; I did not record when.")


def blocking_words(hunt: dict | None = None) -> str:
    """"What's blocking the job hunt?" - the recorded blockers, or that there are none."""
    from aletheia import speech
    hunt = hunt if hunt is not None else job_hunt()
    if not hunt.get("readable"):
        return "I can't read my application records right now, so I can't say what is blocking them."
    parts = []
    if hunt.get("blocked"):
        minds = hunt.get("thinking") or {}
        parts.append("nobody can think: the big models are out and my own model "
                     + str((minds.get("local") or {}).get("why") or "cannot run"))
    waiting = hunt.get("waiting_on_him") or []
    if waiting:
        parts.append(needs_from_him_words(hunt).rstrip("."))
    if hunt.get("blockers"):
        named = [f"{said_name(b['company'], b['job'])} ({said_clause(b['reason'], 110)})"
                 for b in hunt["blockers"][:3]]
        parts.append(f"{speech.count_phrase(len(hunt['blockers']), 'application')} blocked today: "
                     + "; ".join(named))
    if not parts:
        # NOTHING RECORDED IS NOT AN ANSWER TO "WHY". The records say no
        # application is blocked and someone can think; "why is the job
        # hunt stopped" then deserves the investigator, which reads the
        # journal and the receipts, not a fast "nothing here". Empty means
        # the fast lane steps aside (quick may only remove latency).
        return ""
    return ". ".join(p[0].upper() + p[1:] for p in parts) + "."


def repo_words(name: str) -> str | None:
    """"Is the Shorts pipeline running?" - that repo's row of the pulse, or None
    when the pulse does not know a repo by that name."""
    import json
    from aletheia import pulse, speech
    try:
        latest = json.loads((pulse.PULSE_DIR / "latest.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    repos = latest.get("repos") if isinstance(latest.get("repos"), dict) else {}
    key = "".join(ch for ch in str(name or "").casefold() if ch.isalnum())
    if len(key) < 3:
        return None

    def known_as(row: dict, slug: str) -> bool:
        # "shorts" is the Shorts-pipeline; "it" is nothing. The name he
        # says has to be the slug, or how the slug starts.
        for said in (slug, str(row.get("github") or "")):
            plain = "".join(ch for ch in said.casefold() if ch.isalnum())
            if plain == key or plain.startswith(key) or (len(key) >= 5 and key in plain):
                return True
        return False

    row = next((r for slug, r in repos.items() if isinstance(r, dict) and known_as(r, slug)), None)
    if not isinstance(row, dict):
        return None
    said = str(row.get("github") or name)
    health = str(row.get("health") or "unknown")
    flows = row.get("workflows") if isinstance(row.get("workflows"), dict) else {}
    failing = sorted(n for n, w in flows.items()
                     if isinstance(w, dict) and w.get("conclusion") not in (None, "success", "skipped"))
    last = (row.get("commit") or {}).get("date")
    when = speech.ago(last) if last else ""
    bits = [f"{said} is {'healthy' if health == 'green' else 'not healthy' if health == 'red' else health}"]
    if failing:
        bits.append(f"{speech.count_phrase(len(failing), 'workflow')} failing: "
                    + speech.and_list([f.replace('.yml', '') for f in failing[:3]]))
    if when:
        bits.append(f"the last commit was {when}")
    return "; ".join(bits) + "."


def said_name(company: str, job: str) -> str:
    """Who an application is with, sayable. A record with no employer name
    carries its URL in `job`, and "https://jobs.smartrecruiters.com/oneclick-ui/
    company/Keenfinity/publication/dad8a717..." was read out, whole, in a room."""
    import re
    from urllib.parse import urlparse
    name = " ".join(str(company or "").split()) or " ".join(str(job or "").split())
    if re.match(r"^https?://", name):
        host = re.sub(r"^(?:www|jobs|boards|careers|apply|job-boards)\.", "",
                      (urlparse(name).hostname or "").casefold())
        return f"an opening on {host}" if host else "an opening"
    return name or "an opening"


def said_clause(text: str, limit: int = 80) -> str:
    """A reason, cut where a CLAUSE ends rather than where the characters run
    out: "nothing on this page asks for his name, email or phone, so it is not
    an" was a real answer. Codes and class names out, machine paths out."""
    import re
    from aletheia import speech
    said = speech.plainly(str(text or ""))
    said = re.sub(r"\b(?:GET|POST|PUT|DELETE)\s+/\S+", "a request", said)
    said = re.sub(r"https?://\S+", "a web page", said)
    said = re.sub(r"\b[A-Z]\w*(?:Error|Exception|Warning):\s*", "", said)
    said = " ".join(said.split()).strip(" .;")
    if len(said) <= limit:
        return said
    for mark in (". ", "; ", ", so ", " so ", ", which "):
        head = said[:limit]
        at = head.rfind(mark)
        if at >= limit // 3:
            return said[:at].rstrip(" ,;:-")
    return speech.shorten(said, limit)


def wrong_today_words(hunt: dict | None = None) -> str:
    """What went wrong today: blocked applications and journal alerts."""
    from aletheia import recollection, speech
    hunt = hunt if hunt is not None else job_hunt()
    parts = []
    if not hunt.get("readable"):
        parts.append("I can't read my application records right now")
    elif hunt.get("blockers"):
        named = [f"{said_name(b['company'], b['job'])} ({said_clause(b['reason'], 110)})"
                 for b in hunt["blockers"][:4]]
        parts.append(f"{_plural(len(hunt['blockers']), 'application')} blocked today: "
                     + "; ".join(named))
    try:
        trouble = recollection.trouble(hours=recollection.TODAY_HOURS)
        readable = True
    except Exception:
        trouble, readable = [], False
    if not readable:
        parts.append("and I can't read my journal just now")
    elif trouble:
        # Said once each: the same access refusal twice in a row is one fact.
        lines: list[str] = []
        for t in reversed(trouble):
            line = said_clause(str(t.get("what") or t.get("text") or ""), 90)
            if line and line not in lines:
                lines.append(line)
            if len(lines) == 3:
                break
        parts.append(f"{_plural(len(trouble), 'alert')} in the journal today, the latest: "
                     + "; ".join(lines))
    if not parts:
        return ("Nothing went wrong that I recorded today: no applications blocked, "
                "no alerts in the journal.")
    return ". ".join(parts) + "."


def needs_from_him_words(hunt: dict | None = None) -> str:
    """What the job hunt needs from him, or an empty string when nothing."""
    from aletheia import speech
    hunt = hunt if hunt is not None else job_hunt()
    if not hunt.get("readable"):
        return ""
    waiting = hunt.get("waiting_on_him") or []
    if not waiting:
        return ""
    named = []
    for w in waiting[:3]:
        who = said_name(w["company"], w["job"])
        if w.get("questions"):
            # ONE question, and the count of the rest: a question label has
            # commas in it, and `and_list` joins with commas, so two of them
            # ran together into one sentence nobody could parse by ear.
            first = said_clause(w["questions"][0], 140)
            rest = len(w["questions"]) - 1
            named.append(f"{who} asks “{first}”"
                         + (f" and {speech.count_phrase(rest, 'more question')}" if rest else ""))
        else:
            named.append(f"{who} - {w['why']}")
    more = f", and {len(waiting) - 3} more" if len(waiting) > 3 else ""
    return (f"{_plural(len(waiting), 'application')} waiting on you: "
            + "; ".join(named) + more + ".")


#: The state word said as a person says it. The screen can afford a label
#: and a colon — "Stuck: the form wants an account" reads fine in a
#: column. Out loud a colon is nothing at all, so what he hears is two
#: fragments jammed together with no verb between them. Same fact, said
#: in the first person, because it is her answering about herself.
_AGENT_LEAD = {"ACTING": "I'm working on", "LOOKING": "I'm looking at",
               "THINKING": "I'm thinking about", "BLOCKED": "I'm stuck on",
               "NEEDS YOU": "I need you for", "WAITING": "I'm waiting on",
               "LISTENING": "I'm listening for"}


def agent_words(block: dict | None = None) -> str:
    """"What are you doing right now", from the agent block."""
    block = block if block is not None else sections()["agent"]
    state = str(block.get("state") or "IDLE")
    step = str(block.get("step") or "").strip()
    mission = str(block.get("mission") or "").strip()
    if state == "HALTED":
        return ("I'm halted" + (f" — {step}." if step else ".")
                + " Nothing runs until you resume me.")
    if state == "IDLE":
        return "Nothing right now — I'm just here."
    said = f"{_AGENT_LEAD[state]} {step or mission}".strip()
    return said.rstrip(".") + "."


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="The canonical model of now.")
    ap.add_argument("section", nargs="?", help="agent, job_hunt, browser, agent_sessions, code, power "
                                               "or usage; omit for all")
    ap.add_argument("--say", action="store_true", help="the spoken forms")
    args = ap.parse_args(argv)
    if args.say:
        derived = sections(fresh=True)
        print(agent_words(derived["agent"]))
        print(job_hunt_words(derived["job_hunt"]))
        print(wrong_today_words(derived["job_hunt"]))
        print(needs_from_him_words(derived["job_hunt"]) or "Nothing the job hunt needs from you.")
        return 0
    value = snapshot()
    if args.section:
        value = value.get(args.section, {"error": f"no section {args.section!r}"})
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
