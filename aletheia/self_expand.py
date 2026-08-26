"""Phase-20 foundation: gap -> development work -> verified capability -> resume.

This module does not let code generation silently become authority. It can
materialize ordinary development tasks for missing capabilities, then waits
until the capability registry itself says *every* required capability is
AVAILABLE. Only then does it emit a proposal to resume the original target.
"""
from __future__ import annotations

from pathlib import Path

from aletheia import capabilities, gaps
from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

EXPANSIONS_DIR = private_dir("expansions")
TARGET_KINDS = {"task", "goal", "project"}
STATES = {"WAITING_CAPABILITY", "READY_TO_RESUME", "CANCELLED"}


def _path(expansion_id: str) -> Path:
    return EXPANSIONS_DIR / f"{safe_id(expansion_id, name='expansion id')}.json"


def validate(value: dict) -> None:
    required = {"version", "id", "required_capabilities", "resume", "state",
                "development_task_ids", "created_at", "updated_at"}
    missing = required - value.keys()
    if missing:
        raise ValueError(f"expansion missing {sorted(missing)}")
    if value["version"] != 1 or value["state"] not in STATES:
        raise ValueError("unsupported expansion version/state")
    safe_id(value["id"], name="expansion id")
    caps = value["required_capabilities"]
    if not isinstance(caps, list) or not caps or any(not isinstance(c, str) or not c for c in caps):
        raise ValueError("required_capabilities must be non-empty strings")
    if len(set(caps)) != len(caps):
        raise ValueError("required_capabilities must be unique")
    resume = value["resume"]
    if not isinstance(resume, dict) or set(resume) != {"kind", "id"} or resume["kind"] not in TARGET_KINDS:
        raise ValueError("invalid expansion resume target")
    safe_id(resume["id"], name="resume target id")
    if not isinstance(value["development_task_ids"], list):
        raise ValueError("development_task_ids must be a list")


def stage(expansion_id: str, *, required_capabilities: list[str], resume_kind: str,
          resume_id: str, registry: dict | None = None, worker: str = "claude") -> dict:
    path = _path(expansion_id)
    if path.exists():
        return load(expansion_id)
    registry = registry or capabilities.load_registry()
    report = gaps.assess(required_capabilities, registry=registry)
    development = [] if report["satisfied"] else gaps.materialize(required_capabilities, registry=registry, worker=worker)
    now = utcnow()
    value = {"version": 1, "id": safe_id(expansion_id, name="expansion id"),
             "required_capabilities": list(dict.fromkeys(required_capabilities)),
             "resume": {"kind": resume_kind, "id": resume_id},
             "state": "READY_TO_RESUME" if report["satisfied"] else "WAITING_CAPABILITY",
             "development_task_ids": [task["id"] for task in development],
             "missing": [item["id"] for item in report["blocked"]] + report["unknown"],
             "created_at": now, "updated_at": now}
    if report["satisfied"]:
        value["proposal"] = {"kind": "resume", "target": value["resume"], "expansion_id": value["id"]}
    validate(value)
    write_json_atomic(path, value)
    return value


def load(expansion_id: str) -> dict:
    value = read_json(_path(expansion_id))
    validate(value)
    return value


def refresh(expansion_id: str, *, registry: dict | None = None) -> dict:
    value = load(expansion_id)
    if value["state"] == "CANCELLED":
        return value
    registry = registry or capabilities.load_registry()
    report = gaps.assess(value["required_capabilities"], registry=registry)
    value["missing"] = [item["id"] for item in report["blocked"]] + report["unknown"]
    if report["satisfied"]:
        value["state"] = "READY_TO_RESUME"
        value["proposal"] = {"kind": "resume", "target": value["resume"], "expansion_id": value["id"]}
        value["ready_at"] = utcnow()
    else:
        value["state"] = "WAITING_CAPABILITY"
        value.pop("proposal", None)
    value["updated_at"] = utcnow()
    validate(value)
    write_json_atomic(_path(expansion_id), value)
    return value


def consume_event(expansion_id: str, event: dict, *, registry: dict | None = None) -> dict:
    value = load(expansion_id)
    if event.get("kind") != "capability.available":
        return value
    attrs = event.get("attributes", {})
    if not isinstance(attrs, dict) or attrs.get("capability_id") not in value["required_capabilities"]:
        return value
    return refresh(expansion_id, registry=registry)


def cancel(expansion_id: str) -> dict:
    value = load(expansion_id)
    value["state"] = "CANCELLED"
    value.pop("proposal", None)
    value["updated_at"] = utcnow()
    write_json_atomic(_path(expansion_id), value)
    return value
