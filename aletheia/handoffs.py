"""Handoffs: a tool request her session could not run, made durable and approvable.

`agent_session.Broker` decides that a request which writes, reaches the
world or needs his approval does not run INSIDE the loop. Until this module
that decision was a sentence in the session's result and nothing else: the
request was forgotten the moment the session ended, so "hand it to Caleb"
meant "drop it".

Now a handoff is a record and an ordinary approval:

    AgentSession -> Broker says HANDOFF -> handoffs.file()
        -> private record (tool, args, why, session, request_sha256)
        -> policy.request(): the SAME approval every other thing he approves
           goes through (Command Center button, voice, phone issue, and a
           standing grant he has given, where the registry allows one)
    Caleb approves -> handoffs.run_approved() on the Core's beat
        -> every gate again -> execute exactly that request -> receipt
        -> the record, the session record and the ribbon show the outcome

THE BINDING. The approval's `requested_action` carries a sha256 of the exact
request (tool name and arguments, canonical JSON), and so does the record.
At execution both are recomputed from what is about to run: a record edited
on disk, an approval re-pointed at another request, or arguments that
changed in any way are REFUSED, never adapted. The pattern is the one
ratified for computer control and for intents.

ONCE. The record is claimed (RUNNING, written to disk) before the tool runs,
so a second approve, a second beat or a restart cannot run it again. A
record found RUNNING with nobody running it is INTERRUPTED and never
replayed: whether the world changed is unknown.

WHAT NOTHING HERE CAN DO:

- approve itself. An approval decided by one of her own processes (any
  `aletheia-*` or `agent*` actor) is refused, and `approve`, `deny`,
  `resume` are never filed as handoffs at all.
- spend. The broker's spending check (`webtask.would_spend`, the predicate
  every gate shares) runs again at execution and refuses permanently; a
  spending request is never even filed, because no approval can make it
  happen and a pending one would invite him to try.
- outrun the kill switch. Halted, nothing executes; the approved request
  waits (and goes stale like any other approval if the halt outlasts it).

Private state, one JSON file per handoff: the arguments are often his words.
The journal (which is committed) gets the tool name and the id, never them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import threading
import time
from typing import Any, Callable

from aletheia import stateio

ACTOR = "aletheia-handoff"

AWAITING = "AWAITING_APPROVAL"
RUNNING = "RUNNING"
DONE = "DONE"
FAILED = "FAILED"
DENIED = "DENIED"
EXPIRED = "EXPIRED"
REFUSED = "REFUSED"
INTERRUPTED = "INTERRUPTED"
STATES = (AWAITING, RUNNING, DONE, FAILED, DENIED, EXPIRED, REFUSED, INTERRUPTED)
FINISHED = (DONE, FAILED, DENIED, EXPIRED, REFUSED, INTERRUPTED)

#: Tools that decide about authority itself. Never a handoff: a model asking
#: to approve, deny or resume is asking to authorise itself.
SELF_AUTHORITY = frozenset({"approve", "deny", "resume"})

#: `decided_via` prefixes that are her, not him.
HER_OWN = ("aletheia", "agent")

#: How long an approved request may run. A form on someone else's site can
#: take minutes; a local note takes a moment.
SLOW_TIMEOUT_S = 1800.0
QUICK_TIMEOUT_S = 120.0
MAX_OBSERVATION = 1200

_LOCK = threading.Lock()
_IN_FLIGHT: set[str] = set()


class NotFiled(ValueError):
    """The request cannot become a handoff (and says why)."""


def handoffs_dir():
    return stateio.private_dir("handoffs")


def _path(hid: str):
    return handoffs_dir() / f"{stateio.safe_id(hid, name='handoff id')}.json"


def load(hid: str) -> dict:
    return stateio.read_json(_path(hid))


def save(record: dict) -> dict:
    record["updated_at"] = stateio.utcnow()
    stateio.write_json_atomic(_path(record["id"]), record)
    return record


def all_handoffs(state: str | None = None) -> list[dict]:
    folder = handoffs_dir()
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob("handoff-*.json")):
        try:
            value = stateio.read_json(path)
        except (OSError, ValueError):
            continue
        if state is None or value.get("state") == state:
            out.append(value)
    return out


def request_digest(tool: str, args: Any) -> str:
    """The fingerprint of exactly what would run."""
    raw = json.dumps({"tool": str(tool), "args": args}, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def action_for(tool: str, digest: str) -> str:
    return f"agent.handoff:{tool} sha256:{digest}"


def _args_words(args: dict, limit: int = 160) -> str:
    bits = []
    for key, value in args.items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, default=str)
        said = " ".join(str(value).split())
        bits.append(f"{key} “{said[:70]}”" if len(said) > 0 else key)
    text = ", ".join(bits)
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "..."


def consequence_for(tool, args: dict) -> str:
    """What will happen if he says yes, in words he can decide on."""
    from aletheia import sensitivity
    name = str(getattr(tool, "name", tool))
    what = " ".join(str(getattr(tool, "description", "") or "").split())
    what = what.split(". ")[0].rstrip(".")
    if len(what) > 110:
        what = what[:110].rsplit(" ", 1)[0] + "..."
    head = f"Run {name}" + (f" ({what})" if what else "")
    tail = _args_words(args)
    return sensitivity.clean(head + (f" with {tail}" if tail else ""))[:400]


def _reversible(tool) -> bool:
    from aletheia import intercom
    return not (getattr(tool, "destructive", False) or getattr(tool, "open_world", False)
                or getattr(tool, "risk", "") == intercom.TIER_WORLD)


def _spends(tool, args: dict) -> bool:
    from aletheia import agent_session
    return agent_session.Broker.spends(tool, args)


def file(*, tool, args: dict, session_id: str, question: str = "", why: str = "",
         reason: str = "", audience: str = "local") -> dict:
    """Make one handed-off request a durable pending approval. Returns the
    record. Raises `NotFiled` for what must never wait on a yes."""
    from aletheia import journal, policy, sensitivity
    name = str(getattr(tool, "name", "") or "")
    if not name:
        raise NotFiled("a handoff needs a tool")
    if name in SELF_AUTHORITY:
        raise NotFiled(f"{name} decides about authority itself, so it is never handed off")
    if not getattr(tool, "read_only", False) and _spends(tool, args):
        raise NotFiled("that would spend money, and no approval can make that happen")
    args = json.loads(json.dumps(args or {}, default=str))
    digest = request_digest(name, args)
    for open_one in all_handoffs(AWAITING):
        if open_one.get("request_sha256") == digest:
            return open_one            # one question for one request, however often it is asked
    hid = "handoff-" + hashlib.sha256(f"{session_id}|{digest}".encode("utf-8")).hexdigest()[:12]
    if _path(hid).exists():
        return load(hid)
    question = sensitivity.clean(" ".join(str(question or "").split()))[:300]
    record = {
        "id": hid, "approval": hid, "state": AWAITING, "tool": name, "args": args,
        "request_sha256": digest, "session": str(session_id), "question": question,
        "why": sensitivity.clean(str(why or ""))[:200], "broker_reason": str(reason or "")[:300],
        "audience": audience, "capability": getattr(tool, "capability", None),
        "consequence": consequence_for(tool, args), "created_at": stateio.utcnow(),
        "receipts": [],
    }
    save(record)
    asked = f"Thea asked for this while answering “{question[:160]}”" if question else "Thea asked for this"
    approval = policy.request(
        hid, action_for(name, digest),
        reason=asked + (f": {record['why']}" if record["why"] else ""),
        consequence=record["consequence"], reversible=_reversible(tool),
        capability=getattr(tool, "capability", None) or None)
    record["approval_state_at_filing"] = approval.get("state")
    save(record)
    journal.append("event", "handoff", f"{hid}: handed {name} to Caleb for approval", actor=ACTOR)
    return record


# ---- after he decides ---------------------------------------------------------

def _her_own(via: str) -> bool:
    return str(via or "").strip().lower().startswith(HER_OWN)


def _finish(record: dict, state: str, said: str, *, receipt: dict | None = None) -> dict:
    from aletheia import journal
    record["state"] = state
    record["outcome"] = said[:400]
    record["finished_at"] = stateio.utcnow()
    if receipt is not None:
        record.setdefault("receipts", []).append(receipt)
    save(record)
    kind = {DONE: "action", DENIED: "decision", EXPIRED: "decision"}.get(state, "alert")
    try:
        journal.append(kind, "handoff",
                       f"{record['id']}: {record.get('tool')} {state.lower().replace('_', ' ')}", actor=ACTOR)
    except Exception:
        pass
    _update_session(record)
    return record


def _update_session(record: dict) -> None:
    """The session that asked shows what became of it. Never raises."""
    try:
        path = stateio.private_dir("agent-sessions") / f"{stateio.safe_id(record['session'], name='session id')}.json"
        session = stateio.read_json(path)
    except Exception:
        return
    changed = False
    for entry in session.get("handoffs") or []:
        if isinstance(entry, dict) and entry.get("handoff") == record["id"]:
            entry.update({"state": record["state"], "outcome": record.get("outcome", ""),
                          "finished_at": record.get("finished_at")})
            changed = True
    if changed:
        try:
            stateio.write_json_atomic(path, session)
        except Exception:
            pass


def _notify(record: dict) -> None:
    try:
        from aletheia import notifications
        state = record["state"]
        title = {DONE: "Done: what you approved",
                 FAILED: "What you approved did not work",
                 REFUSED: "I refused what you approved",
                 INTERRUPTED: "What you approved was interrupted"}.get(state)
        if not title:
            return
        notifications.publish(title, f"{record.get('consequence', '')[:200]} - {record.get('outcome', '')}"[:400],
                              priority="NORMAL" if state == DONE else "IMPORTANT", source="handoff",
                              dedupe_key=f"handoff-{state.lower()}:{record['id']}",
                              related={"handoff": record["id"]})
    except Exception:
        pass


def _recover_interrupted() -> list[dict]:
    from aletheia import proc
    out = []
    for record in all_handoffs(RUNNING):
        if record["id"] in _IN_FLIGHT:
            continue
        pid = record.get("pid")
        if pid and pid != os.getpid() and proc.pid_alive(pid) is True:
            continue
        _finish(record, INTERRUPTED, "it stopped while running; whether it changed anything is "
                                     "unknown, so it is not run again - ask again if you still want it")
        _notify(record)
        out.append({"handoff": record["id"], "outcome": INTERRUPTED})
    return out


def run_approved(*, catalog: dict | None = None, halted: Callable[[], Any] | None = None,
                 timeout_s: float | None = None) -> list[dict]:
    """Execute every handoff he approved, exactly once each. Called from the
    Core's beat and the moment he says yes. Returns what it did."""
    with _LOCK:
        return _run_approved(catalog=catalog, halted=halted, timeout_s=timeout_s)


