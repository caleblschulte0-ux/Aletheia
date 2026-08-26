"""Small first-class project registry linking goals, tasks, people and blockers."""
from __future__ import annotations

from pathlib import Path

from aletheia.fleet import REPO_ROOT
from aletheia.stateio import read_json, safe_id, utcnow, write_json_atomic

PROJECTS_DIR = REPO_ROOT / "state" / "projects"
STATUSES = {"ACTIVE", "PAUSED", "BLOCKED", "COMPLETED", "CANCELLED"}


def _path(project_id: str) -> Path:
    return PROJECTS_DIR / f"{safe_id(project_id, name='project id')}.json"


def create(project_id: str, title: str, *, goal: str,
           task_ids: list[str] | None = None, people: list[str] | None = None) -> dict:
    if _path(project_id).exists():
        raise FileExistsError(project_id)
    now = utcnow()
    value = {"version": 1, "id": project_id, "title": title.strip(), "goal": goal.strip(),
             "status": "ACTIVE", "task_ids": task_ids or [], "people": people or [],
             "blockers": [], "decisions": [], "created_at": now, "updated_at": now}
    write_json_atomic(_path(project_id), value)
    return value


def load(project_id: str) -> dict:
    return read_json(_path(project_id))


def update(project_id: str, *, status: str | None = None, add_task: str | None = None,
           add_person: str | None = None, blocker: str | None = None,
           decision: str | None = None) -> dict:
    value = load(project_id)
    if value["status"] in {"COMPLETED", "CANCELLED"}:
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
    write_json_atomic(_path(project_id), value)
    return value
