"""Capability-gap detector and idempotent development-task materializer.

When a goal requires abilities that are not AVAILABLE, Aletheia should name the
missing primitive rather than improvise success. Phase 20 can build on this to
turn gaps into reviewable worker tasks and later resume the original goal.
"""
from __future__ import annotations

import hashlib

from aletheia import capabilities, tasks

READY_STATUSES = {"AVAILABLE"}


def assess(required: list[str], *, registry: dict | None = None) -> dict:
    registry = registry or capabilities.load_registry()
    by_id = {c["id"]: c for c in registry.get("capabilities", [])}
    available = []
    blocked = []
    unknown = []
    for cid in dict.fromkeys(required):
        entry = by_id.get(cid)
        if entry is None:
            unknown.append(cid)
        elif entry["status"] in READY_STATUSES:
            available.append(cid)
        else:
            blocked.append({"id": cid, "status": entry["status"],
                            "caller": entry.get("caller"), "notes": entry.get("notes", "")})
    return {"available": available, "blocked": blocked, "unknown": unknown,
            "satisfied": not blocked and not unknown}


def _task_id(capability_id: str) -> str:
    base = "build-" + capability_id.replace(".", "-").replace("_", "-")
    if len(base) <= 60:
        return base
    digest = hashlib.sha256(capability_id.encode()).hexdigest()[:10]
    return base[:49].rstrip("-") + "-" + digest


def development_specs(required: list[str], *, registry: dict | None = None,
                      worker: str = "claude") -> list[dict]:
    report = assess(required, registry=registry)
    specs = []
    for item in report["blocked"]:
        specs.append({"id": _task_id(item["id"]),
                      "description": f"Make capability {item['id']} genuinely AVAILABLE",
                      "goal": f"Close capability gap {item['id']} ({item['status']}) with tests and verification evidence",
                      "required_capabilities": [], "assigned_worker": worker, "priority": 2,
                      "gap": item})
    for cid in report["unknown"]:
        specs.append({"id": _task_id(cid),
                      "description": f"Define and build missing capability {cid}",
                      "goal": f"Add an honest registry contract, implementation, tests, and verification for {cid}",
                      "required_capabilities": [], "assigned_worker": worker, "priority": 2,
                      "gap": {"id": cid, "status": "UNKNOWN"}})
    return specs


def materialize(required: list[str], *, registry: dict | None = None,
                worker: str = "claude") -> list[dict]:
    existing = {t["id"]: t for t in tasks.all_tasks()}
    created = []
    for spec in development_specs(required, registry=registry, worker=worker):
        if spec["id"] in existing:
            created.append(existing[spec["id"]])
            continue
        created.append(tasks.create(spec["id"], spec["description"], goal=spec["goal"],
                                    required_capabilities=spec["required_capabilities"],
                                    assigned_worker=spec["assigned_worker"], priority=spec["priority"]))
    return created