def _is_halted(halted) -> bool:
    try:
        if halted is not None:
            return bool(halted())
        from aletheia import policy
        return policy.halted() is not None
    except Exception:
        return True


def _run_approved(*, catalog, halted, timeout_s) -> list[dict]:
    from aletheia import agent_session, policy, power, tools
    done = _recover_interrupted()
    waiting = all_handoffs(AWAITING)
    if not waiting:
        return done
    catalog = catalog if catalog is not None else tools.catalog()
    for record in waiting:
        hid = record["id"]
        try:
            approval = policy.load(record.get("approval") or hid)
        except (OSError, ValueError, KeyError):
            _finish(record, FAILED, "its approval is missing, so it cannot be run")
            done.append({"handoff": hid, "outcome": FAILED})
            continue
        state = approval.get("state")
        if state == "DENIED":
            _finish(record, DENIED, "you said no, so it did not run")
            done.append({"handoff": hid, "outcome": DENIED})
            continue
        if state == "EXPIRED":
            _finish(record, EXPIRED, str(approval.get("expired_because") or "the approval expired before it ran"))
            done.append({"handoff": hid, "outcome": EXPIRED})
            continue
        if state != "APPROVED":
            continue
        usable, why = policy.usable(approval["id"])
        if not usable:
            _finish(record, EXPIRED, why)
            done.append({"handoff": hid, "outcome": EXPIRED})
            continue
        if _her_own(approval.get("decided_via", "")):
            _finish(record, REFUSED, "the approval was decided by one of my own processes, and I "
                                     "never approve my own requests")
            _notify(record)
            done.append({"handoff": hid, "outcome": REFUSED})
            continue
        name, args = str(record.get("tool") or ""), record.get("args")
        digest = request_digest(name, args)
        if (digest != record.get("request_sha256")
                or approval.get("requested_action") != action_for(name, digest)):
            _finish(record, REFUSED, "the request changed after it was approved, so I will not run "
                                     "something you did not approve")
            _notify(record)
            done.append({"handoff": hid, "outcome": REFUSED})
            continue
        if _is_halted(halted):
            done.append({"handoff": hid, "outcome": "halted", "detail": "approved, waiting for resume"})
            continue
        tool = catalog.get(name)
        if tool is None or not isinstance(args, dict):
            _finish(record, FAILED, f"there is no tool named {name} any more")
            done.append({"handoff": hid, "outcome": FAILED})
            continue
        broker = agent_session.Broker(catalog, audience=record.get("audience") or "local",
                                      halted=lambda: _is_halted(halted))
        decision = broker.check(agent_session.ToolRequest(name, args))
        if decision.verdict == agent_session.REFUSED:
            _finish(record, REFUSED, f"refused when it came to run: {decision.reason}")
            _notify(record)
            done.append({"handoff": hid, "outcome": REFUSED})
            continue
        # CLAIMED ON DISK BEFORE IT RUNS: nothing after this line can run it twice.
        record.update({"state": RUNNING, "started_at": stateio.utcnow(), "pid": os.getpid(),
                       "approved_via": str(approval.get("decided_via") or "")})
        save(record)
        _IN_FLIGHT.add(hid)
        slow = tool.open_world or tool.risk == "world"
        limit = timeout_s if timeout_s is not None else (SLOW_TIMEOUT_S if slow else QUICK_TIMEOUT_S)
        started = time.monotonic()
        try:
            with power.keep_awake(f"approved {name}"):
                outcome, result = agent_session.execute(
                    tool, dict(args), timeout_s=limit,
                    quote=f"approved by Caleb ({approval.get('decided_via')}): {record.get('question', '')[:160]}")
        finally:
            _IN_FLIGHT.discard(hid)
        observation, hidden = agent_session.sanitise(result, tool.provenance, limit=MAX_OBSERVATION)
        receipt = {"at": stateio.utcnow(), "outcome": outcome,
                   "duration_ms": round((time.monotonic() - started) * 1000),
                   "observation": observation, "redacted": hidden,
                   "observation_sha256": hashlib.sha256(observation.encode("utf-8")).hexdigest(),
                   "request_sha256": digest, "approval": approval["id"]}
        if outcome == "ok":
            _finish(record, DONE, _said_result(result), receipt=receipt)
        else:
            _finish(record, FAILED, f"{outcome}: {_said_result(result)}", receipt=receipt)
        _notify(record)
        done.append({"handoff": hid, "outcome": record["state"]})
    return done


