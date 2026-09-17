"""One small seam for "wait until ...", so conversations do not grow a wait system.

Continuity brief IV.14: waiting is first-class. The long-missions wave
(`claude/continuity-long-missions`) is building the general wait/wake API
(conditions like reply_from, time_after, event). Until that merges, every wait a
conversation needs goes through THIS module and nothing else, so reconciling at
merge is replacing three functions:

    reply_from(thread, participant, after_message)  -> a wait record
    time_after(when, why)                             -> a wait record
    satisfied(wait, now)                              -> (bool, detail)

The records are plain dicts stored inside the thread that owns them; the reply
condition is backed by the existing channel-neutral expectation store
(`aletheia.communications.expect_reply`), which `mail.poll_events` already
resolves when a reply arrives. No second store, no second loop.
"""
from __future__ import annotations

import datetime as dt

REPLY_FROM = "reply_from"
TIME_AFTER = "time_after"
KINDS = (REPLY_FROM, TIME_AFTER)


def _stamp(when: dt.datetime) -> str:
    return when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp: str) -> dt.datetime:
    value = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("wait times must be timezone-aware")
    return value.astimezone(dt.timezone.utc)


def reply_from(thread_id: str, participant: str, *, after_message_id: str,
               deadline: dt.datetime | None = None) -> dict:
    """Wait for `participant` to answer on `thread_id` after our message."""
    from aletheia import communications
    expectation_id = f"{after_message_id}-reply"[:80]
    try:
        communications.expect_reply(expectation_id, thread_id=thread_id, after_message_id=after_message_id,
                                    from_participant=participant,
                                    deadline=_stamp(deadline) if deadline else None)
    except FileExistsError:
        pass
    return {"kind": REPLY_FROM, "id": expectation_id, "thread_id": thread_id, "participant": participant,
            "after": after_message_id, "deadline": _stamp(deadline) if deadline else None}


def time_after(when: dt.datetime, why: str) -> dict:
    return {"kind": TIME_AFTER, "at": _stamp(when), "why": str(why)[:200]}


def satisfied(wait: dict, now: dt.datetime | None = None) -> tuple[bool, dict]:
    """Has the condition happened? Never raises; an unreadable wait is unmet."""
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    try:
        if wait.get("kind") == TIME_AFTER:
            return now >= _parse(wait["at"]), {}
        if wait.get("kind") == REPLY_FROM:
            from aletheia import communications
            value = communications.evaluate_expectation(communications.load_expectation(wait["id"]), now=now)
            if value.get("status") == "REPLIED":
                return True, {"reply_message_id": value.get("reply_message_id")}
            return False, {"status": value.get("status")}
    except Exception as exc:  # noqa: BLE001
        return False, {"error": type(exc).__name__}
    return False, {"error": "unknown wait kind"}
