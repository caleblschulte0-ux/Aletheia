"""Durable notification center with dedupe, snooze, priority and acknowledgement.

This module is an inbox, not a transport. It records what deserves operator
attention and when it may surface. A later adapter can speak/show/push due
notifications without every watcher inventing its own notification semantics.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

NOTIFICATIONS_DIR = private_dir("notifications")
PRIORITIES = {"info": 0, "normal": 1, "high": 2, "critical": 3}
STATUSES = {"OPEN", "ACKED", "CANCELLED"}
MAX_SUMMARY = 1000


def _path(notification_id: str) -> Path:
    return NOTIFICATIONS_DIR / f"{safe_id(notification_id, name='notification id')}.json"


def _parse_time(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid notification timestamp {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("notification timestamps must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def validate(value: dict) -> None:
    required = {"version", "id", "topic", "summary", "priority", "status",
                "occurrences", "created_at", "updated_at"}
    missing = required - value.keys()
    if missing:
        raise ValueError(f"notification missing {sorted(missing)}")
    if value["version"] != 1:
        raise ValueError("unsupported notification version")
    safe_id(value["id"], name="notification id")
    if value["priority"] not in PRIORITIES or value["status"] not in STATUSES:
        raise ValueError("invalid notification priority/status")
    for key in ("topic", "summary"):
        if not isinstance(value[key], str) or not value[key].strip():
            raise ValueError(f"notification {key} is required")
    if len(value["summary"]) > MAX_SUMMARY:
        raise ValueError(f"notification summary exceeds {MAX_SUMMARY} characters")
    if type(value["occurrences"]) is not int or value["occurrences"] < 1:
        raise ValueError("notification occurrences must be >= 1")
    for key in ("expires_at", "snoozed_until"):
        if key in value:
            _parse_time(value[key])


def load(notification_id: str) -> dict:
    value = read_json(_path(notification_id))
    validate(value)
    return value


def all_notifications() -> list[dict]:
    if not NOTIFICATIONS_DIR.is_dir():
        return []
    out = []
    for path in NOTIFICATIONS_DIR.glob("*.json"):
        try:
            out.append(load(path.stem))
        except ValueError:
            continue
    return sorted(out, key=lambda n: (PRIORITIES[n["priority"]], n["created_at"]), reverse=True)


def _open_by_dedupe(dedupe_key: str) -> dict | None:
    for value in all_notifications():
        if value["status"] == "OPEN" and value.get("dedupe_key") == dedupe_key:
            return value
    return None


def create(notification_id: str, *, topic: str, summary: str,
           priority: str = "normal", dedupe_key: str | None = None,
           source: str = "aletheia", expires_at: str | None = None) -> dict:
    safe_id(notification_id, name="notification id")
    if dedupe_key is not None and (not isinstance(dedupe_key, str) or not dedupe_key.strip()):
        raise ValueError("dedupe_key must be non-empty when provided")
    if dedupe_key:
        existing = _open_by_dedupe(dedupe_key)
        if existing:
            existing["occurrences"] += 1
            existing["summary"] = summary
            existing["last_seen_at"] = utcnow()
            existing["updated_at"] = utcnow()
            if PRIORITIES.get(priority, -1) > PRIORITIES.get(existing["priority"], -1):
                existing["priority"] = priority
            validate(existing)
            write_json_atomic(_path(existing["id"]), existing)
            return existing
    path = _path(notification_id)
    if path.exists():
        raise FileExistsError(notification_id)
    now = utcnow()
    value = {"version": 1, "id": notification_id, "topic": topic, "summary": summary,
             "priority": priority, "status": "OPEN", "source": source,
             "occurrences": 1, "created_at": now, "updated_at": now}
    if dedupe_key:
        value["dedupe_key"] = dedupe_key
    if expires_at:
        value["expires_at"] = expires_at
    validate(value)
    write_json_atomic(path, value)
    return value


def acknowledge(notification_id: str, *, actor: str = "operator") -> dict:
    value = load(notification_id)
    if value["status"] == "CANCELLED":
        raise ValueError("cancelled notification cannot be acknowledged")
    value["status"] = "ACKED"
    value["acknowledged_by"] = actor
    value["acknowledged_at"] = utcnow()
    value["updated_at"] = utcnow()
    validate(value)
    write_json_atomic(_path(notification_id), value)
    return value


def cancel(notification_id: str, *, reason: str = "") -> dict:
    value = load(notification_id)
    if value["status"] == "ACKED":
        return value
    value["status"] = "CANCELLED"
    value["cancelled_at"] = utcnow()
    if reason:
        value["cancel_reason"] = reason
    value["updated_at"] = utcnow()
    validate(value)
    write_json_atomic(_path(notification_id), value)
    return value


def snooze(notification_id: str, until: str) -> dict:
    value = load(notification_id)
    if value["status"] != "OPEN":
        raise ValueError("only open notifications may be snoozed")
    if _parse_time(until) <= dt.datetime.now(dt.timezone.utc):
        raise ValueError("snooze must end in the future")
    value["snoozed_until"] = until
    value["updated_at"] = utcnow()
    validate(value)
    write_json_atomic(_path(notification_id), value)
    return value


def due(*, now: dt.datetime | None = None) -> list[dict]:
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    now_utc = now.astimezone(dt.timezone.utc)
    out = []
    for value in all_notifications():
        if value["status"] != "OPEN":
            continue
        if value.get("expires_at") and _parse_time(value["expires_at"]) <= now_utc:
            continue
        if value.get("snoozed_until") and _parse_time(value["snoozed_until"]) > now_utc:
            continue
        out.append(value)
    return sorted(out, key=lambda n: (PRIORITIES[n["priority"]], n["created_at"]), reverse=True)
