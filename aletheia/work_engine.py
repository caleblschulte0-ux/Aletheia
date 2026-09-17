"""The work engine: one durable, non-blocking reading of everything unfinished.

His continuity brief (docs/CONTINUITY_BRIEF.md), Part II.3 and the continuity
rules: *"I should never not be able to work on my projects."* If task A needs
Claude and Claude is out, A is checkpointed and B runs. So:

- **One state model over the existing stores, not a new store for them.** Tasks
  keep `contracts.TASK_STATES`, charter steps keep todo/doing/done/blocked,
  handoffs and browser missions keep theirs. Each SOURCE below READS its store and
  says what every item means in `work_states.WORK_STATES`, with a reason and a next
  condition (rule 3). Nothing here rewrites another store's state.
- **A durable overlay** (`state/private/work/items.json`) holds what only the
  engine knows: that an item is BLOCKED_MODEL until Claude's reset at 4:40 PM,
  RETRY_LATER not before 10:05, NEEDS_STRONGER_MODEL. It is keyed by the native
  state it was written against, so when the store moves on the overlay is dropped
  rather than believed. Its own native items live there too: capability gaps turned
  into next actions (Part II.6). The file survives a restart (rule 7).
- **The picker** walks every unfinished item and asks `work_requirements` whether
  it can run NOW. Unmet requirements checkpoint that item with the precise state and
  wake condition; every other item is still considered (rule 2). An item whose
  condition has cleared (the reset passed, the model is back) wakes to READY.
- **It runs inside the Core's beat** (`runtime.tick` -> `reconcile`), bounded and
  guarded like every other subsystem; it is not a second loop. It EXECUTES only its
  own native items (turning a gap into its next action through existing gates:
  `gaps.materialize`, a notification). Items owned by another store are run by that
  store's executor (the handoff runner, the project loop, the cloud builder); for
  them the engine is the inventory and the checkpoint, never a second executor.

Money is never hers (`payment` is never satisfied), approvals are never hers
(`user_approval` is satisfied only by an APPROVED record), and a halted Aletheia runs
nothing here. `python -m aletheia.work_engine inventory --frontier-off` prints what
there is, what can run now and what is blocked and why, read-only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from typing import Any, Callable

from aletheia import stateio, work_requirements as wr, work_states as ws

ACTOR = "aletheia-work"
MAX_HISTORY = 20
MAX_RUNS_PER_BEAT = 2
#: Unfinished-state precedence when several requirements are unmet: the one that
#: needs a PERSON is the truest description of why it is not moving.
PRECEDENCE = [ws.BLOCKED_USER, ws.BLOCKED_LOGIN, ws.BLOCKED_EXTERNAL, ws.NEEDS_STRONGER_MODEL,
              ws.BLOCKED_MODEL, ws.RETRY_LATER]


def store_path():
    return stateio.private_dir("work") / "items.json"


def _now(now: dt.datetime | None = None) -> dt.datetime:
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)


def _stamp(when: dt.datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp) -> dt.datetime | None:
    text = str(stamp or "").strip()
    if not text:
        return None
    try:
        when = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


def item(id: str, source: str, title: str, state: str, *, requires=(), reason: str = "",
         next: str = "", not_before: str | None = None, priority: int = 3, native_state: str = "",
         owner: str = "", kind: str = "", payload: dict | None = None, evidence: dict | None = None,
         updated: str = "", stronger: bool = False) -> dict:
    """One work item view. Pure."""
    return {"id": id, "source": source, "title": str(title or id)[:200], "state": state,
            "requires": [r for r in dict.fromkeys(requires or []) if r in ws.REQUIREMENTS],
            "reason": str(reason or "")[:300], "next": str(next or "")[:300], "not_before": not_before,
            "priority": int(priority), "native_state": str(native_state or ""), "owner": owner,
            "kind": kind, "payload": dict(payload or {}), "evidence": dict(evidence or {}),
            "updated": updated, "stronger": bool(stronger)}


# ---- the durable overlay + native items ------------------------------------------------

def load_store() -> dict:
    try:
        value = json.loads(store_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"items": {}}
    if not isinstance(value, dict) or not isinstance(value.get("items"), dict):
        return {"items": {}}
    return value


def save_store(store: dict) -> None:
    store_path().parent.mkdir(parents=True, exist_ok=True)
    store["updated"] = stateio.utcnow()
    stateio.write_json_atomic(store_path(), store)


def _history(record: dict, text: str, now: dt.datetime) -> None:
    rows = list(record.get("history") or [])
    rows.append({"at": _stamp(now), "did": str(text)[:200]})
    record["history"] = rows[-MAX_HISTORY:]


def add(title: str, *, requires=(), kind: str = "", payload: dict | None = None, priority: int = 3,
        state: str = ws.READY, reason: str = "", next: str = "", not_before: str | None = None,
        key: str = "", now: dt.datetime | None = None) -> dict:
    """File one NATIVE work item durably. Idempotent on `key` (or title+kind)."""
    now = _now(now)
    if state not in ws.WORK_STATES:
        raise ValueError(f"state {state!r} not in {sorted(ws.WORK_STATES)}")
    digest = hashlib.sha256(f"{kind}:{key or title}".encode("utf-8")).hexdigest()[:12]
    wid = f"work:{digest}"
    store = load_store()
    if wid in store["items"]:
        return store["items"][wid]
    record = item(wid, "work", title, state, requires=requires, reason=reason, next=next,
                  not_before=not_before, priority=priority, native_state=state, kind=kind,
                  payload=payload, updated=_stamp(now))
    record["created"] = _stamp(now)
    problems = ws.problems(record)
    if problems:
        raise ValueError("work item violates the vocabulary: " + "; ".join(problems))
    _history(record, f"filed as {state}", now)
    store["items"][wid] = record
    save_store(store)
    _journal("task", wid, f"work filed ({state}): {record['title']}")
    return record


def _journal(kind: str, subject: str, text: str) -> None:
    try:
        from aletheia import journal
        journal.append(kind, subject, text, actor=ACTOR)
    except Exception:
        pass


# ---- sources: each reads ONE existing store and maps it -------------------------------

def _caps_to_requirements(capability_ids, worker: str = "") -> list[str]:
    """Registry capability ids and an assigned worker -> requirement names."""
    reqs = []
    worker = str(worker or "").lower()
    if worker in {"claude", "codex", "chatgpt", "frontier"}:
        reqs.append("frontier_reasoning")
    elif worker in {"local", "local-repair", "ollama", "aletheia-local"}:
        reqs.append("local_reasoning")
    for cid in capability_ids or []:
        head = str(cid).split(".")[0]
        reqs += {"browser": ["browser"], "web": ["browser"], "research": ["browser"],
                 "mail": ["email"], "email": ["email"], "message": ["email"],
                 "calendar": ["calendar"], "github": ["github"], "repo": ["filesystem"],
                 "code": ["code_execution"], "script": ["code_execution"],
                 "purchase": ["payment"], "shopping": ["payment"]}.get(head, [])
    return reqs


def source_tasks(now: dt.datetime) -> list[dict]:
    from aletheia import tasks
    rows = tasks.all_tasks()
    index = {t.get("id"): t for t in rows}
    out = []
    for t in rows:
        tid, status = str(t.get("id")), str(t.get("status") or "")
        common = dict(requires=_caps_to_requirements(t.get("required_capabilities"), t.get("assigned_worker")),
                      priority=int(t.get("priority") or 3), native_state=status,
                      owner=str(t.get("assigned_worker") or ""), updated=str(t.get("updated_at") or ""),
                      # Work deliberately assigned to a frontier worker is reserved for a
                      # stronger model: with none able to think it NEEDS one, it is not merely
                      # waiting for a busy one.
                      stronger=str(t.get("assigned_worker") or "").lower() in {"claude", "codex", "chatgpt"})
        note = str(t.get("result") or t.get("error") or "")
        title = str(t.get("description") or tid)
        if status == "COMPLETED":
            state, reason, nxt = ws.DONE, "", ""
        elif status in {"CANCELLED", "FAILED_TERMINAL"}:
            state, reason, nxt = ws.FAILED, note or status.lower(), ""
        elif status == "RUNNING":
            state, reason, nxt = ws.RUNNING, "", "record what came of it"
        elif status == "WAITING_OPERATOR":
            state, reason, nxt = ws.BLOCKED_USER, note or "waiting on Caleb", "when Caleb does his part"
        elif status == "WAITING_EXTERNAL":
            state, reason, nxt = ws.BLOCKED_EXTERNAL, note or "waiting on the world", "when the answer arrives"
        elif status in {"RETRY_SCHEDULED", "FAILED_RETRYABLE"}:
            state, reason, nxt = ws.RETRY_LATER, note or "failed and may be retried", "retry it"
        elif status == "BLOCKED":
            state, reason, nxt = ws.BLOCKED_EXTERNAL, note or "blocked", "when the blocker clears"
        else:  # QUEUED, READY, WAITING_DEPENDENCY
            waiting = [d for d in t.get("dependencies") or []
                       if (index.get(d) or {}).get("status") != "COMPLETED"]
            if waiting:
                state, reason, nxt = (ws.BLOCKED_EXTERNAL, "waiting on " + ", ".join(waiting),
                                      "when " + ", ".join(waiting) + " complete")
            else:
                state, reason, nxt = ws.READY, "", f"run by {t.get('assigned_worker') or 'whoever picks it'}"
        out.append(item(f"task:{tid}", "tasks", title, state, reason=reason, next=nxt,
                        not_before=_stamp(now) if state == ws.RETRY_LATER else None, **common))
    return out


def source_charters(now: dt.datetime) -> list[dict]:
    from aletheia import plans
    out = []
    for plan in plans.all_plans():
        if plan.get("state") != "open":
            continue
        slug = str(plan.get("slug") or "")
        charter = plans.is_charter(plan)
        steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
        done = {s.get("n") for s in steps if s.get("state") == "done"}
        for step in steps:
            n, st = step.get("n"), str(step.get("state") or "")
            title = f"{plan.get('title') or slug}: {step.get('text') or ''}"
            who = plans.owner(step) if charter else "thea"
            requires = ["github", "frontier_reasoning"] if charter and who != "caleb" else (
                ["reasoning"] if who != "caleb" else ["user_decision"])
            common = dict(requires=requires, native_state=st, owner=who, priority=2 if charter else 3)
            wid = f"plan:{slug}#{n}"
            if st == "done":
                out.append(item(wid, "plans", title, ws.DONE, **common))
                continue
            if st == "doing":
                out.append(item(wid, "plans", title, ws.RUNNING, next="a pull request that names this step",
                                **common))
                continue
            needs = [x for x in step.get("needs") or [] if x not in done]
            if needs:
                out.append(item(wid, "plans", title, ws.BLOCKED_EXTERNAL,
                                reason="needs step " + ", ".join(f"#{x}" for x in needs) + " first",
                                next="when those steps are done", **common))
            elif st == "blocked":
                out.append(item(wid, "plans", title, ws.BLOCKED_EXTERNAL, reason="the step is marked blocked",
                                next="when its blocker is cleared", **common))
            elif who == "caleb":
                out.append(item(wid, "plans", title, ws.BLOCKED_USER, reason="this step is Caleb's",
                                next="when he replies done on the brief", **common))
            else:
                out.append(item(wid, "plans", title, ws.READY,
                                next=("the project builder takes it" if charter else "work the step"), **common))
    return out


def source_handoffs(now: dt.datetime) -> list[dict]:
    from aletheia import handoffs
    out = []
    for record in handoffs.all_handoffs():
        state = str(record.get("state") or "")
        title = str(record.get("consequence") or record.get("tool") or record.get("id"))
        wid = f"handoff:{record.get('id')}"
        evidence = {"approval": record.get("approval")} if record.get("approval") else {}
        if state == handoffs.AWAITING:
            out.append(item(wid, "handoffs", title, ws.BLOCKED_USER, requires=["user_approval"],
                            reason="a request her session handed to Caleb", next="when Caleb approves or denies it",
                            native_state=state, evidence=evidence))
        elif state == handoffs.RUNNING:
            out.append(item(wid, "handoffs", title, ws.RUNNING, native_state=state, next="record what came of it"))
        elif state == handoffs.DONE:
            out.append(item(wid, "handoffs", title, ws.DONE, native_state=state))
        else:
            out.append(item(wid, "handoffs", title, ws.FAILED, native_state=state,
                            reason=str(record.get("outcome") or state.lower())))
    return out


_LOGIN = re.compile(r"SIGN|LOGIN|ACCOUNT|CODE|VERIF|MFA|SMS", re.I)


def source_browser_missions(now: dt.datetime) -> list[dict]:
    from aletheia import browser_mission as bm
    out = []
    for record in bm.all_missions():
        state = str(record.get("state") or "")
        boundary = record.get("boundary") or {}
        kind = str(boundary.get("kind") or "")
        title = str(record.get("goal") or record.get("id"))
        wid = f"browser:{record.get('id')}"
        said = str(boundary.get("say") or kind or state)
        common = dict(requires=["browser"], native_state=state, updated=str(record.get("beat") or ""))
        if state == bm.RUNNING:
            if bm.stale(record):
                out.append(item(wid, "browser_missions", title, ws.RETRY_LATER,
                                reason="it stopped moving mid-run (the process may have exited)",
                                next="resume from its last checkpoint", not_before=_stamp(now), **common))
            else:
                out.append(item(wid, "browser_missions", title, ws.RUNNING, **common))
        elif state == bm.NEEDS_YOU:
            blocked = ws.BLOCKED_LOGIN if _LOGIN.search(kind) else ws.BLOCKED_USER
            out.append(item(wid, "browser_missions", title, blocked, reason=said,
                            next="when Caleb passes that boundary; it resumes from the checkpoint", **common))
        elif state == bm.AWAITING_APPROVAL:
            out.append(item(wid, "browser_missions", title, ws.BLOCKED_USER,
                            reason="the committing press waits for his yes", next="when Caleb approves the press",
                            **{**common, "requires": ["browser", "user_approval"]}))
        elif state in (bm.SUBMITTING, bm.SUBMITTED_UNCONFIRMED):
            out.append(item(wid, "browser_missions", title, ws.BLOCKED_EXTERNAL,
                            reason="pressed; the site's verdict is not read yet",
                            next="when the confirmation is read (never pressed twice)", **common))
        elif state == bm.DONE:
            out.append(item(wid, "browser_missions", title, ws.DONE, **common))
        else:
            out.append(item(wid, "browser_missions", title, ws.FAILED, reason=said, **common))
    return out


def source_project_asks(now: dt.datetime) -> list[dict]:
    from aletheia import charters
    out = []
    for row in charters.pending():
        ident = str(row.get("id") or hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()[:10])
        title = f"project ask ({row.get('kind')}): {row.get('text') or row.get('project') or ''}"
        why = str(row.get("why") or "")
        if why.startswith("ReasonerUnavailable"):
            out.append(item(f"ask:{ident}", "project_asks", title, ws.BLOCKED_MODEL, requires=["reasoning", "github"],
                            reason=why[:200], next="the project loop drafts it when a model can think",
                            native_state="pending"))
        else:
            out.append(item(f"ask:{ident}", "project_asks", title, ws.READY, requires=["reasoning", "github"],
                            next="the project loop drafts it", native_state="pending"))
    return out


def source_native(now: dt.datetime) -> list[dict]:
    return [dict(v) for v in load_store()["items"].values()
            if isinstance(v, dict) and v.get("source") == "work"]


#: Every store the engine reads, by name. A new queue adds ONE line here.
SOURCES: dict[str, Callable[[dt.datetime], list[dict]]] = {
    "tasks": source_tasks,
    "plans": source_charters,
    "handoffs": source_handoffs,
    "browser_missions": source_browser_missions,
    "project_asks": source_project_asks,
    "work": source_native,
}


def gather(now: dt.datetime | None = None, *, sources: dict | None = None) -> tuple[list[dict], list[str]]:
    """Every item from every source, with the durable overlay applied. Never raises."""
    now = _now(now)
    overlay = load_store()["items"]
    items, notes = [], []
    for name, fn in (sources if sources is not None else SOURCES).items():
        try:
            rows = fn(now)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{name} could not be read ({type(exc).__name__})")
            continue
        for row in rows:
            held = overlay.get(row["id"])
            if (row["source"] != "work" and isinstance(held, dict)
                    and held.get("native_state") == row["native_state"]
                    and held.get("state") in ws.WORK_WAITING):
                row = {**row, **{k: held[k] for k in ("state", "reason", "next", "not_before") if k in held}}
            items.append(row)
    return items, notes


# ---- the picker -----------------------------------------------------------------------

def _halted() -> dict | None:
    try:
        from aletheia import policy
        return policy.halted()
    except Exception:
        return {"reason": "the kill switch could not be read (fail closed)"}


def _blocked_by(unmet: list[dict]) -> dict:
    ranked = sorted(unmet, key=lambda u: PRECEDENCE.index(u["blocked_state"])
                    if u["blocked_state"] in PRECEDENCE else len(PRECEDENCE))
    first = ranked[0]
    stamps = [_parse(u.get("not_before")) for u in unmet if u.get("not_before")]
    return {"state": first["blocked_state"], "reason": "; ".join(u["why"] for u in ranked)[:300],
            "next": first.get("wake") or "when that is available",
            "not_before": _stamp(max(stamps)) if stamps else None,
            "unmet": [u["requirement"] for u in ranked]}


def assess(it: dict, now: dt.datetime, *, probe: bool = False, persist: bool = False,
           halted: dict | None = None) -> dict:
    """What one item can do NOW: {"verdict": run|wait|skip, ...}. Never raises."""
    state = it["state"]
    if state in ws.WORK_TERMINAL or state == ws.RUNNING:
        return {"verdict": "skip"}
    if halted:
        return {"verdict": "wait", "state": ws.BLOCKED_USER, "checkpoint": False,
                "reason": f"Aletheia is halted ({halted.get('reason') or 'kill switch on'})",
                "next": "when Caleb resumes her (she never lifts her own kill switch)", "not_before": None}
    if state in (ws.BLOCKED_USER, ws.BLOCKED_LOGIN, ws.BLOCKED_EXTERNAL):
        # A person or the world has to move first; its own store says when.
        items_reqs = [r for r in it["requires"] if r in wr.ITEM_REQUIREMENTS]
        if not items_reqs or wr.unmet(items_reqs, it, now=now):
            return {"verdict": "wait", "state": state, "reason": it["reason"], "next": it["next"],
                    "not_before": it.get("not_before"), "checkpoint": False}
    not_before = _parse(it.get("not_before"))
    if state == ws.RETRY_LATER and not_before and not_before > now:
        return {"verdict": "wait", "state": state, "reason": it["reason"], "next": it["next"],
                "not_before": it["not_before"], "checkpoint": False}
    requires = list(it["requires"])
    if state == ws.NEEDS_STRONGER_MODEL and "frontier_reasoning" not in requires:
        requires.append("frontier_reasoning")
    unmet = wr.unmet(requires, it, now=now, probe=probe, persist=persist)
    if unmet:
        blocked = _blocked_by(unmet)
        if (state == ws.NEEDS_STRONGER_MODEL or it.get("stronger")) and blocked["state"] == ws.BLOCKED_MODEL:
            blocked["state"] = ws.NEEDS_STRONGER_MODEL
        return {"verdict": "wait", **blocked,
                "checkpoint": (blocked["state"], blocked["reason"], blocked.get("not_before"))
                != (state, it["reason"], it.get("not_before"))}
    return {"verdict": "run", "woke": state != ws.READY, "was": state}


def pick(items: list[dict], now: dt.datetime | None = None, *, probe: bool = False,
         persist: bool = False) -> dict:
    """Split items into executable now / waiting, never letting one block another."""
    now = _now(now)
    halted = _halted()
    runnable, waiting, woke, checkpoints, counts = [], [], [], [], {s: 0 for s in sorted(ws.WORK_STATES)}
    for it in sorted(items, key=lambda i: (i.get("priority", 3), i.get("updated") or "", i["id"])):
        try:
            verdict = assess(it, now, probe=probe, persist=persist, halted=halted)
        except Exception as exc:  # noqa: BLE001 - one broken item never stops the rest
            verdict = {"verdict": "wait", "state": ws.RETRY_LATER, "checkpoint": True,
                       "reason": f"could not be assessed ({type(exc).__name__})", "next": "look again",
                       "not_before": _stamp(now + dt.timedelta(minutes=15))}
        if verdict["verdict"] == "skip":
            counts[it["state"]] += 1
            continue
        if verdict["verdict"] == "run":
            view = {**it, "state": ws.READY}
            if verdict.get("woke"):
                woke.append({"id": it["id"], "was": verdict["was"]})
                view.update(reason="", next=it.get("next") if it["source"] != "work" else "run it",
                            not_before=None)
            runnable.append(view)
            counts[ws.READY] += 1
            continue
        view = {**it, "state": verdict["state"], "reason": verdict["reason"], "next": verdict["next"],
                "not_before": verdict.get("not_before"), "unmet": verdict.get("unmet", [])}
        waiting.append(view)
        counts[view["state"]] += 1
        if verdict.get("checkpoint"):
            checkpoints.append(view)
    return {"as_of": _stamp(now), "halted": bool(halted), "counts": counts, "executable": runnable,
            "blocked": waiting, "woke": woke, "checkpoints": checkpoints}


# ---- running native items: a gap becomes its next action --------------------------------

def _run_gap(it: dict, now: dt.datetime) -> dict:
    from aletheia import work_gaps
    return work_gaps.act(it, now=now)


RUNNERS: dict[str, Callable[[dict, dt.datetime], dict]] = {"gap": _run_gap}


def _write_checkpoints(store: dict, views: list[dict], now: dt.datetime) -> list[str]:
    changed = []
    for view in views:
        held = dict(store["items"].get(view["id"]) or {})
        base = held if view["source"] == "work" else {"id": view["id"], "source": view["source"],
                                                     "title": view["title"]}
        base.update({k: view.get(k) for k in ("state", "reason", "next", "not_before")})
        base["native_state"] = view["native_state"] if view["source"] != "work" else base.get("native_state", "")
        base["updated"] = _stamp(now)
        _history(base, f"-> {view['state']}: {view['reason'][:120]}", now)
        store["items"][view["id"]] = base
        changed.append(view["id"])
        _journal("event", view["id"], f"checkpointed {view['state']}: {view['reason'][:160]}; next: {view['next'][:80]}")
    return changed


def reconcile(now: dt.datetime | None = None, *, probe: bool = True, max_runs: int = MAX_RUNS_PER_BEAT,
              sources: dict | None = None) -> dict:
    """One beat: gather, pick, checkpoint the blocked, wake the cleared, run native items.
    Called from `runtime.tick`. Writes only the engine's own store (and whatever the
    existing gates a native item's next action goes through write)."""
    now = _now(now)
    try:
        from aletheia import work_gaps
        work_gaps.file_from_demand(now=now)
    except Exception:  # noqa: BLE001
        pass
    items, notes = gather(now, sources=sources)
    picked = pick(items, now, probe=probe, persist=True)
    store = load_store()
    changed = _write_checkpoints(store, picked["checkpoints"], now)
    for w in picked["woke"]:
        held = store["items"].get(w["id"])
        if isinstance(held, dict):
            held.update(state=ws.READY, reason="", not_before=None, updated=_stamp(now))
            if held.get("source") != "work":
                store["items"].pop(w["id"], None)
            else:
                _history(held, f"woke from {w['was']}", now)
            _journal("event", w["id"], f"woke: {w['was']} cleared")
    ran = []
    for it in picked["executable"]:
        if len(ran) >= max_runs or picked["halted"]:
            break
        runner = RUNNERS.get(it.get("kind") or "") if it["source"] == "work" else None
        if runner is None:
            continue
        held = store["items"].get(it["id"]) or it
        try:
            outcome = runner(it, now)
        except Exception as exc:  # noqa: BLE001
            outcome = {"state": ws.RETRY_LATER, "reason": f"the runner failed ({type(exc).__name__}: {exc})"[:200],
                       "next": "try again", "not_before": _stamp(now + dt.timedelta(minutes=30))}
        held.update({k: outcome.get(k, held.get(k)) for k in ("state", "reason", "next", "not_before")})
        held["updated"] = _stamp(now)
        _history(held, f"ran -> {held['state']}: {str(held.get('reason') or held.get('next'))[:120]}", now)
        store["items"][it["id"]] = held
        ran.append({"id": it["id"], "state": held["state"], "next": held.get("next")})
        _journal("action", it["id"], f"work ran -> {held['state']}: {str(held.get('next') or '')[:160]}")
    if changed or picked["woke"] or ran:
        save_store(store)
    return {"counts": picked["counts"], "executable": len(picked["executable"]), "checkpointed": changed,
            "woke": picked["woke"], "ran": ran, "notes": notes}


