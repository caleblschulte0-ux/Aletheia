""""Work on my projects.": a bounded work session that finds and does real work.

The final target of his continuity brief (docs/CONTINUITY_BRIEF.md): *"He opens
Aletheia and says 'Work on my projects.' and she finds productive work even with
Claude and Codex unavailable."* Acceptance test A: she inventories available work,
completes what she can locally, investigates harder tasks, queues what genuinely
needs stronger reasoning with specific blocked reasons, and does not stop.

A SESSION is a durable record (`state/private/work/sessions/<id>.json`) and a worker
thread in the process that heard him:

    start      the inventory before, the reply he hears at once (what she is taking
               now, what waits and on whom) - never "I can't work" while anything
               is executable
    loop       one item at a time, until nothing she can run or investigate is
               left or the time he gave runs out:
                 gather + pick (the one engine), checkpoint what is blocked,
                 then the next candidate: READY work her runners carry
                 (`work_engine.run_one` -> `work_runners`, `program_run`, gap
                 items), then work reserved for a stronger model that has not
                 been INVESTIGATED yet (rule 5: a packet first)
               her own model runs under the WORK lease, so conversation goes first
    finish     the inventory after, receipts for everything done, why it stopped
               (and proof: what was still executable when it stopped), the spoken
               report, one notification

Each item is attempted once per session; its outcome is written to its own store
or the engine's overlay before the next one starts, so a crash costs at most the
item in flight, and a session whose process died is resumed by the next beat while
its time lasts (rule 7). Halting her stops the loop at the next check.

    python -m aletheia.project_work start [--minutes 25] [--frontier-off]
    python -m aletheia.project_work status
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import secrets
import threading
import time
from typing import Any, Callable

from aletheia import stateio, work_states as ws

ACTOR = "aletheia-work-session"
DEFAULT_MINUTES = 25.0
MAX_MINUTES = 120.0
HEARTBEAT_STALE_S = 15 * 60
MAX_RECEIPTS = 60
#: Routes that start nothing here: somebody else carries them.
LEFT_ROUTES = {"builder", "frontier_worker", "wait_stronger"}
#: Cheapest first, so the quick wins land before the long local-model work.
ROUTE_COST = {"his": 0, "verify": 1, "compose": 2, "frontier_packet": 3, "investigate": 4, "escalate": 5,
              "change": 5, "doc": 5, "failure": 6}
INVESTIGATE_STATES = {ws.NEEDS_STRONGER_MODEL, ws.BLOCKED_MODEL}
WORK_SOURCES = {"tasks", "plans", "charter_ci"}
RUNNING, DONE, INTERRUPTED = "RUNNING", "DONE", "INTERRUPTED"

_JOB: dict[str, Any] = {"thread": None, "session": None}
_LOCK = threading.Lock()


def sessions_dir():
    return stateio.private_dir("work", "sessions")


def _now(now: dt.datetime | None = None) -> dt.datetime:
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)


def _stamp(when: dt.datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def load(session_id: str) -> dict:
    return stateio.read_json(sessions_dir() / f"{stateio.safe_id(session_id, name='session id')}.json")


def save(record: dict) -> dict:
    sessions_dir().mkdir(parents=True, exist_ok=True)
    record["updated_at"] = stateio.utcnow()
    stateio.write_json_atomic(sessions_dir() / f"{stateio.safe_id(record['id'], name='session id')}.json", record)
    return record


def all_sessions() -> list[dict]:
    directory = sessions_dir()
    if not directory.is_dir():
        return []
    rows = []
    for path in directory.glob("work-*.json"):
        try:
            value = stateio.read_json(path)
        except ValueError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return sorted(rows, key=lambda r: str(r.get("started_at") or ""))


def latest() -> dict | None:
    rows = all_sessions()
    return rows[-1] if rows else None


def _journal(kind: str, subject: str, text: str) -> None:
    try:
        from aletheia import journal
        journal.append(kind, subject, text, actor=ACTOR)
    except Exception:  # noqa: BLE001
        pass


# ---- what there is to do ---------------------------------------------------------------------

def _frontier(now: dt.datetime) -> dict:
    from aletheia import work_requirements as wr
    return {"frontier": wr.world("frontier_reasoning", now=now), "local": wr.world("local_reasoning", now=now)}


def candidates(picked: dict, *, attempted: set[str], frontier: bool) -> list[tuple[dict, str, str]]:
    """(item, mode, route) she can carry now, cheapest first. Pure but for the router.

    READY items with a runner, then unfinished work reserved for a stronger model
    that has no packet yet (investigate before escalating)."""
    from aletheia import work_engine as we, work_runners
    out = []
    for it in picked.get("executable") or []:
        if it["id"] in attempted or we.runner_for(it) is None:
            continue
        where = work_runners.route(it, frontier=frontier) if it["source"] in WORK_SOURCES else {"route": "compose"}
        if where["route"] in LEFT_ROUTES:
            continue
        out.append((it, "run", where["route"]))
    for it in picked.get("blocked") or []:
        if it["id"] in attempted or it["source"] not in WORK_SOURCES or it["state"] not in INVESTIGATE_STATES:
            continue
        if (it.get("evidence") or {}).get("packet"):
            continue
        where = work_runners.route(it, frontier=frontier, investigate=True)
        if where["route"] in LEFT_ROUTES:
            continue
        out.append((it, "investigate", where["route"]))
    return sorted(out, key=lambda row: (ROUTE_COST.get(row[2], 3), 0 if row[1] == "run" else 1,
                                        row[0].get("priority", 3), row[0]["id"]))


def _brief(it: dict) -> dict:
    return {"id": it["id"], "title": it.get("title"), "state": it.get("state"), "reason": it.get("reason") or "",
            "next": it.get("next") or "", "source": it.get("source"),
            "aliases": [a.get("id") for a in it.get("aliases") or []]}


def snapshot(now: dt.datetime | None = None, *, attempted: set[str] | None = None) -> dict:
    """The inventory as the session sees it: counts, what she can take now, what waits."""
    from aletheia import work_engine as we
    now = _now(now)
    items, notes = we.gather(now)
    picked = we.pick(items, now, probe=False, persist=False)
    minds = _frontier(now)
    can = candidates(picked, attempted=attempted or set(), frontier=bool(minds["frontier"]["ok"]))
    from aletheia import work_runners
    left = [it for it in picked["executable"]
            if it["source"] in WORK_SOURCES and work_runners.route(it, frontier=bool(minds["frontier"]["ok"]))["route"]
            in LEFT_ROUTES]
    return {"as_of": _stamp(now), "counts": {k: v for k, v in picked["counts"].items() if v},
            "halted": picked["halted"], "can_now": [dict(_brief(it), mode=mode, route=route) for it, mode, route in can],
            "left_to_others": [_brief(it) for it in left],
            "waiting": [_brief(it) for it in picked["blocked"]],
            "frontier": {"ok": minds["frontier"]["ok"], "why": minds["frontier"]["why"]},
            "local": {"ok": minds["local"]["ok"], "why": minds["local"]["why"]}, "notes": notes}


# ---- starting ---------------------------------------------------------------------------------

def active() -> dict | None:
    """The session running right now in this process, or on record and still fresh."""
    worker = _JOB.get("thread")
    if worker is not None and worker.is_alive() and _JOB.get("session"):
        try:
            return load(_JOB["session"])
        except (OSError, ValueError):
            return None
    record = latest()
    if record and record.get("state") == RUNNING:
        beat = _parse(record.get("heartbeat_at"))
        if beat and (_now() - beat).total_seconds() < HEARTBEAT_STALE_S and record.get("pid") == os.getpid():
            return record
    return None


def start(*, via: str, words: str = "", minutes: float | None = None, inline: bool = False,
          now: dt.datetime | None = None, runner: Callable | None = None) -> dict:
    """Begin a work session. Returns {"started", "session", "said"}; the work continues
    in a thread (or inline) and ends in a report."""
    from aletheia import policy
    now = _now(now)
    halted = policy.halted()
    if halted:
        return {"started": False, "session": None,
                "said": "I'm halted, so I won't start work until you say resume."}
    with _LOCK:
        running = active()
        if running:
            return {"started": False, "session": running, "said": already_words(running)}
        budget = max(1.0, min(float(minutes or DEFAULT_MINUTES), MAX_MINUTES)) * 60.0
        before = snapshot(now)
        record = {"version": 1, "id": f"work-{now.strftime('%Y%m%dt%H%M%S')}-{secrets.token_hex(3)}",
                  "state": RUNNING, "via": str(via)[:120], "words": " ".join(str(words or "").split())[:300],
                  "started_at": _stamp(now), "heartbeat_at": _stamp(now), "pid": os.getpid(),
                  "budget_s": budget, "deadline": _stamp(now + dt.timedelta(seconds=budget)),
                  "rehearsal": _rehearsing(), "before": before, "running": None, "receipts": [], "left": [],
                  "attempted": [], "stopped": None, "after": None, "said_at_start": "", "report": ""}
        record["said_at_start"] = opening_words(before)
        save(record)
        _journal("action", f"work:{record['id']}",
                 f"work session started by {record['via']}: {len(before['can_now'])} to take now, "
                 f"{len(before['waiting'])} waiting")
        if inline:
            run_session(record["id"], runner=runner)
        else:
            worker = threading.Thread(target=_guarded, args=(record["id"], runner), daemon=True,
                                      name="aletheia-work-session")
            _JOB.update(thread=worker, session=record["id"])
            worker.start()
    return {"started": True, "session": load(record["id"]), "said": record["said_at_start"]}


def _guarded(session_id: str, runner: Callable | None) -> None:
    try:
        run_session(session_id, runner=runner)
    except Exception as exc:  # noqa: BLE001
        _journal("alert", f"work:{session_id}", f"the work session stopped with an error ({type(exc).__name__}: {exc})")
        try:
            record = load(session_id)
            record.update(state=INTERRUPTED, stopped={"why": "error", "detail": f"{type(exc).__name__}: {exc}"[:300]})
            save(record)
        except (OSError, ValueError):
            pass


def _rehearsing() -> bool:
    from aletheia import intercom
    return intercom.rehearsing()


# ---- the loop ---------------------------------------------------------------------------------

def run_session(session_id: str, *, runner: Callable | None = None, clock: Callable[[], dt.datetime] | None = None,
                max_items: int = 200) -> dict:
    """Carry the session to its end. `runner(it, now, mode)` replaces the real one in tests."""
    from aletheia import charter_ci, local_lease, policy, work_engine as we, work_runners
    clock = clock or (lambda: _now())
    record = load(session_id)
    deadline = _parse(record["deadline"]) or (clock() + dt.timedelta(minutes=DEFAULT_MINUTES))
    attempted: set[str] = set(record.get("attempted") or [])
    try:
        charter_ci.refresh(now=clock())
    except Exception as exc:  # noqa: BLE001
        record.setdefault("notes", []).append(f"CI on charter branches could not be read ({type(exc).__name__})")
    stopped = None
    count = 0
    with local_lease.purpose(local_lease.WORK), work_runners.session_scope(record):
        while True:
            now = clock()
            if policy.halted():
                stopped = {"why": "halted"}
                break
            if now >= deadline:
                stopped = {"why": "time"}
                break
            if count >= max_items:
                stopped = {"why": "item_cap"}
                break
            items, _notes = we.gather(now)
            picked = we.pick(items, now, probe=False, persist=True)
            store = we.load_store()
            if picked["checkpoints"]:
                we._write_checkpoints(store, picked["checkpoints"], now)
                we.save_store(store)
            minds = _frontier(now)
            queue = candidates(picked, attempted=attempted, frontier=bool(minds["frontier"]["ok"]))
            if not queue:
                stopped = {"why": "nothing_left"}
                break
            it, mode, route = queue[0]
            attempted.update([it["id"]] + [a["id"] for a in it.get("aliases") or []])
            record.update(running={"id": it["id"], "title": it.get("title"), "mode": mode, "route": route,
                                   "since": _stamp(now)},
                          heartbeat_at=_stamp(now), attempted=sorted(attempted))
            save(record)
            began = time.monotonic()
            try:
                if runner is not None:
                    outcome = runner(it, now, mode)
                elif mode == "investigate":
                    outcome = work_runners.run(it, now, investigate=True)
                else:
                    store = we.load_store()
                    outcome = we.run_one(it, now, store)
                    if outcome is not None and not outcome.get("noop"):
                        we.save_store(store)
            except policy.Halted:
                stopped = {"why": "halted"}
                break
            except Exception as exc:  # noqa: BLE001 - one item never ends the session
                outcome = {"state": ws.RETRY_LATER, "kind": "failed",
                           "reason": f"it failed ({type(exc).__name__}: {str(exc)[:160]})",
                           "did": f"tried {it.get('title')} and it failed ({type(exc).__name__})"}
            count += 1
            outcome = outcome or {"noop": True}
            if mode == "investigate" and not outcome.get("noop"):
                we.record_outcome(it, outcome, now)
            record = load(session_id)
            if outcome.get("noop"):
                record.setdefault("left", []).append({"id": it["id"], "title": it.get("title"),
                                                      "next": outcome.get("next") or ""})
            else:
                receipt = {"id": it["id"], "title": it.get("title"), "source": it.get("source"), "mode": mode,
                           "route": outcome.get("route") or route,
                           "kind": outcome.get("kind") or ("started" if outcome.get("state") == ws.RUNNING else ""),
                           "state": outcome.get("state"), "did": outcome.get("did") or "",
                           "reason": outcome.get("reason") or "", "next": outcome.get("next") or "",
                           "evidence": outcome.get("evidence") or {},
                           "aliases": [a["id"] for a in it.get("aliases") or []],
                           "seconds": round(time.monotonic() - began, 1), "at": _stamp(clock())}
                record["receipts"] = (record.get("receipts") or [])[-MAX_RECEIPTS + 1:] + [receipt]
                _journal("action", f"work:{session_id}", receipt["did"] or f"{it.get('title')}: {receipt['state']}")
            record.update(running=None, heartbeat_at=_stamp(clock()), attempted=sorted(attempted))
            save(record)
    return finish(session_id, stopped or {"why": "nothing_left"}, attempted=attempted, clock=clock)


def finish(session_id: str, stopped: dict, *, attempted: set[str], clock: Callable[[], dt.datetime]) -> dict:
    now = clock()
    record = load(session_id)
    after = snapshot(now, attempted=attempted)
    # PROOF IT DID NOT STOP WHILE WORK WAS EXECUTABLE: what she could still take when it ended.
    stopped = {**stopped, "executable_left": [c["id"] for c in after["can_now"]], "at": _stamp(now)}
    if stopped["why"] == "nothing_left" and stopped["executable_left"]:
        stopped["why"] = "nothing_left_this_session"
    record.update(state=DONE, running=None, stopped=stopped, after=after, finished_at=_stamp(now),
                  heartbeat_at=_stamp(now))
    record["report"] = report_words(record)
    save(record)
    _journal("action", f"work:{session_id}", f"work session finished ({stopped['why']}): {len(record['receipts'])} "
                                              f"thing(s) done or investigated")
    try:
        from aletheia import notifications
        notifications.publish("Work session", record["report"], priority="NORMAL", source="work",
                              dedupe_key=f"work-session:{session_id}", related={"work_session": session_id})
    except Exception:  # noqa: BLE001
        pass
    return record


def resume_orphaned(now: dt.datetime | None = None) -> dict | None:
    """A session whose process died with time left is continued here (rule 7). Returns
    the new session, or None."""
    now = _now(now)
    record = latest()
    if not record or record.get("state") != RUNNING or active():
        return None
    beat = _parse(record.get("heartbeat_at"))
    alive = record.get("pid") == os.getpid() and _JOB.get("thread") is not None and _JOB["thread"].is_alive()
    if alive or (beat and (now - beat).total_seconds() < HEARTBEAT_STALE_S and record.get("pid") != os.getpid()):
        return None
    deadline = _parse(record.get("deadline"))
    record.update(state=INTERRUPTED, stopped={"why": "process_exited", "at": _stamp(now)})
    save(record)
    if not deadline or deadline <= now:
        return None
    left = (deadline - now).total_seconds() / 60.0
    return start(via=f"resumed {record['id']}", words=record.get("words") or "", minutes=left, now=now)


# ---- the words --------------------------------------------------------------------------------

_STOPWORDS_AT_END = {"a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or", "with", "which", "that",
                     "by", "from", "noted", "is", "are", "its", "his", "her", "their", "your", "my"}


def _say_title(title: str, limit: int = 9) -> str:
    """A title a room can hear: the work's own words up to the first clause, never cut
    on a dangling "of the", no commas (they collide with a spoken list), and the project
    named after the work ("fix the goTo mismatch in Barkly")."""
    import re
    text = " ".join(str(title or "").split())
    head, sep, rest = text.partition(": ")
    project = head if sep and len(head) <= 30 else ""
    body = rest if project else text
    body = re.split(r"(?<=\w)[.;:(]\s|\s\(|: ", body)[0]
    words = body.replace(",", "").replace("\u2014", " ").split()
    words = words[:limit]
    while len(words) > 2 and words[-1].lower().strip(".") in _STOPWORDS_AT_END:
        words.pop()
    said = " ".join(words).rstrip(".")
    said = said[:1].lower() + said[1:] if said[:2].isalpha() and not said[:2].isupper() else said
    return f"{said} in {project}" if project else said


def opening_words(snap: dict) -> str:
    """What he hears the moment he says it. Never "I can't work" while there is work."""
    from aletheia import speech
    can = snap.get("can_now") or []
    waiting = snap.get("waiting") or []
    left = snap.get("left_to_others") or []
    parts = []
    if snap.get("halted"):
        return "I'm halted, so I won't start work until you say resume."
    lead = ""
    if not (snap.get("frontier") or {}).get("ok"):
        lead = ("Claude and Codex are out, so I'm working with my own model. " if (snap.get("local") or {}).get("ok")
                else "Claude, Codex and my own model are all out, so I'll do what needs no model. ")
    run_now = [c for c in can if c.get("mode") == "run"]
    look = [c for c in can if c.get("mode") == "investigate"]
    if can:
        names = [_say_title(c["title"], 7) for c in (run_now + look)[:3]]
        parts.append(f"On it. {lead}I can take {speech.count_phrase(len(can), 'thing')} right now, starting with "
                     f"{speech.and_list(names)}" + ("." if len(can) <= 3 else ", and more."))
        if look:
            parts.append(f"{speech.count_phrase(len(look), 'of those', 'of those')} I'll investigate for a stronger "
                         "model rather than guess at." if len(look) > 1 else
                         "One of those I'll investigate for a stronger model rather than guess at.")
    elif left:
        parts.append(f"On it. {lead}The project builder has your charter steps "
                     f"({speech.count_phrase(len(left), 'step')}), so there's nothing for me to run here right now.")
    else:
        parts.append(f"{lead}Everything on record is waiting on something, so here is what would move it.")
    if waiting:
        yours = sum(1 for w in waiting if w.get("state") in (ws.BLOCKED_USER, ws.BLOCKED_LOGIN))
        stronger = sum(1 for w in waiting if w.get("state") in (ws.NEEDS_STRONGER_MODEL, ws.BLOCKED_MODEL))
        bits = []
        if yours:
            bits.append(f"{yours} on you")
        if stronger:
            bits.append(f"{stronger} on a stronger model")
        other = len(waiting) - yours - stronger
        if other:
            bits.append(f"{other} on other steps or the world")
        parts.append(f"{speech.count_phrase(len(waiting), 'thing')} {'is' if len(waiting) == 1 else 'are'} waiting: "
                     f"{speech.and_list(bits)}.")
    if can:
        parts.append("I'll tell you what I got done.")
    return " ".join(parts)


def already_words(record: dict) -> str:
    running = record.get("running") or {}
    done = len(record.get("receipts") or [])
    now_on = f" Right now I'm on {_say_title(running.get('title'))}." if running else ""
    return (f"I'm already working on your projects: {done} thing{'s' if done != 1 else ''} done or investigated so "
            f"far.{now_on}")


FINISHED_KINDS = {"completed", "repaired", "drafted", "verified", "started"}
QUEUED_KINDS = {"investigated"}
HANDED_KINDS = {"asked", "handed", "refused"}


def report_words(record: dict) -> str:
    """The spoken report: what I did, what I'm doing, what's waiting and on what, what I need from you."""
    from aletheia import speech
    receipts = record.get("receipts") or []
    started, ended = _parse(record.get("started_at")), _parse(record.get("finished_at") or record.get("heartbeat_at"))
    minutes = max(1, round(((ended - started).total_seconds() if started and ended else 60) / 60))
    finished = [r for r in receipts if r.get("kind") in FINISHED_KINDS]
    queued = [r for r in receipts if r.get("kind") in QUEUED_KINDS]
    handed = [r for r in receipts if r.get("kind") in HANDED_KINDS]
    other = [r for r in receipts if r not in finished + queued + handed]
    stopped = record.get("stopped") or {}
    parts = [f"I worked on your projects for {speech.count_phrase(minutes, 'minute')}."]
    if finished:
        parts.append(f"I finished {len(finished)}: " + "; ".join(_finished_words(r) for r in finished[:4]) + ".")
    if queued:
        whys = [f"{_say_title(r['title'], 7)}, because {_reason_words(r)}" for r in queued[:4]]
        parts.append(f"I investigated {len(queued)} and queued {'them' if len(queued) > 1 else 'it'} for Claude or "
                     f"Codex with the evidence: " + "; ".join(whys) + ".")
    if handed:
        parts.append(f"I handed {len(handed)} to you: " + "; ".join(_say_title(r["title"], 8) for r in handed[:4]) + ".")
    if other:
        parts.append(f"{len(other)} didn't finish: " + "; ".join(
            f"{_say_title(r['title'], 7)} ({_reason_words(r)})" for r in other[:3]) + ".")
    if not receipts:
        parts.append("There was nothing I could run or investigate without you or a stronger model.")
    after = record.get("after") or {}
    waiting = after.get("waiting") or []
    if waiting:
        yours = [w for w in waiting if w.get("state") in (ws.BLOCKED_USER, ws.BLOCKED_LOGIN)]
        stronger = [w for w in waiting if w.get("state") in (ws.NEEDS_STRONGER_MODEL, ws.BLOCKED_MODEL)]
        rest = len(waiting) - len(yours) - len(stronger)
        bits = []
        if stronger:
            bits.append(f"{len(stronger)} for a stronger model")
        if yours:
            bits.append(f"{len(yours)} on you")
        if rest:
            bits.append(f"{rest} on other steps or the world")
        parts.append("Still waiting: " + speech.and_list(bits) + ".")
        asks = [f"{_say_title(w['title'], 8)}" for w in yours if w.get("id") not in {r["id"] for r in handed}][:3]
        needs = [_say_title(r["title"], 8) for r in handed[:3]] + asks
        if needs:
            parts.append("What I need from you: " + "; ".join(needs[:4]) + ".")
    left = after.get("can_now") or []
    if stopped.get("why") == "time" and left:
        parts.append(f"I ran out of the time you gave me with {len(left)} more I could take; say work on my projects "
                     "and I'll pick them up.")
    elif stopped.get("why") == "halted":
        parts.append("I stopped because I was halted.")
    return " ".join(p for p in parts if p)


def _finished_words(receipt: dict) -> str:
    """One finished item in a clause: what it was and what came of it."""
    title = _say_title(receipt.get("title"), 8)
    kind = receipt.get("kind")
    ev = receipt.get("evidence") or {}
    if kind == "verified":
        return f"{title}: its tests pass, and the live proof is yours to authorize"
    if kind == "drafted":
        return f"{title}: a draft of {ev.get('file') or 'it'} is on a branch for you to read"
    if kind == "repaired":
        return f"{title}: a repair its tests prove is on a branch for you to review"
    if kind == "started":
        return f"{title}: started"
    return f"{title}: done"


def _reason_words(receipt: dict) -> str:
    reason = " ".join(str(receipt.get("reason") or "it needs more than I can do here").split())
    reason = reason.split("; ")[0]
    for prefix in ("multi_system: ", "dependency_change: ", "auth: ", "security: ", "authority: ", "unlocated: "):
        reason = reason.replace(prefix, "")
    return reason[:140].rstrip(".")


def spoken_status(about: str = "") -> str:
    """"What did you get done" / "how's the work session going", from the receipts."""
    record = active() or latest()
    if record is None:
        return "I haven't run a work session yet. Say work on my projects and I'll start one."
    if record.get("state") == RUNNING:
        receipts = record.get("receipts") or []
        running = record.get("running") or {}
        parts = [f"I'm working on your projects now: {len(receipts)} done or investigated so far."]
        if receipts:
            parts.append("Latest: " + str(receipts[-1].get("did") or receipts[-1].get("title")).rstrip(".") + ".")
        if running:
            parts.append(f"Right now I'm on {_say_title(running.get('title'))}.")
        return " ".join(parts)
    return record.get("report") or report_words(record)


def summary(now: dt.datetime | None = None) -> dict:
    """The compact block the Command Center and current_state show. Never raises."""
    try:
        record = active() or latest()
    except Exception as exc:  # noqa: BLE001
        return {"readable": False, "note": f"the work sessions could not be read ({type(exc).__name__})"}
    if record is None:
        return {"readable": True, "session": None, "note": "no work session has run yet"}
    receipts = record.get("receipts") or []
    after = record.get("after") or record.get("before") or {}
    return {"readable": True, "session": {
        "id": record["id"], "state": record.get("state"), "started_at": record.get("started_at"),
        "finished_at": record.get("finished_at"), "deadline": record.get("deadline"), "via": record.get("via"),
        "rehearsal": record.get("rehearsal"), "running": record.get("running"),
        "done": [{k: r.get(k) for k in ("id", "title", "kind", "state", "did", "reason", "at", "seconds")}
                 for r in receipts[-12:]],
        "waiting": [{k: w.get(k) for k in ("id", "title", "state", "reason", "next")}
                    for w in (after.get("waiting") or [])[:12]],
        "stopped": record.get("stopped"), "said": spoken_status()}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Work on his projects: a bounded work session.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start", help="start a session and wait for its report")
    s.add_argument("--minutes", type=float, default=DEFAULT_MINUTES)
    s.add_argument("--frontier-off", action="store_true", help="simulate Claude/Codex/ChatGPT unavailable")
    sub.add_parser("status", help="the latest session in words")
    sub.add_parser("preview", help="what a session would take now (reads only)")
    args = ap.parse_args(argv)
    if getattr(args, "frontier_off", False):
        from aletheia import reasoning_gateway
        os.environ[reasoning_gateway.FRONTIER_OFF_ENV] = "1"
    if args.cmd == "preview":
        print(json.dumps(snapshot(), indent=1, ensure_ascii=False, default=str))
        return 0
    if args.cmd == "status":
        print(spoken_status())
        return 0
    from aletheia import closed
    if closed.is_closed():
        print("Aletheia is closed; no work runs.")
        return 0
    began = start(via="cli", words="work on my projects", minutes=args.minutes, inline=True)
    print(began["said"])
    if began.get("session"):
        print(load(began["session"]["id"]).get("report") or "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
