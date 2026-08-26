"""Persistent 'handle it' planning without pretending arbitrary understanding.

Callers provide a resolved intent, exact required capabilities and an optional
command proposal. The handler checks registry truth, materializes capability-gap
work when blocked, and persists the request so it can be resumed after the gap
closes. It never bypasses policy or executes a command directly.
"""
from __future__ import annotations

from pathlib import Path

from aletheia import gaps
from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

REQUESTS_DIR = private_dir("handler") / "requests"
STATES = {"BLOCKED_CAPABILITY", "READY", "COMPLETED", "CANCELLED"}


def _path(request_id: str) -> Path:
    return REQUESTS_DIR / f"{safe_id(request_id, name='request id')}.json"


def create(request_id: str, *, intent: str, required_capabilities: list[str],
           command: dict | None = None, registry: dict | None = None,
           materialize_gaps: bool = True) -> dict:
    if _path(request_id).exists():
        raise FileExistsError(request_id)
    if not isinstance(intent, str) or not intent.strip():
        raise ValueError("intent is required")
    if not isinstance(required_capabilities, list) or any(not isinstance(x, str) or not x for x in required_capabilities):
        raise ValueError("required_capabilities must be capability ids")
    if command is not None and (not isinstance(command, dict) or not isinstance(command.get("kind"), str)):
        raise ValueError("command proposal must be an object with kind")
    report = gaps.assess(required_capabilities, registry=registry)
    work = []
    if not report["satisfied"] and materialize_gaps:
        work = gaps.materialize(required_capabilities, registry=registry)
    now = utcnow()
    value = {"version": 1, "id": safe_id(request_id, name="request id"), "intent": intent.strip(),
             "required_capabilities": required_capabilities, "assessment": report,
             "state": "READY" if report["satisfied"] else "BLOCKED_CAPABILITY",
             "gap_tasks": [t["id"] for t in work], "created_at": now, "updated_at": now}
    if command is not None:
        value["command_proposal"] = command
    write_json_atomic(_path(request_id), value)
    return value


def load(request_id: str) -> dict:
    return read_json(_path(request_id))


def refresh(request_id: str, *, registry: dict | None = None,
            materialize_gaps: bool = True) -> dict:
    value = load(request_id)
    if value["state"] in {"COMPLETED", "CANCELLED"}:
        return value
    report = gaps.assess(value["required_capabilities"], registry=registry)
    value["assessment"] = report
    value["state"] = "READY" if report["satisfied"] else "BLOCKED_CAPABILITY"
    if not report["satisfied"] and materialize_gaps:
        work = gaps.materialize(value["required_capabilities"], registry=registry)
        value["gap_tasks"] = sorted(set(value.get("gap_tasks", [])) | {t["id"] for t in work})
    value["updated_at"] = utcnow()
    write_json_atomic(_path(request_id), value)
    return value


def complete(request_id: str, *, evidence: str) -> dict:
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError("completion requires evidence")
    value = load(request_id)
    if value["state"] != "READY":
        raise ValueError("request is not ready for completion")
    value["state"] = "COMPLETED"
    value["evidence"] = evidence.strip()
    value["completed_at"] = utcnow()
    value["updated_at"] = utcnow()
    write_json_atomic(_path(request_id), value)
    return value


def cancel(request_id: str, *, reason: str) -> dict:
    value = load(request_id)
    if value["state"] == "COMPLETED":
        raise ValueError("completed request cannot be cancelled")
    value["state"] = "CANCELLED"
    value["cancel_reason"] = reason
    value["updated_at"] = utcnow()
    write_json_atomic(_path(request_id), value)
    return value
