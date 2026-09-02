"""Answers that arrive after the sentence that asked for them.

A person standing in a room will wait about two seconds. Reasoning about
an arbitrary request takes ten to thirty. Those two facts are the whole of
this module: the Core acknowledges immediately, thinks in the background,
and speaks the real answer when it exists — instead of holding an open
microphone in silence for half a minute and then saying something.

The worker remains in-process, but production follow-ups leave a private
durable delivery record. A completed answer becomes an IMPORTANT notification
until its requesting surface actually takes it. If the Core restarts while a
worker is still pending, the successor converts that orphan into an honest
failure notification instead of silently forgetting that it promised a reply.

Bounded on purpose: SLOTS at a time, TTL_S each, and a worker thread that
cannot raise into the Core. A background thread that can wedge the process
would trade a latency problem for an uptime one, and uptime is the more
expensive of the two.
"""
from __future__ import annotations

import threading
import time
import uuid

from aletheia import journal, notifications, stateio

SLOTS = 8
TTL_S = 300.0

PENDING, READY, FAILED = "PENDING", "READY", "FAILED"
DELIVERED = "DELIVERED"

_LOCK = threading.Lock()
_SLOTS: dict[str, dict] = {}
_PROCESS_ID = uuid.uuid4().hex


def _journal(kind: str, detail: str) -> None:
    """Delivery must not fail merely because its audit sink is unavailable."""
    try:
        journal.append(kind, "followup", detail, actor="aletheia-followups")
    except Exception:
        pass


def records_dir():
    return stateio.private_dir("followups")


def _record_path(followup_id: str):
    return records_dir() / f"{stateio.safe_id(followup_id, name='follow-up id')}.json"


def _load_record(followup_id: str) -> dict | None:
    path = _record_path(followup_id)
    if not path.is_file():
        return None
    try:
        value = stateio.read_json(path)
    except ValueError:
        return None
    if value.get("id") != followup_id or value.get("state") not in {
            PENDING, READY, FAILED, DELIVERED}:
        return None
    return value


def _publish_terminal(record: dict) -> str | None:
    title = ("Aletheia finished thinking" if record["state"] == READY
             else "Aletheia could not finish a reply")
    try:
        notice = notifications.publish(
            title, record["say"], priority="IMPORTANT", source="aletheia.followups",
            dedupe_key=f"followup:{record['id']}",
            related={"followup_id": record["id"]})
        return notice["id"]
    except Exception as exc:
        _journal("event",
                 f"{record['id']}: notification failed ({type(exc).__name__})")
        return None


def _persist_terminal(followup_id: str, state: str, said: str) -> str | None:
    record = _load_record(followup_id)
    if record is None or record.get("state") != PENDING:
        return None
    record.update({"state": state, "say": said, "finished_at": stateio.utcnow(),
                   "updated_at": stateio.utcnow()})
    # The delivery record is the source of truth.  Commit it before publishing
    # the notification so a notification-store failure cannot erase an answer.
    stateio.write_json_atomic(_record_path(followup_id), record)
    notice_id = _publish_terminal(record)
    if notice_id:
        record["notification_id"] = notice_id
        stateio.write_json_atomic(_record_path(followup_id), record)
    _journal("event", f"{followup_id}: {state}")
    return notice_id


def recover_pending() -> list[dict]:
    """Fail orphaned workers and ensure every terminal result is surfaced.

    Called once when the Core starts, after the PC journal is selected.
    """
    recovered = []
    directory = records_dir()
    if not directory.is_dir():
        return recovered
    for path in directory.glob("fu-*.json"):
        record = _load_record(path.stem)
        if record is None or record.get("state") == DELIVERED:
            continue
        changed = False
        if record.get("state") == PENDING and record.get("owner") != _PROCESS_ID:
            record.update({
                "state": FAILED,
                "say": ("I was interrupted before I finished that answer. "
                        "Please ask me again."),
                "finished_at": stateio.utcnow(),
                "updated_at": stateio.utcnow(),
                "recovered_after_restart": True,
            })
            changed = True
        if record.get("state") in (READY, FAILED) and not record.get("notification_id"):
            notice_id = _publish_terminal(record)
            if notice_id:
                record["notification_id"] = notice_id
                changed = True
        if changed:
            stateio.write_json_atomic(path, record)
            recovered.append({"id": record["id"], "state": record["state"]})
            _journal("alert" if record["state"] == FAILED else "event",
                     f"{record['id']}: recovered {record['state']}")
    return recovered


def _prune(now: float | None = None) -> None:
    """Caller holds the lock. Drops expired slots, then oldest over capacity."""
    now = now if now is not None else time.monotonic()
    for key in [k for k, v in _SLOTS.items() if now - v["created"] > TTL_S]:
        _SLOTS.pop(key, None)
    if len(_SLOTS) > SLOTS:
        for key in sorted(_SLOTS, key=lambda k: _SLOTS[k]["created"])[:-SLOTS]:
            _SLOTS.pop(key, None)


