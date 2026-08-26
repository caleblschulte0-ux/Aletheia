"""Channel-neutral communication threads, messages, and reply expectations.

Email exists today; SMS/phone come later. This model keeps intent above the
transport: person, conversation, request, response expected and deadline.
Sensitive content lives in private runtime state, never committed by default.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from aletheia.stateio import create_json_exclusive, private_dir, read_json, safe_id, utcnow, write_json_atomic

BASE_DIR = private_dir("communications")
THREADS_DIR = BASE_DIR / "threads"
MESSAGES_DIR = BASE_DIR / "messages"
EXPECT_DIR = BASE_DIR / "expectations"
CHANNELS = {"email", "sms", "phone", "chat", "other"}
DIRECTIONS = {"INBOUND", "OUTBOUND"}


def _parse_time(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid communication timestamp {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("communication timestamps must be timezone-aware")
    return parsed


def _thread_path(thread_id: str) -> Path:
    return THREADS_DIR / f"{safe_id(thread_id, name='thread id')}.json"


def validate_thread(value: dict) -> None:
    required = {"version", "id", "participants", "subject", "created_at", "updated_at", "status"}
    missing = required - value.keys()
    if missing:
        raise ValueError(f"thread missing {sorted(missing)}")
    if value["version"] != 1 or value["status"] not in {"OPEN", "CLOSED"}:
        raise ValueError("unsupported thread version/status")
    safe_id(value["id"], name="thread id")
    participants = value["participants"]
    if not isinstance(participants, list) or not participants or any(not isinstance(x, str) or not x.strip() for x in participants):
        raise ValueError("participants must be non-empty strings")
    if len(set(participants)) != len(participants):
        raise ValueError("participants must be unique")


def create_thread(thread_id: str, *, participants: list[str], subject: str = "") -> dict:
    if _thread_path(thread_id).exists():
        raise FileExistsError(thread_id)
    now = utcnow()
    value = {"version": 1, "id": safe_id(thread_id, name="thread id"), "participants": participants,
             "subject": subject, "created_at": now, "updated_at": now, "status": "OPEN"}
    validate_thread(value)
    write_json_atomic(_thread_path(thread_id), value)
    return value


def load_thread(thread_id: str) -> dict:
    value = read_json(_thread_path(thread_id))
    validate_thread(value)
    return value


def close_thread(thread_id: str) -> dict:
    value = load_thread(thread_id)
    value["status"] = "CLOSED"
    value["updated_at"] = utcnow()
    write_json_atomic(_thread_path(thread_id), value)
    return value


def record_message(message_id: str, *, thread_id: str, direction: str, channel: str,
                   participant: str, summary: str, external_id: str | None = None,
                   occurred_at: str | None = None) -> dict:
    safe_id(message_id, name="message id")
    thread = load_thread(thread_id)
    if thread["status"] != "OPEN":
        raise ValueError("cannot append to a closed thread")
    if direction not in DIRECTIONS:
        raise ValueError("invalid direction")
    if channel not in CHANNELS:
        raise ValueError("invalid channel")
    if not isinstance(participant, str) or not participant.strip():
        raise ValueError("participant is required")
    if participant not in thread["participants"]:
        raise ValueError("message participant is not in thread")
    timestamp = occurred_at or utcnow()
    _parse_time(timestamp)
    value = {"version": 1, "id": message_id, "thread_id": thread_id, "direction": direction,
             "channel": channel, "participant": participant, "summary": summary,
             "occurred_at": timestamp, "recorded_at": utcnow()}
    if external_id:
        value["external_id"] = external_id
    create_json_exclusive(MESSAGES_DIR / safe_id(thread_id) / f"{message_id}.json", value)
    thread["updated_at"] = utcnow()
    write_json_atomic(_thread_path(thread_id), thread)
    return value


def messages(thread_id: str) -> list[dict]:
    load_thread(thread_id)
    root = MESSAGES_DIR / safe_id(thread_id)
    if not root.is_dir():
        return []
    values = []
    for path in root.glob("*.json"):
        try:
            value = read_json(path)
            _parse_time(value["occurred_at"])
            values.append(value)
        except (KeyError, ValueError):
            continue
    return sorted(values, key=lambda m: _parse_time(m["occurred_at"]).astimezone(dt.timezone.utc))


def _message_by_id(thread_id: str, message_id: str) -> dict:
    for message in messages(thread_id):
        if message["id"] == message_id:
            return message
    raise KeyError(f"message {message_id!r} is not in thread {thread_id!r}")


def expect_reply(expectation_id: str, *, thread_id: str, after_message_id: str,
                 from_participant: str, deadline: str | None = None) -> dict:
    safe_id(expectation_id, name="expectation id")
    thread = load_thread(thread_id)
    if from_participant not in thread["participants"]:
        raise ValueError("expected participant is not in thread")
    anchor = _message_by_id(thread_id, after_message_id)
    if anchor["direction"] != "OUTBOUND":
        raise ValueError("reply expectation must be anchored to an outbound message")
    value = {"version": 1, "id": expectation_id, "thread_id": thread_id,
             "after_message_id": after_message_id, "from_participant": from_participant,
             "created_at": utcnow(), "status": "WAITING"}
    if deadline:
        _parse_time(deadline)
        value["deadline"] = deadline
    path = EXPECT_DIR / f"{expectation_id}.json"
    if path.exists():
        raise FileExistsError(expectation_id)
    write_json_atomic(path, value)
    return value


def load_expectation(expectation_id: str) -> dict:
    return read_json(EXPECT_DIR / f"{safe_id(expectation_id, name='expectation id')}.json")


def all_expectations() -> list[dict]:
    if not EXPECT_DIR.is_dir():
        return []
    out = []
    for path in sorted(EXPECT_DIR.glob("*.json")):
        try:
            out.append(load_expectation(path.stem))
        except ValueError:
            continue
    return out


def evaluate_expectation(value: dict, *, now: dt.datetime | None = None) -> dict:
    if value.get("status") != "WAITING":
        return value
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    anchor = _message_by_id(value["thread_id"], value["after_message_id"])
    anchor_time = _parse_time(anchor["occurred_at"]).astimezone(dt.timezone.utc)
    for message in messages(value["thread_id"]):
        occurred = _parse_time(message["occurred_at"]).astimezone(dt.timezone.utc)
        if occurred <= anchor_time:
            continue
        if message["direction"] == "INBOUND" and message["participant"] == value["from_participant"]:
            updated = dict(value)
            updated["status"] = "REPLIED"
            updated["reply_message_id"] = message["id"]
            updated["resolved_at"] = utcnow()
            write_json_atomic(EXPECT_DIR / f"{value['id']}.json", updated)
            return updated
    if value.get("deadline") and now.astimezone(dt.timezone.utc) > _parse_time(value["deadline"]).astimezone(dt.timezone.utc):
        updated = dict(value)
        updated["status"] = "OVERDUE"
        updated["resolved_at"] = utcnow()
        write_json_atomic(EXPECT_DIR / f"{value['id']}.json", updated)
        return updated
    return value


def evaluate_all(*, now: dt.datetime | None = None) -> list[dict]:
    return [evaluate_expectation(value, now=now) for value in all_expectations()]
