"""Long missions: an objective he holds for weeks or months, carried as durable structure.

His continuity brief, Part IV.11: *"A long-duration mission concept above
bounded missions ... mission -> outcomes -> workstreams -> projects -> tasks ->
recurring activities -> monitoring -> waiting states -> decisions -> completed
results. Persists across restarts and model outages."* And IV.12: do not
predefine what a mission means. The first real one will be his: *"I do not like
the life I am currently living. Help me change it."* Nothing in this file knows
that, or anything else a mission might be about.

WHERE IT SITS. `aletheia.mission` is a BUDGET (one goal kind, hours, a work
ceiling); `plans/` and charters are committed project records; `tasks` is the
shared task store. A long mission is above all of them and duplicates none:

- it lives in PRIVATE state (`state/private/programs/<id>.json`), because what
  he wants from his life is not a committed file;
- its tasks are WORK ITEMS (`program_run.source`, a source of
  `work_engine.SOURCES`), scheduled by the one picker with the shared state
  vocabulary and requirements - there is no second scheduler;
- its waits are `aletheia.waits` records, woken on the Core's beat;
- its recurring activities are `aletheia.scheduler` schedules whose command is
  the intercom kind `mission_activity` - there is no second cron;
- each task is a composition of existing tools (`program_compose`), executed
  through `agent_session.Broker`: reads run, anything that changes the world is
  handed to Caleb (`handoffs`), money is refused.

LIFECYCLE. `propose` (his words) -> DRAFTING -> a model shapes a DRAFT
(`program_shaping`, the gateway's standard class; the draft says who wrote it)
-> he answers its questions (`answer`, a re-draft) -> `confirm`, reached only by
his words, makes it ACTIVE. `revise` drafts a revision he confirms the same way.
`decide` records HIS choice; `mark_outcome` records his judgement that an
outcome is met - a worker finishing tasks is not evidence the outcome is met.

Every writer here has a reader: `status`, `waiting_view`, the `missions` intercom
kind, the `mission.status` / `mission.waiting` session tools, the mission-control
provider and the `programs` section of current_state.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import secrets
import threading
from pathlib import Path
from typing import Any, Callable

from aletheia import stateio, waits, work_states as ws

ACTOR = "aletheia-programs"
VERSION = 1
OWNER = "programs"

DRAFTING, DRAFT, ACTIVE, PAUSED, DONE, DROPPED = "DRAFTING", "DRAFT", "ACTIVE", "PAUSED", "DONE", "DROPPED"
STATES = (DRAFTING, DRAFT, ACTIVE, PAUSED, DONE, DROPPED)
LIVE = (DRAFTING, DRAFT, ACTIVE, PAUSED)

MAX_HISTORY = 25
MAX_RESULTS = 40
MAX_ASKS = 40
HER_OWN_VIA = ("aletheia", "agent", "thea")

_LOCK = threading.RLock()


class ProgramError(ValueError):
    pass


# ---- time and store -------------------------------------------------------------------

def _now(now: dt.datetime | None = None) -> dt.datetime:
    return waits._now(now)


stamp = waits.stamp
parse = waits.parse


def programs_dir() -> Path:
    return stateio.private_dir("programs")


def _path(pid: str) -> Path:
    return programs_dir() / f"{stateio.safe_id(pid, name='mission id')}.json"


def load(pid: str) -> dict:
    return stateio.read_json(_path(pid))


def save(record: dict) -> dict:
    stateio.write_json_atomic(_path(record["id"]), record)
    return record


def all_programs() -> list[dict]:
    root = programs_dir()
    if not root.is_dir():
        return []
    out = []
    for path in sorted(root.glob("prog-*.json")):
        try:
            value = stateio.read_json(path)
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("id") == path.stem:
            out.append(value)
    return out


def update(pid: str, fn: Callable[[dict], Any]) -> tuple[dict, Any]:
    """Load, change, save under one lock. Returns (record, what fn returned)."""
    with _LOCK:
        record = load(pid)
        said = fn(record)
        save(record)
        return record, said


def _journal(kind: str, subject: str, text: str) -> None:
    try:
        from aletheia import journal
        journal.append(kind, subject, str(text)[:400], actor=ACTOR)
    except Exception:
        pass


def _history(row: dict, text: str, now: dt.datetime) -> None:
    rows = list(row.get("history") or [])
    rows.append({"at": stamp(now), "did": str(text)[:220]})
    row["history"] = rows[-MAX_HISTORY:]


def _clean(text: Any, limit: int = 1500) -> str:
    return " ".join(str(text or "").split())[:limit]


def _her_own(via: str) -> bool:
    low = str(via or "").strip().lower()
    return not low or any(low.startswith(p) for p in HER_OWN_VIA)


def item_id(pid: str, key: str) -> str:
    return f"program:{pid}/{key}"


# ---- finding one ----------------------------------------------------------------------

def find(which: str = "", *, include_finished: bool = False) -> dict | None:
    """The mission he means: by id, by words of its title/objective, or the most recent live one."""
    rows = [p for p in all_programs() if include_finished or p.get("state") in LIVE]
    if not rows:
        return None
    which = _clean(which, 200).lower()
    if which:
        exact = next((p for p in rows if p["id"] == which), None)
        if exact:
            return exact
        want = {w for w in re.findall(r"[a-z0-9]{3,}", which) if w not in {"mission", "the", "my", "big", "long"}}
        if want:
            scored = sorted(((len(want & set(re.findall(r"[a-z0-9]{3,}",
                                                         f"{p.get('title', '')} {p.get('objective', '')}".lower()))), p)
                             for p in rows), key=lambda x: (-x[0], x[1].get("updated_at") or ""))
            if scored and scored[0][0]:
                return scored[0][1]
    return sorted(rows, key=lambda p: p.get("updated_at") or "")[-1]


# ---- his words in ---------------------------------------------------------------------

def propose(words: str, *, via: str, now: dt.datetime | None = None) -> dict:
    """A new long mission from his sentence. Nothing runs until he confirms a draft."""
    now = _now(now)
    words = _clean(words)
    if len(words) < 3:
        raise ProgramError("a mission needs a sentence saying what it is for")
    pid = f"prog-{now.strftime('%Y%m%d')}-{secrets.token_hex(3)}"
    record = {
        "version": VERSION, "id": pid, "state": DRAFTING, "title": words[:80], "objective": words,
        "horizon": "", "created_at": stamp(now), "updated_at": stamp(now),
        "asks": [{"at": stamp(now), "kind": "objective", "words": words, "via": str(via)[:60]}],
        "needs_shape": True, "shape": None, "draft": None, "pending_revision": None,
        "questions": [], "outcomes": [], "workstreams": [], "tasks": [], "activities": [], "decisions": [],
        "results": [], "confirmed": None, "drafted_by": None, "history": [],
    }
    _history(record, "asked for: " + words[:160], now)
    with _LOCK:
        save(record)
    _journal("task", f"program:{pid}", f"new long mission asked for: {words[:200]}")
    return record


def _answer_into(record: dict, words: str, via: str, now: dt.datetime) -> dict | None:
    open_q = next((q for q in record.get("questions") or [] if not q.get("answer")), None)
    if open_q is None:
        return None
    open_q.update(answer=words, answered_at=stamp(now), via=str(via)[:60])
    record["asks"] = (record.get("asks") or [])[-MAX_ASKS:] + [
        {"at": stamp(now), "kind": "answer", "words": words, "via": str(via)[:60], "question": open_q["ask"]}]
    if all(q.get("answer") for q in record["questions"]):
        record["needs_shape"] = True           # every question answered: re-draft with his answers
    _history(record, f"he answered: {open_q['ask'][:80]} -> {words[:80]}", now)
    return open_q


def answer(pid: str, words: str, *, via: str, now: dt.datetime | None = None) -> dict:
    """His answer to the draft's next open question."""
    now = _now(now)
    words = _clean(words, 600)
    if _her_own(via):
        raise PermissionError("an answer to his mission's questions comes from Caleb")

    def change(record):
        if record.get("state") not in (DRAFTING, DRAFT):
            raise ProgramError("that mission is not a draft with questions")
        said = _answer_into(record, words, via, now)
        if said is None:
            raise ProgramError("there is no open question on that draft")
        record["updated_at"] = stamp(now)
        return said
    return update(pid, change)[1]


