"""First-class private project records linking goals, tasks, people and blockers."""
from __future__ import annotations

from pathlib import Path

from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

PROJECTS_DIR = private_dir("projects")
STATUSES = {"ACTIVE", "PAUSED", "BLOCKED", "COMPLETED", "CANCELLED"}
TERMINAL = {"COMPLETED", "CANCELLED"}


def _path(project_id: str) -> Path:
    return PROJECTS_DIR / f"{safe_id(project_id, name='project id')}.json"


def validate(value: dict) -> None:
    required = {"version", "id", "title", "goal", "status", "task_ids", "people",
                "blockers", "decisions", "created_at", "updated_at"}
    missing = required - value.keys()
    if missing:
        raise ValueError(f"project missing {sorted(missing)}")
    if value["version"] != 1 or value["status"] not in STATUSES:
        raise ValueError("unsupported project version/status")
    safe_id(value["id"], name="project id")
    if not isinstance(value["title"], str) or not value["title"].strip():
        raise ValueError("project title is required")
    if not isinstance(value["goal"], str) or not value["goal"].strip():
        raise ValueError("project goal is required")
    for key in ("task_ids", "people"):
        items = value[key]
        if not isinstance(items, list) or any(not isinstance(item, str) or not item.strip() for item in items):
            raise ValueError(f"{key} must contain strings")
        if len(set(items)) != len(items):
            raise ValueError(f"{key} must be unique")
    for key in ("blockers", "decisions"):
        if not isinstance(value[key], list):
            raise ValueError(f"{key} must be a list")


def create(project_id: str, title: str, *, goal: str,
           task_ids: list[str] | None = None, people: list[str] | None = None) -> dict:
    if _path(project_id).exists():
        raise FileExistsError(project_id)
    now = utcnow()
    value = {"version": 1, "id": safe_id(project_id, name="project id"), "title": title.strip(),
             "goal": goal.strip(), "status": "ACTIVE", "task_ids": task_ids or [],
             "people": people or [], "blockers": [], "decisions": [],
             "created_at": now, "updated_at": now}
    validate(value)
    write_json_atomic(_path(project_id), value)
    return value


def load(project_id: str) -> dict:
    value = read_json(_path(project_id))
    validate(value)
    return value


def all_projects() -> list[dict]:
    if not PROJECTS_DIR.is_dir():
        return []
    out = []
    for path in sorted(PROJECTS_DIR.glob("*.json")):
        try:
            out.append(load(path.stem))
        except ValueError:
            continue
    return sorted(out, key=lambda p: (p["status"] in TERMINAL, p["updated_at"]), reverse=False)


def update(project_id: str, *, status: str | None = None, add_task: str | None = None,
           add_person: str | None = None, blocker: str | None = None,
           decision: str | None = None) -> dict:
    value = load(project_id)
    if value["status"] in TERMINAL:
        raise ValueError("terminal project cannot change")
    if status:
        if status not in STATUSES:
            raise ValueError("invalid project status")
        value["status"] = status
    if add_task and add_task not in value["task_ids"]:
        value["task_ids"].append(add_task)
    if add_person and add_person not in value["people"]:
        value["people"].append(add_person)
    if blocker:
        value["blockers"].append({"at": utcnow(), "text": blocker})
    if decision:
        value["decisions"].append({"at": utcnow(), "text": decision})
    value["updated_at"] = utcnow()
    validate(value)
    write_json_atomic(_path(project_id), value)
    return value