def _said_result(result: Any) -> str:
    if isinstance(result, dict):
        for key in ("text", "said", "error", "note"):
            if result.get(key):
                return " ".join(str(result[key]).split())[:300]
    return " ".join(json.dumps(result, ensure_ascii=False, default=str).split())[:300]


_BACKGROUND: dict[str, Any] = {"thread": None}


def start_approved() -> bool:
    """Run the approved handoffs off the caller's thread (the Core's beat must
    not wait minutes on a website). False when a run is already going."""
    worker = _BACKGROUND.get("thread")
    if worker is not None and worker.is_alive():
        return False

    def body():
        try:
            run_approved()
        except Exception as exc:  # noqa: BLE001
            try:
                from aletheia import journal
                journal.append("alert", "handoff", f"approved handoffs could not run ({type(exc).__name__})",
                               actor=ACTOR)
            except Exception:
                pass
    worker = threading.Thread(target=body, name="aletheia-handoffs", daemon=True)
    _BACKGROUND["thread"] = worker
    worker.start()
    return True


def describe(record: dict) -> str:
    state = record.get("state")
    what = record.get("consequence") or record.get("tool") or "a request"
    if state == AWAITING:
        return f"Waiting for your yes or no: {what}."
    if state == RUNNING:
        return f"Doing what you approved: {what}."
    return f"{what}: {str(state).lower().replace('_', ' ')} - {record.get('outcome', '')}".strip(" -")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Requests her sessions handed to Caleb.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("run-approved", help="execute what he approved, once each")
    args = ap.parse_args(argv)
    if args.cmd == "list":
        for record in all_handoffs():
            print(f"[{record.get('state'):17}] {record['id']}  {describe(record)}")
        return 0
    print(json.dumps(run_approved(), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
