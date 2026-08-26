"""Channel-neutral communication threads, messages, and reply expectations.

Email is already a capability, while SMS/phone are later. This model keeps the
operator's intent above the transport: who, what conversation, what was sent,
and whether a reply is expected by a deadline.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from aletheia.fleet import REPO_ROOT
from aletheia.stateio import create_json_exclusive, read_json, safe_id, utcnow, write_json_atomic

THREADS_DIR = REPO_ROOT / "state" / "communications" / "threads"
MESSAGES_DIR = REPO_ROOT / "state" / "communications" / "messages"
EXPECT_DIR = REPO_ROOT / "state" / "communications" / "expectations"


def _thread_path(thread_id: str) -> Path:
    return THREADS_DIR / f"{safe_id(thread_id, name='thread id')}.json"


def create_thread(thread_id: str, *, participants: list[str], subject: str = "") -> dict:
    if not participants or len(set(participants)) != len(participants):
        raise ValueError("participants must be unique and non-empty")
    if _thread_path(thread_id).exists():
        raise FileExistsError(thread_id)
    now = utcnow()
    value = {"version": 1, "id": thread_id, "participants": participants, "subject": subject,
             "created_at": now, "updated_at": now, "status": "OPEN"}
    write_json_atomic(_thread_path(thread_id), value)
    return value


def load_thread(thread_id: str) -> dict:
    return read_json(_thread_path(thread_id))


def record_message(message_id: str, *, thread_id: str, direction: str, channel: str,
                   participant: str, summary: str, external_id: str | None = None,
                   occurred_at: str | None = None) -> dict:
    safe_id(message_id, name="message id")
    load_thread(thread_id)
    if direction not in {"INBOUND", "OUTBOUND"}:
        raise ValueError("invalid direction")
    if channel not in {"email", "sms", "phone", "chat", "other"}:
        raise ValueError("invalid channel")
    value = {"version": 1, "id": message_id, "thread_id": thread_id, "direction": direction,
             "channel": channel, "participant": participant, "summary": summary,
             "occurred_at": occurred_at or utcnow(), "recorded_at": utcnow()}
    if external_id:
        value["external_id"] = external_id
    create_json_exclusive(MESSAGES_DIR / safe_id(thread_id) / f"{message_id}.json", value)
    return value


def expect_reply(expectation_id: str, *, thread_id: str, after_message_id: str,
                 from_participant: str, deadline: str | None = None) -> dict:
    safe_id(expectation_id, name="expectation id")
    load_thread(thread_id)
    value = {"version": 1, "id": expectation_id, "thread_id": thread_id,
             "after_message_id": after_message_id, "from_participant": from_participant,
             "created_at": utcnow(), "status": "WAITING"}
    if deadline:
        parsed = dt.datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("deadline must be timezone-aware")
        value["deadline"] = deadline
    path = EXPECT_DIR / f"{expectation_id}.json"
    if path.exists():
        raise FileExistsError(expectation_id)
    write_json_atomic(path, value)
    return value


def _messages(thread_id: str) -> list[dict]:
    root = MESSAGES_DIR / safe_id(thread_id)
    if not root.is_dir():
        return []
    values = []
    for p in root.glob("*.json"):
        try:
            values.append(read_json(p))
        except ValueError:
            continue
    return sorted(values, key=lambda m: m["occurred_at"])


def evaluate_expectation(value: dict) -> dict:
    if value.get("status") != "WAITING":
        return value
    seen_after = False
    for msg in _messages(value["thread_id"]):
        if msg["id"] == value["after_message_id"]:
            seen_after = True
            continue
        if seen_after and msg["direction"] == "INBOUND" and msg["participant"] == value["from_participant"]:
            updated = dict(value)
            updated["status"] = "REPLIED"
            updated["reply_message_id"] = msg["id"]
            updated["resolved_at"] = utcnow()
            write_json_atomic(EXPECT_DIR / f"{value['id']}.json", updated)
            return updated
    if value.get("deadline"):
        deadline = dt.datetime.fromisoformat(value["deadline"].replace("Z", "+00:00"))
        if dt.datetime.now(dt.timezone.utc) > deadline.astimezone(dt.timezone.utc):
            updated = dict(value)
            updated["status"] = "OVERDUE"
            updated["resolved_at"] = utcnow()
            write_json_atomic(EXPECT_DIR / f"{value['id']}.json", updated)
            return updated
    return value