# ---- the read-only inventory -------------------------------------------------------------

def inventory(now: dt.datetime | None = None, *, probe: bool = False, sources: dict | None = None,
              listed: int = 12, with_availability: bool = True, with_gaps: bool = True) -> dict:
    """What there is, what can run now, what is blocked and why. Writes nothing."""
    now = _now(now)
    items, notes = gather(now, sources=sources)
    picked = pick(items, now, probe=probe, persist=False)
    by_source: dict[str, int] = {}
    for it in items:
        if it["state"] not in ws.WORK_TERMINAL:
            by_source[it["source"]] = by_source.get(it["source"], 0) + 1

    def brief(it: dict) -> dict:
        return {"id": it["id"], "title": it["title"], "state": it["state"], "reason": it.get("reason", ""),
                "next": it.get("next", ""), "not_before": it.get("not_before"),
                "requires": it.get("requires", []), "owner": it.get("owner", "")}
    unfinished = len(picked["executable"]) + len(picked["blocked"]) + picked["counts"].get(ws.RUNNING, 0)
    return {"as_of": _stamp(now), "halted": picked["halted"], "counts": picked["counts"],
            "unfinished": unfinished, "by_source": by_source,
            "executable_now": [brief(i) for i in picked["executable"][:listed]],
            "executable_total": len(picked["executable"]),
            "blocked": [brief(i) for i in picked["blocked"][:listed * 2]],
            "blocked_total": len(picked["blocked"]),
            "availability": ({k: {"ok": v["ok"], "why": v["why"], "live": v["live"],
                                  "unverified": bool(v.get("unverified"))}
                              for k, v in wr.availability(now=now, probe=probe).items()}
                             if with_availability else {}),
            "gaps_to_file": _gaps_preview() if with_gaps else [],
            "notes": notes}


