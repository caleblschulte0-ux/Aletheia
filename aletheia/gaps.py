"""Capability-gap detector and idempotent work materializer.

Aletheia names the exact missing primitive instead of improvising success.
NOT_BUILT/UNAVAILABLE/unknown capabilities become reviewable development work;
NEEDS_CONFIGURATION becomes operator setup work; EXPERIMENTAL/DEGRADED become
verification/repair work. No gap task grants authority by itself.
"""
from __future__ import annotations

import hashlib

from aletheia import capabilities, tasks

READY_STATUSES = {"AVAILABLE"}
BUILD_STATUSES = {"NOT_BUILT", "UNAVAILABLE"}
VERIFY_STATUSES = {"EXPERIMENTAL", "DEGRADED"}
CONFIG_STATUSES = {"NEEDS_CONFIGURATION"}


def assess(required: list[str], *, registry: dict | None = None) -> dict:
    registry = registry or capabilities.load_registry()
    by_id = {c["id"]: c for c in registry.get("capabilities", [])}
    available, blocked, unknown = [], [], []
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


def _task_id(prefix: str, capability_id: str) -> str:
    base = prefix + "-" + capability_id.replace(".", "-").replace("_", "-")
    if len(base) <= 60:
        return base
    digest = hashlib.sha256(f"{prefix}:{capability_id}".encode()).hexdigest()[:10]
    return base[:49].rstrip("-") + "-" + digest


def work_specs(required: list[str], *, registry: dict | None = None,
               worker: str = "claude") -> list[dict]:
    report = assess(required, registry=registry)
    specs: list[dict] = []
    for item in report["blocked"]:
        cid, status = item["id"], item["status"]
        if status in CONFIG_STATUSES:
            specs.append({
                "id": _task_id("configure", cid),
                "description": f"Configure capability {cid}",
                "goal": f"Complete the documented operator/environment setup for {cid} and verify it live",
                "required_capabilities": [], "assigned_worker": None, "priority": 2,
                "initial_status": "WAITING_OPERATOR", "gap": item,
            })
        elif status in VERIFY_STATUSES:
            specs.append({
                "id": _task_id("verify", cid),
                "description": f"Verify or repair capability {cid}",
                "goal": f"Produce live evidence for {cid} ({status}); repair implementation if evidence fails",
                "required_capabilities": [], "assigned_worker": worker, "priority": 2,
                "initial_status": "QUEUED", "gap": item,
            })
        else:
            specs.append({
                "id": _task_id("build", cid),
                "description": f"Make capability {cid} genuinely AVAILABLE",
                "goal": f"Close capability gap {cid} ({status}) with implementation, tests, review and evidence",
                "required_capabilities": [], "assigned_worker": worker, "priority": 2,
                "initial_status": "QUEUED", "gap": item,
            })
    for cid in report["unknown"]:
        specs.append({
            "id": _task_id("build", cid),
            "description": f"Define and build missing capability {cid}",
            "goal": f"Add an honest registry contract, implementation, tests and verification for {cid}",
            "required_capabilities": [], "assigned_worker": worker, "priority": 2,
            "initial_status": "QUEUED", "gap": {"id": cid, "status": "UNKNOWN"},
        })
    return specs


def development_specs(required: list[str], *, registry: dict | None = None,
                      worker: str = "claude") -> list[dict]:
    """Compatibility name: now returns all gap work, including configuration."""
    return work_specs(required, registry=registry, worker=worker)


def materialize(required: list[str], *, registry: dict | None = None,
                worker: str = "claude") -> list[dict]:
    existing = {t["id"]: t for t in tasks.all_tasks()}
    created = []
    for spec in work_specs(required, registry=registry, worker=worker):
        if spec["id"] in existing:
            created.append(existing[spec["id"]])
            continue
        task = tasks.create(spec["id"], spec["description"], goal=spec["goal"],
                            required_capabilities=spec["required_capabilities"],
                            assigned_worker=spec["assigned_worker"], priority=spec["priority"])
        if spec["initial_status"] != "QUEUED":
            task = tasks.set_status(task["id"], spec["initial_status"],
                                    f"capability {spec['gap']['id']} requires operator/environment setup")
        created.append(task)
    return created
