"""Waiting is a state, not a failure: the durable wait and what wakes it.

His continuity brief (docs/CONTINUITY_BRIEF.md), Part IV.14: *"Waiting for a
recruiter, a landlord, a result, a showing date, a model, Caleb, tomorrow, a
verification, any external condition: states, not failures. Remember them,
wake them when appropriate, keep working meanwhile."* And rule 3: every
unfinished thing has a reason and a next condition.

So a WAIT is one small durable record (`state/private/waits/<id>.json`):

- `item`       what is waiting (any id: a long-mission task, an outbound
               message, a work item). Waits know nothing about what it is.
- `owner`      who is told when something happens to it (`HANDLERS`).
- `reason`     why it is waiting, in a sentence he can hear.
- `condition`  what wakes it: one of `CONDITION_KINDS` (below), checked on the
               Core's beat through the work engine (`reconcile`).
- `follow_up`  when to nudge and whether a nudge needs his approval. Waits
               never send anything: a due nudge is handed to the owner, and an
               owner that sends goes through its own gates.
- `timeout`    when to stop waiting and what that MEANS. A timeout is not a
               failure: it wakes the item with outcome "timeout" and the
               meaning attached, so the owner decides the next action.

THE PUBLIC API (stable; the outbound-communication and calendar layers build on
it):

    wait_for(item, condition, *, reason, owner="", follow_up=None, timeout=None,
             key="", now=None) -> wait record           (idempotent per item+key)
    check(wait, now=None) -> {"met": bool, "outcome", "evidence", "why"}
    reconcile(now=None) -> [transitions]                 (the beat)
    decide(wait_id, choice, *, words, via, now=None)     (his answer; never hers)
    signal(kind, subject, summary, *, attributes=None, source=...) -> event
    cancel(wait_id, *, why, now=None)
    waiting(owner=None, item=None) / for_item(item) / load(wait_id) / all_waits()
    register(owner, "module:function")                   (who hears about it)

Condition kinds (`{"kind": ..., ...}`):

    time_after       {"at": ISO}                      a date, tomorrow, a showing
    reply_from       {"thread_id", "participant", "after_message_id"?}
                     or {"expectation_id"}            a person answers
                     (read from `aletheia.communications`, the channel-neutral store)
    event            {"event_kind", "subject_prefix"?, "attributes"?}
                     something happened (`aletheia.events`; `signal` emits one)
    user_decision    {"question", "options"?}         Caleb chooses (`decide`)
    approval         {"approval_id"}                  Caleb approves or denies
    handoff          {"handoff_id"}                   a handed-off request finished
    model_available  {"requirement"?}                 a model can think again
    requirement      {"requirement"}                  any world requirement returns
    verification     {"action_id"}                    an action's outcome is verified
    any_of           {"conditions": [...]}            whichever comes first

Each `check` returns the evidence it saw. A handler that raises never stops the
beat, and a wait whose condition cannot be read stays WAITING and says why.
Money and authority are untouched here: waits grant nothing, send nothing,
approve nothing, and `decide` refuses any `via` that is her own.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import importlib
import json
from pathlib import Path
from typing import Any, Callable

from aletheia import stateio, work_states as ws

ACTOR = "aletheia-waits"
VERSION = 1

WAITING, WOKEN, TIMED_OUT, CANCELLED = "WAITING", "WOKEN", "TIMED_OUT", "CANCELLED"
STATES = (WAITING, WOKEN, TIMED_OUT, CANCELLED)
FINISHED = (WOKEN, TIMED_OUT, CANCELLED)

CONDITION_KINDS = ("time_after", "reply_from", "event", "user_decision", "approval", "handoff",
                   "model_available", "requirement", "verification", "any_of")

#: The work state an item holds while it waits on each kind of condition.
WORK_STATE = {
    "time_after": ws.BLOCKED_EXTERNAL,
    "reply_from": ws.BLOCKED_EXTERNAL,
    "event": ws.BLOCKED_EXTERNAL,
    "handoff": ws.BLOCKED_USER,
    "verification": ws.BLOCKED_EXTERNAL,
    "user_decision": ws.BLOCKED_USER,
    "approval": ws.BLOCKED_USER,
    "model_available": ws.BLOCKED_MODEL,
    "requirement": ws.BLOCKED_EXTERNAL,
}

#: What the owner is told, and when (`HANDLERS`).
WOKE, FOLLOW_UP, TIMEOUT = "woke", "follow_up", "timeout"
TIMEOUT_THEN = ("wake", "ask_caleb", "follow_up")

#: Who hears about a wait, by owner: "module:function(wait, event, now) -> dict|None".
#: A new owner adds one line (or calls `register`). Resolved lazily, so this
#: module imports nothing heavy and anything may import it.
HANDLERS: dict[str, str] = {
    "programs": "aletheia.programs:on_wait",
}

#: A handler's own id, never accepted as the author of his decision.
HER_OWN_VIA = ("aletheia", "agent", "thea")
MAX_HISTORY = 30


class WaitError(ValueError):
    pass


# ---- time --------------------------------------------------------------------------

def _now(now: dt.datetime | None = None) -> dt.datetime:
    value = now or dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise WaitError("now must be timezone-aware")
    return value.astimezone(dt.timezone.utc)


def stamp(when: dt.datetime) -> str:
    return when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(value: Any) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        when = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)).astimezone(dt.timezone.utc)


# ---- the store -----------------------------------------------------------------------

def waits_dir() -> Path:
    return stateio.private_dir("waits")


def _path(wait_id: str) -> Path:
    return waits_dir() / f"{stateio.safe_id(wait_id, name='wait id')}.json"


def load(wait_id: str) -> dict:
    return stateio.read_json(_path(wait_id))


def save(record: dict) -> dict:
    stateio.write_json_atomic(_path(record["id"]), record)
    return record


def all_waits() -> list[dict]:
    root = waits_dir()
    if not root.is_dir():
        return []
    out = []
    for path in sorted(root.glob("wait-*.json")):
        try:
            value = stateio.read_json(path)
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("id") == path.stem:
            out.append(value)
    return out


def waiting(owner: str | None = None, item: str | None = None) -> list[dict]:
    return [w for w in all_waits() if w.get("state") == WAITING
            and (owner is None or w.get("owner") == owner)
            and (item is None or w.get("item") == item)]


def for_item(item: str) -> list[dict]:
    return [w for w in all_waits() if w.get("item") == item]


def _journal(kind: str, subject: str, text: str) -> None:
    try:
        from aletheia import journal
        journal.append(kind, subject, text[:400], actor=ACTOR)
    except Exception:
        pass


def _history(record: dict, text: str, now: dt.datetime) -> None:
    rows = list(record.get("history") or [])
    rows.append({"at": stamp(now), "did": str(text)[:200]})
    record["history"] = rows[-MAX_HISTORY:]


# ---- validation ------------------------------------------------------------------------

def _seconds(value: Any, name: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise WaitError(f"{name} must be a number of seconds") from exc
    if seconds < 0:
        raise WaitError(f"{name} must not be negative")
    return seconds


def validate_condition(condition: Any) -> dict:
    """The condition, normalised. Raises WaitError on anything it cannot check."""
    if not isinstance(condition, dict):
        raise WaitError("a condition must be an object with a kind")
    kind = condition.get("kind")
    if kind not in CONDITION_KINDS:
        raise WaitError(f"condition kind {kind!r} is not one of {', '.join(CONDITION_KINDS)}")
    out = dict(condition)
    if kind == "time_after":
        if parse(out.get("at")) is None:
            raise WaitError("time_after needs an ISO time in 'at'")
        out["at"] = stamp(parse(out["at"]))
    elif kind == "reply_from":
        if not out.get("expectation_id") and not (out.get("thread_id") and out.get("participant")):
            raise WaitError("reply_from needs an expectation_id, or a thread_id and a participant")
    elif kind == "event":
        if not str(out.get("event_kind") or "").strip():
            raise WaitError("event needs an event_kind")
        if out.get("attributes") is not None and not isinstance(out["attributes"], dict):
            raise WaitError("event attributes must be an object")
    elif kind == "user_decision":
        if not str(out.get("question") or "").strip():
            raise WaitError("user_decision needs the question he is being asked")
        options = out.get("options")
        if options is not None and (not isinstance(options, list) or not all(isinstance(o, str) for o in options)):
            raise WaitError("user_decision options must be a list of strings")
    elif kind == "approval":
        if not str(out.get("approval_id") or "").strip():
            raise WaitError("approval needs an approval_id")
    elif kind == "handoff":
        if not str(out.get("handoff_id") or "").strip():
            raise WaitError("handoff needs a handoff_id")
    elif kind == "model_available":
        req = out.get("requirement") or "reasoning"
        if req not in {"reasoning", "local_reasoning", "frontier_reasoning"}:
            raise WaitError("model_available requirement must be reasoning, local_reasoning or frontier_reasoning")
        out["requirement"] = req
    elif kind == "requirement":
        if out.get("requirement") not in ws.REQUIREMENTS:
            raise WaitError(f"requirement must be one of {sorted(ws.REQUIREMENTS)}")
        if out["requirement"] in {"user_approval", "user_decision", "external_reply", "payment", "login"}:
            raise WaitError("an item requirement is waited on through its own condition kind "
                            "(approval, user_decision, reply_from); payment is never waited into")
    elif kind == "verification":
        if not str(out.get("action_id") or "").strip():
            raise WaitError("verification needs an action_id")
    elif kind == "any_of":
        inner = out.get("conditions")
        if not isinstance(inner, list) or not inner:
            raise WaitError("any_of needs a non-empty list of conditions")
        out["conditions"] = [validate_condition(c) for c in inner]
        if any(c["kind"] == "any_of" for c in out["conditions"]):
            raise WaitError("any_of does not nest")
    return out


def _validate_follow_up(policy: Any, created: dt.datetime) -> dict | None:
    if policy in (None, {}, False):
        return None
    if not isinstance(policy, dict):
        raise WaitError("follow_up must be an object")
    after = _seconds(policy.get("after_s"), "follow_up.after_s")
    at = parse(policy.get("at"))
    if after is None and at is None:
        raise WaitError("follow_up needs after_s or at: WHEN to nudge")
    every = _seconds(policy.get("every_s"), "follow_up.every_s")
    if every is not None and every < 60:
        raise WaitError("follow_up.every_s must be at least a minute")
    most = policy.get("max", 1)
    if type(most) is not int or not 1 <= most <= 20:
        raise WaitError("follow_up.max must be 1..20")
    first = at or (created + dt.timedelta(seconds=after or 0))
    return {"after_s": after, "at": stamp(at) if at else None, "every_s": every, "max": most,
            # A nudge reaches another person, so by default it asks him first.
            "needs_approval": bool(policy.get("needs_approval", True)),
            "say": str(policy.get("say") or "")[:400],
            "action": dict(policy["action"]) if isinstance(policy.get("action"), dict) else None,
            "next_at": stamp(first), "sent": []}


def _validate_timeout(policy: Any, created: dt.datetime) -> dict | None:
    if policy in (None, {}, False):
        return None
    if not isinstance(policy, dict):
        raise WaitError("timeout must be an object")
    after = _seconds(policy.get("after_s"), "timeout.after_s")
    at = parse(policy.get("at"))
    if after is None and at is None:
        raise WaitError("timeout needs after_s or at")
    means = " ".join(str(policy.get("means") or "").split())
    if not means:
        raise WaitError("timeout needs 'means': what running out of time says (it is not a failure)")
    then = policy.get("then", "wake")
    if then not in TIMEOUT_THEN:
        raise WaitError(f"timeout.then must be one of {TIMEOUT_THEN}")
    return {"at": stamp(at or created + dt.timedelta(seconds=after or 0)), "means": means[:300], "then": then}


def wake_words(condition: dict) -> str:
    """What wakes it, as a phrase for the room: "when <...>"."""
    kind = condition.get("kind")
    if kind == "time_after":
        return f"at {condition['at']}"
    if kind == "reply_from":
        who = condition.get("participant") or "they"
        return f"when {who} replies"
    if kind == "event":
        return f"when {condition.get('describe') or str(condition['event_kind']).replace('.', ' ')} happens"
    if kind == "user_decision":
        return "when Caleb decides: " + str(condition["question"])[:120]
    if kind == "approval":
        return "when Caleb approves or denies it"
    if kind == "handoff":
        return "when the request handed to Caleb has run"
    if kind == "model_available":
        return {"frontier_reasoning": "when a frontier model can think again",
                "local_reasoning": "when her own model is running"}.get(condition["requirement"],
                                                                        "when any model can think again")
    if kind == "requirement":
        return f"when {condition['requirement'].replace('_', ' ')} is available again"
    if kind == "verification":
        return "when the action's outcome is verified"
    if kind == "any_of":
        return " or ".join(wake_words(c) for c in condition["conditions"])
    return "when its condition is met"


def work_state_for(condition: dict) -> str:
    kind = condition.get("kind")
    if kind == "any_of":
        states = [work_state_for(c) for c in condition["conditions"]]
        for preferred in (ws.BLOCKED_USER, ws.BLOCKED_EXTERNAL, ws.BLOCKED_MODEL):
            if preferred in states:
                return preferred
        return states[0]
    if kind == "requirement":
        return ws.BLOCKED_BY.get(condition["requirement"], ws.BLOCKED_EXTERNAL)
    return WORK_STATE.get(kind, ws.BLOCKED_EXTERNAL)


# ---- the one writer -------------------------------------------------------------------

def wait_for(item: str, condition: dict, *, reason: str, owner: str = "", follow_up: dict | None = None,
             timeout: dict | None = None, key: str = "", context: dict | None = None,
             now: dt.datetime | None = None) -> dict:
    """Hold `item` until `condition`. Durable, idempotent per (item, key|condition)."""
    now = _now(now)
    item = " ".join(str(item or "").split())
    if not item:
        raise WaitError("a wait needs the item that waits")
    reason = " ".join(str(reason or "").split())
    if not reason:
        raise WaitError("a wait needs a reason (rule 3: every unfinished thing says why)")
    condition = validate_condition(condition)
    identity = key or json.dumps(condition, sort_keys=True)
    wid = "wait-" + hashlib.sha256(f"{item}|{identity}".encode("utf-8")).hexdigest()[:14]
    path = _path(wid)
    if path.is_file():
        try:
            existing = stateio.read_json(path)
            if existing.get("state") == WAITING:
                return existing
        except ValueError:
            pass
    record = {
        "version": VERSION, "id": wid, "item": item[:200], "owner": str(owner or "")[:60],
        "reason": reason[:300], "condition": condition, "state": WAITING,
        "work_state": work_state_for(condition), "next": wake_words(condition)[:300],
        "follow_up": _validate_follow_up(follow_up, now), "timeout": _validate_timeout(timeout, now),
        "context": json.loads(json.dumps(context or {}, default=str)),
        "created_at": stamp(now), "updated_at": stamp(now), "outcome": None,
    }
    _history(record, f"waiting: {reason[:120]} ({record['next'][:60]})", now)
    save(record)
    _journal("event", f"wait:{wid}", f"{item}: waiting ({record['work_state']}) - {reason}; {record['next']}")
    return record


def cancel(wait_id: str, *, why: str, now: dt.datetime | None = None) -> dict:
    now = _now(now)
    record = load(wait_id)
    if record.get("state") != WAITING:
        return record
    record.update(state=CANCELLED, updated_at=stamp(now),
                  outcome={"outcome": "cancelled", "why": str(why or "")[:200], "at": stamp(now)})
    _history(record, f"cancelled: {why}", now)
    save(record)
    _journal("event", f"wait:{wait_id}", f"{record['item']}: stopped waiting ({why})")
    return record


def _her_own(via: str) -> bool:
    low = str(via or "").strip().lower()
    return not low or any(low.startswith(p) for p in HER_OWN_VIA)


def decide(wait_id: str, choice: str, *, words: str, via: str, now: dt.datetime | None = None) -> dict:
    """Record HIS decision on a user_decision wait. Her own actors are refused:
    a decision she makes for him is not his decision."""
    now = _now(now)
    if _her_own(via):
        raise PermissionError("a decision waiting on Caleb is recorded only from Caleb")
    record = load(wait_id)
    kinds = [record["condition"]["kind"]] + [c["kind"] for c in record["condition"].get("conditions") or []]
    if "user_decision" not in kinds:
        raise WaitError(f"{wait_id} is not waiting on a decision")
    if record.get("state") != WAITING:
        raise WaitError(f"{wait_id} is no longer waiting ({record.get('state')})")
    choice = " ".join(str(choice or "").split())
    if not choice:
        raise WaitError("a decision needs the choice")
    record["decision"] = {"choice": choice[:200], "words": " ".join(str(words or "").split())[:300],
                          "via": str(via)[:60], "at": stamp(now)}
    save(record)
    _journal("decision", f"wait:{wait_id}", f"Caleb decided for {record['item']}: {choice[:120]}")
    return record


def signal(kind: str, subject: str, summary: str, *, attributes: dict | None = None,
           source: str = "aletheia.waits", occurred_at: str | None = None) -> dict:
    """Something happened: an event any `event` wait may wake on (`aletheia.events`)."""
    from aletheia import events
    return events.emit(kind, subject, summary, source=source, attributes=attributes or {},
                       occurred_at=occurred_at)["event"]


# ---- checking one condition ------------------------------------------------------------

def _no(why: str, **evidence) -> dict:
    return {"met": False, "outcome": None, "why": why, "evidence": evidence}


def _yes(outcome: str, why: str, **evidence) -> dict:
    return {"met": True, "outcome": outcome, "why": why, "evidence": evidence}


def _check_reply(cond: dict, record: dict, now: dt.datetime) -> dict:
    from aletheia import communications as comms
    if cond.get("expectation_id"):
        try:
            value = comms.load_expectation(cond["expectation_id"])
        except (ValueError, OSError):
            return _no("the reply expectation could not be read")
        if value.get("status") == "REPLIED":
            return _yes("replied", "the reply arrived", reply_message_id=value.get("reply_message_id"))
        return _no("no reply yet")
    try:
        rows = comms.messages(cond["thread_id"])
    except (ValueError, OSError, KeyError):
        return _no("the conversation could not be read")
    floor = parse(record.get("created_at"))
    anchor_id = cond.get("after_message_id")
    if anchor_id:
        anchor = next((m for m in rows if m.get("id") == anchor_id), None)
        if anchor is not None:
            floor = parse(anchor.get("occurred_at")) or floor
    who = str(cond["participant"]).strip().lower()
    for message in rows:
        when = parse(message.get("occurred_at"))
        if (message.get("direction") == "INBOUND" and str(message.get("participant") or "").strip().lower() == who
                and when is not None and (floor is None or when > floor)):
            return _yes("replied", f"{cond['participant']} replied", reply_message_id=message.get("id"),
                        occurred_at=message.get("occurred_at"))
    return _no(f"no reply from {cond['participant']} yet")


def _check_event(cond: dict, record: dict, now: dt.datetime) -> dict:
    from aletheia import events
    floor = parse(record.get("created_at"))
    prefix = str(cond.get("subject_prefix") or "")
    wanted = cond.get("attributes") or {}
    for event in events.list_events(limit=500):
        if event.get("kind") != cond["event_kind"]:
            continue
        when = parse(event.get("occurred_at"))
        if floor is not None and when is not None and when < floor:
            continue
        if prefix and not str(event.get("subject") or "").startswith(prefix):
            continue
        attrs = event.get("attributes") or {}
        if any(attrs.get(k) != v for k, v in wanted.items()):
            continue
        return _yes("happened", event.get("summary") or "it happened", event_id=event.get("id"),
                    subject=event.get("subject"))
    return _no("it has not happened yet")


def _check_approval(cond: dict, record: dict, now: dt.datetime) -> dict:
    from aletheia import policy
    for row in policy.all_approvals():
        if str(row.get("id")) == str(cond["approval_id"]):
            state = str(row.get("state") or "")
            if state == "APPROVED":
                return _yes("approved", "Caleb approved it", approval_id=row.get("id"))
            if state in {"DENIED", "EXPIRED"}:
                return _yes(state.lower(), f"the approval was {state.lower()}", approval_id=row.get("id"))
            return _no("it is still waiting for Caleb's answer", approval_state=state)
    return _no("the approval is not on record yet")


def _check_handoff(cond: dict, record: dict, now: dt.datetime) -> dict:
    from aletheia import handoffs
    try:
        row = handoffs.load(cond["handoff_id"])
    except (ValueError, OSError, FileNotFoundError):
        return _no("the handed-off request could not be read")
    state = str(row.get("state") or "")
    if state in handoffs.FINISHED:
        return _yes(state.lower(), f"the handed-off request is {state.lower()}", handoff_id=row.get("id"),
                    said=str(row.get("outcome") or "")[:300])
    return _no(f"the handed-off request is {state.lower() or 'unknown'}")


def _check_requirement(req: str, now: dt.datetime) -> dict:
    from aletheia import work_requirements as wr
    result = wr.world(req, now=now, probe=False)
    if result.get("ok") and not result.get("unverified"):
        return _yes("available", result.get("why") or f"{req} is available")
    if result.get("ok"):
        return _yes("available", f"{req} looks available (not verified live)")
    return _no(result.get("why") or f"{req} is not available", not_before=result.get("not_before"))


def _check_verification(cond: dict, record: dict, now: dt.datetime) -> dict:
    from aletheia import outcomes
    try:
        value = outcomes.load(cond["action_id"])
    except (ValueError, OSError, FileNotFoundError):
        return _no("the action record is not there yet")
    status = str(value.get("status") or "")
    if status == "VERIFIED":
        return _yes("verified", "the outcome was verified", action_id=cond["action_id"])
    if status in {"FAILED_TERMINAL", "CANCELLED"}:
        return _yes(status.lower(), f"the action ended {status.lower()}", action_id=cond["action_id"])
    return _no(f"the action is {status.lower() or 'unrecorded'}")


def _check_one(cond: dict, record: dict, now: dt.datetime) -> dict:
    kind = cond["kind"]
    if kind == "time_after":
        at = parse(cond["at"])
        return (_yes("time_passed", f"it is now past {cond['at']}", at=cond["at"])
                if at is not None and now >= at else _no(f"not until {cond['at']}"))
    if kind == "reply_from":
        return _check_reply(cond, record, now)
    if kind == "event":
        return _check_event(cond, record, now)
    if kind == "user_decision":
        decision = record.get("decision")
        if isinstance(decision, dict) and decision.get("choice"):
            return _yes("decided", f"Caleb chose {decision['choice']}", **decision)
        return _no("Caleb has not decided yet")
    if kind == "approval":
        return _check_approval(cond, record, now)
    if kind == "handoff":
        return _check_handoff(cond, record, now)
    if kind in ("model_available", "requirement"):
        return _check_requirement(cond["requirement"], now)
    if kind == "verification":
        return _check_verification(cond, record, now)
    if kind == "any_of":
        whys = []
        for inner in cond["conditions"]:
            said = _check_one(inner, record, now)
            if said["met"]:
                return {**said, "evidence": {**said["evidence"], "by": inner["kind"]}}
            whys.append(said["why"])
        return _no("; ".join(whys))
    return _no(f"unknown condition {kind!r}")


def check(record: dict, now: dt.datetime | None = None) -> dict:
    """Is this wait's condition met NOW? Never raises."""
    now = _now(now)
    try:
        return _check_one(record["condition"], record, now)
    except Exception as exc:  # noqa: BLE001 - an unreadable condition keeps waiting, and says so
        return _no(f"the condition could not be checked ({type(exc).__name__})")