def _gaps_preview() -> list[dict]:
    """What the next beat would file from the demand ledger, classified. Writes nothing."""
    try:
        from aletheia import work_gaps
        return [{"capability": v["capability"], "outcome": v["outcome"], "why": v["why"], "next": v["next"]}
                for v in work_gaps.preview_from_demand()]
    except Exception as exc:  # noqa: BLE001
        return [{"capability": "", "outcome": "", "why": f"the demand ledger could not be read ({type(exc).__name__})",
                 "next": ""}]


def summary(now: dt.datetime | None = None) -> dict:
    """The compact block current_state and mission control show. Never raises; no probes."""
    try:
        inv = inventory(now, probe=False, listed=8, with_availability=False, with_gaps=False)
    except Exception as exc:  # noqa: BLE001
        return {"readable": False, "note": f"the work inventory could not be read ({type(exc).__name__})"}
    return {"readable": True, "as_of": inv["as_of"], "halted": inv["halted"],
            "counts": {k: v for k, v in inv["counts"].items() if v}, "unfinished": inv["unfinished"],
            "executable_total": inv["executable_total"], "executable_now": inv["executable_now"][:5],
            "blocked_total": inv["blocked_total"], "blocked": inv["blocked"][:8],
            "said": spoken(inv), "notes": inv["notes"]}


