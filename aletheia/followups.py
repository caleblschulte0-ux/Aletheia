"""Answers that arrive after the sentence that asked for them.

A person standing in a room will wait about two seconds. Reasoning about
an arbitrary request takes ten to thirty. Those two facts are the whole of
this module: the Core acknowledges immediately, thinks in the background,
and speaks the real answer when it exists — instead of holding an open
microphone in silence for half a minute and then saying something.

Deliberately in-process and short-lived. A follow-up is one turn of one
conversation; if the Core restarts, the turn is over and pretending
otherwise would be worse than dropping it. Anything that must OUTLIVE the
conversation is already durable elsewhere — the intent record, its
approval, and a notification — and that is what the operator sees later.

Bounded on purpose: SLOTS at a time, TTL_S each, and a worker thread that
cannot raise into the Core. A background thread that can wedge the process
would trade a latency problem for an uptime one, and uptime is the more
expensive of the two.
"""
from __future__ import annotations

import threading
import time
import uuid

SLOTS = 8
TTL_S = 300.0

PENDING, READY, FAILED = "PENDING", "READY", "FAILED"

_LOCK = threading.Lock()
_SLOTS: dict[str, dict] = {}


def _prune(now: float | None = None) -> None:
    """Caller holds the lock. Drops expired slots, then oldest over capacity."""
    now = now if now is not None else time.monotonic()
    for key in [k for k, v in _SLOTS.items() if now - v["created"] > TTL_S]:
        _SLOTS.pop(key, None)
    if len(_SLOTS) > SLOTS:
        for key in sorted(_SLOTS, key=lambda k: _SLOTS[k]["created"])[:-SLOTS]:
            _SLOTS.pop(key, None)


def start(work, acknowledgement: str = "One moment.") -> dict:
    """Run `work()` in the background; return the slot to poll.

    `work` returns the sentence to say. It runs with no lock held, and any
    exception it raises becomes a FAILED slot with an honest sentence —
    never a silent nothing, and never an exception in the Core.
    """
    followup_id = "fu-" + uuid.uuid4().hex[:10]
    with _LOCK:
        _SLOTS[followup_id] = {"id": followup_id, "state": PENDING, "say": None,
                               "created": time.monotonic()}
        _prune()  # after inserting, so the cap counts THIS slot too

    def runner():
        try:
            said = work()
            state = READY
        except Exception as exc:
            said = f"That didn't work: {type(exc).__name__}: {exc}"
            state = FAILED
        with _LOCK:
            slot = _SLOTS.get(followup_id)
            if slot is not None:  # may have been pruned; then nobody is waiting
                slot["state"] = state
                slot["say"] = str(said)[:2000]

    threading.Thread(target=runner, name=f"followup-{followup_id}",
                     daemon=True).start()
    return {"id": followup_id, "state": PENDING, "say": acknowledgement}


def poll(followup_id: str) -> dict:
    """The slot's current state. Unknown ids read as expired, not as an error:
    a caller that waited too long should hear that, not a 404."""
    with _LOCK:
        _prune()
        slot = _SLOTS.get(followup_id)
        if slot is None:
            return {"id": followup_id, "state": "EXPIRED", "say": None}
        return {"id": slot["id"], "state": slot["state"], "say": slot["say"]}


def take(followup_id: str) -> dict:
    """Poll, and remove the slot once it has been delivered. Keeps a spoken
    answer from being said twice if a listener polls after speaking."""
    with _LOCK:
        _prune()
        slot = _SLOTS.get(followup_id)
        if slot is None:
            return {"id": followup_id, "state": "EXPIRED", "say": None}
        if slot["state"] in (READY, FAILED):
            _SLOTS.pop(followup_id, None)
        return {"id": slot["id"], "state": slot["state"], "say": slot["say"]}


def pending_count() -> int:
    with _LOCK:
        _prune()
        return sum(1 for v in _SLOTS.values() if v["state"] == PENDING)


def undelivered_count() -> int:
    """Answers the Core has promised but the room has not collected yet.

    READY and FAILED still count.  A self-update between computation and the
    listener's next poll would otherwise erase the finished sentence just as
    surely as restarting while the provider is still working.
    """
    with _LOCK:
        _prune()
        return len(_SLOTS)


def reset() -> None:
    """Tests only."""
    with _LOCK:
        _SLOTS.clear()
