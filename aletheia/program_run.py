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


def _result(task: dict, step: int | None, tool: str, outcome: str, said: str, now: dt.datetime, **more) -> None:
    rows = list(task.get("results") or [])
    rows.append({"at": pg.stamp(now), "step": step, "tool": tool, "outcome": outcome, "said": str(said)[:600], **more})
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
    from aletheia import handoffs
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


def _found(record: dict, task: dict) -> list[str]:
    """What this task's earlier steps and the tasks it needs have read, plus his answers."""
    keys = set(task.get("needs") or [])
    rows = [r for t in record.get("tasks") or [] if t.get("key") in keys for r in t.get("results") or []]
    rows += list(task.get("results") or [])
    found = [str(r.get("said") or "") for r in rows if r.get("outcome") == "ok" and r.get("said")][-5:]
    answers = his_answers(record)
    return ([f"What Caleb has told this mission:\n{answers[:2000]}"] if answers else []) + found


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
    from aletheia import program_compose as compose
    plan = task.get("plan")
    if not plan or not plan.get("steps"):
        return None
    held = pg.current_wait(task) if task["state"] in ws.WORK_WAITING else None
    purpose = ((held or {}).get("context") or {}).get("purpose")
    refused = task["state"] == ws.FAILED and " was refused: " in str(task.get("reason") or "")
    # A write that failed three times on a path outside her workspace (2026-10-10) was a bad
    # argument, not a bad task: the path is dropped and filled now, so it may try again.
    bad_path = task["state"] == ws.FAILED and "OutsideWorkspace" in str(task.get("reason") or "")
    # A document that failed for want of anything to write from has his answers to read now; once.
    no_source = (task["state"] == ws.FAILED and "ComposeError" in str(task.get("reason") or "")
                 and not task.get("source_retried"))
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
        old_tools = [s["tool"] for s in plan["steps"]]
        new_tools = [s["tool"] for s in fresh["steps"]]
        if new_tools[:i] != old_tools[:i]:
            # The steps that already ran would be chosen differently now. They stay as they ran;
            # only the step it is parked on is chosen again, from what that step was for.
            fresh = _rechoose_step(task, plan, tools, i)
            if fresh is None:
                return None
            new_tools = [s["tool"] for s in fresh["steps"]]
        candidate = dict(task, plan=fresh if new_tools != old_tools else plan)
    if purpose == "args" and not task.get("args_retried") and not _would_go_further(
            candidate, candidate["plan"], tools, purpose) and _found(record, task):
        # Asked him for arguments the steps before it have since found (the events a search
        # read, his answers): once, it tries again with them in front of the model.
        candidate = dict(candidate, mark="args_retried")
        return _release(record, task, candidate, held, purpose, now)
    if not _would_go_further(candidate, candidate["plan"], tools, purpose or "refused"):
        return None
    if no_source:
        candidate = dict(candidate, mark="source_retried")
    return _release(record, task, candidate, held, purpose, now)


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
    key, new_plan, mark = task["key"], candidate["plan"], candidate.get("mark")

    def change(r, key=key, new_plan=new_plan, mark=mark):
        t = next((x for x in r.get("tasks") or [] if x["key"] == key), None)
        if t is None:
            return None
        t.update(plan=new_plan, state=ws.READY, reason="", next="run its next step", run=None,
                 not_before=None, attempts=0, updated_at=pg.stamp(now))
        if mark:
            t[mark] = True
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
    from aletheia import agent_session, handoffs, program_compose as compose, reasoner, work_gaps
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
        if "sources" in ((tool.input_schema or {}).get("properties") or {}) and tool.writes \
                and set(tool.writes) <= {"workspace"}:
            # A document written "from Caleb's answers" reads them: without a source that reads,
            # compose refuses rather than invent (2026-10-10: "compose failed 3 times").
            kept = _answers_file(record)
            given = args.get("sources") or []
            given = [given] if isinstance(given, str) else list(given)
            if kept and kept not in given:
                args["sources"] = given + [kept]
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
        if missing:
            step["args"] = args
            question = (f"For \"{task['title']}\", what should I use for {' and '.join(missing)}? "
                        f"({step.get('for') or tool.name})")
            pg.hold(record, task, {"kind": "user_decision", "question": question}, reason=question,
                    purpose="args", now=now, extra={"step": i, "missing": missing})
            task["run"] = None
            _commit(pid, task, now)
            return {"state": ws.BLOCKED_USER, "why": question}
        step["args"] = args
        broker = agent_session.Broker(tools, audience="all")
        decision = broker.check(agent_session.ToolRequest(tool.name, args))
        if decision.verdict == agent_session.RUN:
            outcome, result = agent_session.execute(
                tool, args, timeout_s=TOOL_TIMEOUT_S,
                quote=f"long mission {record.get('title')}: {task['title']}"[:200])
            said = _said(result)
            _result(task, i, tool.name, outcome, said, now)
            if outcome != "ok":
                task["attempts"] = int(task.get("attempts") or 0) + 1
                if task["attempts"] >= MAX_ATTEMPTS:
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


def _after_steps(pid: str, record: dict, task: dict, now: dt.datetime) -> dict:
    tw = task.get("then_wait")
    if not tw or task.get("waited"):
        return _finish(pid, task, now)
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


def _finish(pid: str, task: dict, now: dt.datetime, text: str = "") -> dict:
    said = text or next((r["said"] for r in reversed(task.get("results") or []) if r.get("said")), "") or "done"
    task.update(state=ws.DONE, run=None, reason="", next="", not_before=None, updated_at=pg.stamp(now))
    pg._history(task, "done: " + said[:160], now)

    def extra(record):
        record["results"] = (record.get("results") or [])[-pg.MAX_RESULTS:] + [
            {"at": pg.stamp(now), "task": task["key"], "text": f"{task['title']}: {said[:300]}"}]
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
