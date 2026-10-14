"""Long-mission work, run by the one work engine: its source, its runner, its executor.

A long mission (`aletheia.programs`) does not schedule itself. Its drafting and
its tasks are WORK ITEMS in `work_engine.SOURCES["programs"]`, so the one picker
decides what can run now with the shared vocabulary (READY, RUNNING,
BLOCKED_MODEL, BLOCKED_USER, BLOCKED_EXTERNAL, RETRY_LATER, DONE, FAILED) and
the shared requirement checks; the engine calls `run_item` for what it picks
(`work_engine.SOURCE_RUNNERS`). One blocked task never blocks another (rule 2);
every unfinished one says why and what wakes it (rule 3); everything is on disk
before and after each step, so a process exit costs at most the step in flight,
and a task whose runner vanished is resumed from its cursor (rule 7).

THE EXECUTOR does one task as a composition of existing tools
(`program_compose`), one step at a time, through the SAME gate an agent session
uses (`agent_session.Broker`):

- RUN (it only reads): executed now, its result kept on the task.
- HANDOFF (it changes something, reaches someone, needs his approval): filed as
  a handoff (`handoffs.file`, one pending approval) and the task WAITS on it
  (`waits` condition "handoff"). The Core's beat runs it after his yes.
- REFUSED: money, authority, a tool this machine cannot run - the task fails
  with the rule named, or asks him how to proceed.

A step whose arguments the task's words do not give asks a ROUTINE thinker, and
waits for a model when none can think, or asks Caleb when the words are simply
not there. A need no tool meets is a capability gap (`work_gaps.record`), never
a dead end. After its steps, a task may WAIT for the world (`then_wait`: a
reply, a date, an event, his decision) with a follow-up policy and a timeout
meaning; `on_wait` hears what happened and moves the task on.

Execution is off the beat's thread by default (one job at a time); tests and
the scenario run it inline.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import threading
import uuid
from typing import Any, Callable

from aletheia import programs as pg, stateio, waits, work_states as ws

ACTOR = pg.ACTOR
#: "thread" off the beat (production), or "inline" (tests, the scenario).
EXECUTION = os.environ.get("ALETHEIA_PROGRAM_EXECUTION", "thread")
PROCESS_ID = uuid.uuid4().hex[:12]
STALE_S = 45 * 60
MAX_ATTEMPTS = 3
TOOL_TIMEOUT_S = 600.0
RETRY_AFTER = dt.timedelta(minutes=30)
MODEL_RETRY = dt.timedelta(minutes=15)

_JOB: dict[str, Any] = {"thread": None}
#: Test seams: a catalog and a thinker to use instead of the real ones.
CATALOG: dict | None = None
THINK: Callable | None = None


def catalog() -> dict:
    if CATALOG is not None:
        return CATALOG
    from aletheia import tools
    return tools.catalog()


# ---- the source -------------------------------------------------------------------------

def _stale(run: dict | None, now: dt.datetime) -> bool:
    if not isinstance(run, dict):
        return True
    at = pg.parse(run.get("at"))
    if run.get("owner") != PROCESS_ID:
        return True
    return at is None or (now - at).total_seconds() > STALE_S


_unmet_needs = pg.unmet_needs


def source(now: dt.datetime) -> list[dict]:
    """Every long mission's unfinished work, in the shared vocabulary. Reads only."""
    from aletheia import work_engine as we
    out: list[dict] = []
    for record in pg.all_programs():
        state, pid, title = record.get("state"), record["id"], record.get("title") or record["id"]
        if state not in pg.LIVE:
            continue
        if record.get("needs_shape"):
            shape = record.get("shape") or {}
            until = shape.get("until")
            if shape.get("running") and not _stale(shape.get("run"), now):
                row_state, reason, nxt = ws.RUNNING, "", "store the draft"
            elif shape.get("blocked") and pg.parse(until) and pg.parse(until) > now:
                row_state, reason, nxt = ws.BLOCKED_MODEL, shape["blocked"], "when a model can think again"
            elif shape.get("failed") and pg.parse(until) and pg.parse(until) > now:
                row_state, reason, nxt = ws.RETRY_LATER, shape["failed"], "draft it again"
            else:
                partial = shape.get("partial") or {}
                pieces = len(partial.get("providers") or [])
                row_state, reason = ws.READY, ""
                nxt = (f"write the next piece of the draft ({pieces} done)" if pieces
                       else "draft the mission structure")
            out.append(we.item(f"program:{pid}#shape", "programs",
                               f"{'Revise' if state in (pg.ACTIVE, pg.PAUSED) else 'Draft'} the mission: {title}",
                               row_state, requires=["reasoning"], reason=reason, next=nxt,
                               not_before=until if row_state != ws.READY else None, priority=2,
                               native_state=(f"shape:{len(record.get('asks') or [])}:{row_state}:"
                                             f"{len(((shape.get('partial') or {}).get('providers')) or [])}"),
                               owner=pg.OWNER,
                               kind="program_shape", payload={"program": pid}))
        if state == pg.DRAFT and not record.get("needs_shape"):
            open_q = [q["ask"] for q in record.get("questions") or [] if not q.get("answer")]
            out.append(we.item(f"program:{pid}#confirm", "programs", f"Confirm the mission draft: {title}",
                               ws.BLOCKED_USER, requires=["user_decision"],
                               reason=("drafted; " + (f"{len(open_q)} question(s) for Caleb first" if open_q
                                                      else "waiting for Caleb's yes")),
                               next="when Caleb answers and says confirm my mission", priority=2,
                               native_state="draft", owner=pg.OWNER, kind="program_confirm", payload={"program": pid}))
        if record.get("pending_revision"):
            out.append(we.item(f"program:{pid}#revision", "programs", f"Confirm the change to: {title}",
                               ws.BLOCKED_USER, requires=["user_decision"], reason="a revision is drafted",
                               next="when Caleb says confirm my mission", priority=2, native_state="revision",
                               owner=pg.OWNER, kind="program_confirm", payload={"program": pid}))
        if state not in (pg.ACTIVE, pg.PAUSED):
            continue
        for decision in record.get("decisions") or []:
            if decision.get("state") == "open":
                out.append(we.item(pg.item_id(pid, f"decision-{decision['key']}"), "programs",
                                   f"{title}: {decision['question']}", ws.BLOCKED_USER, requires=["user_decision"],
                                   reason="a choice only Caleb makes", next="when Caleb decides", priority=2,
                                   native_state="decision:open", owner=pg.OWNER, kind="program_decision",
                                   payload={"program": pid, "decision": decision["key"]}))
        for task in record.get("tasks") or []:
            t_state = task["state"]
            reason, nxt, not_before = task.get("reason") or "", task.get("next") or "", task.get("not_before")
            if state == pg.PAUSED and t_state not in ws.WORK_TERMINAL:
                t_state, reason, nxt = ws.BLOCKED_USER, "the mission is paused", "when Caleb resumes the mission"
            elif t_state == ws.RUNNING and _stale(task.get("run"), now):
                t_state, reason, nxt = ws.READY, "", "resume from its last finished step"
            elif t_state == ws.READY:
                blocked = pg.blocked_by_needs(record, task)
                if blocked:
                    t_state, reason, nxt = blocked
                else:
                    nxt = nxt or "run its next step"
            elif t_state in ws.WORK_WAITING:
                held = pg.current_wait(task)
                if held is not None:
                    reason, nxt, not_before = held["reason"], held["next"], waits.next_wake_at(held)
            out.append(we.item(pg.item_id(pid, task["key"]), "programs", f"{title}: {task['title']}", t_state,
                               requires=((task.get("plan") or {}).get("requires") or []),
                               reason=reason or ("waiting" if t_state in ws.WORK_WAITING else ""),
                               next=nxt or ("look again" if t_state in ws.WORK_WAITING else ""),
                               not_before=not_before, priority=3,
                               native_state=f"{task['state']}:{task.get('cursor', 0)}:{task.get('attempts', 0)}",
                               owner=pg.OWNER, kind="program_task", updated=str(task.get("updated_at") or ""),
                               payload={"program": pid, "task": task["key"]}))
    return out


# ---- the runner the engine calls ----------------------------------------------------------

def _busy() -> bool:
    worker = _JOB.get("thread")
    return worker is not None and worker.is_alive()


def _start(body: Callable[[], Any]) -> None:
    if EXECUTION == "inline":
        body()
        return

    def guarded():
        try:
            body()
        except Exception as exc:  # noqa: BLE001
            pg._journal("alert", "programs", f"a piece of mission work failed ({type(exc).__name__}: {exc})")
    worker = threading.Thread(target=guarded, name="aletheia-program-work", daemon=True)
    _JOB["thread"] = worker
    worker.start()


def run_item(it: dict, now: dt.datetime) -> dict:
    """`work_engine.SOURCE_RUNNERS["programs"]`. Starts the work; the store holds the truth."""
    payload = it.get("payload") or {}
    pid = payload.get("program")
    if not pid:
        return {"state": ws.FAILED, "reason": "not a mission item", "next": ""}
    if EXECUTION != "inline" and _busy():
        return {"state": ws.READY, "reason": "", "next": "after the mission work already running"}
    kind = it.get("kind")
    if kind == "program_shape":
        _claim_shape(pid, now)
        _start(lambda: do_shape(pid, now=now if EXECUTION == "inline" else None))
        return {"state": ws.RUNNING, "reason": "", "next": "store the draft"}
    if kind == "program_task":
        key = payload.get("task")
        if not _claim_task(pid, key, now):
            return {"state": ws.READY, "reason": "", "next": "nothing to claim"}
        _start(lambda: run_task(pid, key, now=now if EXECUTION == "inline" else None))
        return {"state": ws.RUNNING, "reason": "", "next": "run its next step"}
    return {"state": ws.BLOCKED_USER, "reason": "it waits on Caleb", "next": it.get("next") or ""}


def _claim_shape(pid: str, now: dt.datetime) -> None:
    def change(record):
        record["shape"] = {"running": True, "run": {"owner": PROCESS_ID, "at": pg.stamp(now)},
                           "partial": (record.get("shape") or {}).get("partial")}
    pg.update(pid, change)


def _claim_task(pid: str, key: str, now: dt.datetime) -> bool:
    def change(record):
        task = next((t for t in record.get("tasks") or [] if t["key"] == key), None)
        if task is None or task["state"] in ws.WORK_TERMINAL or record.get("state") != pg.ACTIVE:
            return False
        task.update(state=ws.RUNNING, run={"owner": PROCESS_ID, "at": pg.stamp(now)}, reason="",
                    next="record what came of it", updated_at=pg.stamp(now))
        return True
    return bool(pg.update(pid, change)[1])


# ---- drafting ---------------------------------------------------------------------------------

