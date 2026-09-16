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
- `browser`: active, site, purpose, stage.
- `code`: repo, branch, dirty, latest commit, and whether the running Core
  predates the code on disk.

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
    out["anyone"] = claude is None or codex is None or bool(local_ok)
    return out


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
            labels = [str(q.get("label") or "")[:80] for q in (r.get("questions") or [])
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


def browser(now: dt.datetime | None = None, *, hunt: dict | None = None) -> dict:
    """Active, site, purpose, stage — derived from the campaign lock, the
    submit processes, and the newest record being worked. Never raises."""
    from aletheia import apply_run, proc
    now = _utc(now)
    hunt = hunt if hunt is not None else job_hunt(now)
    lock = hunt.get("campaign") or None
    try:
        rows = apply_run.all_runs()
    except Exception as exc:  # noqa: BLE001
        return {"active": bool(lock and lock.get("running")), "site": "", "purpose": "",
                "stage": "unknown", "readable": False,
                "note": f"the application records could not be read ({type(exc).__name__})"}

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
        return {"active": True, "site": _site(record.get("url")),
                "purpose": f"sending the application for {job}",
                "stage": "pressing submit", "since": record.get("pressed_at"),
                "application": record.get("id")}
    if lock and lock.get("running"):
        started = str(lock.get("started_at") or "")
        worked = [r for r in rows if str(r.get("staged_at") or "") >= started]
        record = newest(worked, "staged_at")
        kind = lock.get("kind") or "apply"
        purpose = {"retry": "re-reading the applications that were waiting on questions",
                   "answer": "putting your answer into the forms that asked for it"
                   }.get(kind, "finding openings and filling their forms")
        if record is None:
            return {"active": True, "site": "", "purpose": purpose,
                    "stage": "looking for openings" if kind == "apply" else "reading records",
                    "since": lock.get("started_at"), "application": None}
        stage = {"AWAITING_YOU": "form filled, waiting for confirmation",
                 "NEEDS_YOU": "stopped on questions only you can answer",
                 "NEEDS_ACCOUNT": "stopped at an account wall",
                 "FAILED": "the form would not go", "REJECTED": "the site refused the form",
                 "SUBMITTED": "sent", "CLOSED": "closed without applying"
                 }.get(str(record.get("state")), str(record.get("state") or "")).lower()
        return {"active": True, "site": _site(record.get("url")), "purpose": purpose,
                "stage": stage, "since": lock.get("started_at"),
                "application": record.get("id")}
    last = newest([r for r in rows if r.get("state") in WORKED_STATES],
                  "pressed_at", "submitted_at", "staged_at")
    out = {"active": False, "site": "", "purpose": "", "stage": "idle", "since": None,
           "application": None}
    if last is not None:
        out["last"] = {"application": last.get("id"), "site": _site(last.get("url")),
                       "what": _name(last)[1], "state": last.get("state"),
                       "at": last.get("submitted_at") or last.get("pressed_at") or last.get("staged_at")}
    return out


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
          waiting_operator: list | None = None, waiting_replies: list | None = None) -> dict:
    """Her state in the tiny vocabulary, with the evidence it came from.

    The order is the order of what he needs to know: halted beats
    everything; something in flight beats something waiting; something
    waiting on him beats something waiting on the world; quiet is last.
    """
    from aletheia import closed, ears, followups
    now = _utc(now)
    hunt = hunt if hunt is not None else job_hunt(now)
    browsing = browsing if browsing is not None else browser(now, hunt=hunt)

    halt = _safe(policy.halted, None)
    if halt:
        return {"state": "HALTED", "mission": "nothing acts until you resume",
                "step": str(halt.get("reason") or ""), "since": halt.get("halted_at")}
    if _safe(closed.is_closed, False):
        return {"state": "HALTED", "mission": "closed - staying shut until you open me",
                "step": _safe(closed.why, "") or "", "since": None}
    if browsing.get("active"):
        state = "LOOKING" if browsing.get("stage") == "looking for openings" else "ACTING"
        return {"state": state, "mission": "job hunt",
                "step": (browsing.get("purpose") or "") +
                        (f" - {browsing['stage']}" if browsing.get("stage") else "")
                        + (f" at {browsing['site']}" if browsing.get("site") else ""),
                "since": browsing.get("since")}
    if _safe(followups.pending_count, 0):
        return {"state": "THINKING", "mission": "answering you", "step": "a reply is on its way",
                "since": None}
    if hunt.get("readable") and hunt.get("blocked"):
        minds = hunt.get("thinking") or {}
        until = (minds.get("claude") or {}).get("resting_until")
        return {"state": "BLOCKED", "mission": "job hunt",
                "step": "nobody can think: Claude and Codex are out and my own model "
                        + str((minds.get("local") or {}).get("why") or "cannot run"),
                "since": until}
    pending = pending_approvals if pending_approvals is not None else \
        [a for a in _safe(policy.all_approvals, []) if a.get("state") == "PENDING"]
    waiting_him = list(hunt.get("waiting_on_him") or []) if hunt.get("readable") else []
    if pending or waiting_him or waiting_operator:
        parts = []
        if pending:
            parts.append(f"{len(pending)} approval{'s' if len(pending) != 1 else ''}")
        if waiting_him:
            parts.append(f"{len(waiting_him)} application{'s' if len(waiting_him) != 1 else ''}")
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