# ---- the beat --------------------------------------------------------------------------

def register(owner: str, target: str) -> None:
    """Name who hears about waits of `owner`: "module:function"."""
    if ":" not in str(target):
        raise WaitError("a handler is 'module:function'")
    HANDLERS[str(owner)] = str(target)


def _handler(owner: str) -> Callable | None:
    target = HANDLERS.get(str(owner or ""))
    if not target:
        return None
    module_name, _, name = target.partition(":")
    try:
        return getattr(importlib.import_module(module_name), name)
    except Exception:  # noqa: BLE001
        return None


def _tell(record: dict, event: str, now: dt.datetime) -> dict | None:
    fn = _handler(record.get("owner", ""))
    if fn is None:
        return None
    try:
        said = fn(record, event, now)
        return said if isinstance(said, dict) else {"said": str(said or "")}
    except Exception as exc:  # noqa: BLE001 - one owner's bug never stops the beat
        _journal("alert", f"wait:{record['id']}", f"the {record.get('owner')} handler failed on {event} "
                 f"({type(exc).__name__}: {exc})")
        return {"error": f"{type(exc).__name__}: {exc}"[:200]}


def _notify_follow_up(record: dict, n: int) -> None:
    try:
        from aletheia import notifications
        fu = record["follow_up"]
        body = (f"{record['reason']}. " + (fu.get("say") or "It may be time to follow up.")
                + (" Say the word and I'll draft the nudge for your approval." if fu.get("needs_approval")
                   else ""))
        notifications.publish("Still waiting", body[:400], priority="NORMAL", source="waits",
                              dedupe_key=f"wait-follow-up:{record['id']}:{n}", related={"wait": record["id"]})
    except Exception:
        pass