def do_shape(pid: str, *, think: Callable | None = None, now: dt.datetime | None = None) -> dict:
    from aletheia import program_shaping, reasoner
    now = pg._now(now)
    record = pg.load(pid)
    objective, revision, answered = pg.shape_words(record)
    current = None
    if record.get("state") in (pg.ACTIVE, pg.PAUSED):
        current = {k: record.get(k) for k in ("title", "objective", "outcomes", "workstreams", "tasks",
                                              "activities", "decisions")}
        current["tasks"] = [{k: t.get(k) for k in ("key", "workstream", "title", "detail", "state")}
                            for t in current["tasks"] or [] if not t.get("from_activity")]
    elif record.get("draft"):
        current = record["draft"]
    think = think or THINK
    try:
        staged = think is None and not _frontier_available()
        if staged:
            shaped = _shape_one_piece(pid, record, objective, revision, answered, current, now)
            if shaped is None:
                return {"state": "partial"}
        else:
            shaped = program_shaping.shape(objective, catalog=catalog(), answers=answered, current=current,
                                           revision=revision, think=think, now=now, staged=False)
    except reasoner.ReasonerUnavailable as exc:
        def blocked(r):
            r["shape"] = {"blocked": f"no model could draft it ({str(exc)[:400]})",
                          "until": pg.stamp(now + MODEL_RETRY), "partial": (r.get("shape") or {}).get("partial")}
        pg.update(pid, blocked)
        pg._journal("event", f"program:{pid}", f"drafting waits for a model: {str(exc)[:160]}")
        return {"state": ws.BLOCKED_MODEL, "why": str(exc)}
    except Exception as exc:  # noqa: BLE001 - an unusable draft is retried, never believed
        def failed(r):
            r["shape"] = {"failed": f"the draft came back unusable ({type(exc).__name__}: {str(exc)[:200]})",
                          "until": pg.stamp(now + RETRY_AFTER), "partial": (r.get("shape") or {}).get("partial")}
        pg.update(pid, failed)
        return {"state": ws.RETRY_LATER, "why": str(exc)}
    pg.apply_shape(pid, shaped, now=now)
    return {"state": "drafted", "by": shaped.get("drafted_by")}


def _frontier_available() -> bool:
    try:
        from aletheia import reasoning_gateway
        return reasoning_gateway.frontier_available()
    except Exception:  # noqa: BLE001
        return False


def _shape_one_piece(pid: str, record: dict, objective: str, revision: str, answered: list[dict],
                     current: dict | None, now: dt.datetime) -> dict | None:
    """With no frontier model: ONE small call per run (the skeleton, or the next workstream's plan), each
    finished piece kept on disk. Returns the whole shaped draft when the last piece lands, else None."""
    from aletheia import program_shaping
    tools = catalog()
    generation = len(record.get("asks") or [])
    partial = (record.get("shape") or {}).get("partial") or {}
    if partial.get("generation") != generation:
        partial = {"generation": generation, "skeleton": None, "parts": {}, "providers": []}
    context = program_shaping.staged_context(objective, catalog=tools, answers=answered, current=current,
                                             revision=revision, now=now)
    if partial["skeleton"] is None:
        got = program_shaping.skeleton(objective, context)
        partial["skeleton"] = got["value"]
    else:
        stream = next((w for w in partial["skeleton"]["workstreams"] if w["key"] not in partial["parts"]), None)
        got = None
        if stream is not None:
            got = program_shaping.stream_plan(objective, partial["skeleton"], stream, context, catalog=tools)
            partial["parts"][stream["key"]] = got["value"]
    if got is not None:
        partial["providers"].append({"provider": got["provider"], "degraded": got["degraded"], "at": pg.stamp(now)})
    done = all(w["key"] in partial["parts"] for w in partial["skeleton"]["workstreams"])
    if not done:
        def keep(r):
            r["shape"] = {"partial": partial}
            pg._history(r, f"draft piece {len(partial['providers'])} of {len(partial['skeleton']['workstreams']) + 1} "
                           f"written by {partial['providers'][-1]['provider']}", now)
        pg.update(pid, keep)
        return None
    last = partial["providers"][-1] if partial["providers"] else {"provider": "", "degraded": None}
    return {"structure": program_shaping.merge(partial["skeleton"], partial["parts"], catalog=tools),
            "drafted_by": last["provider"], "degraded": last["degraded"], "staged": True}


# ---- executing one task -------------------------------------------------------------------------

def _commit(pid: str, task: dict, now: dt.datetime, extra: Callable[[dict], Any] | None = None) -> dict:
    """Write one task back into the FRESH record (other writers may have moved meanwhile)."""
    def change(record):
        for i, row in enumerate(record.get("tasks") or []):
            if row["key"] == task["key"]:
                record["tasks"][i] = task
                break
        else:
            record.setdefault("tasks", []).append(task)
        if extra is not None:
            extra(record)
        _open_ready_decisions(record, now)
        record["updated_at"] = pg.stamp(now)
    return pg.update(pid, change)[0]


def _open_ready_decisions(record: dict, now: dt.datetime) -> None:
    done = {t["key"] for t in record.get("tasks") or [] if t["state"] == ws.DONE}
    for decision in record.get("decisions") or []:
        if decision.get("state") == "pending" and decision.get("after") and set(decision["after"]) <= done:
            pg.open_decision(record, decision, now)


SAID_CHARS = 2400


def _result(task: dict, step: int | None, tool: str, outcome: str, said: str, now: dt.datetime, **more) -> None:
    rows = list(task.get("results") or [])
    # What a look found is kept whole enough to write from: a comparison of five places cut at 600
    # characters left the document after it with one place and a half (2026-10-11).
    keep = SAID_CHARS if outcome == "ok" else 600
    rows.append({"at": pg.stamp(now), "step": step, "tool": tool, "outcome": outcome, "said": str(said)[:keep], **more})
    task["results"] = rows[-12:]


#: The one capability a mission step may carry out under a standing grant
#: instead of a handoff: his sign-ups ruling (2026-10-09, "signing me up for
#: stuff"). `event_signup` spends the grant itself, after every one of its
#: refusals, so a page that costs money or wants an account never gets near it.
SIGN_UP_CAPABILITY = "event.register"


def _signed_up_under_grant(tool, args: dict, task: dict, step: int, now: dt.datetime) -> bool:
    """True when the sign-up was settled here (done, or left for a stated
    reason); False hands the step to Caleb as before - the switch is off, the
    grant is missing or spent, or the page broke."""
    if tool.capability != SIGN_UP_CAPABILITY:
        return False
    try:
        from aletheia import agent_session, event_signup
        if not event_signup.status()["on"]:
            return False
        outcome, result = agent_session.execute(tool, args, timeout_s=TOOL_TIMEOUT_S,
                                                quote=f"sign-up for {task.get('title', '')}"[:200])
    except Exception:  # noqa: BLE001 - anything unclear is his
        return False
    state = str((result or {}).get("state") or "") if isinstance(result, dict) else ""
    if outcome != "ok" or state in ("", "needs_grant", "failed"):
        return False
    _result(task, step, tool.name, "ok", str((result or {}).get("said") or state), now, sign_up=state)
    return True


def _said(result: Any) -> str:
    """What a step said, kept whole enough for the steps after it. The shared receipt line is cut
    at 300 characters and a plain answer came back JSON-quoted, so a look's "Dated:" lines - at the
    end of what it said - never reached the hold after it, nor its figures the document (2026-10-11)."""
    from aletheia import handoffs
    if isinstance(result, str):
        return result.strip()[:SAID_CHARS]
    if isinstance(result, dict):
        for key in ("text", "said", "error", "note"):
            if result.get(key):
                text = str(result[key]).strip()
                return (" ".join(text.split()) if key == "error" else text)[:SAID_CHARS]
    return handoffs._said_result(result)


def his_answers(record: dict) -> str:
    """What he has told this mission - its questions with his answers, and what he added since -
    as text a step can write from. "Save Caleb's answers" and "write the move criteria from
    Caleb's answers" had nothing to read: the answers live on the record, not in a file."""
    rows = [f"Q: {q.get('ask')}\nA: {q.get('answer')}" for q in record.get("questions") or []
            if q.get("answer")]
    said = {str(q.get("answer")) for q in record.get("questions") or []}
    rows += [str(a["words"]) for a in record.get("asks") or []
             if a.get("kind") in ("objective", "more", "revision") and a.get("words") and a["words"] not in said]
    return "\n\n".join(rows)


def _answers_file(record: dict) -> str | None:
    """His answers kept as a file of hers, so a step that writes FROM them has a source. Returns
    the workspace-relative path, or None when there is nothing to keep or no workspace."""
    text = his_answers(record)
    if not text:
        return None
    from aletheia import workspace
    rel = f"missions/{record['id']}-his-answers.md"
    body = f"# What Caleb has told {record.get('title') or 'this mission'}\n\n{text}\n"
    try:
        target = workspace.resolve(rel)
        if not target.exists() or target.read_text(encoding="utf-8") != body:
            workspace.write(rel, body, why="his answers, for the mission steps that write from them")
    except Exception:  # noqa: BLE001 - no workspace: the step goes on without the file
        return None
    return rel


def _stale_look(task: dict, plan: dict, tools: dict, i: int) -> int | None:
    """The look before step `i` whose answer was read the old way - before `research.REVISION` -
    when it has not already looked again on this revision; None otherwise. A look that ran on the
    current reading is never run twice."""
    look = next((n for n in range(i - 1, -1, -1) if (tools.get(plan["steps"][n].get("tool")) is not None
                 and tools[plan["steps"][n]["tool"]].read_only
                 and tools[plan["steps"][n]["tool"]].open_world)), None)
    from aletheia import research
    if look is None or int(task.get("relooked") or 0) >= research.REVISION:
        return None
    ran = [r for r in task.get("results") or [] if r.get("step") == look and r.get("outcome") == "ok"]
    if ran and int(ran[-1].get("revision") or 0) >= research.REVISION:
        return None
    return look


def _stale_needs(record: dict, task: dict, tools: dict) -> list[tuple[dict, int]]:
    """The tasks this one needs whose look read its pages the old way - (task, its look's step) -
    when each has not already looked again on this revision.

    A write-up's sources are mostly the looks of the tasks it NEEDS, not its own: the ranked
    comparison has no look of its own, so the check above found nothing stale, and it wrote from
    the comparison's 300-character pages again and refused again (his PC, 2026-10-11)."""
    by_key = {t.get("key"): t for t in record.get("tasks") or []}
    out = []
    for key in task.get("needs") or []:
        need = by_key.get(key)
        if need is None or need.get("state") != ws.DONE or not (need.get("plan") or {}).get("steps"):
            continue
        steps = need["plan"]["steps"]
        look = _stale_look(need, need["plan"], tools, len(steps))
        if look is not None:
            out.append((need, look))
    return out


#: What a writing step is handed to write from, revised: 2 is the found file beside his answers.
WRITES_FROM = 2


def _found_file(record: dict, task: dict) -> str | None:
    """What this task's earlier steps and the tasks it needs have read, kept as a file of hers so
    a step that writes has it to write from. Workspace-relative path, or None when nothing was read."""
    found = _found(record, task, answers=False)
    if not found:
        return None
    from aletheia import workspace
    rel = f"missions/{record['id']}-{task.get('key')}-found.md"
    body = (f"# What was found for: {task.get('title') or task.get('key')}\n\n"
            + "\n\n".join(found) + "\n")
    try:
        target = workspace.resolve(rel)
        if not target.exists() or target.read_text(encoding="utf-8") != body:
            workspace.write(rel, body, why="what the steps before it read, for the step that writes from it")
    except Exception:  # noqa: BLE001 - no workspace: the step goes on without the file
        return None
    return rel