def add_words(pid: str, words: str, *, via: str, now: dt.datetime | None = None) -> dict:
    """Anything he adds: a choice for an open decision, an answer, or a revision. Returns what it became."""
    now = _now(now)
    words = _clean(words, 800)
    if not words:
        raise ProgramError("there is nothing to add")
    if _her_own(via):
        raise PermissionError("what he adds to his mission comes from Caleb")
    record = load(pid)
    if re.match(r"(?:retry|try again|redo)\b", words.lower()):
        try:
            task = retry(pid, re.sub(r"^(?:retry|try again|redo)\s*(?:on|with)?\s*", "", words.lower()), via=via, now=now)
            return {"became": "retry", "task": task["title"]}
        except ProgramError:
            pass
    for decision in record.get("decisions") or []:
        if decision.get("state") != "open":
            continue
        chosen = _match_option(decision, words)
        if chosen:
            decide(pid, decision["key"], chosen, words=words, via=via, now=now)
            return {"became": "decision", "question": decision["question"], "choice": chosen}

    def change(record):
        record["updated_at"] = stamp(now)
        if record.get("state") in (DRAFTING, DRAFT):
            said = _answer_into(record, words, via, now)
            if said is not None:
                return {"became": "answer", "question": said["ask"],
                        "remaining": sum(1 for q in record["questions"] if not q.get("answer"))}
            record["asks"] = (record.get("asks") or [])[-MAX_ASKS:] + [
                {"at": stamp(now), "kind": "more", "words": words, "via": str(via)[:60]}]
            record["needs_shape"] = True
            _history(record, "he added: " + words[:160], now)
            return {"became": "draft_input"}
        if record.get("state") in (ACTIVE, PAUSED):
            record["asks"] = (record.get("asks") or [])[-MAX_ASKS:] + [
                {"at": stamp(now), "kind": "revision", "words": words, "via": str(via)[:60]}]
            record["needs_shape"] = True
            _history(record, "he asked for a change: " + words[:160], now)
            return {"became": "revision"}
        raise ProgramError(f"that mission is {record.get('state', '').lower()}")
    return update(pid, change)[1]


