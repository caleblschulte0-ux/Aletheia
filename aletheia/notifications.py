"""Private durable notification center.

A notification is an operator-facing fact that needs surfacing; it is not an
execution mechanism. Dedupe keys prevent alert storms and acknowledgements are
explicit. External push delivery is a later provider concern.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from aletheia import stateio
from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

NOTICES_DIR = private_dir("notifications")
PRIORITIES = {"INFO", "NORMAL", "IMPORTANT", "URGENT"}
STATES = {"UNREAD", "READ", "ACKNOWLEDGED"}

# ---------------------------------------------------------------- policy
# WHEN SHE IS ALLOWED TO INTERRUPT HIM. His rule, 2026-09-18: tell him
# when something important FINISHES, FAILS, CHANGES or genuinely NEEDS
# HIM — and let routine reversible work happen quietly.
#
# That rule had nowhere to live. Every caller picked its own priority, and
# `IMPORTANT` is not a description of the notice, it is a request to
# interrupt: it is what `desktop_notify.LOUD` toasts, what `announce`
# speaks into the room, and what the wall puts in its headline. So 42
# call sites were each deciding, on their own, how loud his house is —
# and the job hunt alone published one IMPORTANT per application sent.
# Overnight that is twenty-five toasts for twenty-five things that went
# exactly as he approved them.
#
# `about` says what KIND of fact this is, and the policy is one function
# over it. A caller that says nothing keeps what it asked for, so this
# can be adopted one noisy caller at a time rather than in a flag day.
ROUTINE = "ROUTINE"          # reversible work going normally; quiet
FINISHED = "FINISHED"        # something he was waiting for is done
FAILED = "FAILED"            # it broke, and he would want to know
CHANGED = "CHANGED"          # the world moved under him
NEEDS_YOU = "NEEDS_YOU"      # he has to do something
ABOUT = {ROUTINE, FINISHED, FAILED, CHANGED, NEEDS_YOU}

#: The priorities that reach a surface which interrupts him.
INTERRUPTS = ("IMPORTANT", "URGENT")
#: What ROUTINE is capped at. NOT dropped: the receipt still exists, the
#: activity view still shows it, "what did you do today" still counts it.
#: Quiet means not interrupting, never not recorded — a notification she
#: silently declined to write is a store with a writer and no reader.
QUIET = "NORMAL"


def loudness(priority: str, about: str = "") -> str:
    """How loud this notice may actually be. Pure.

    Only ROUTINE is capped, and only downwards. Nothing here can make a
    notice louder than the caller asked for: a policy that PROMOTES would
    be a policy that can invent an interruption, and the whole point is
    to remove them.
    """
    if about and about not in ABOUT:
        raise ValueError(f"notification about must be one of {sorted(ABOUT)}")
    if about == ROUTINE and priority in INTERRUPTS:
        return QUIET
    return priority


def _path(notice_id: str) -> Path:
    return NOTICES_DIR / f"{safe_id(notice_id, name='notification id')}.json"


def _dedupe_id(key: str) -> str:
    return "notice-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def validate(value: dict) -> None:
    required = {"version", "id", "title", "body", "priority", "state", "created_at", "updated_at"}
    missing = required - value.keys()
    if missing:
        raise ValueError(f"notification missing {sorted(missing)}")
    if value["version"] != 1 or value["priority"] not in PRIORITIES or value["state"] not in STATES:
        raise ValueError("unsupported notification version/priority/state")
    safe_id(value["id"], name="notification id")
    for key in ("title", "body"):
        if not isinstance(value[key], str) or not value[key].strip():
            raise ValueError(f"notification {key} is required")


def _sayable(text: str) -> str:
    """One line of a notice, fit to be read out — or left exactly as it was.

    Fails OPEN on purpose: `validate` refuses an empty title or body, so a
    line the door happens to reduce to nothing must keep its original
    rather than turn a notification into an exception. A slightly ugly
    notice is a bad day; a notice that was never filed is the thing he
    needed to know and never heard.
    """
    try:
        from aletheia import speech
        said = speech.for_the_room(text)
    except Exception:
        return str(text or "")
    return said if said.strip() else str(text or "")


#: Forbidden to a planner and still one tap of HIS: the switches, a decision,
#: a second send. A notice may offer these and nothing else a plan may not.
HIS_TAP_KINDS = ("approve", "deny", "resume", "restart", "update_now", "open", "mic_on", "apply_retry",
                 "fault_ack")


def action_shape(action: object) -> dict:
    """{"label", "kind", "args"} or ValueError. The one command a notice asks
    of him, for the page to put a button on; nothing a page could turn into
    a second command path - it is sent through /api/command like a tap."""
    if not isinstance(action, dict):
        raise ValueError("action must be an object")
    label, kind = str(action.get("label") or "").strip(), str(action.get("kind") or "").strip()
    args = action.get("args") or {}
    if not label or not kind or not isinstance(args, dict):
        raise ValueError("action needs a label, a kind and an object of args")
    from aletheia import intercom
    if kind not in intercom.KIND_ARGS or kind in intercom.PLANNER_FORBIDDEN and kind not in HIS_TAP_KINDS:
        raise ValueError(f"action kind {kind!r} is not one a notice may offer")
    return {"label": label[:40], "kind": kind, "args": {str(k): v for k, v in args.items()}}


def publish(title: str, body: str, *, priority: str = "NORMAL", source: str = "aletheia",
            dedupe_key: str | None = None, related: dict | None = None,
            about: str = "", action: dict | None = None) -> dict:
    """File a notice. `about` decides whether it may interrupt him.

    The policy is applied HERE rather than at each call site, because a
    rule 42 callers have to remember is a rule that holds in 41 places.
    """
    priority = loudness(priority, about)
    # AND EVERY BODY GOES THROUGH THE SPEECH DOOR, for the same reason the
    # policy does. `speech.notice_line` cleans the HEADING, and every
    # surface renders the body raw underneath it — so this reached his
    # phone verbatim: "https://jobs.ashbyhq.com/notion/c1324c38-abc7-4bcf
    # -9b62-2e1f86d5aa72/application — RuntimeError: ApplyError: the
    # Submit button would not take a click". A link, a UUID and two class
    # names in front of the one clause that says what happened.
    #
    # Here rather than at each caller, because a rule forty-two callers
    # have to remember is a rule that holds in forty-one places; and the
    # ids and the URL are still on `related`, where a page can link them.
    title, body = _sayable(title), _sayable(body)
    notice_id = _dedupe_id(dedupe_key) if dedupe_key else _dedupe_id(f"{utcnow()}:{title}:{body}")
    path = _path(notice_id)
    if path.exists():
        return load(notice_id)
    now = utcnow()
    value = {"version": 1, "id": notice_id, "title": title.strip(), "body": body.strip(),
             "priority": priority, "state": "UNREAD", "source": source,
             "created_at": now, "updated_at": now}
    if about:
        value["about"] = about
    if dedupe_key:
        value["dedupe_key"] = dedupe_key
    if related is not None:
        if not isinstance(related, dict):
            raise ValueError("related must be an object")
        value["related"] = related
    if action is not None:
        # The button on the notice (2026-09-23): "Got it" was every
        # notice's only control, while fifteen bodies told him to do
        # something. Validated here so a stored notice never carries a
        # command the page would send blind.
        value["action"] = action_shape(action)
    validate(value)
    write_json_atomic(path, value)
    return value


def load(notice_id: str) -> dict:
    value = read_json(_path(notice_id))
    validate(value)
    return value


def all_notifications(*, state: str | None = None, limit: int = 100) -> list[dict]:
    if state is not None and state not in STATES:
        raise ValueError("invalid notification state")
    if limit < 1 or limit > 500:
        raise ValueError("limit must be 1..500")
    if not NOTICES_DIR.is_dir():
        return []
    out = []
    for value in stateio.parsed_dir(NOTICES_DIR):
        if state is None or value["state"] == state:
            out.append(value)     # `parsed_dir` already returns copies
    out.sort(key=lambda n: (n["created_at"], n["id"]), reverse=True)
    return out[:limit]


def set_state(notice_id: str, state: str) -> dict:
    if state not in STATES:
        raise ValueError("invalid notification state")
    value = load(notice_id)
    value["state"] = state
    value["updated_at"] = utcnow()
    if state == "ACKNOWLEDGED":
        value["acknowledged_at"] = utcnow()
    write_json_atomic(_path(notice_id), value)
    return value


def unread_count() -> int:
    return len(all_notifications(state="UNREAD", limit=500))