def _found(record: dict, task: dict, *, answers: bool = True) -> list[str]:
    """What this task's earlier steps and the tasks it needs have read, plus his answers."""
    keys = set(task.get("needs") or [])
    rows = [r for t in record.get("tasks") or []
            if t.get("key") in keys or (t.get("from_activity") and t.get("key") != task.get("key"))
            for r in t.get("results") or []]
    rows.sort(key=lambda r: str(r.get("at") or ""))
    rows += list(task.get("results") or [])
    gone = pg.taken_back_titles()
    found = [pg.without_taken_back(str(r.get("said") or ""), gone) for r in rows
             if r.get("outcome") == "ok" and r.get("said")]
    found = [f for f in found if f.strip()][-5:]
    # A recurring watch reads what the finished work it is about found, ahead of its own last five:
    # otherwise the shortlist it watches is the oldest line and the first to fall off (2026-10-11).
    watched = [said for t in pg.what_it_watches(record, task) if t.get("key") not in keys
               for said in [next((str(r.get("said")) for r in reversed(t.get("results") or [])
                                  if r.get("outcome") == "ok" and r.get("said")), "")] if said]
    told = his_answers(record) if answers else ""
    return ([f"What Caleb has told this mission:\n{told[:2000]}"] if told else []) + watched + found


#: The arguments that say WHEN, and what a date or a time looks like written down.
WHEN_ARGS = ("start", "when", "date", "time", "at")
DATED = re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}|\d{1,2}(?::\d{2})?\s?(?:am|pm)|\d{1,2}:\d{2}|"
                   r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
                   r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
                   r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|tonight|tomorrow)\b", re.I)
NOTHING_DATED_RETRY = dt.timedelta(days=1)
#: The arguments that say WHERE on the web, which only something found can fill.
WHERE_ARGS = ("url", "link")


#: "Evenings after 5:30 pm and weekends", as he says it: both words, and the time if he gave one.
EVENINGS = re.compile(r"\bevenings?\b", re.I)
WEEKENDS = re.compile(r"\bweekends?\b", re.I)
AFTER_TIME = re.compile(r"\bafter\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?", re.I)
DEFAULT_EVENING = dt.time(17, 0)


def his_hours(record: dict) -> dt.time | None:
    """When his evenings start, when he has told this mission he is free evenings and weekends;
    None when he has said no such thing. Read from his own words on the record, never assumed."""
    told = " ".join([his_answers(record), str(record.get("objective") or "")])
    if not (EVENINGS.search(told) and WEEKENDS.search(told)):
        return None
    for m in AFTER_TIME.finditer(told):
        hour, minute, half = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
        if half.startswith("p") and hour < 12:
            hour += 12
        if 15 <= hour <= 21 and minute < 60:
            return dt.time(hour, minute)
    return DEFAULT_EVENING


def _finds_free_time(tool) -> bool:
    props = (tool.input_schema or {}).get("properties") or {}
    return "part" in props and "when" in props and tool.read_only


def _readable_window(when) -> bool:
    from aletheia import calendar_reasoning
    try:
        calendar_reasoning.window(str(when or ""))
        return bool(str(when or "").strip())
    except Exception:  # noqa: BLE001
        return False


#: A look that came back saying it found nothing to answer with: "I can't give you a comparison
#: from these sources", "none of them has data on". Done on that is done on nothing.
NOTHING_FOUND = re.compile(
    r"\bI (?:can['\u2019]?t|cannot|couldn['\u2019]?t|could not|was unable to) (?:give|answer|tell|find|say|compare|provide)"
    r"[^.]{0,120}\b(?:from (?:these|the|those) (?:sources|pages)|sources|pages)\b"
    # "I can't give you a sourced comparison from what I was handed" (2026-10-10, his PC): the
    # same empty answer in other words, so the look counted as done and fed nothing onward.
    r"|\bI (?:can['\u2019]?t|cannot|couldn['\u2019]?t|could not)\b[^.]{0,80}\b(?:sources?|sourced|pages|extracts|handed|supplied)\b"
    # "The supplied sources can't answer this" (2026-10-11): the sources as the subject.
    r"|\b(?:sources?|pages|extracts)\b[^.]{0,40}\b(?:can['\u2019]?t|cannot|don['\u2019]?t|do not)\b[^.]{0,20}\b(?:answer|say|tell)\b"
    r"|\bnone (?:of them |of these |of the pages )?(?:has|have|had|contains?|mentions?) (?:any )?"
    r"(?:data|information|details|anything)\b"
    r"|\bI won'?t invent\b|\bno readable sources\b", re.I)


def _looks_again_tomorrow(record: dict, task: dict) -> bool:
    """A recurring sweep is never given up on while it is the newest of its kind: a search that is
    broken today is this week's sweep lost for good otherwise (2026-10-10: the weekly event sweep
    went FAILED on three bad searches in one evening). Once a newer occurrence exists, that one
    carries the work and this one may fail."""
    activity = task.get("from_activity")
    if not activity:
        return False
    return not any(t is not task and t.get("from_activity") == activity and str(t.get("key")) > str(task.get("key"))
                   for t in record.get("tasks") or [])


def _writes_holds(tool) -> bool:
    props = (tool.input_schema or {}).get("properties") or {}
    return (tool.capability == "calendar.hold" and not tool.read_only and bool(tool.writes)
            and "title" in props and "start" in props)


def _dated_hold(record: dict, task: dict, tool, args: dict, now: dt.datetime) -> dict:
    """{"start", "title"} for the soonest dated, timed line the steps before it read that would make
    a right hold (in the future, inside his hours, named by what was found); {} when there is none.
    Read deterministically (`dated_text`), never guessed: a line with no time is not a hold."""
    from aletheia import dated_text, localtime
    best = None
    for text in _found(record, task, answers=False):
        for occ in dated_text.occurrences(text, now=now, tz=localtime.operator_tz()):
            if not occ["timed"]:
                continue
            # Written as the planner writes a start: his local time, which a hold reads in his zone.
            start = dt.datetime.fromisoformat(occ["start"]).strftime("%Y-%m-%dT%H:%M")
            # Named by what was found, never by what the task called itself (2026-10-11: a hold was
            # titled with the task's own name at a free-time slot).
            filled = {"start": start, "title": occ["title"]}
            if _wrong_hold(record, task, tool, dict(args, **filled), now):
                continue
            if best is None or occ["start"] < best["start"]:
                best = filled
    return best or {}


#: Words in a hold's title that say nothing about what it is for.
_HOLD_FILLER = re.compile(r"\b(?:hold|holds|tentative|pencil(?:led)?|calendar|event|events|for|the|a|an|at|on|in|"
                          r"to|of|and|with|am|pm|today|tomorrow|tonight|monday|tuesday|wednesday|thursday|"
                          r"friday|saturday|sunday|\d+(?::\d+)?)\b", re.I)


#: Words that say what KIND of work something is, or when he is free, rather than what it names:
#: a hold's title and the line it was found on are matched on what is left.
_TASK_FILLER = re.compile(r"\b(?:find|finds|finding|search|searches|searching|sweep|sweeps|look|looks|looking|"
                          r"check|checks|new|newly|listed|list|lists|listing|listings|upcoming|nearby|near|local|"
                          r"area|free|fitting|fit|fits|ones|one|any|some|register|registers|sign|signs|ups?|book|"
                          r"weekly|daily|monthly|every|week|weeks|month|weekends?|evenings?|mornings?|afternoons?|"
                          r"nights?|time|times|slots?|windows?|shortlist|shortlisted|good|best|more|other|this|"
                          r"that|these|those|his|her|him|them|they|their|what|which|where|when|from|into|"
                          r"about|around|within|after|before|next|soon|soonest|first|each|all|add|adds|put|puts|get|set|use|"
                          r"make|makes|onto|into|over|out|few|see|try|keep|tentative|pencil|pencils)\b", re.I)


def _content_words(text: str, *, shortest: int = 3) -> set[str]:
    text = _TASK_FILLER.sub(" ", _HOLD_FILLER.sub(" ", str(text or "").lower()))
    return set(re.findall(r"[a-z]{%d,}" % shortest, text))


def _found_event(record: dict, task: dict, title: str, day: dt.date, now: dt.datetime) -> dict | None:
    """The dated line, among what the steps before it read, that a hold titled `title` on `day` is
    for: on that day, and sharing a word of its title. None when nothing read says so."""
    from aletheia import dated_text, localtime
    named = _content_words(title, shortest=4)
    for text in _found(record, task, answers=False):
        for occ in dated_text.occurrences(text, now=now, tz=localtime.operator_tz()):
            if occ["date"] != day.isoformat():
                continue
            if named & _content_words(occ["title"] + " " + occ["line"], shortest=4):
                return occ
    return None


#: The reading of pages from which a look that names a baseline is measured against it (research
#: REVISION 5): a finished look read before then is done once more.
MEASURED_FROM_REVISION = 5


#: Raised whenever what makes a hold right gets stricter, so holds made under the looser rules are
#: checked again once (1: time, hours and title; 2: a found event on that day, not its own name).
HOLD_RULES = 2


def _wrong_hold(record: dict, task: dict, tool, args: dict, now: dt.datetime, *,
                made_at: dt.datetime | None = None) -> str:
    """Why a hold this mission step would make (or made, at `made_at`) is wrong; "" when it is not."""
    if not _writes_holds(tool) or not str(args.get("start") or "").strip():
        return ""
    from aletheia import localtime
    try:
        start = dt.datetime.fromisoformat(str(args["start"]).replace("Z", "+00:00"))
    except ValueError:
        return f"its time ({str(args['start'])[:40]}) could not be read"
    if start.tzinfo is None:
        start = start.replace(tzinfo=localtime.operator_tz())
    if start <= (made_at or now):
        return "that time had already passed"
    hours = his_hours(record)
    local = start.astimezone(localtime.operator_tz())
    if hours and local.weekday() < 5 and local.time() < hours:
        return f"it is in his working day, and he said evenings from {hours:%H:%M} and weekends"
    words = {w for w in re.findall(r"[a-z]{4,}", _HOLD_FILLER.sub(" ", str(args.get("title") or "").lower()))}
    # What its own earlier steps found counts too: the weekly sweep's look is its own first step.
    seen = " ".join(str(r.get("said") or "") for t in record.get("tasks") or [] for r in t.get("results") or []
                    if r.get("outcome") == "ok" and (t.get("key") != task.get("key") or r.get("tool") != tool.name)
                    ).lower()
    if words and not any(w in seen for w in words):
        return "its title names nothing the steps before it found"
    own = " ".join([str(task.get("title") or "")] + [str(n) for n in task.get("does") or []]).lower()
    if not words or words <= {w for w in re.findall(r"[a-z]{4,}", _HOLD_FILLER.sub(" ", own))}:
        # Its title is the task's own name (2026-10-11: "Pencilled in Find free ... events for the
        # shortlisted ... tomorrow at 6:15 pm" - a free slot, and no event at all).
        return "its title is the task's own name, not something found"
    if _found_event(record, task, str(args.get("title") or ""), local.date(), made_at or now) is None:
        # A hold is for something found: a dated line the steps before it read names it on that day.
        # Anything free he could go to in his hours counts - he asked for his calendar filled - so
        # what it is about is not narrowed (2026-10-11).
        return "nothing the steps before it read names it on that day"
    if made_at is None:
        clash = _clashes_on_calendar(args, start)
        if clash:
            return clash
    return ""


