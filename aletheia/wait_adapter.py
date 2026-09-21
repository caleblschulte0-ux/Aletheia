"""One small seam for "wait until ...", so conversations do not grow a wait system.

Continuity brief IV.14: waiting is first-class. The long-missions wave
(`claude/continuity-long-missions`) builds the general durable wait
(`aletheia.waits`: wait_for / check / reconcile, conditions reply_from,
time_after, event ...). Every wait a conversation needs goes through THIS module
and nothing else, so the two branches meet in three functions:

    reply_from(thread, participant, after_message)  -> a wait record
    time_after(when, why)                             -> a wait record
    satisfied(wait, now)                              -> (bool, detail)

When `aletheia.waits` is importable (after that branch merges) a reply wait is
ALSO filed there - item `conversation:<thread>`, the same `reply_from` condition,
idempotent per message - so its beat, its screen and its readers see the
conversation waiting, and `satisfied` asks `waits.check`. Either way the reply
condition is backed by the channel-neutral expectation store
(`communications.expect_reply`), because that is what `mail.poll_events`
resolves when a reply arrives: no second store, no second loop.

FOLLOW-UPS HAVE ONE OWNER (C3). A conversation he started keeps its own
follow-up date (the thread's `follow_up.due`), because that follow-up is drafted
and authority-checked by `conversations`. A message sent for a long mission's
task is recorded by `conversations` too (`record_sent_elsewhere` / `link_sent`),
but its follow-up belongs to the task's wait (`waits` follow_up policy): the
thread carries `follow_up.owner` and no date, so nothing nudges twice.
"""
from __future__ import annotations

import datetime as dt

REPLY_FROM = "reply_from"
TIME_AFTER = "time_after"
KINDS = (REPLY_FROM, TIME_AFTER)
OWNER = "conversations"


def _stamp(when: dt.datetime) -> str:
    return when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp: str) -> dt.datetime:
    value = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("wait times must be timezone-aware")
    return value.astimezone(dt.timezone.utc)


def _waits():
    try:
        from aletheia import waits  # the long-missions API, once merged
        return waits
    except ImportError:
        return None


def reply_from(thread_id: str, participant: str, *, after_message_id: str, reason: str = "",
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
    record = {"kind": REPLY_FROM, "id": expectation_id, "thread_id": thread_id, "participant": participant,
              "after": after_message_id, "deadline": _stamp(deadline) if deadline else None}
    waits = _waits()
    if waits is not None:
        try:
            filed = waits.wait_for(f"conversation:{thread_id}",
                                   {"kind": REPLY_FROM, "thread_id": thread_id, "participant": participant,
                                    "after_message_id": after_message_id},
                                   reason=reason or f"waiting for {participant} to reply",
                                   owner=OWNER, key=after_message_id)
            record["wait_id"] = filed.get("id")
        except Exception:  # noqa: BLE001 - the expectation above still carries the wait
            pass
    return record


def time_after(when: dt.datetime, why: str) -> dict:
    return {"kind": TIME_AFTER, "at": _stamp(when), "why": str(why)[:200]}


def satisfied(wait: dict, now: dt.datetime | None = None) -> tuple[bool, dict]:
    """Has the condition happened? Never raises; an unreadable wait is unmet."""
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    try:
        if wait.get("kind") == TIME_AFTER:
            return now >= _parse(wait["at"]), {}
        if wait.get("kind") == REPLY_FROM:
            waits = _waits()
            if waits is not None and wait.get("wait_id"):
                said = waits.check(waits.load(wait["wait_id"]), now)
                if said.get("met"):
                    return True, dict(said.get("evidence") or {})
            from aletheia import communications
            value = communications.evaluate_expectation(communications.load_expectation(wait["id"]), now=now)
            if value.get("status") == "REPLIED":
                return True, {"reply_message_id": value.get("reply_message_id")}
            return False, {"status": value.get("status")}
    except Exception as exc:  # noqa: BLE001
        return False, {"error": type(exc).__name__}
    return False, {"error": "unknown wait kind"}