def sections(now: dt.datetime | None = None, *, fresh: bool = False) -> dict:
    """The four derived sections, cached for a few seconds. Never raises."""
    now = _utc(now)
    clock = time.monotonic()
    if not fresh and _SECTIONS["value"] is not None and clock - _SECTIONS["at"] < SECTIONS_CACHE_S:
        return json.loads(json.dumps(_SECTIONS["value"]))
    hunt = _safe(lambda: job_hunt(now), {"readable": False, "note": "the job hunt could not be read"})
    browsing = _safe(lambda: browser(now, hunt=hunt),
                     {"active": False, "site": "", "purpose": "", "stage": "unknown",
                      "readable": False})
    value = {
        "agent": _safe(lambda: agent(now, hunt=hunt, browsing=browsing),
                       {"state": "IDLE", "mission": "", "step": "", "since": None,
                        "readable": False}),
        "job_hunt": hunt,
        "browser": browsing,
        "code": _safe(code, {"readable": False}),
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
                      waiting_replies=waiting_replies),
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
        "code": derived["code"],
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
            named = [f"{b['company'] or b['job']} - {speech.shorten(b['reason'], 70)}"
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
        said += (f" Claude is out until {reasoner.spoken_time(when)}, so it is thinking with "
                 + ("my own model." if (minds.get('local') or {}).get('allowed')
                    else "Codex." if not (minds.get('codex') or {}).get('resting_until')
                    else "nobody, until then."))
    return said


def wrong_today_words(hunt: dict | None = None) -> str:
    """What went wrong today: blocked applications and journal alerts."""
    from aletheia import recollection, speech
    hunt = hunt if hunt is not None else job_hunt()
    parts = []
    if not hunt.get("readable"):
        parts.append("I can't read my application records right now")
    elif hunt.get("blockers"):
        named = [f"{b['company'] or b['job']} ({speech.shorten(b['reason'], 80)})"
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
        lines = [speech.shorten(str(t.get("what") or t.get("text") or ""), 90)
                 for t in trouble[-3:]]
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
        who = w["company"] or w["job"]
        if w.get("questions"):
            named.append(f"{who} asks {speech.and_list(w['questions'][:2])}")
        else:
            named.append(f"{who} - {w['why']}")
    more = f", and {len(waiting) - 3} more" if len(waiting) > 3 else ""
    return (f"{_plural(len(waiting), 'application')} waiting on you: "
            + "; ".join(named) + more + ".")


def agent_words(block: dict | None = None) -> str:
    """"What are you doing right now", from the agent block."""
    block = block if block is not None else sections()["agent"]
    state = str(block.get("state") or "IDLE")
    step = str(block.get("step") or "").strip()
    mission = str(block.get("mission") or "").strip()
    if state == "HALTED":
        return "Halted" + (f" - {step}." if step else ".") + " Nothing runs until you resume me."
    if state == "IDLE":
        return "Nothing in flight right now."
    lead = {"ACTING": "Working on", "LOOKING": "Looking:", "THINKING": "Thinking:",
            "BLOCKED": "Stuck:", "NEEDS YOU": "Waiting on you:", "WAITING": "Waiting:",
            "LISTENING": "Listening:"}[state]
    said = f"{lead} {step or mission}".strip()
    return said.rstrip(".") + "."


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="The canonical model of now.")
    ap.add_argument("section", nargs="?", help="agent, job_hunt, browser or code; omit for all")
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