def _clashes_on_calendar(args: dict, start: dt.datetime) -> str:
    """Why a hold about to be made at `start` would be refused for what is already on his calendar;
    "" when nothing is in the way. Asked BEFORE the hold, so a sweep picks the next thing it found
    rather than failing three times on the one it already pencilled in (2026-10-13: the weekly sweep
    found new evenings, chose the trail walk again, and was refused "it overlaps" three times)."""
    from aletheia import calendar_reasoning
    try:
        if str(args.get("end") or "").strip():
            end = dt.datetime.fromisoformat(str(args["end"]).replace("Z", "+00:00"))
            end = end if end.tzinfo else end.replace(tzinfo=start.tzinfo)
        else:
            end = start + dt.timedelta(minutes=int(args.get("minutes") or 60))
        own = calendar_reasoning.hold_id(" ".join(str(args.get("title") or "").split()), start.isoformat(),
                                         str(args.get("thread") or ""))
        clashes = calendar_reasoning.conflicts_for(start.isoformat(), end.isoformat(),
                                                   location=args.get("location") or None, ignore={own})
    except Exception:  # noqa: BLE001 - an unreadable calendar is the hold's own refusal to make
        return ""
    if not clashes:
        return ""
    return f"it clashes with {clashes[0].get('title') or 'something'} already on his calendar"


#: The waits a step's CLASSIFICATION put a task in: handed to him, refused, or asked an argument.
#: A rule change can make any of them wrong; a wait for a reply, a date or a model it cannot.
RECLASSIFIABLE = ("handoff", "refused", "args")


def _would_go_further(task: dict, plan: dict, tools: dict, was: str) -> bool:
    """Would the rules as they stand now carry this parked step past where `was` stopped it?

    A step handed to him goes on only when it would now RUN (or sign up under his ruling); a
    step refused or missing an argument goes on when it is neither any more - at worst it is
    handed to him properly, which is still further than a refusal or a wrong question."""
    from aletheia import agent_session, program_compose as compose
    i = int(task.get("cursor") or 0)
    if i >= len(plan["steps"]):
        return False
    tool = tools.get(plan["steps"][i]["tool"])
    if tool is None:
        return False
    args, missing = compose.fill_args(tool, task, plan["steps"][i].get("args"))
    args.update(compose.default_args(tool, task, missing))
    if any(not str(args.get(m) or "").strip() for m in missing):
        return False
    verdict = agent_session.Broker(tools, audience="all").check(agent_session.ToolRequest(tool.name, args)).verdict
    if was == "source":
        return verdict == agent_session.RUN
    if was == "path":
        # It ran and failed on where it wrote; it goes on only with a path it would not fail on.
        return verdict == agent_session.RUN and args.get("path") != (plan["steps"][i].get("args") or {}).get("path")
    if verdict == agent_session.RUN:
        return True
    if verdict == agent_session.HANDOFF and tool.capability == SIGN_UP_CAPABILITY:
        from aletheia import event_signup
        if event_signup.status()["on"]:
            return True
    return was != "handoff" and verdict != agent_session.REFUSED


def _requeue_one(record: dict, task: dict, tools: dict, now: dt.datetime) -> dict | None:
    from aletheia import program_compose as compose, research
    plan = task.get("plan")
    if not plan or not plan.get("steps"):
        return None
    if task.get("state") == ws.DONE:
        return _recheck_done(record, task, tools, now)
    taken = _recheck_holds_made(record, task, tools, now)
    if taken:
        return taken
    if task.get("state") == ws.RETRY_LATER and str(task.get("next") or "").startswith("look again"):
        # Parked until tomorrow on what an old reading found: the weekly sweep kept the found text
        # from before looks read dates, and waited a day each time to find the same (his PC,
        # 2026-10-11). Once per revision of how pages are read, it looks again now.
        look = _stale_look(task, plan, tools, int(task.get("cursor") or 0) + 1)
        if look is not None:
            _commit(record["id"], dict(task, cursor=look, relooked=research.REVISION, state=ws.READY, not_before=None,
                                       attempts=0, run=None, reason="", next="look again on the current reading"), now)
            return {"program": record["id"], "task": task["key"], "was": "stale_look"}
    held = pg.current_wait(task) if task["state"] in ws.WORK_WAITING else None
    purpose = ((held or {}).get("context") or {}).get("purpose")
    refused = task["state"] == ws.FAILED and (
        " was refused: " in str(task.get("reason") or "")
        # A need the money door refused, re-read on the door as it stands now: the fresh plan
        # below is refused again if it still spends (2026-10-10: "adjusted pay equivalent").
        or "only Caleb spends money" in str(task.get("reason") or ""))
    # A write that failed three times on a path outside her workspace (2026-10-10) was a bad
    # argument, not a bad task: the path is dropped and filled now, so it may try again.
    bad_path = task["state"] == ws.FAILED and "OutsideWorkspace" in str(task.get("reason") or "")
    # A document that failed for want of anything to write from has his answers to read now; once.
    # And once more each time what a writing step is handed grows: the found file (2026-10-11).
    no_source = (task["state"] == ws.FAILED and "ComposeError" in str(task.get("reason") or "")
                 and (not task.get("source_retried") or int(task.get("written_from") or 0) < WRITES_FROM))
    if (purpose == "then" and held is not None and _waits_only_on_his_ok(task)
            and int(task.get("cursor") or 0) >= len(plan["steps"])):
        # Parked on his okay of her own work before that stopped being a gate: done, and his
        # okay is an open choice instead.
        waits.cancel(held["id"], why="his okay is a choice now, not a gate", now=now)
        _finish(record["id"], dict(task), now, extra=_confirm_later(task))
        return {"program": record["id"], "task": task["key"], "was": "then"}
    if (task["state"] == ws.FAILED and held is None and not task.get("recurring_released")
            and re.search(r" failed \d+ times: ", str(task.get("reason") or ""))
            and _looks_again_tomorrow(record, task)):
        # A recurring sweep that failed before it looked again instead: it is still the newest of its
        # kind, so this week's sweep goes on (2026-10-10: the weekly event sweep).
        return _release(record, task, dict(task, plan=plan, mark="recurring_released"), None, "recurring", now)
    if (task["state"] in (ws.FAILED, ws.RETRY_LATER) and not refused and not bad_path and not no_source
            and held is None and not task.get("recomposed")):
        # A LOOK composed under rules since changed: "search for free newcomer events" went to the
        # free-time tool and failed three times (2026-10-10) after the composer learned better. Once,
        # when the composer would no longer choose the tool it is stuck on, the task is planned again;
        # steps that already ran must come out the same. A doing step that failed is left alone.
        fresh = compose.compose(task, tools)
        old_tools = [s["tool"] for s in plan["steps"]]
        new_tools = [s["tool"] for s in fresh["steps"]]
        i = int(task.get("cursor") or 0)
        stuck = tools.get(old_tools[i]) if i < len(old_tools) else None
        # And a look is planned again only as a look: the comparison's research step came back as
        # the website tool and waited for his yes on a read (2026-10-11).
        now_at = tools.get(new_tools[i]) if i < len(new_tools) else None
        if (stuck is not None and stuck.read_only and stuck.name not in new_tools
                and now_at is not None and now_at.read_only
                and new_tools and new_tools[:i] == old_tools[:i]
                and not any(g["outcome"] == "refuse_policy" for g in fresh["gaps"])):
            return _release(record, task, dict(task, plan=fresh, mark="recomposed"), None, "recomposed", now)
    if (task["state"] == ws.FAILED and held is None
            and int(task.get("research_revision") or 0) < research.REVISION
            and not task.get("from_activity")
            and str(task.get("reason") or "").startswith("research failed")
            and int(task.get("cursor") or 0) < len(plan["steps"])
            and plan["steps"][int(task.get("cursor") or 0)].get("tool") == "research"):
        # A look that failed for want of pages that answer it: once, on the pages she reads now
        # (2026-10-11: the city comparison failed before it read each city's own figures). After the
        # re-plan above, which comes first; a task planned again once may still try again here.
        # Once per revision of how a look reads its pages: each pages a failed look is retried on.
        return _release(record, task, dict(task, plan=plan, mark="sources_retried",
                                           also={"research_revision": research.REVISION}), None, "sources", now)
    if bad_path:
        purpose = "path"
    elif no_source:
        purpose = "source"
    if purpose not in RECLASSIFIABLE and not refused and not bad_path and not no_source:
        return None
    i = int(task.get("cursor") or 0)
    if bad_path or no_source:
        # A bad path is a bad argument to the right step: the plan stays exactly as it was.
        candidate = dict(task, plan=plan)
    else:
        fresh = compose.compose(task, tools)
        if any(g["outcome"] == "refuse_policy" for g in fresh["gaps"]):
            return None
        fresh_gaps = fresh["gaps"]
        old_tools = [s["tool"] for s in plan["steps"]]
        new_tools = [s["tool"] for s in fresh["steps"]]
        if new_tools[:i] != old_tools[:i]:
            # The steps that already ran would be chosen differently now. They stay as they ran;
            # only the step it is parked on is chosen again, from what that step was for.
            fresh = _rechoose_step(task, plan, tools, i)
            if fresh is None:
                return None
            new_tools = [s["tool"] for s in fresh["steps"]]
        # The plan it keeps carries the gaps as they read NOW: the stored one still held the refusal
        # that failed it, so a money need re-read as no money was refused again on the very next
        # run (2026-10-10: the comparison stayed FAILED after the fix that cleared its words).
        kept = plan if new_tools != old_tools or not refused else dict(plan, gaps=fresh_gaps)
        candidate = dict(task, plan=fresh if new_tools != old_tools else kept)
    asked_when = set(((held or {}).get("context") or {}).get("missing") or []) & set(WHEN_ARGS)
    if purpose == "args" and asked_when and (task.get("needs") or int(task.get("cursor") or 0) > 0):
        # Asked him WHEN about something earlier tasks were to find, before "nothing dated yet"
        # was a look-again (2026-10-10, still asking after the fifth fix): once more on the
        # current rules, which either fill it from what was found or look again tomorrow. A step
        # whose own task looked first is the same: the weekly sweep has no needs (2026-10-11).
        return _release(record, task, dict(candidate, mark="dated_retried"), held, purpose, now)
    asked_where = set(((held or {}).get("context") or {}).get("missing") or []) & set(WHERE_ARGS)
    if (purpose == "args" and asked_where and not task.get("where_retried")
            and (task.get("needs") or int(task.get("cursor") or 0) > 0)):
        # Asked him for an ADDRESS for something earlier tasks were to find, before "nothing with an
        # address yet" was a look-again (his PC, 2026-10-11: still "what should I use for url?" after
        # the fix that stopped asking). Once, on the current rules: filled from what was found, or a
        # look again later.
        return _release(record, task, dict(candidate, mark="where_retried"), held, purpose, now)
    if purpose == "args" and not task.get("args_retried") and not _would_go_further(
            candidate, candidate["plan"], tools, purpose) and _found(record, task):
        # Asked him for arguments the steps before it have since found (the events a search
        # read, his answers): once, it tries again with them in front of the model.
        candidate = dict(candidate, mark="args_retried")
        return _release(record, task, candidate, held, purpose, now)
    if refused and "only Caleb spends money" in str(task.get("reason") or "") and not bad_path and not no_source:
        # Refused as spending before any step ran, and the money door no longer says so: the task
        # simply runs, and its steps meet their own gates (2026-10-10: "stop at payment" stayed
        # FAILED because its sign-up step had no address yet, which is no reason to stay refused).
        return _release(record, task, candidate, held, purpose, now)
    if not _would_go_further(candidate, candidate["plan"], tools, purpose or "refused"):
        return None
    if no_source:
        candidate = dict(candidate, mark="source_retried", also={"written_from": WRITES_FROM})
    return _release(record, task, candidate, held, purpose, now)


