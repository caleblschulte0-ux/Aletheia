"""Persistent obligations: what Aletheia is waiting for and what resumes next.

Tasks already know WAITING_EXTERNAL. This module adds the missing semantic link:
*which* future event satisfies the wait, an optional deadline, and the target
that should be proposed for resumption. It consumes event-shaped dictionaries
but does not require or execute the Phase-17 event bus.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

OBLIGATIONS_DIR = private_dir("obligations")
STATUSES = {"WAITING", "OVERDUE", "SATISFIED", "CANCELLED"}
TARGET_KINDS = {"task", "goal", "project"}


def _path(obligation_id: str) -> Path:
    return OBLIGATIONS_DIR / f"{safe_id(obligation_id, name='obligation id')}.json"


def _parse_time(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid obligation timestamp {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("obligation timestamps must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def _validate_match(match: dict) -> None:
    allowed = {"kind", "source", "subject_prefix", "attributes"}
    unknown = set(match) - allowed
    if unknown:
        raise ValueError(f"unknown obligation matcher fields {sorted(unknown)}")
    if not match:
        raise ValueError("obligation matcher may not match everything")
    for key in ("kind", "source", "subject_prefix"):
        if key in match and (not isinstance(match[key], str) or not match[key]):
            raise ValueError(f"matcher {key} must be a non-empty string")
    attrs = match.get("attributes", {})
    if not isinstance(attrs, dict) or len(attrs) > 16:
        raise ValueError("matcher attributes must be an object with at most 16 keys")
    for key, value in attrs.items():
        if not isinstance(key, str) or not key or isinstance(value, (dict, list)):
            raise ValueError("matcher attributes must use scalar exact values")


def validate(value: dict) -> None:
    required = {"version", "id", "summary", "match", "resume", "status", "created_at", "updated_at"}
    missing = required - value.keys()
    if missing:
        raise ValueError(f"obligation missing {sorted(missing)}")
    if value["version"] != 1 or value["status"] not in STATUSES:
        raise ValueError("unsupported obligation version/status")
    safe_id(value["id"], name="obligation id")
    if not isinstance(value["summary"], str) or not value["summary"].strip():
        raise ValueError("obligation summary is required")
    _validate_match(value["match"])
    resume = value["resume"]
    if not isinstance(resume, dict) or set(resume) != {"kind", "id"}:
        raise ValueError("resume target must contain exactly kind and id")
    if resume["kind"] not in TARGET_KINDS:
        raise ValueError("invalid resume target kind")
    safe_id(resume["id"], name="resume target id")
    if "deadline" in value:
        _parse_time(value["deadline"])


def create(obligation_id: str, *, summary: str, match: dict, resume_kind: str,
           resume_id: str, deadline: str | None = None) -> dict:
    if _path(obligation_id).exists():
        raise FileExistsError(obligation_id)
    now = utcnow()
    value = {"version": 1, "id": safe_id(obligation_id, name="obligation id"),
             "summary": summary, "match": match,
             "resume": {"kind": resume_kind, "id": resume_id},
             "status": "WAITING", "created_at": now, "updated_at": now}
    if deadline:
        value["deadline"] = deadline
    validate(value)
    write_json_atomic(_path(obligation_id), value)
    return value


def load(obligation_id: str) -> dict:
    value = read_json(_path(obligation_id))
    validate(value)
    return value


def all_obligations() -> list[dict]:
    if not OBLIGATIONS_DIR.is_dir():
        return []
    out = []
    for path in sorted(OBLIGATIONS_DIR.glob("*.json")):
        try:
            out.append(load(path.stem))
        except ValueError:
            continue
    return out


def matches(match: dict, event: dict) -> bool:
    _validate_match(match)
    if match.get("kind") and event.get("kind") != match["kind"]:
        return False
    if match.get("source") and event.get("source") != match["source"]:
        return False
    if match.get("subject_prefix") and not str(event.get("subject", "")).startswith(match["subject_prefix"]):
        return False
    attrs = event.get("attributes", {})
    if not isinstance(attrs, dict):
        return False
    for key, expected in match.get("attributes", {}).items():
        if attrs.get(key) != expected:
            return False
    return True


def evaluate(value: dict, event: dict) -> dict:
    validate(value)
    if value["status"] in {"SATISFIED", "CANCELLED"}:
        return value
    if not matches(value["match"], event):
        return value
    event_id = safe_id(str(event.get("id", "")), name="event id")
    updated = dict(value)
    updated["status"] = "SATISFIED"
    updated["satisfied_by_event"] = event_id
    updated["satisfied_at"] = utcnow()
    updated["updated_at"] = utcnow()
    updated["proposal"] = {"kind": "resume", "target": updated["resume"], "obligation_id": updated["id"]}
    validate(updated)
    write_json_atomic(_path(updated["id"]), updated)
    return updated


def check_deadline(value: dict, *, now: dt.datetime | None = None) -> dict:
    validate(value)
    if value["status"] in {"SATISFIED", "CANCELLED"} or not value.get("deadline"):
        return value
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if _parse_time(value["deadline"]) <= now.astimezone(dt.timezone.utc) and value["status"] != "OVERDUE":
        value = dict(value)
        value["status"] = "OVERDUE"
        value["overdue_at"] = utcnow()
        value["updated_at"] = utcnow()
        validate(value)
        write_json_atomic(_path(value["id"]), value)
    return value


def cancel(obligation_id: str, *, reason: str = "") -> dict:
    value = load(obligation_id)
    if value["status"] == "SATISFIED":
        return value
    value["status"] = "CANCELLED"
    value["cancelled_at"] = utcnow()
    if reason:
        value["cancel_reason"] = reason
    value["updated_at"] = utcnow()
    validate(value)
    write_json_atomic(_path(obligation_id), value)
    return value