def revise(pid: str, words: str, *, via: str, now: dt.datetime | None = None) -> dict:
    record = load(pid)
    if record.get("state") not in (ACTIVE, PAUSED):
        raise ProgramError("only an active mission is revised; a draft takes answers")
    return add_words(pid, words, via=via, now=now)


def _match_option(decision: dict, words: str) -> str:
    low = words.lower()
    options = decision.get("options") or []
    hits = [o for o in options if o and o.lower() in low]
    return hits[0] if len(hits) == 1 else ""


# ---- the model's draft in ---------------------------------------------------------------

def shape_words(record: dict) -> tuple[str, str, list[dict]]:
    """(objective words, revision words, answered questions) for the shaper."""
    objective = next((a["words"] for a in record.get("asks") or [] if a.get("kind") == "objective"),
                     record.get("objective") or "")
    more = [a["words"] for a in record.get("asks") or [] if a.get("kind") in ("more", "revision")]
    answered = [q for q in record.get("questions") or [] if q.get("answer")]
    return objective, " ".join(more)[-800:], answered


def apply_shape(pid: str, shaped: dict, *, now: dt.datetime | None = None) -> dict:
    """Store a model's structure: a DRAFT to confirm, or a pending revision of an active mission."""
    now = _now(now)
    structure = shaped["structure"]

    def change(record):
        record["needs_shape"] = False
        record["shape"] = None
        record["drafted_by"] = {"provider": str(shaped.get("drafted_by") or "")[:80],
                                "degraded": shaped.get("degraded"), "at": stamp(now),
                                "local": str(shaped.get("drafted_by") or "").startswith("ollama:")}
        answered = {q["ask"]: q for q in record.get("questions") or [] if q.get("answer")}
        if record.get("state") in (ACTIVE, PAUSED):
            record["pending_revision"] = structure
            _history(record, "a revision is drafted and waits for his yes", now)
            return "revision"
        record["draft"] = structure
        record["title"] = structure.get("title") or record["title"]
        record["objective"] = structure.get("objective") or record["objective"]
        record["horizon"] = structure.get("horizon") or ""
        questions = [dict(answered.get(q["ask"], q)) for q in structure.get("questions") or []]
        # An answer he already gave is never asked again, even if the model rephrased around it.
        record["questions"] = list(answered.values()) + [q for q in questions if q["ask"] not in answered]
        record["state"] = DRAFT
        record["updated_at"] = stamp(now)
        _history(record, f"drafted by {record['drafted_by']['provider']}: {len(structure.get('outcomes') or [])} "
                         f"outcomes, {len(structure.get('workstreams') or [])} workstreams, "
                         f"{len(structure.get('tasks') or [])} tasks", now)
        return "draft"
    record, became = update(pid, change)
    _journal("event", f"program:{pid}", f"mission {became} drafted by {record['drafted_by']['provider']}")
    _notify_draft(record, became)
    return record


def _notify_draft(record: dict, became: str) -> None:
    try:
        from aletheia import notifications
        open_q = [q["ask"] for q in record.get("questions") or [] if not q.get("answer")]
        who = " by my own model, because the frontier models were out" if record["drafted_by"]["local"] else ""
        body = (f"I drafted {record['title']}{who}. "
                + (f"First, {open_q[0]}" if open_q else "Say confirm my mission when it looks right."))
        notifications.publish("Your mission draft" if became == "draft" else "A change to your mission",
                              body[:400], priority="NORMAL", source="programs",
                              dedupe_key=f"program-draft:{record['id']}:{record['drafted_by']['at']}",
                              related={"program": record["id"]})
    except Exception:
        pass


# ---- his yes ------------------------------------------------------------------------------

def _task_from(row: dict, now: dt.datetime, *, activity: str | None = None) -> dict:
    return {"key": row["key"], "workstream": row.get("workstream") or "", "title": row["title"],
            "detail": row.get("detail") or "", "does": list(row.get("does") or []), "uses": list(row.get("uses") or []),
            "needs": list(row.get("needs") or []), "then_wait": row.get("then_wait"),
            "outcomes": list(row.get("outcomes") or []), "from_activity": activity, "watch": bool(row.get("watch")),
            "plan": None, "state": ws.READY, "reason": "", "next": "", "not_before": None, "cursor": 0,
            "attempts": 0, "results": [], "waits": [], "run": None, "created_at": stamp(now),
            "updated_at": stamp(now), "history": []}