def start(work, acknowledgement: str = "One moment.", *, durable: bool = False) -> dict:
    """Run `work()` in the background; return the slot to poll.

    `work` returns the sentence to say. It runs with no lock held, and any
    exception it raises becomes a FAILED slot with an honest sentence —
    never a silent nothing, and never an exception in the Core.
    """
    followup_id = "fu-" + uuid.uuid4().hex[:10]
    with _LOCK:
        _SLOTS[followup_id] = {"id": followup_id, "state": PENDING, "say": None,
                               "created": time.monotonic(), "durable": durable}
        _prune()  # after inserting, so the cap counts THIS slot too
    if durable:
        now = stateio.utcnow()
        try:
            stateio.write_json_atomic(_record_path(followup_id), {
                "version": 1, "id": followup_id, "state": PENDING, "say": None,
                "owner": _PROCESS_ID, "created_at": now, "updated_at": now,
            })
        except Exception:
            with _LOCK:
                _SLOTS.pop(followup_id, None)
            raise
        _journal("event", f"{followup_id}: PENDING")

    def runner():
        try:
            said = work()
            state = READY
        except Exception as exc:
            said = f"That didn't work: {type(exc).__name__}: {exc}"
            state = FAILED
        said = str(said)[:2000]
        notice_id = None
        if durable:
            try:
                notice_id = _persist_terminal(followup_id, state, said)
            except Exception as exc:
                # The live requester must still receive the computed result.
                # A persistence failure is journaled, never allowed to kill the
                # worker before it updates the in-memory delivery slot.
                _journal(
                    "alert",
                    f"{followup_id}: persistence failed ({type(exc).__name__})")
        with _LOCK:
            slot = _SLOTS.get(followup_id)
            if slot is not None:  # may have been pruned; then nobody is waiting
                slot["state"] = state
                slot["say"] = said
                if notice_id:
                    slot["notification_id"] = notice_id

    threading.Thread(target=runner, name=f"followup-{followup_id}",
                     daemon=True).start()
    return {"id": followup_id, "state": PENDING, "say": acknowledgement}


def poll(followup_id: str) -> dict:
    """The slot's current state. Unknown ids read as expired, not as an error:
    a caller that waited too long should hear that, not a 404."""
    with _LOCK:
        _prune()
        slot = _SLOTS.get(followup_id)
        if slot is not None:
            return {"id": slot["id"], "state": slot["state"], "say": slot["say"]}
    # Filesystem access stays outside the hot in-process lock.
    record = _load_record(followup_id)
    if record and record.get("state") in (READY, FAILED):
        return {"id": record["id"], "state": record["state"],
                "say": record["say"]}
    return {"id": followup_id, "state": "EXPIRED", "say": None}


def acknowledge(followup_id: str) -> dict:
    """Consume a delivered answer, AFTER the listener has actually said it.

    Ported from PR #75, whose diagnosis was right: reading and consuming in
    one HTTP GET means a response lost in transit destroys the only copy of
    the answer — the operator's original complaint, reappearing one layer
    down. The wall makes that likely rather than theoretical: a browser tab
    is a flaky client, and it now polls this slot on every slow ask.

    So the GET is a pure read and this is the consume. Idempotent from the
    listener's side: a retried ACK reads EXPIRED, which means the finished
    slot is already gone and is safe to treat as delivered.
    """
    result = poll(followup_id)
    if result["state"] not in (READY, FAILED):
        return result
    with _LOCK:
        _SLOTS.pop(followup_id, None)
    record = _load_record(followup_id)
    if record and record.get("state") in (READY, FAILED):
        notice_id = record.get("notification_id")
        if notice_id:
            try:
                notifications.set_state(notice_id, "ACKNOWLEDGED")
            except Exception:
                pass
        record["state"] = DELIVERED
        record["delivered_at"] = stateio.utcnow()
        record["updated_at"] = record["delivered_at"]
        stateio.write_json_atomic(_record_path(followup_id), record)
    return {"id": followup_id, "state": "ACKED",
            "delivered_state": result["state"], "say": result["say"]}


def take(followup_id: str) -> dict:
    """Read and consume in one call — for in-process listeners only.

    The room microphone speaks in the same process that reads the slot, so
    nothing can be lost between the two. Anything reaching this over HTTP
    must use poll() then acknowledge() instead.
    """
    result = poll(followup_id)
    if result["state"] not in (READY, FAILED):
        return result
    with _LOCK:
        _SLOTS.pop(followup_id, None)
    record = _load_record(followup_id)
    if record and record.get("state") in (READY, FAILED):
        notice_id = record.get("notification_id")
        if notice_id:
            try:
                notifications.set_state(notice_id, "ACKNOWLEDGED")
            except Exception:
                pass
        record["state"] = DELIVERED
        record["delivered_at"] = stateio.utcnow()
        record["updated_at"] = record["delivered_at"]
        stateio.write_json_atomic(_record_path(followup_id), record)
    return result


def pending_count() -> int:
    with _LOCK:
        _prune()
        return sum(1 for v in _SLOTS.values() if v["state"] == PENDING)


def reset() -> None:
    """Tests only."""
    with _LOCK:
        _SLOTS.clear()