#: How recently a finished task must have run for steps the current rules give it to be added.
STEPS_ADDED_WITHIN = dt.timedelta(days=14)


def _steps_it_never_had(task: dict, steps: list[dict], tools: dict, now: dt.datetime) -> list[dict]:
    """Steps the composer gives this finished task now, after the ones it ran: the weekly sweep was
    composed as a look alone before a task that also holds and signs up kept those steps, so it
    found "605 Connections" and said it had no way to hold it (2026-10-11). Once per task, only for
    one that ran lately, and only when the steps it ran come out the same."""
    from aletheia import program_compose as compose
    if task.get("steps_added") or not steps:
        return []
    last = max((str(r.get("at") or "") for r in task.get("results") or []), default="")
    if not last or waits.parse(last) < now - STEPS_ADDED_WITHIN:
        return []
    fresh = compose.compose(task, tools)
    if any(g["outcome"] == "refuse_policy" for g in fresh["gaps"]):
        return []
    old = [s.get("tool") for s in steps]
    new = [s["tool"] for s in fresh["steps"]]
    if len(new) <= len(old) or new[:len(old)] != old:
        return []
    return fresh["steps"][len(old):]


def _add_steps(record: dict, task: dict, steps: list[dict], added: list[dict], now: dt.datetime) -> dict | None:
    key, at = task["key"], len(steps)
    names = ", ".join(s["tool"] for s in added)

    def change(r):
        t = next((x for x in r.get("tasks") or [] if x["key"] == key), None)
        if t is None or t.get("state") != ws.DONE:
            return None
        t["plan"] = dict(t.get("plan") or {}, steps=list(steps) + [dict(s, args={}) for s in added])
        t.update(state=ws.READY, cursor=at, reason="", next="run its next step", run=None, not_before=None,
                 attempts=0, steps_added=True, updated_at=pg.stamp(now))
        pg._history(t, f"opened again: it has steps it never ran ({names})", now)
        r["updated_at"] = pg.stamp(now)
        return t
    if pg.update(record["id"], change)[1] is None:
        return None
    pg._journal("event", pg.item_id(record["id"], key),
                f"{record.get('title') or record['id']}: {task['title']} goes on to {names}"[:240])
    return {"program": record["id"], "task": key, "was": "done", "why": f"steps it never ran: {names}"}


def _last_empty_recheck(task: dict) -> str:
    """When this task was last opened again for an empty look ("" for never)."""
    mark = task.get("empty_rechecked")
    if isinstance(mark, str):
        return mark
    if not mark:
        return ""
    return max((str(h.get("at") or "") for h in task.get("history") or []
                if str(h.get("did") or "").startswith("opened again: its look found nothing")), default="")


_LINKED = re.compile(r"([^;/]*?)\s*\(link (https?://[^\s)]+)\)")