def _structure_into(record: dict, structure: dict, now: dt.datetime) -> list[str]:
    """Merge a structure into the live mission. Work already started is kept; never-started work
    the structure no longer has is removed. Returns what changed."""
    changed = []
    record["title"] = structure.get("title") or record["title"]
    record["objective"] = structure.get("objective") or record["objective"]
    record["horizon"] = structure.get("horizon") or record.get("horizon") or ""
    old_outcomes = {o["key"]: o for o in record.get("outcomes") or []}
    record["outcomes"] = [{**{"status": "open", "evidence": None}, **old_outcomes.get(o["key"], {}), **o,
                           "status": old_outcomes.get(o["key"], {}).get("status", "open")}
                          for o in structure.get("outcomes") or []]
    record["workstreams"] = [dict(w) for w in structure.get("workstreams") or []]
    old_tasks = {t["key"]: t for t in record.get("tasks") or []}
    new_keys = set()
    tasks = []
    for row in structure.get("tasks") or []:
        new_keys.add(row["key"])
        if row["key"] in old_tasks:
            kept = old_tasks[row["key"]]
            if kept["state"] == ws.READY and not kept.get("cursor") and not kept.get("results"):
                fresh = _task_from(row, now)
                fresh["created_at"] = kept.get("created_at")
                tasks.append(fresh)
                if (kept.get("title"), kept.get("detail")) != (row["title"], row.get("detail") or ""):
                    changed.append(f"changed task {row['title']}")
            else:
                tasks.append(kept)
        else:
            tasks.append(_task_from(row, now))
            changed.append(f"added task {row['title']}")
    for key, kept in old_tasks.items():
        if key in new_keys:
            continue
        if kept.get("from_activity") or kept["state"] != ws.READY or kept.get("cursor") or kept.get("results"):
            tasks.append(kept)                    # started work is not silently thrown away
        else:
            changed.append(f"removed task {kept['title']}")
    record["tasks"] = tasks
    old_acts = {a["key"]: a for a in record.get("activities") or []}
    record["activities"] = [{**old_acts.get(a["key"], {}), **a,
                             "schedule_id": (old_acts.get(a["key"]) or {}).get("schedule_id"),
                             "last_digest": (old_acts.get(a["key"]) or {}).get("last_digest")}
                            for a in structure.get("activities") or []]
    old_dec = {d["key"]: d for d in record.get("decisions") or []}
    decisions = []
    for d in structure.get("decisions") or []:
        kept = old_dec.get(d["key"])
        decisions.append(kept if kept and kept.get("state") == "decided"
                         else {**d, "state": "pending", "choice": None, "wait": (kept or {}).get("wait")})
    decisions += [d for k, d in old_dec.items() if k not in {x["key"] for x in decisions} and d.get("state") == "decided"]
    record["decisions"] = decisions
    return changed


def confirm(pid: str, *, words: str, via: str, now: dt.datetime | None = None) -> dict:
    """His yes: the ONE door from a draft (or a drafted revision) to active work."""
    now = _now(now)
    if _her_own(via):
        raise PermissionError("a mission becomes active only on Caleb's own yes")

    def change(record):
        if record.get("state") == DRAFT and record.get("draft"):
            _structure_into(record, record["draft"], now)
            record["state"] = ACTIVE
            record["confirmed"] = {"at": stamp(now), "via": str(via)[:60], "words": _clean(words, 200)}
            record["draft"] = None
            _history(record, "confirmed by Caleb: " + _clean(words, 120), now)
            return "activated"
        if record.get("state") in (ACTIVE, PAUSED) and record.get("pending_revision"):
            changed = _structure_into(record, record["pending_revision"], now)
            record["pending_revision"] = None
            record.setdefault("revisions", []).append({"at": stamp(now), "via": str(via)[:60],
                                                       "words": _clean(words, 200), "changed": changed[:20]})
            _history(record, f"revision confirmed: {len(changed)} changes", now)
            return "revised"
        if record.get("state") == DRAFTING:
            raise ProgramError("that mission is still being drafted; there is nothing to confirm yet")
        raise ProgramError("that mission has nothing waiting for a yes")
    with _LOCK:
        record, became = update(pid, change)
        for activity in record.get("activities") or []:
            _schedule_activity(record, activity, now)
        for decision in record.get("decisions") or []:
            if decision.get("state") == "pending" and not decision.get("after"):
                open_decision(record, decision, now)
        record["updated_at"] = stamp(now)
        save(record)
    _journal("decision", f"program:{pid}", f"mission {became} on Caleb's yes: {record['title']}")
    return record


# ---- recurring activities through the existing scheduler ---------------------------------

