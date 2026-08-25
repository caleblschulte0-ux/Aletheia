"""The durable task engine (Playbook §§27–29, 139; Phase 3, v0).

A task is real work that outlives any conversation: it persists as one
JSON file in `state/tasks/`, carries the §28 lifecycle, can depend on
other tasks, counts its attempts, and remembers its result. "I called
once and they didn't answer" is WAITING_EXTERNAL with attempts=1 — not
a forgotten chat message and not a failure.

v0 is file-backed and CLI-driven — the same store the local Core (Phase
6+) will take over, so nothing here is throwaway. Rules:

- **States come from `contracts.TASK_STATES`** — never restated here.
- **Readiness is derived, never stored**: a QUEUED/WAITING_DEPENDENCY
  task is ready when every dependency is COMPLETED; `ready()` computes
  it fresh each call.
- **A terminal task never changes state again** (§28: CANCELLED,
  COMPLETED, FAILED_TERMINAL are the end).
- **Every state change is journaled** — the audit trail is not optional.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

from aletheia import contracts, journal
from aletheia.fleet import REPO_ROOT

TASKS_DIR = REPO_ROOT / "state" / "tasks"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _path(tid: str) -> Path:
    return TASKS_DIR / f"{tid}.json"


def load(tid: str) -> dict:
    return json.loads(_path(tid).read_text(encoding="utf-8"))


def save(task: dict) -> None:
    problems = contracts.validate_task(task)
    if problems:
        raise ValueError("task violates the contract: " + "; ".join(problems))
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    _path(task["id"]).write_text(
        json.dumps(task, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def all_tasks() -> list[dict]:
    if not TASKS_DIR.is_dir():
        return []
    out = []
    for f in sorted(TASKS_DIR.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return out


def create(tid: str, description: str, goal: str | None = None,
           dependencies: list[str] | None = None,
           required_capabilities: list[str] | None = None,
           assigned_worker: str | None = None,
           priority: int = 3, deadline: str | None = None) -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", tid):
        raise ValueError(f"task id {tid!r} must be lowercase-kebab")
    if _path(tid).exists():
        raise FileExistsError(f"task {tid!r} already exists")
    for dep in dependencies or []:
        if not _path(dep).exists():
            raise KeyError(f"dependency {dep!r} does not exist")
    now = _now()
    task = {
        "id": tid, "description": description, "status": "QUEUED",
        "created_at": now, "updated_at": now, "attempts": 0,
        "priority": priority,
    }
    if goal:
        task["goal"] = goal
    if dependencies:
        task["dependencies"] = dependencies
    if required_capabilities:
        task["required_capabilities"] = required_capabilities
    if assigned_worker:
        task["assigned_worker"] = assigned_worker
    if deadline:
        task["deadline"] = deadline
    save(task)
    journal.append("task", f"task:{tid}", f"created — {description}")
    return task


def set_status(tid: str, status: str, note: str = "") -> dict:
    if status not in contracts.TASK_STATES:
        raise ValueError(f"status must be one of {sorted(contracts.TASK_STATES)}")
    task = load(tid)
    if task["status"] in contracts.TASK_TERMINAL:
        raise ValueError(f"task {tid!r} is {task['status']} — terminal states never change")
    before = task["status"]
    task["status"] = status
    task["updated_at"] = _now()
    if status == "RUNNING":
        task["attempts"] = task.get("attempts", 0) + 1
    if note:
        key = "error" if status.startswith("FAILED") else "result"
        task[key] = note
    save(task)
    journal.append("task", f"task:{tid}",
                   f"{before} -> {status}" + (f" — {note}" if note else ""))
    return task


def is_ready(task: dict, index: dict[str, dict] | None = None) -> bool:
    """Derived: waiting on nothing. Never persisted (Playbook: derive, don't assert)."""
    if task["status"] not in ("QUEUED", "WAITING_DEPENDENCY", "READY"):
        return False
    index = index if index is not None else {t["id"]: t for t in all_tasks()}
    return all(
        index.get(dep, {}).get("status") == "COMPLETED"
        for dep in task.get("dependencies", [])
    )


def ready() -> list[dict]:
    index = {t["id"]: t for t in all_tasks()}
    out = [t for t in index.values() if is_ready(t, index)]
    return sorted(out, key=lambda t: (t.get("priority", 3), t["created_at"]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Durable tasks.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_new = sub.add_parser("new")
    p_new.add_argument("id"); p_new.add_argument("description")
    p_new.add_argument("--goal"); p_new.add_argument("--worker")
    p_new.add_argument("--dep", action="append", default=[])
    p_new.add_argument("--cap", action="append", default=[])
    p_new.add_argument("--priority", type=int, default=3)
    p_new.add_argument("--deadline")
    p_st = sub.add_parser("status")
    p_st.add_argument("id"); p_st.add_argument("state")
    p_st.add_argument("--note", default="")
    sub.add_parser("list")
    sub.add_parser("ready")
    p_show = sub.add_parser("show"); p_show.add_argument("id")
    args = ap.parse_args(argv)

    if args.cmd == "new":
        create(args.id, args.description, goal=args.goal,
               dependencies=args.dep or None, required_capabilities=args.cap or None,
               assigned_worker=args.worker, priority=args.priority,
               deadline=args.deadline)
        print(f"task {args.id} queued")
    elif args.cmd == "status":
        t = set_status(args.id, args.state, args.note)
        print(f"{t['id']} -> {t['status']}")
    elif args.cmd == "show":
        print(json.dumps(load(args.id), indent=2, ensure_ascii=False))
    elif args.cmd == "ready":
        for t in ready():
            print(f"[p{t.get('priority', 3)}] {t['id']:28} {t['description']}")
    else:
        for t in all_tasks():
            worker = t.get("assigned_worker", "-")
            print(f"[{t['status']:19}] {t['id']:28} {worker:14} {t['description']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
