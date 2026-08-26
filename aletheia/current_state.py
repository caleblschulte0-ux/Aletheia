"""Derived 'what is happening right now' snapshot.

Aletheia has durable tasks, projects, approvals, obligations, notifications,
actions and schedules. This module turns those stores into one read-only current
state without creating a second source of truth. Every field is derived fresh.
"""
from __future__ import annotations

from aletheia import notifications, obligations, outcomes, policy, projects, scheduler, tasks
from aletheia.stateio import utcnow


def _group(rows: list[dict], key: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for row in rows:
        out.setdefault(str(row.get(key, "UNKNOWN")), []).append(row)
    return out


def snapshot(*, task_rows: list[dict] | None = None,
             project_rows: list[dict] | None = None,
             approval_rows: list[dict] | None = None,
             obligation_rows: list[dict] | None = None,
             notification_rows: list[dict] | None = None,
             action_rows: list[dict] | None = None,
             schedule_rows: list[dict] | None = None) -> dict:
    task_rows = tasks.all_tasks() if task_rows is None else task_rows
    project_rows = _all_projects() if project_rows is None else project_rows
    approval_rows = policy.all_approvals() if approval_rows is None else approval_rows
    obligation_rows = obligations.all_obligations() if obligation_rows is None else obligation_rows
    notification_rows = notifications.all_notifications() if notification_rows is None else notification_rows
    action_rows = outcomes.all_actions() if action_rows is None else action_rows
    schedule_rows = scheduler.all_schedules() if schedule_rows is None else schedule_rows

    task_groups = _group(task_rows, "status")
    project_groups = _group(project_rows, "status")
    obligation_groups = _group(obligation_rows, "status")
    action_groups = _group(action_rows, "status")

    pending_approvals = [a for a in approval_rows if a.get("state") == "PENDING"]
    open_notifications = [n for n in notification_rows if n.get("status") == "OPEN"]
    critical_notifications = [n for n in open_notifications if n.get("priority") == "critical"]
    enabled_schedules = [s for s in schedule_rows if s.get("enabled") is True]

    attention: list[dict] = []
    for n in critical_notifications:
        attention.append({"kind": "notification", "id": n.get("id"), "reason": n.get("summary", "critical notification")})
    for a in pending_approvals:
        attention.append({"kind": "approval", "id": a.get("id"), "reason": a.get("requested_action", "approval required")})
    for o in obligation_groups.get("OVERDUE", []):
        attention.append({"kind": "obligation", "id": o.get("id"), "reason": o.get("summary", "overdue obligation")})
    for t in task_groups.get("FAILED_RETRYABLE", []) + task_groups.get("FAILED_TERMINAL", []):
        attention.append({"kind": "task", "id": t.get("id"), "reason": t.get("error") or t.get("description", "task failed")})
    for action in action_groups.get("AWAITING_VERIFICATION", []):
        attention.append({"kind": "verification", "id": action.get("id"), "reason": action.get("intent", "action needs verification")})

    return {
        "generated_at": utcnow(),
        "counts": {
            "tasks_total": len(task_rows),
            "tasks_running": len(task_groups.get("RUNNING", [])),
            "tasks_ready": len(task_groups.get("READY", [])),
            "tasks_waiting": sum(len(task_groups.get(s, [])) for s in ("WAITING_OPERATOR", "WAITING_EXTERNAL", "WAITING_DEPENDENCY", "RETRY_SCHEDULED")),
            "projects_active": len(project_groups.get("ACTIVE", [])),
            "projects_blocked": len(project_groups.get("BLOCKED", [])),
            "approvals_pending": len(pending_approvals),
            "obligations_waiting": len(obligation_groups.get("WAITING", [])),
            "obligations_overdue": len(obligation_groups.get("OVERDUE", [])),
            "notifications_open": len(open_notifications),
            "actions_awaiting_verification": len(action_groups.get("AWAITING_VERIFICATION", [])),
            "schedules_enabled": len(enabled_schedules),
        },
        "running_tasks": task_groups.get("RUNNING", []),
        "ready_tasks": task_groups.get("READY", []),
        "waiting_obligations": obligation_groups.get("WAITING", []),
        "overdue_obligations": obligation_groups.get("OVERDUE", []),
        "pending_approvals": pending_approvals,
        "open_notifications": open_notifications,
        "attention": attention,
    }


def _all_projects() -> list[dict]:
    if not projects.PROJECTS_DIR.is_dir():
        return []
    out = []
    for path in sorted(projects.PROJECTS_DIR.glob("*.json")):
        try:
            out.append(projects.load(path.stem))
        except ValueError:
            continue
    return out