def spoken(inv: dict) -> str:
    """One or two sentences for the room."""
    run, blocked = inv.get("executable_total", 0), inv.get("blocked_total", 0)
    if inv.get("halted"):
        return "I'm halted, so nothing runs until you resume me."
    if not run and not blocked:
        return "There is no unfinished work on record."
    parts = [f"{run} thing{'s' if run != 1 else ''} I can work on now"]
    if blocked:
        parts.append(f"{blocked} waiting")
    return "I have " + " and ".join(parts) + "."


def render(inv: dict) -> str:
    lines = [f"WORK INVENTORY  {inv['as_of']}" + ("  [HALTED]" if inv.get("halted") else "")]
    avail = inv.get("availability") or {}
    lines.append("minds and tools:")
    for key, val in avail.items():
        mark = "NO " if not val["ok"] else ("?? " if val.get("unverified") else "ok ")
        lines.append(f"  {mark} {key:19} {val['why']}")
    counts = {k: v for k, v in (inv.get("counts") or {}).items() if v}
    lines.append("counts: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    lines.append("unfinished by source: " + ", ".join(f"{k}={v}" for k, v in inv.get("by_source", {}).items()))
    lines.append(f"\nCAN RUN NOW ({inv['executable_total']}):")
    for it in inv["executable_now"]:
        lines.append(f"  - [{it['id']}] {it['title'][:90]}" + (f"  (next: {it['next']})" if it['next'] else ""))
    lines.append(f"\nBLOCKED / WAITING ({inv['blocked_total']}):")
    for it in inv["blocked"]:
        when = f" not before {it['not_before']}" if it.get("not_before") else ""
        lines.append(f"  - {it['state']:20} [{it['id']}] {it['title'][:80]}")
        lines.append(f"      why: {it['reason'][:160]}")
        lines.append(f"      next: {it['next'][:120]}{when}")
    gaps = inv.get("gaps_to_file") or []
    if gaps:
        lines.append(f"\nCAPABILITY GAPS FROM THE DEMAND LEDGER ({len(gaps)}), classified:")
        for g in gaps:
            lines.append(f"  - {g['capability']}: {g['outcome']} ({g['why']}); next: {g['next']}")
    for note in inv.get("notes") or []:
        lines.append(f"note: {note}")
    return "\n".join(lines)


def _read_live_repo(root: str) -> None:
    """Point the repo-anchored stores at another checkout, for READING (the inventory)."""
    from pathlib import Path
    from aletheia import plans, policy, tasks
    base = Path(root)
    tasks.TASKS_DIR = base / "state" / "tasks"
    plans.PLANS_DIR = base / "plans"
    policy.HALT_PATH = base / "state" / "policy" / "halt.json"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aletheia's work inventory (read-only).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    inv = sub.add_parser("inventory", help="what there is, what can run now, what is blocked and why")
    inv.add_argument("--frontier-off", action="store_true",
                     help="simulate Claude/Codex/ChatGPT unavailable (sets ALETHEIA_FRONTIER_OFF)")
    inv.add_argument("--probe", action="store_true", help="make the expensive live checks (a browser load)")
    inv.add_argument("--repo-root", help="read tasks/plans/halt from this checkout (read-only)")
    inv.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.frontier_off:
        from aletheia import reasoning_gateway
        os.environ[reasoning_gateway.FRONTIER_OFF_ENV] = "1"
    if args.repo_root:
        _read_live_repo(args.repo_root)
    value = inventory(probe=args.probe)
    print(json.dumps(value, indent=2, ensure_ascii=False) if args.json else render(value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