def reconcile(now: dt.datetime | None = None) -> list[dict]:
    """One beat: wake what is met, time out what ran out, hand due nudges to their owners.

    Writes only the waits store (and whatever an owner's handler does through its
    own gates). Returns the transitions."""
    now = _now(now)
    transitions: list[dict] = []
    for record in waiting():
        said = check(record, now)
        if said["met"]:
            record.update(state=WOKEN, updated_at=stamp(now), woke_at=stamp(now),
                          outcome={"outcome": said["outcome"], "why": said["why"],
                                   "evidence": said["evidence"], "at": stamp(now)})
            _history(record, f"woke: {said['why'][:140]}", now)
            save(record)
            _journal("event", f"wait:{record['id']}", f"{record['item']}: woke ({said['why'][:160]})")
            told = _tell(record, WOKE, now)
            transitions.append({"wait": record["id"], "item": record["item"], "to": WOKEN,
                                "outcome": said["outcome"], "why": said["why"], "handler": told})
            continue
        timeout = record.get("timeout") or {}
        deadline = parse(timeout.get("at"))
        if deadline is not None and now >= deadline:
            record.update(state=TIMED_OUT, updated_at=stamp(now), woke_at=stamp(now),
                          outcome={"outcome": "timeout", "why": timeout["means"], "then": timeout["then"],
                                   "at": stamp(now)})
            _history(record, f"timed out: {timeout['means'][:140]}", now)
            save(record)
            _journal("event", f"wait:{record['id']}", f"{record['item']}: stopped waiting at the timeout - "
                     f"{timeout['means'][:160]} (not a failure)")
            told = _tell(record, TIMEOUT, now)
            transitions.append({"wait": record["id"], "item": record["item"], "to": TIMED_OUT,
                                "outcome": "timeout", "why": timeout["means"], "then": timeout["then"],
                                "handler": told})
            continue
        fu = record.get("follow_up") or {}
        due = parse(fu.get("next_at"))
        if due is not None and now >= due and len(fu.get("sent") or []) < int(fu.get("max") or 1):
            n = len(fu.get("sent") or []) + 1
            told = _tell(record, FOLLOW_UP, now)
            if told is None:
                _notify_follow_up(record, n)
            fu.setdefault("sent", []).append({"n": n, "at": stamp(now), "needs_approval": fu.get("needs_approval"),
                                              "handled_by": record.get("owner") if told is not None else "notification"})
            every = fu.get("every_s")
            fu["next_at"] = (stamp(now + dt.timedelta(seconds=every))
                             if every and n < int(fu.get("max") or 1) else None)
            record["follow_up"] = fu
            record["updated_at"] = stamp(now)
            _history(record, f"follow-up {n} due" + (" (needs his approval)" if fu.get("needs_approval") else ""), now)
            save(record)
            transitions.append({"wait": record["id"], "item": record["item"], "to": "FOLLOW_UP", "n": n,
                                "needs_approval": fu.get("needs_approval"), "handler": told})
    return transitions


