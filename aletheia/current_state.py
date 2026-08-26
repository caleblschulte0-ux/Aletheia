"""Canonical model of NOW for every Aletheia interface.

This aggregates durable truth; it does not invent live activity. Missing or
unconfigured stores degrade to empty/error sections rather than fake status.
"""
from __future__ import annotations

import datetime as dt

from aletheia import capabilities, communications, notifications, policy, projects, scheduler, tasks

TERMINAL_TASKS = {"COMPLETED", "CANCELLED", "FAILED_TERMINAL"}


def snapshot(*, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    all_tasks = tasks.all_tasks()
    all_projects = projects.all_projects()
    approvals = policy.all_approvals()
    expectations = communications.all_expectations()
    schedules = scheduler.all_schedules()
    registry = capabilities.load_registry()

    waiting_replies = [e for e in expectations if e.get("status") == "WAITING"]
    overdue_replies = [e for e in expectations if e.get("status") == "OVERDUE"]
    active_projects = [p for p in all_projects if p.get("status") not in {"COMPLETED", "CANCELLED"}]
    active_tasks = [t for t in all_tasks if t.get("status") not in TERMINAL_TASKS]
    blocked_tasks = [t for t in active_tasks if t.get("status") in {"BLOCKED", "FAILED_RETRYABLE"}]
    waiting_operator = [t for t in active_tasks if t.get("status") == "WAITING_OPERATOR"]
    pending_approvals = [a for a in approvals if a.get("state") == "PENDING"]

    upcoming = []
    for spec in schedules:
        try:
            occurrence = scheduler.next_occurrence(spec, now)
        except ValueError:
            continue
        if occurrence is not None:
            upcoming.append({"schedule_id": spec["id"], "at": occurrence.isoformat(),
                             "command_kind": spec["command"].get("kind")})
    upcoming.sort(key=lambda item: item["at"])

    unavailable = [c for c in registry.get("capabilities", []) if c.get("status") != "AVAILABLE"]
    return {
        "version": 1,
        "as_of": now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "halted": bool(policy.halted()),
        "focus": {
            "active_projects": [{"id": p["id"], "title": p["title"], "status": p["status"]}
                                for p in active_projects],
            "active_tasks": [{"id": t["id"], "description": t["description"], "status": t["status"]}
                             for t in active_tasks],
        },
        "needs_attention": {
            "pending_approvals": [a["id"] for a in pending_approvals],
            "waiting_operator": [t["id"] for t in waiting_operator],
            "blocked_tasks": [t["id"] for t in blocked_tasks],
            "overdue_replies": [e["id"] for e in overdue_replies],
            "unread_notifications": notifications.unread_count(),
        },
        "waiting": {"replies": [e["id"] for e in waiting_replies]},
        "upcoming": upcoming[:20],
        "capability_gaps": [{"id": c["id"], "status": c["status"]} for c in unavailable],
    }