def _held_event_link(record: dict, task: dict) -> str:
    """The link a found dated line carries for an event this mission has pencilled in and not taken
    back; "" when none is plainly that event. The title words decide, as `_found_event` does."""
    found = " ; ".join(_found(record, task, answers=False))
    linked = [(line, url) for line, url in _LINKED.findall(found)]
    if not linked:
        return ""
    gone = pg.taken_back_titles()
    held = [str(r.get("said") or "") for t in record.get("tasks") or [] for r in t.get("results") or []
            if r.get("outcome") == "ok" and str(r.get("said") or "").startswith("Pencilled in")]
    held = [pg.without_taken_back(h, gone) for h in held]
    held_words = [_content_words(h, shortest=4) for h in held if h.strip()]
    for line, url in linked:
        words = _content_words(line.split(",")[0], shortest=4)
        if len(words) >= 2 and any(len(words & h) >= max(2, (len(words) + 1) // 2) for h in held_words):
            return url
    return ""


def _take_back(args: dict, why: str) -> bool:
    """Release her own tentative hold that a step made with `args`; False when none is left."""
    from aletheia import calendar as _calendar, calendar_reasoning, localtime
    try:
        start = dt.datetime.fromisoformat(str(args["start"]).replace("Z", "+00:00"))
        start = start if start.tzinfo else start.replace(tzinfo=localtime.operator_tz())
        event_id = calendar_reasoning.hold_id(" ".join(str(args.get("title") or "").split()),
                                              start.isoformat(), str(args.get("thread") or ""))
        held = _calendar.load(event_id)
        if held and held.get("status") != "CANCELLED":
            calendar_reasoning.release_hold(event_id, why=f"taken back: {why}")
            return True
    except (ValueError, OSError, KeyError):
        pass  # no such hold left to take back
    return False


def _recheck_holds_made(record: dict, task: dict, tools: dict, now: dt.datetime) -> dict | None:
    """A task still under way that made a hold the current rules call wrong takes it back, once
    per tightening of the rules, and goes on from where it is (2026-10-11: a task whose later
    step was waiting kept a hold titled with its own name at a free slot)."""
    if int(task.get("holds_rechecked") or 0) >= HOLD_RULES:
        return None
    steps = (task.get("plan") or {}).get("steps") or []
    taken: list[str] = []
    made_any = False
    for i, step in enumerate(steps):
        tool = tools.get(step.get("tool"))
        if tool is None or not _writes_holds(tool):
            continue
        made = next((r.get("at") for r in task.get("results") or []
                     if r.get("step") == i and r.get("outcome") == "ok"), None)
        if made is None:
            continue
        made_any = True
        why = _wrong_hold(record, task, tool, step.get("args") or {}, now, made_at=waits.parse(made))
        if why and _take_back(step.get("args") or {}, why):
            taken.append(why)
    if not made_any:
        return None
    key = task["key"]

    def change(r):
        t = next((x for x in r.get("tasks") or [] if x["key"] == key), None)
        if t is None:
            return None
        t["holds_rechecked"] = HOLD_RULES
        for why in taken:
            pg._history(t, f"took back a calendar hold: {why}", now)
        return t
    pg.update(record["id"], change)
    if not taken:
        return None
    pg._journal("event", pg.item_id(record["id"], key),
                f"{record.get('title') or record['id']}: took back a calendar hold from {task['title']}: "
                f"{taken[0]}"[:240])
    return {"program": record["id"], "task": key, "was": "hold", "why": taken[0]}


def _recheck_done(record: dict, task: dict, tools: dict, now: dt.datetime) -> dict | None:
    """A finished task whose step did the wrong thing under rules since made stricter is opened
    again at that step: a hold that was wrong when it was made is taken back first (her own
    tentative hold, released with the reason), and a free-time read that looked at his working
    day reads again. Once per task each: what it does the second time stands."""
    from aletheia import research
    steps = (task.get("plan") or {}).get("steps") or []
    added = _steps_it_never_had(task, steps, tools, now)
    if added:
        return _add_steps(record, task, steps, added, now)
    hours = his_hours(record)
    for i, step in enumerate(steps):
        tool = tools.get(step.get("tool"))
        args = step.get("args") or {}
        if tool is None:
            continue
        why, mark = "", ""
        if _writes_holds(tool) and int(task.get("holds_rechecked") or 0) < HOLD_RULES:
            made = next((r.get("at") for r in task.get("results") or []
                         if r.get("step") == i and r.get("outcome") == "ok"), None)
            if made is None:
                continue
            why = _wrong_hold(record, task, tool, args, now, made_at=waits.parse(made))
            mark = "holds_rechecked"
            if why:
                _take_back(args, why)
        elif hours and _finds_free_time(tool) and not str(args.get("part") or "").strip() \
                and not task.get("hours_rechecked"):
            why, mark = "it counted his working day as free", "hours_rechecked"
        elif tool.read_only and tool.open_world and any(
                r.get("step") == i and r.get("outcome") == "ok" and NOTHING_FOUND.search(str(r.get("said") or ""))
                and str(r.get("at") or "") > _last_empty_recheck(task)
                for r in (task.get("results") or [])[-1:]):
            why, mark = "its look found nothing to answer with", "empty_rechecked"
        elif tool.read_only and tool.open_world and not task.get("baseline_rechecked") and any(
                r.get("outcome") == "ok" and int(r.get("revision") or 0) < MEASURED_FROM_REVISION
                # The last time THIS step ran: the write after it is the task's last result, and
                # looking only at that kept the comparison from ever being redone (2026-10-14).
                for r in [x for x in task.get("results") or [] if x.get("step") == i][-1:]) and (
                research.baseline_for(str(args.get("question") or ""))
                # Its own question may name only the places ("Tampa, Austin, Nashville..."); the task
                # it serves names the comparison, and that is what the redo is asked (2026-10-14).
                or research.baseline_for(" ".join([str(task.get("title") or "")]
                                                  + [str(d) for d in task.get("does") or []]))):
            # A comparison looked at before looks measured it against where he lives: the move
            # comparison was written against the pages' New York index and stood as done after the
            # fix that measures it against Sioux Falls (his PC, 2026-10-14). Once.
            why, mark = "it was measured against another place, not where he lives", "baseline_rechecked"
        if not why:
            continue
        key = task["key"]

        def change(r, key=key, i=i, mark=mark, why=why):
            t = next((x for x in r.get("tasks") or [] if x["key"] == key), None)
            if t is None or t.get("state") != ws.DONE:
                return None
            t["plan"]["steps"][i]["args"] = {}
            t.update(state=ws.READY, cursor=i, reason="", next="run its next step", run=None, not_before=None,
                     attempts=0, updated_at=pg.stamp(now))
            # An empty look is opened again whenever it came back empty SINCE the last time: the
            # second answer said the same nothing in other words and stood as done (2026-10-10).
            t[mark] = pg.stamp(now) if mark == "empty_rechecked" else HOLD_RULES if mark == "holds_rechecked" else True
            pg._history(t, f"opened again: {why}", now)
            # What was done FROM it is done again after it, where nothing of that reached anybody
            # (2026-10-10: the job search was retargeted on an empty comparison).
            again, grew = {key}, True
            while grew:
                grew = False
                for d in r.get("tasks") or []:
                    if d["key"] in again or d.get("state") != ws.DONE or not set(d.get("needs") or []) & again:
                        continue
                    steps_d = (d.get("plan") or {}).get("steps") or []
                    if any(getattr(tools.get(x.get("tool")), "consequence", "outward") == "outward" for x in steps_d):
                        continue
                    d.update(state=ws.READY, cursor=0, reason="", next="run its next step", run=None,
                             not_before=None, attempts=0, updated_at=pg.stamp(now))
                    pg._history(d, f"opened again: {t['title'][:80]} is being done again", now)
                    again.add(d["key"])
                    grew = True
            r["updated_at"] = pg.stamp(now)
            return t
        pg.update(record["id"], change)
        pg._journal("event", pg.item_id(record["id"], key),
                    f"{record.get('title') or record['id']}: {task['title']} is done again: {why}"[:240])
        return {"program": record["id"], "task": key, "was": "done", "why": why}
    return None


def _rechoose_step(task: dict, plan: dict, tools: dict, i: int) -> dict | None:
    """The plan with only step i chosen again; None when nothing better can be said."""
    from aletheia import program_compose as compose
    if i >= len(plan["steps"]):
        return None
    need = str(plan["steps"][i].get("for") or task.get("title") or "")
    again = compose.compose({"title": task.get("title"), "detail": need, "does": [need], "uses": []}, tools)
    if len(again["steps"]) != 1 or any(g["outcome"] == "refuse_policy" for g in again["gaps"]):
        return None
    step = dict(plan["steps"][i], tool=again["steps"][0]["tool"], args={})
    return dict(plan, steps=plan["steps"][:i] + [step] + plan["steps"][i + 1:])


def _release(record: dict, task: dict, candidate: dict, held: dict | None, purpose: str | None,
             now: dt.datetime) -> dict | None:
    from aletheia import handoffs
    handoff_id = ((held or {}).get("condition") or {}).get("handoff_id")
    if handoff_id and not handoffs.withdraw(handoff_id, "not needed any more: the step runs on its own now"):
        return None  # he already answered it: his answer moves the task, not this
    if held is not None:
        waits.cancel(held["id"], why="the rules that parked it have changed", now=now)
    key, new_plan, mark, also = task["key"], candidate["plan"], candidate.get("mark"), candidate.get("also") or {}

    def change(r, key=key, new_plan=new_plan, mark=mark, also=also):
        t = next((x for x in r.get("tasks") or [] if x["key"] == key), None)
        if t is None:
            return None
        t.update(plan=new_plan, state=ws.READY, reason="", next="run its next step", run=None,
                 not_before=None, attempts=0, updated_at=pg.stamp(now))
        if mark:
            t[mark] = True
        t.update(also)
        pg._history(t, "trying again: the rules that parked it have changed", now)
        r["updated_at"] = pg.stamp(now)
        return t
    pg.update(record["id"], change)
    pg._journal("event", pg.item_id(record["id"], key),
                f"{record.get('title') or record['id']}: {task['title']} tries again on the current rules")
    return {"program": record["id"], "task": key, "was": purpose or "refused"}


def requeue_reclassified(*, now: dt.datetime | None = None) -> list[dict]:
    """A mission task parked under rules that have since changed tries again.

    A task's plan and its wait are stored, so a fix to how steps are chosen or gated
    reached only tasks composed after it: seven of his mission's tasks went on waiting
    for a yes to a web search, failing a workspace note as "spending", and asking which
    calendar a check should write to, on the new code (2026-10-09). Each beat this re-composes a task
    whose wait came from a step's classification and lets it run when the current rules
    would carry it further. Unknown means leave it: it never releases a step he already
    approved, a step that still needs him, or a task whose finished steps would change."""
    now = pg._now(now)
    tools = catalog()
    released: list[dict] = []
    for record in pg.all_programs():
        if record.get("state") != pg.ACTIVE:
            continue
        for task in record.get("tasks") or []:
            try:
                row = _requeue_one(record, task, tools, now)
            except Exception as exc:  # noqa: BLE001 - one odd task must not stop the others' re-check
                pg._journal("alert", pg.item_id(record["id"], task.get("key", "?")),
                            f"could not re-check {task.get('title', '')[:80]}: {type(exc).__name__}: {exc}"[:240])
                continue
            if row:
                released.append(row)
    return released


def run_task(pid: str, key: str, *, now: dt.datetime | None = None, think: Callable | None = None) -> dict:
    """Carry one task as far as it can go now. Returns {"state", ...}. Never raises for a step's failure."""
    from aletheia import agent_session, handoffs, program_compose as compose, reasoner, research, work_gaps
    now = pg._now(now)
    think = think or THINK
    record = pg.load(pid)
    task = next((t for t in record.get("tasks") or [] if t["key"] == key), None)
    if task is None:
        return {"state": ws.FAILED, "why": "no such task"}
    if record.get("state") != pg.ACTIVE:
        return {"state": task["state"], "why": "the mission is not active"}
    tools = catalog()
    unmet = _unmet_needs(record, task)
    if unmet:
        task.update(state=ws.READY, run=None, reason="", next="")
        _commit(pid, task, now)
        return {"state": ws.BLOCKED_EXTERNAL, "why": "needs other tasks first"}

    if not task.get("plan"):
        task["plan"] = compose.compose(task, tools)
        _history_plan(task, now)
        for gap in task["plan"]["gaps"]:
            try:
                work_gaps.record(gap["need"], asked=f"{record.get('title')}: {task['title']}"[:140], now=now)
            except Exception:  # noqa: BLE001 - the gap still shapes the task below
                pass
    plan = task["plan"]
    refused = next((g for g in plan["gaps"] if g["outcome"] == "refuse_policy"), None)
    if refused is not None:
        # One step that would spend money refuses the TASK: running the rest is not a smaller version of it.
        task.update(state=ws.FAILED, run=None, reason=f"{refused['need']}: {refused['why']}", next=refused["next"])
        _commit(pid, task, now)
        return {"state": ws.FAILED, "why": refused["why"]}
    if not plan["steps"]:
        return _no_tool(record, task, now)

    while task.get("cursor", 0) < len(plan["steps"]):
        i = task.get("cursor", 0)
        step = plan["steps"][i]
        tool = tools.get(step["tool"])
        if tool is None:
            task.update(plan=None, state=ws.RETRY_LATER, run=None, reason=f"the tool {step['tool']} is gone",
                        next="compose the task again", not_before=pg.stamp(now))
            _commit(pid, task, now)
            return {"state": ws.RETRY_LATER}
        args, missing = compose.fill_args(tool, task, step.get("args"))
        if tool.read_only and task.get("title"):
            # A look's question stored before it carried the task's title is asked with it now: the
            # comparison asked "pick a shortlist ...; compare cost of living ..." with no word of
            # which places, and read only national pages (2026-10-11).
            for key in compose.TOPIC_ARGS:
                value = str(args.get(key) or "")
                if value.strip() and str(task["title"]).casefold() not in value.casefold():
                    args[key] = f"{task['title']}: {value}"[:480]
        writes_from = ("sources" in ((tool.input_schema or {}).get("properties") or {}) and tool.writes
                       and set(tool.writes) <= {"workspace"})
        look = _stale_look(task, plan, tools, i) if writes_from else None
        if look is not None:
            # A write-up whose look read its pages the old way writes from that old reading: the
            # comparison's look kept 300 characters a page and its write-up refused (2026-10-11).
            # Once per revision, it looks again first.
            step["args"] = args
            task.update(cursor=look, relooked=research.REVISION, state=ws.READY, run=None,
                        reason="", next="look again on the current reading, then write")
            _commit(pid, task, now)
            return {"state": ws.READY, "why": "looking again on the current reading"}
        stale = _stale_needs(record, task, tools) if writes_from else []
        if stale:
            # Once per revision, each task it needs looks again first, and this one waits for them.
            for need, at in stale:
                need.update(cursor=at, relooked=research.REVISION, state=ws.READY, run=None, reason="",
                            next="look again on the current reading")
                _commit(pid, need, now)
            step["args"] = args
            task.update(state=ws.READY, run=None, reason="",
                        next="write once " + "; ".join(n["title"] for n, _ in stale)[:160] + " has looked again")
            _commit(pid, task, now)
            return {"state": ws.BLOCKED_EXTERNAL, "why": "the tasks it writes from are looking again"}
        if writes_from:
            # A document written "from Caleb's answers" reads them: without a source that reads,
            # compose refuses rather than invent (2026-10-10: "compose failed 3 times").
            given = args.get("sources") or []
            given = [given] if isinstance(given, str) else list(given)
            # And what the steps before it read: "write the ranked comparison" had only his answers
            # to write from, never the look it followed, and said it could not (2026-10-11).
            ours = [f for f in (_found_file(record, task), _answers_file(record)) if f]
            if ours:
                args["sources"] = ours + [g for g in given if g not in ours]
        if missing and set(missing) & set(WHERE_ARGS):
            # The event's own page, carried on the dated line it was found on, for something this
            # mission already pencilled in: no model needed, and no guess (2026-10-11: the trail walk
            # was held and its sign-up had no address).
            link = _held_event_link(record, task)
            if link:
                args.update({m: link for m in missing if m in WHERE_ARGS})
                missing = [m for m in missing if not str(args.get(m) or "").strip()]
        if missing and _writes_holds(tool) and set(missing) & set(WHEN_ARGS):
            # A date and a time the steps before it read, as the page wrote them, need no model.
            args.update(_dated_hold(record, task, tool, args, now))
            missing = [m for m in missing if not str(args.get(m) or "").strip()]
        if missing:
            try:
                args.update(compose.model_args(tool, task, args, missing, think=think,
                                               found=_found(record, task)))
            except reasoner.ReasonerUnavailable as exc:
                step["args"] = args
                pg.hold(record, task, {"kind": "model_available", "requirement": "reasoning",
                                       "not_before": pg.stamp(now + MODEL_RETRY)},
                        reason=f"needs a model to work out the {', '.join(missing)} for {tool.name} ({str(exc)[:80]})",
                        purpose="model", now=now, extra={"step": i})
                task["run"] = None
                _commit(pid, task, now)
                return {"state": ws.BLOCKED_MODEL}
            except Exception:  # noqa: BLE001 - an unusable answer means ask him
                pass
            missing = [m for m in missing if not str(args.get(m) or "").strip()]
        if missing:
            # What needs nobody's judgement (the window a read looks over, where a new file of
            # hers goes) is never a question for him.
            args.update(compose.default_args(tool, task, missing))
            missing = [m for m in missing if not str(args.get(m) or "").strip()]
        if missing and (set(missing) & set(WHEN_ARGS) or (_writes_holds(tool) and "title" in missing)) \
                and (task.get("needs") or i > 0):
            # "When?" about something the steps before it were to find, and nothing they found has
            # a date: there is nothing to put on the calendar YET. That is a look again tomorrow,
            # never a question for him he could only answer by doing the search himself.
            # Free windows have dates and are still not an event (2026-10-10: it asked him "what
            # should I use for start and title?" once the free time had been read). Whatever was found,
            # a when nobody could fill is a look again, never a question only a search could answer.
            # The same holds for a step whose own task looked first: the weekly sweep has no needs,
            # its look is its first step, and it asked him all the same (2026-10-11).
            dated = any(DATED.search(x) for x in _found(record, task, answers=False))
            look = _stale_look(task, plan, tools, i)
            if look is not None:
                # Its own look ran before looks carried the dated lines they read: it looks again
                # now, once per revision of how pages are read, rather than in a week (2026-10-11).
                step["args"] = args
                task.update(cursor=look, relooked=research.REVISION, state=ws.READY, run=None,
                            reason="", next="look again, reading the dates off the pages")
                _commit(pid, task, now)
                return {"state": ws.READY, "why": "looking again on the current reading"}
            step["args"] = args
            task.update(state=ws.RETRY_LATER, run=None, next="look again for something dated",
                        reason=("nothing found yet says what to put on the calendar and when" if dated
                                else "nothing found yet has a date to put on the calendar"),
                        not_before=pg.stamp(now + NOTHING_DATED_RETRY))
            _commit(pid, task, now)
            return {"state": ws.RETRY_LATER, "why": "nothing dated found yet"}
        if missing and set(missing) & set(WHERE_ARGS) and (task.get("needs") or i > 0):
            # An address for something the steps before it were to find: nothing found yet has one,
            # so there is nothing to sign up for YET (2026-10-11: "what should I use for url?").
            look = _stale_look(task, plan, tools, i)
            if look is not None:
                # Its own look ran before looks carried the event links: it looks again now, once per
                # revision of how pages are read, rather than waiting a day on the old reading.
                step["args"] = args
                task.update(cursor=look, relooked=research.REVISION, state=ws.READY, run=None,
                            reason="", next="look again, reading the events' own links")
                _commit(pid, task, now)
                return {"state": ws.READY, "why": "looking again on the current reading"}
            step["args"] = args
            task.update(state=ws.RETRY_LATER, run=None, next="look again for something with an address",
                        reason="nothing found yet has an address to use",
                        not_before=pg.stamp(now + NOTHING_DATED_RETRY))
            _commit(pid, task, now)
            return {"state": ws.RETRY_LATER, "why": "nothing with an address found yet"}
        if missing:
            step["args"] = args
            question = (f"For \"{task['title']}\", what should I use for {' and '.join(missing)}? "
                        f"({step.get('for') or tool.name})")
            pg.hold(record, task, {"kind": "user_decision", "question": question}, reason=question,
                    purpose="args", now=now, extra={"step": i, "missing": missing})
            task["run"] = None
            _commit(pid, task, now)
            return {"state": ws.BLOCKED_USER, "why": question}
        if _finds_free_time(tool) and not _readable_window(args.get("when")):
            # "the next 30 days" is not a stretch the calendar reads: it failed as a ValueError three
            # times (2026-10-10). A read over the default stretch needs nobody's judgement.
            args["when"] = compose.DEFAULT_WINDOW
        hours = his_hours(record)
        if hours and _finds_free_time(tool) and not str(args.get("part") or "").strip():
            # He said when he is free for this mission; a free-time read looks only there.
            from aletheia import calendar_reasoning
            args["part"] = calendar_reasoning.after_work_part(hours)
        wrong = _wrong_hold(record, task, tool, args, now)
        if wrong and _writes_holds(tool):
            # The time it was given is no good (most often: already on his calendar), but the look may
            # have found other things: the next one that fits is held instead of waiting a day.
            bare = {k: v for k, v in args.items() if k not in ("start", "title", "end", "minutes")}
            again = _dated_hold(record, task, tool, bare, now)
            if again:
                args, wrong = dict(bare, **again), ""
        if wrong:
            # A hold at a time that has passed, inside his working day, or titled with nothing the
            # steps before it found is a wrong hold, never a hold: the step looks again tomorrow,
            # its arguments worked out afresh (2026-10-10: "Hold Friday at 10 for the tour", for
            # a Friday three years gone).
            # Never a failure: what was found may simply not fit him yet.
            step["args"] = {}
            task.update(state=ws.RETRY_LATER, run=None, reason=f"left a calendar hold: {wrong}",
                        next="look again for something that fits", not_before=pg.stamp(now + NOTHING_DATED_RETRY))
            _commit(pid, task, now)
            return {"state": task["state"], "why": wrong}
        step["args"] = args
        broker = agent_session.Broker(tools, audience="all")
        decision = broker.check(agent_session.ToolRequest(tool.name, args))
        if decision.verdict == agent_session.RUN:
            outcome, result = agent_session.execute(
                tool, args, timeout_s=TOOL_TIMEOUT_S,
                quote=f"long mission {record.get('title')}: {task['title']}"[:200])
            said = _said(result)
            if outcome == "ok" and tool.read_only and tool.open_world and NOTHING_FOUND.search(said):
                # The look ran and found nothing it could answer with: a try that failed, so the task
                # looks again later instead of handing an empty answer to the tasks after it.
                outcome = "empty"
            _result(task, i, tool.name, outcome, said, now,
                    **({"revision": research.REVISION} if tool.read_only and tool.open_world else {}))
            if outcome != "ok":
                task["attempts"] = int(task.get("attempts") or 0) + 1
                if task["attempts"] >= MAX_ATTEMPTS and _looks_again_tomorrow(record, task):
                    task.update(state=ws.RETRY_LATER, run=None, attempts=0,
                                reason=f"{tool.name} failed {MAX_ATTEMPTS} times: {said[:160]}",
                                next="look again tomorrow", not_before=pg.stamp(now + NOTHING_DATED_RETRY))
                elif task["attempts"] >= MAX_ATTEMPTS:
                    task.update(state=ws.FAILED, run=None, reason=f"{tool.name} failed {task['attempts']} times: {said[:160]}",
                                next="")
                else:
                    task.update(state=ws.RETRY_LATER, run=None, reason=f"{tool.name} {outcome}: {said[:160]}",
                                next="try the step again", not_before=pg.stamp(now + RETRY_AFTER * task["attempts"]))
                _commit(pid, task, now)
                return {"state": task["state"], "why": said}
            task["cursor"] = i + 1
            extra = (lambda r, t=task, s=said: pg.record_monitor(r, t, s, now)) if task.get("from_activity") else None
            _commit(pid, task, now, extra)
            continue
        if decision.verdict == agent_session.HANDOFF and _signed_up_under_grant(tool, args, task, i, now):
            # His sign-ups ruling covers this one act: the step ran under the grant (or was left by
            # one of the sign-up rules), so there is nothing to hand him.
            task["cursor"] = i + 1
            _commit(pid, task, now)
            continue
        if decision.verdict == agent_session.HANDOFF:
            try:
                # A retried step is a NEW request for his yes: an earlier handoff that already finished
                # (failed, expired, denied) is never waited on again.
                for n in range(int(task.get("attempts") or 0), int(task.get("attempts") or 0) + 6):
                    filed = handoffs.file(tool=tool, args=args, session_id=f"mission-{pid}-{key}-{i}-{n}",
                                          question=f"{record.get('title')}: {task['title']}",
                                          why=step.get("for") or task.get("detail") or "", reason=decision.reason,
                                          audience="all")
                    if filed.get("state") == handoffs.AWAITING:
                        break
            except handoffs.NotFiled as exc:
                task.update(state=ws.FAILED, run=None, reason=str(exc)[:240], next="")
                _commit(pid, task, now)
                return {"state": ws.FAILED, "why": str(exc)}
            pg.hold(record, task, {"kind": "handoff", "handoff_id": filed["id"]},
                    reason=f"needs Caleb's approval to {(step.get('for') or task['title'])[:160]}", purpose="handoff",
                    now=now, extra={"step": i})
            task["run"] = None
            _commit(pid, task, now)
            return {"state": ws.BLOCKED_USER, "handoff": filed["id"]}
        # REFUSED
        if decision.permanent:
            task.update(state=ws.FAILED, run=None, reason=f"{tool.name} was refused: {decision.reason}"[:240], next="")
            _commit(pid, task, now)
            return {"state": ws.FAILED, "why": decision.reason}
        question = f"I couldn't use {tool.name} for \"{task['title']}\" ({decision.reason[:120]}). How should I do it?"
        pg.hold(record, task, {"kind": "user_decision", "question": question}, reason=question, purpose="refused",
                now=now, extra={"step": i})
        task["run"] = None
        _commit(pid, task, now)
        return {"state": ws.BLOCKED_USER, "why": decision.reason}
    return _after_steps(pid, record, task, now)


def _history_plan(task: dict, now: dt.datetime) -> None:
    plan = task["plan"]
    pg._history(task, "composed: " + (", ".join(s["tool"] for s in plan["steps"]) or "no tool")
                + (f"; gaps: {', '.join(g['need'] for g in plan['gaps'])}" if plan["gaps"] else ""), now)


def _no_tool(record: dict, task: dict, now: dt.datetime) -> dict:
    """No existing tool can do this task: the classified gap is its next action."""
    gap = task["plan"]["gaps"][0] if task["plan"]["gaps"] else {"outcome": "ask_caleb", "why": "nothing matched",
                                                               "next": "ask Caleb", "need": task["title"]}
    pid = record["id"]
    if gap["outcome"] == "refuse_policy":
        task.update(state=ws.FAILED, run=None, reason=gap["why"], next=gap["next"])
    elif gap["outcome"] == "ask_caleb":
        question = f"How should I do \"{gap['need']}\" for {record.get('title')}? No tool of mine can."
        pg.hold(record, task, {"kind": "user_decision", "question": question}, reason=question, purpose="gap", now=now)
        task["run"] = None
    else:
        # Queued as a capability (or an outside event): wait, and look again whether a tool exists.
        pg.hold(record, task, {"kind": "event", "event_kind": "mission.capability",
                               "subject_prefix": pg.item_id(pid, task["key"])},
                reason=f"no tool can {gap['need']} yet ({gap['why']}); next: {gap['next']}", purpose="gap", now=now,
                timeout={"after_s": 7 * 86400, "means": "time to look again whether a tool can do it now",
                         "then": "wake"})
        task["run"] = None
    _commit(pid, task, now)
    return {"state": task["state"], "gap": gap["outcome"]}


#: Who "a reply from" means when it means him.
HIM = re.compile(r"\b(?:caleb|him|me|operator)\b", re.I)


def _waits_only_on_his_ok(task: dict) -> bool:
    """A task that wrote something of hers and then waits for HIS reply, having sent nobody
    anything: "ask him to confirm the list". His okay is a choice he makes when he likes, not a
    gate on everything after it (2026-10-10: the whole move plan waited on "waiting for Caleb")."""
    tw = task.get("then_wait") or {}
    return (tw.get("for") == "reply" and bool(HIM.search(str(tw.get("who") or "")))
            and not any(r.get("sent_to") for r in task.get("results") or []))


def _confirm_later(task: dict) -> Callable[[dict], None]:
    """The record change that leaves his okay as an open choice once the task is done."""
    def add(record: dict) -> None:
        key = f"confirm-{task['key']}"
        if any(d.get("key") == key for d in record.get("decisions") or []):
            return
        record.setdefault("decisions", []).append(
            {"key": key, "workstream": task.get("workstream", ""), "question":
             f"I did \"{task['title']}\" from what you've told me. Does it look right, or should I change it?",
             "options": ["Looks right", "Change it"], "after": [task["key"]], "state": "pending"})
    return add


def _after_steps(pid: str, record: dict, task: dict, now: dt.datetime) -> dict:
    tw = task.get("then_wait")
    if not tw or task.get("waited"):
        return _finish(pid, task, now)
    if _waits_only_on_his_ok(task):
        return _finish(pid, task, now, extra=_confirm_later(task))
    kind = tw["for"]
    item = pg.item_id(pid, task["key"])
    follow_up = ({"after_s": float(tw["follow_up_days"]) * 86400, "needs_approval": True,
                  "say": f"No answer yet on {task['title']}."} if tw.get("follow_up_days") else None)
    timeout = ({"after_s": float(tw["timeout_days"]) * 86400, "then": "ask_caleb",
                "means": tw.get("timeout_means") or f"no {kind} within {tw['timeout_days']:g} days"}
               if tw.get("timeout_days") else None)
    who = tw.get("who") or ""
    if kind == "reply":
        sent = next((r for r in reversed(task.get("results") or []) if r.get("sent_to")), None)
        if sent:
            condition = {"kind": "reply_from", "thread_id": sent["thread"], "participant": sent["sent_to"]}
            who = who or sent["sent_to"]
        else:
            condition = {"kind": "event", "event_kind": "mission.reply", "subject_prefix": item,
                         "describe": f"a reply from {who or 'them'} is recorded"}
        reason = f"waiting for {who or 'a reply'} about {task['title']}"
    elif kind == "date":
        at = now + dt.timedelta(days=float(tw.get("in_days") or 1))
        condition = {"kind": "time_after", "at": pg.stamp(at)}
        reason = f"waiting until {at.date().isoformat()} for {task['title']}"
    elif kind == "decision":
        condition = {"kind": "user_decision", "question": tw.get("question") or task["title"],
                     "options": list(tw.get("options") or [])}
        reason = f"a choice for Caleb: {condition['question']}"
    else:
        condition = {"kind": "event", "event_kind": f"mission.{kind}", "subject_prefix": item,
                     "describe": f"the {kind} for {task['title']} is recorded"}
        reason = f"waiting for the {kind} of {task['title']}"
    pg.hold(record, task, condition, reason=reason, purpose="then", now=now, follow_up=follow_up, timeout=timeout)
    task["run"] = None
    _commit(pid, task, now)
    return {"state": task["state"], "waiting": kind}


def _finish(pid: str, task: dict, now: dt.datetime, text: str = "",
            extra: Callable[[dict], None] | None = None) -> dict:
    said = text or next((r["said"] for r in reversed(task.get("results") or []) if r.get("said")), "") or "done"
    task.update(state=ws.DONE, run=None, reason="", next="", not_before=None, updated_at=pg.stamp(now))
    pg._history(task, "done: " + said[:160], now)

    more = extra

    def extra(record):
        record["results"] = (record.get("results") or [])[-pg.MAX_RESULTS:] + [
            {"at": pg.stamp(now), "task": task["key"], "text": f"{task['title']}: {said[:300]}"}]
        if more is not None:
            more(record)
    _commit(pid, task, now, extra)
    pg._journal("action", pg.item_id(pid, task["key"]), f"mission task done: {task['title']}")
    return {"state": ws.DONE}


# ---- hearing back from a wait ------------------------------------------------------------------

RECIPIENT_ARGS = ("to", "person", "recipient", "email", "phone", "contact", "who")


#: Tools whose own module already records what they send (`aletheia.conversations`).
CONVERSATION_SEND_TOOLS = ("thread.send", "thread_send")


def _record_outbound(pid: str, task: dict, held: dict, now: dt.datetime) -> None:
    """A handed-off step that reached someone is recorded ONCE, by the one owner of
    outbound messages (`aletheia.conversations`), so a reply can be awaited.

    Until C3 this wrote its own `mission-<pid>-<task>` communications thread while a
    `thread.send` step had already been recorded by conversations under another,
    each with its own follow-up clock. Now: a conversation's own send is LINKED,
    any other door's send is recorded on a conversation, and the follow-up policy
    belongs to this task's wait (`then_wait.follow_up_days` -> `waits`), not to a
    second date on the thread."""
    from aletheia import conversations, handoffs
    try:
        row = handoffs.load(held["condition"]["handoff_id"])
    except Exception:  # noqa: BLE001
        return
    args = row.get("args") or {}
    item = pg.item_id(pid, task["key"])
    owner = item if (task.get("then_wait") or {}).get("follow_up_days") else ""
    try:
        if row.get("tool") in CONVERSATION_SEND_TOOLS and args.get("thread"):
            linked = conversations.link_sent(str(args["thread"]), work_item=item, follow_up_owner=owner, now=now)
        else:
            who = next((str(args[k]).strip() for k in RECIPIENT_ARGS if str(args.get(k) or "").strip()), "")
            if not who:
                return
            linked = conversations.record_sent_elsewhere(
                who, subject=task["title"][:120], summary=str(row.get("consequence") or row.get("tool"))[:300],
                work_item=item, via=f"mission:{pid}", follow_up_owner=owner, now=now)
    except (conversations.ConversationError, ValueError, OSError):
        return
    for r in reversed(task.get("results") or []):
        if r.get("tool") == row.get("tool"):
            r.update(sent_to=linked["participant"], thread=linked["comms_thread"], conversation=linked["thread"])
            break


def _nudge(record: dict, task: dict, now: dt.datetime, n: int) -> dict:
    """A due follow-up becomes a small task of its own. Its outbound step asks Caleb first, like any other."""
    tools_used = [s["tool"] for s in ((task.get("plan") or {}).get("steps") or [])]
    who = next((r.get("sent_to") for r in reversed(task.get("results") or []) if r.get("sent_to")), "") \
        or (task.get("then_wait") or {}).get("who") or ""
    key = f"{task['key']}-nudge{n}"
    if any(t["key"] == key for t in record["tasks"]):
        return next(t for t in record["tasks"] if t["key"] == key)
    then = {"for": "", "who": who} if who else None
    nudge = pg._task_from({"key": key, "workstream": task.get("workstream"),
                           "title": f"Follow up: {task['title']}",
                           "detail": f"Follow up{' with ' + who if who else ''} about: {task.get('detail') or task['title']}",
                           "does": [f"send a follow-up message{' to ' + who if who else ''}"],
                           "uses": tools_used[-1:], "needs": [], "then_wait": then,
                           "outcomes": task.get("outcomes")}, now)
    nudge["waited"] = True          # the nudge itself is not waited on; the original task still is
    record["tasks"].append(nudge)
    return nudge


def on_wait(pid: str, held: dict, event: str, now: dt.datetime) -> dict:
    ctx = held.get("context") or {}
    purpose = ctx.get("purpose")
    outcome = (held.get("outcome") or {}).get("outcome")
    with pg._LOCK:
        record = pg.load(pid)
        if purpose == "decision":
            decision = next((d for d in record.get("decisions") or [] if d["key"] == ctx.get("decision")), None)
            choice = (held.get("decision") or {}).get("choice")
            if decision is not None and event == waits.WOKE and choice and decision.get("state") != "decided":
                decision.update(state="decided", choice=choice, decided_at=pg.stamp(now))
                pg.save(record)
            return {"said": f"decision {ctx.get('decision')}: {choice or outcome}"}
        task = next((t for t in record.get("tasks") or [] if t["key"] == ctx.get("task")), None)
        if task is None or task["state"] in ws.WORK_TERMINAL:
            return {"said": "nothing to move"}
        step = ctx.get("step")
        said = ""
        if event == waits.FOLLOW_UP:
            n = len((held.get("follow_up") or {}).get("sent") or []) + 1
            nudge = _nudge(record, task, now, n)
            pg._history(task, f"follow-up {n} due: {nudge['title']} filed (asks Caleb before anything is sent)", now)
            said = f"filed {nudge['key']}"
        elif event == waits.TIMEOUT:
            timeout = held.get("timeout") or {}
            then = timeout.get("then", "wake")
            _result(task, step, "", "timeout", timeout.get("means") or "timed out", now)
            if then == "ask_caleb":
                question = f"{str(timeout.get('means') or 'nothing came').rstrip('.')}. What next?"
                task["waited"] = True
                pg.hold(record, task, {"kind": "user_decision", "question": question,
                                       "options": ["follow up again", "wait longer", "move on"]},
                        reason=question, purpose="timeout_decision", now=now)
                said = "asked Caleb what next"
            elif then == "follow_up":
                _nudge(record, task, now, 1)
                task.update(state=ws.DONE, reason="", next="")
                said = "filed a follow-up"
            else:
                task["waited"] = True
                task.update(state=ws.READY, reason="", next="")
                if purpose == "gap":
                    task["plan"] = None
                said = "woke at the timeout"
        else:  # WOKE
            evidence = (held.get("outcome") or {}).get("evidence") or {}
            choice = str(evidence.get("choice") or "")
            if purpose == "handoff":
                if outcome == "done":
                    _result(task, step, "", "done", evidence.get("said") or "done after Caleb's approval", now)
                    task["results"][-1]["tool"] = ((task.get("plan") or {}).get("steps") or [{}])[step or 0].get("tool", "")
                    _record_outbound(pid, task, held, now)
                    task.update(cursor=(step or 0) + 1, state=ws.READY, reason="", next="")
                    said = "approved step done"
                elif outcome == "denied":
                    task.update(state=ws.FAILED, reason="Caleb said no to it", next="")
                    said = "denied"
                elif outcome == "expired":
                    task.update(state=ws.READY, reason="", next="ask Caleb again")
                    said = "approval expired; will ask again"
                else:
                    task["attempts"] = int(task.get("attempts") or 0) + 1
                    why = evidence.get("said") or outcome
                    if task["attempts"] >= MAX_ATTEMPTS:
                        task.update(state=ws.FAILED, reason=f"the approved step did not work: {why}"[:240], next="")
                    else:
                        task.update(state=ws.RETRY_LATER, reason=f"the approved step did not work: {why}"[:240],
                                    next="try again", not_before=pg.stamp(now + RETRY_AFTER))
                    said = f"handoff {outcome}"
            elif purpose == "then":
                task["waited"] = True
                if choice:
                    _result(task, None, "", "decided", f"Caleb chose {choice}", now)
                else:
                    _result(task, None, "", outcome or "woke", (held.get("outcome") or {}).get("why") or "", now)
                pg.save(record)
                return _finish_locked(pid, record, task, now)
            elif purpose == "timeout_decision":
                low = choice.lower()
                if "follow" in low:
                    _nudge(record, task, now, len([t for t in record["tasks"] if t["key"].startswith(task["key"] + "-nudge")]) + 1)
                    task.update(state=ws.DONE, reason="", next="")
                elif "wait" in low:
                    task["waited"] = False
                    task.update(state=ws.READY, reason="", next="wait again")
                else:
                    task.update(state=ws.DONE, reason="", next="")
                said = f"Caleb chose {choice}"
            elif purpose == "args":
                missing = ctx.get("missing") or []
                steps = (task.get("plan") or {}).get("steps") or []
                if steps and step is not None and step < len(steps) and missing:
                    steps[step].setdefault("args", {})[missing[0]] = choice
                task.update(state=ws.READY, reason="", next="")
                said = "his answer filled the step"
            elif purpose in ("refused", "gap"):
                task["detail"] = (f"{task.get('detail') or ''} Caleb said: {choice}".strip())[:480] if choice else task.get("detail")
                task.update(plan=None, cursor=0, state=ws.READY, reason="", next="compose it again")
                said = "recomposed with his words"
            else:  # model came back
                task.update(state=ws.READY, reason="", next="")
                said = "a model can think again"
        task["updated_at"] = pg.stamp(now)
        _open_ready_decisions(record, now)
        record["updated_at"] = pg.stamp(now)
        pg.save(record)
    return {"said": said}


def _finish_locked(pid: str, record: dict, task: dict, now: dt.datetime) -> dict:
    said = next((r["said"] for r in reversed(task.get("results") or []) if r.get("said")), "") or "done"
    task.update(state=ws.DONE, run=None, reason="", next="", not_before=None, updated_at=pg.stamp(now))
    pg._history(task, "done: " + said[:160], now)
    record["results"] = (record.get("results") or [])[-pg.MAX_RESULTS:] + [
        {"at": pg.stamp(now), "task": task["key"], "text": f"{task['title']}: {said[:300]}"}]
    _open_ready_decisions(record, now)
    record["updated_at"] = pg.stamp(now)
    pg.save(record)
    pg._journal("action", pg.item_id(pid, task["key"]), f"mission task done: {task['title']}")
    return {"said": "done"}