def next_wake_at(record: dict) -> str | None:
    """The soonest KNOWN time something may happen to this wait (a date, a nudge, the timeout)."""
    times = []
    cond = record.get("condition") or {}
    for c in [cond] + list(cond.get("conditions") or []):
        if c.get("kind") == "time_after":
            times.append(parse(c.get("at")))
    times.append(parse((record.get("follow_up") or {}).get("next_at")))
    times.append(parse((record.get("timeout") or {}).get("at")))
    known = [t for t in times if t is not None]
    return stamp(min(known)) if known else None


def describe(record: dict) -> dict:
    """The compact, sayable view every reader uses."""
    fu = record.get("follow_up") or {}
    to = record.get("timeout") or {}
    return {"id": record.get("id"), "item": record.get("item"), "owner": record.get("owner"),
            "state": record.get("state"), "work_state": record.get("work_state"),
            "reason": record.get("reason"), "wakes": record.get("next"),
            "condition": (record.get("condition") or {}).get("kind"),
            "next_wake_at": next_wake_at(record) if record.get("state") == WAITING else None,
            "follow_up": ({"next_at": fu.get("next_at"), "needs_approval": fu.get("needs_approval"),
                           "sent": len(fu.get("sent") or []), "max": fu.get("max")} if fu else None),
            "timeout": ({"at": to.get("at"), "means": to.get("means")} if to else None),
            "since": record.get("created_at"), "outcome": record.get("outcome")}


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Durable waits: what is waiting, why, and what wakes it.")
    ap.add_argument("cmd", choices=("list", "all"))
    args = ap.parse_args(argv)
    rows = waiting() if args.cmd == "list" else all_waits()
    for row in rows:
        d = describe(row)
        print(f"{d['state']:9} {d['work_state'] or '':17} {d['item'][:50]:50} {d['reason'][:60]}  ({d['wakes']})")
    if not rows:
        print("nothing is waiting")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