def schedule_id(pid: str, key: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", f"mission-{pid}-{key}".lower())[:120]


def _schedule_activity(record: dict, activity: dict, now: dt.datetime) -> None:
    from aletheia import scheduler
    sid = schedule_id(record["id"], activity["key"])
    activity["schedule_id"] = sid
    cadence = activity.get("cadence") or {}
    command = {"kind": "mission_activity", "mission": record["id"], "activity": activity["key"]}
    try:
        from aletheia import localtime
        tz = localtime.operator_timezone()
    except Exception:
        tz = "UTC"
    try:
        existing = scheduler.load(sid)
        if not existing.get("enabled"):
            scheduler.set_enabled(sid, True)
        return
    except (ValueError, OSError):
        pass
    try:
        if cadence.get("every") == "hours":
            scheduler.create(sid, command, kind="interval", every_minutes=int(cadence.get("hours") or 24) * 60,
                             anchor=stamp(now))
        elif cadence.get("every") == "week":
            scheduler.create(sid, command, kind="weekly", timezone=tz, time=cadence.get("at") or "08:00",
                             weekdays=list(cadence.get("weekdays") or [0]))
        else:
            scheduler.create(sid, command, kind="daily", timezone=tz, time=cadence.get("at") or "08:00")
    except FileExistsError:
        pass


def activity_due(pid: str, key: str, *, now: dt.datetime | None = None) -> dict:
    """A schedule fired: this occurrence of a recurring activity becomes a task. Idempotent per hour."""
    now = _now(now)

    def change(record):
        if record.get("state") != ACTIVE:
            return {"made": None, "why": f"the mission is {str(record.get('state')).lower()}"}
        activity = next((a for a in record.get("activities") or [] if a["key"] == key), None)
        if activity is None:
            return {"made": None, "why": "that activity is no longer part of the mission"}
        tkey = f"{key}-{now.strftime('%Y%m%d%H')}"
        if any(t["key"] == tkey for t in record.get("tasks") or []):
            return {"made": None, "why": "this occurrence is already on the list"}
        task = _task_from({**activity, "key": tkey, "needs": [], "then_wait": None}, now, activity=key)
        record["tasks"].append(task)
        activity["last_run"] = stamp(now)
        # Finished occurrences of a recurring activity are history, not clutter.
        done = [t for t in record["tasks"] if t.get("from_activity") == key and t["state"] in ws.WORK_TERMINAL]
        for old in done[:-3]:
            record["tasks"].remove(old)
        record["updated_at"] = stamp(now)
        return {"made": tkey, "title": activity["title"]}
    return update(pid, change)[1]


def record_monitor(record: dict, task: dict, text: str, now: dt.datetime) -> bool:
    """A watching activity compares this run with the last; a change is an event any wait may wake on."""
    activity = next((a for a in record.get("activities") or [] if a["key"] == task.get("from_activity")), None)
    if activity is None or not activity.get("watch"):
        return False
    digest = hashlib.sha256(_clean(text, 4000).encode("utf-8")).hexdigest()[:16]
    before = activity.get("last_digest")
    activity["last_digest"] = digest
    if before and before != digest:
        try:
            waits.signal("mission.changed", f"{item_id(record['id'], activity['key'])}",
                         f"{activity['title']}: something changed since the last check",
                         attributes={"mission": record["id"], "activity": activity["key"]},
                         source=ACTOR, occurred_at=stamp(now))
        except Exception:
            pass
        record["results"] = (record.get("results") or [])[-MAX_RESULTS:] + [
            {"at": stamp(now), "task": task["key"], "text": f"{activity['title']}: changed since the last check"}]
        return True
    return False


# ---- decisions -----------------------------------------------------------------------------

def open_decision(record: dict, decision: dict, now: dt.datetime) -> dict:
    """A decision that is now his to make becomes a durable wait on him."""
    held = waits.wait_for(item_id(record["id"], f"decision-{decision['key']}"),
                          {"kind": "user_decision", "question": decision["question"],
                           "options": list(decision.get("options") or [])},
                          reason=f"a choice for Caleb: {decision['question']}", owner=OWNER,
                          context={"program": record["id"], "decision": decision["key"], "purpose": "decision"},
                          now=now)
    decision.update(state="open", wait=held["id"], opened_at=stamp(now))
    return held


def decide(pid: str, key: str, choice: str, *, words: str, via: str, now: dt.datetime | None = None) -> dict:
    now = _now(now)
    if _her_own(via):
        raise PermissionError("his decisions are recorded only from Caleb")
    record = load(pid)
    decision = next((d for d in record.get("decisions") or [] if d["key"] == key), None)
    if decision is None:
        raise ProgramError("no such decision on that mission")
    if decision.get("state") == "decided":
        return decision
    if not decision.get("wait"):
        with _LOCK:
            record = load(pid)
            decision = next(d for d in record["decisions"] if d["key"] == key)
            open_decision(record, decision, now)
            save(record)
    waits.decide(decision["wait"], choice, words=words, via=via, now=now)

    def change(record):
        d = next(x for x in record["decisions"] if x["key"] == key)
        d.update(state="decided", choice=_clean(choice, 200), words=_clean(words, 300), decided_at=stamp(now),
                 via=str(via)[:60])
        record["results"] = (record.get("results") or [])[-MAX_RESULTS:] + [
            {"at": stamp(now), "decision": key, "text": f"Caleb chose {d['choice']}: {d['question']}"}]
        record["updated_at"] = stamp(now)
        return d
    return update(pid, change)[1]


def mark_outcome(pid: str, key: str, *, met: bool, words: str, via: str, now: dt.datetime | None = None) -> dict:
    """His judgement that an outcome is met (or not yet). Tasks finishing is not that judgement."""
    now = _now(now)
    if _her_own(via):
        raise PermissionError("an outcome is met when Caleb says so")

    def change(record):
        outcome = next((o for o in record.get("outcomes") or [] if o["key"] == key), None)
        if outcome is None:
            raise ProgramError("no such outcome")
        outcome.update(status="met" if met else "open",
                       evidence={"words": _clean(words, 300), "via": str(via)[:60], "at": stamp(now)})
        if record["outcomes"] and all(o.get("status") == "met" for o in record["outcomes"]):
            record["state"] = DONE
            _history(record, "every outcome met, in Caleb's words", now)
        record["updated_at"] = stamp(now)
        return outcome
    return update(pid, change)[1]


def set_state(pid: str, state: str, *, via: str, why: str = "", now: dt.datetime | None = None) -> dict:
    """Pause, resume or drop a mission. Dropping stops its schedules and its waits."""
    now = _now(now)
    if state not in (ACTIVE, PAUSED, DROPPED):
        raise ProgramError("a mission is set active, paused or dropped")
    if _her_own(via):
        raise PermissionError("pausing or dropping his mission is his call")
    from aletheia import scheduler

    def change(record):
        record["state"] = state
        record["updated_at"] = stamp(now)
        _history(record, f"{state.lower()} by Caleb" + (f": {why}" if why else ""), now)
    record = update(pid, change)[0]
    for activity in record.get("activities") or []:
        if activity.get("schedule_id"):
            try:
                scheduler.set_enabled(activity["schedule_id"], state == ACTIVE)
            except (ValueError, OSError):
                pass
    if state == DROPPED:
        for held in waits.waiting(owner=OWNER):
            if (held.get("context") or {}).get("program") == pid:
                waits.cancel(held["id"], why="the mission was dropped", now=now)
    return record


# ---- waits: holding a task, and hearing back ----------------------------------------------

def hold(record: dict, task: dict, condition: dict, *, reason: str, purpose: str, now: dt.datetime,
         follow_up: dict | None = None, timeout: dict | None = None, extra: dict | None = None) -> dict:
    """Put one task into a durable wait. The caller saves the record."""
    context = {"program": record["id"], "task": task["key"], "purpose": purpose, **(extra or {})}
    held = waits.wait_for(item_id(record["id"], task["key"]), condition, reason=reason, owner=OWNER,
                          follow_up=follow_up, timeout=timeout, key=f"{purpose}:{task.get('cursor', 0)}:"
                          + json.dumps(extra or {}, sort_keys=True), context=context, now=now)
    task["waits"] = (task.get("waits") or [])[-10:] + [held["id"]]
    task.update(state=held["work_state"], reason=held["reason"], next=held["next"],
                not_before=waits.next_wake_at(held), updated_at=stamp(now))
    _history(task, f"waiting ({held['work_state']}): {reason[:120]}", now)
    return held


def current_wait(task: dict) -> dict | None:
    for wid in reversed(task.get("waits") or []):
        try:
            held = waits.load(wid)
        except (ValueError, OSError):
            continue
        if held.get("state") == waits.WAITING:
            return held
    return None


def on_wait(held: dict, event: str, now: dt.datetime) -> dict:
    """`waits.HANDLERS["programs"]`: something happened to one of this layer's waits."""
    ctx = held.get("context") or {}
    pid = ctx.get("program")
    if not pid:
        return {"said": "not a mission wait"}
    from aletheia import program_run
    return program_run.on_wait(pid, held, event, now)


# ---- reading it back ---------------------------------------------------------------------

def unmet_needs(record: dict, task: dict) -> list[dict]:
    """The tasks this one needs first that are not done."""
    by_key = {t["key"]: t for t in record.get("tasks") or []}
    return [by_key[k] for k in task.get("needs") or [] if k in by_key and by_key[k]["state"] != ws.DONE]


def blocked_by_needs(record: dict, task: dict) -> tuple[str, str, str] | None:
    """(state, reason, next) for a task still waiting on others; None when it may run.

    A task it needs that FAILED will never be "done", so waiting for it would be a wait with no
    wake: that is his call (retry it, or go on without it), and it says so."""
    unmet = unmet_needs(record, task)
    if not unmet:
        return None
    failed = [t for t in unmet if t["state"] == ws.FAILED]
    if failed:
        return (ws.BLOCKED_USER, "a task it needs did not work: " + "; ".join(
                    f"{t['title']} ({t.get('reason') or 'failed'})" for t in failed)[:240],
                "when Caleb says retry it, or to go on without it")
    return (ws.BLOCKED_EXTERNAL, "needs " + "; ".join(t["title"] for t in unmet)[:200] + " first",
            "when that is done")


def retry(pid: str, which: str, *, via: str, now: dt.datetime | None = None) -> dict:
    """His word to try a failed task again (or, with `without`, to drop it as a need of the others)."""
    now = _now(now)
    if _her_own(via):
        raise PermissionError("retrying or dropping failed work is Caleb's call")
    want = set(re.findall(r"[a-z0-9]{3,}", str(which).lower()))

    def change(record):
        failed = [t for t in record.get("tasks") or [] if t["state"] == ws.FAILED]
        scored = sorted(((len(want & set(re.findall(r"[a-z0-9]{3,}", t["title"].lower()))), t) for t in failed),
                        key=lambda x: -x[0])
        if not scored or (want and not scored[0][0]):
            raise ProgramError("no failed task of that mission matches")
        task = scored[0][1]
        task.update(state=ws.READY, reason="", next="", attempts=0, plan=None, cursor=0, run=None, not_before=None)
        _history(task, f"retry asked by Caleb ({via})", now)
        record["updated_at"] = stamp(now)
        return task
    return update(pid, change)[1]


def _task_view(record: dict, task: dict) -> dict:
    held = current_wait(task) if task["state"] in ws.WORK_WAITING else None
    state, reason, nxt = task["state"], task.get("reason") or "", task.get("next") or ""
    if state == ws.READY:
        blocked = blocked_by_needs(record, task)
        if blocked:
            state, reason, nxt = blocked
    view = {"key": task["key"], "title": task["title"], "workstream": task.get("workstream"),
            "state": state, "reason": reason, "next": nxt,
            "not_before": task.get("not_before"), "recurring": task.get("from_activity"),
            "tools": [s["tool"] for s in ((task.get("plan") or {}).get("steps") or [])],
            "gaps": [g["need"] for g in ((task.get("plan") or {}).get("gaps") or [])],
            "last_result": (task.get("results") or [{}])[-1].get("said") if task.get("results") else None}
    if held is not None:
        d = waits.describe(held)
        view.update(reason=d["reason"], next=d["wakes"], not_before=d["next_wake_at"], wait=d["id"],
                    follow_up=d["follow_up"], timeout=d["timeout"], since=d["since"])
    return view


def summary(record: dict, now: dt.datetime | None = None) -> dict:
    """One mission, read for a card, a tool or the room."""
    now = _now(now)
    tasks = record.get("tasks") or []
    counts: dict[str, int] = {}
    for t in tasks:
        counts[t["state"]] = counts.get(t["state"], 0) + 1
    views = [_task_view(record, t) for t in tasks]
    waiting_rows = [v for v in views if v["state"] in ws.WORK_WAITING]
    decisions = [d for d in record.get("decisions") or [] if d.get("state") == "open"]
    outcomes = []
    for o in record.get("outcomes") or []:
        linked = [t for t in tasks if o["key"] in (t.get("outcomes") or [])
                  or o["key"] in next((w.get("outcomes") or [] for w in record.get("workstreams") or []
                                       if w["key"] == t.get("workstream")), [])]
        outcomes.append({"key": o["key"], "text": o["text"], "measure": o.get("measure"), "status": o.get("status"),
                         "tasks_done": sum(1 for t in linked if t["state"] == ws.DONE), "tasks": len(linked)})
    streams = []
    for w in record.get("workstreams") or []:
        mine = [v for v in views if v["workstream"] == w["key"]]
        streams.append({"key": w["key"], "title": w["title"], "why": w.get("why"),
                        "done": sum(1 for v in mine if v["state"] == ws.DONE), "total": len(mine),
                        "tasks": [{k: v[k] for k in ("key", "title", "state", "reason", "next", "not_before")}
                                  for v in mine]})
    wakes = sorted(v["not_before"] for v in waiting_rows if v.get("not_before"))
    open_q = [q["ask"] for q in record.get("questions") or [] if not q.get("answer")]
    return {
        "id": record["id"], "title": record.get("title"), "objective": record.get("objective"),
        "state": record.get("state"), "horizon": record.get("horizon"), "updated_at": record.get("updated_at"),
        "drafted_by": record.get("drafted_by"), "confirmed": record.get("confirmed"),
        "counts": counts, "done": counts.get(ws.DONE, 0), "total": len(tasks),
        "outcomes": outcomes, "workstreams": streams,
        "executing": [v for v in views if v["state"] == ws.RUNNING],
        "ready": [v for v in views if v["state"] == ws.READY],
        "waiting": waiting_rows,
        "decisions": [{"key": d["key"], "question": d["question"], "options": d.get("options") or [],
                       "wait": d.get("wait")} for d in decisions],
        "questions": open_q if record.get("state") in (DRAFTING, DRAFT) else [],
        "needs_confirm": record.get("state") == DRAFT or bool(record.get("pending_revision")),
        "drafting": bool(record.get("needs_shape")),
        "drafting_blocked": ((record.get("shape") or {}).get("blocked") or (record.get("shape") or {}).get("failed"))
        if record.get("needs_shape") else None,
        "drafting_until": (record.get("shape") or {}).get("until") if record.get("needs_shape") else None,
        "next_wake_at": wakes[0] if wakes else None,
        "results": (record.get("results") or [])[-8:],
        "activities": [{"key": a["key"], "title": a["title"], "cadence": a.get("cadence"), "watch": a.get("watch"),
                        "last_run": a.get("last_run"), "schedule": a.get("schedule_id")}
                       for a in record.get("activities") or []],
        "draft": ({k: record["draft"].get(k) for k in ("outcomes", "workstreams", "tasks", "activities", "decisions")}
                  if record.get("draft") else None),
    }


def status(which: str = "", *, now: dt.datetime | None = None) -> dict:
    """Every live mission (or the one he named), summarised. Says which of full/empty/unreadable."""
    try:
        rows = all_programs()
    except Exception as exc:  # noqa: BLE001
        return {"readable": False, "missions": [], "note": f"the missions could not be read ({type(exc).__name__})"}
    live = [p for p in rows if p.get("state") in LIVE]
    if which:
        found = find(which, include_finished=True)
        live = [found] if found else []
    out = {"readable": True, "total": len(rows), "missions": [summary(p, now) for p in live]}
    if not rows:
        out["note"] = ("READ AND EMPTY: the long-mission store exists and holds no missions. "
                       "Say none has been started; never say there is no such thing.")
    elif not live:
        out["note"] = f"no live mission matches{' ' + repr(which) if which else ''}; {len(rows)} on record"
    return out


def waiting_view(which: str = "", *, now: dt.datetime | None = None) -> dict:
    """Everything the missions are waiting on, why, and when each may move."""
    said = status(which, now=now)
    rows = []
    for m in said.get("missions") or []:
        for w in m["waiting"]:
            rows.append({"mission": m["title"], "task": w["title"], "state": w["state"], "why": w["reason"],
                         "wakes": w["next"], "when": w.get("not_before"),
                         "follow_up": w.get("follow_up"), "timeout": w.get("timeout")})
        for d in m["decisions"]:
            rows.append({"mission": m["title"], "task": d["question"], "state": ws.BLOCKED_USER,
                         "why": "a choice only Caleb makes", "wakes": "when Caleb decides",
                         "when": None, "options": d["options"]})
        if m.get("drafting_blocked"):
            rows.append({"mission": m["title"], "task": "writing the draft", "state": ws.BLOCKED_MODEL,
                         "why": m["drafting_blocked"], "wakes": "when a model can think again",
                         "when": m.get("drafting_until")})
        if m["needs_confirm"]:
            rows.append({"mission": m["title"], "task": "the draft", "state": ws.BLOCKED_USER,
                         "why": "drafted; nothing runs until Caleb confirms it",
                         "wakes": "when Caleb says confirm my mission", "when": None,
                         "questions": m["questions"]})
    rows.sort(key=lambda r: (r["state"] != ws.BLOCKED_USER, r.get("when") or "9999"))
    out = {"readable": said.get("readable", False), "waiting": rows, "missions": len(said.get("missions") or [])}
    if said.get("note"):
        out["note"] = said["note"]
    return out


def _when_words(stamp_text: str | None) -> str:
    when = parse(stamp_text)
    if when is None:
        return ""
    try:
        from aletheia import reasoner
        return reasoner.spoken_time(when)
    except Exception:
        return when.strftime("%b %d %H:%M UTC")


def spoken_status(which: str = "", *, now: dt.datetime | None = None) -> str:
    from aletheia import speech
    said = status(which, now=now)
    if not said.get("readable"):
        return "I couldn't read your missions just now."
    missions = said["missions"]
    if not missions:
        return "You haven't started a long mission yet." if not said.get("total") else "No mission is live right now."
    parts = []
    for m in missions[:2]:
        if m["state"] == DRAFTING:
            parts.append(f"I'm still drafting {m['title']}.")
            continue
        if m["state"] == DRAFT:
            q = m["questions"]
            parts.append(f"{m['title']} is a draft waiting for you"
                         + (f"; first, {q[0].rstrip('.?!')}?" if q else "; say confirm my mission to start it."))
            continue
        bits = [f"{m['title']}: {m['done']} of {speech.count_phrase(m['total'], 'task')} done"]
        if m["executing"]:
            bits.append(f"working on {m['executing'][0]['title']}")
        if m["waiting"]:
            bits.append(f"{len(m['waiting'])} waiting")
        if m["decisions"]:
            bits.append(f"{speech.count_phrase(len(m['decisions']), 'decision')} for you")
        parts.append(", ".join(bits) + ".")
    return " ".join(parts)


def spoken_waiting(which: str = "", *, now: dt.datetime | None = None) -> str:
    view = waiting_view(which, now=now)
    if not view.get("readable"):
        return "I couldn't read your missions just now."
    rows = view["waiting"]
    if not rows:
        return "Nothing in your missions is waiting right now." if view["missions"] else "You haven't started a long mission yet."
    lines = []
    for r in rows[:4]:
        when = _when_words(r.get("when"))
        nudge = (r.get("follow_up") or {}).get("next_at")
        if when and nudge and nudge == r.get("when"):
            tail = f"; I'll check in about a follow-up {when}"
        elif when and r["state"] != ws.BLOCKED_USER:
            tail = f", until {when}"
        else:
            tail = ""
        lines.append(f"{r['task']}: {r['why']}{tail}")
    more = f" And {len(rows) - 4} more." if len(rows) > 4 else ""
    return f"{len(rows)} waiting. " + "; ".join(lines) + "." + more


def section(now: dt.datetime | None = None) -> dict:
    """The compact block current_state carries. Never raises."""
    try:
        said = status(now=now)
    except Exception as exc:  # noqa: BLE001
        return {"readable": False, "note": f"the missions could not be read ({type(exc).__name__})"}
    missions = said.get("missions") or []
    return {"readable": said.get("readable", False), "live": len(missions),
            "missions": [{"id": m["id"], "title": m["title"], "state": m["state"], "done": m["done"],
                          "total": m["total"], "waiting": len(m["waiting"]), "decisions": len(m["decisions"]),
                          "needs_confirm": m["needs_confirm"], "next_wake_at": m["next_wake_at"]} for m in missions],
            "note": said.get("note", "")}
