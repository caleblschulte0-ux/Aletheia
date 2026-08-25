"""Approval-gated Windows computer control (Phase 7, isolated Codex draft).

This module is intentionally not wired into the Core or capability registry yet.
It is the first reviewable slice: a typed action plan, fail-closed policy checks,
an accessibility-first Windows UI Automation backend, and an injectable backend
for hermetic tests.  It accepts no screen coordinates and performs no automatic
fallback to visual clicking.

Proposed CLI after review::

    python -m aletheia.computer status
    python -m aletheia.computer plan steps.json
    python -m aletheia.computer run steps.json --approval APPROVAL_ID
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Protocol

from aletheia import journal, policy


ACTION_FIELDS = {
    "open_app": {"action", "app", "arguments", "timeout_s"},
    "wait_window": {"action", "window", "timeout_s"},
    "focus_window": {"action", "window", "timeout_s"},
    "invoke": {"action", "window", "control", "timeout_s"},
    "set_text": {"action", "window", "control", "text", "timeout_s"},
    "close_window": {"action", "window", "timeout_s"},
}
WINDOW_SELECTOR_FIELDS = {"title", "title_re", "class_name", "auto_id", "control_type"}
CONTROL_SELECTOR_FIELDS = WINDOW_SELECTOR_FIELDS | {"best_match"}
DEFAULT_TIMEOUT_S = 10.0
ACTOR = "aletheia-computer"
_CLAIM_LOCK = threading.Lock()


class ApprovalRequired(PermissionError):
    """A computer action was attempted without an approved operator decision."""


class ComputerBackend(Protocol):
    """Small seam that keeps policy tests independent of a real Windows desktop."""

    def perform(self, step: dict) -> dict:
        """Perform one already-validated step and return verification evidence."""


def available() -> tuple[bool, str]:
    """Return the honest local availability of the proposed Windows adapter."""
    if os.name != "nt":
        return False, "Windows UI Automation is available only on Windows"
    try:
        import pywinauto  # noqa: F401
    except ImportError:
        return False, "pywinauto is not installed (pip install pywinauto)"
    return True, "ready for local acceptance testing"


def _selector(value: object, name: str, allowed: set[str]) -> list[str]:
    if not isinstance(value, dict) or not value:
        return [f"{name}: expected a non-empty selector object"]
    problems = []
    unknown = set(value) - allowed
    if unknown:
        problems.append(f"{name}: unsupported fields {sorted(unknown)}")
    if any(key in value for key in ("x", "y", "coordinates", "position")):
        problems.append(f"{name}: screen coordinates are not accepted")
    for key, item in value.items():
        if key in allowed and (not isinstance(item, str) or not item.strip()):
            problems.append(f"{name}.{key}: expected a non-empty string")
    return problems


def validate_steps(steps: object) -> list[str]:
    """Validate the complete plan before approval lookup or desktop access."""
    if not isinstance(steps, list) or not steps:
        return ["steps must be a non-empty list"]
    problems: list[str] = []
    for index, step in enumerate(steps):
        label = f"steps[{index}]"
        if not isinstance(step, dict):
            problems.append(f"{label}: expected an object")
            continue
        action = step.get("action")
        if action not in ACTION_FIELDS:
            problems.append(f"{label}.action: {action!r} not in {sorted(ACTION_FIELDS)}")
            continue
        unknown = set(step) - ACTION_FIELDS[action]
        if unknown:
            problems.append(f"{label}: unsupported fields {sorted(unknown)}")
        if "timeout_s" in step and (
                isinstance(step["timeout_s"], bool)
                or not isinstance(step["timeout_s"], (int, float))
                or not 0 < float(step["timeout_s"]) <= 60):
            problems.append(f"{label}.timeout_s: expected a number from 0 to 60")
        if action == "open_app":
            if not isinstance(step.get("app"), str) or not step["app"].strip():
                problems.append(f"{label}.app: expected a non-empty executable or path")
            args = step.get("arguments", [])
            if not isinstance(args, list) or any(not isinstance(v, str) for v in args):
                problems.append(f"{label}.arguments: expected a list of strings")
        else:
            problems += _selector(step.get("window"), f"{label}.window",
                                  WINDOW_SELECTOR_FIELDS)
        if action in ("invoke", "set_text"):
            problems += _selector(step.get("control"), f"{label}.control",
                                  CONTROL_SELECTOR_FIELDS)
        if action == "set_text" and not isinstance(step.get("text"), str):
            problems.append(f"{label}.text: expected a string")
    return problems


def plan_digest(steps: list[dict]) -> str:
    canonical = json.dumps(
        steps, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def approval_action(steps: list[dict]) -> str:
    """Exact requested_action stored in the approval object for this plan."""
    return f"computer.control:{plan_digest(steps)}"


def _require_approval(approval_id: str, steps: list[dict]) -> None:
    if not approval_id:
        raise ApprovalRequired(
            f"approval {approval_id!r} is not APPROVED; computer control never self-authorizes")
    try:
        approval = policy.load(approval_id)
    except (OSError, json.JSONDecodeError, KeyError):
        approval = {}
    if approval.get("state") != "APPROVED":
        raise ApprovalRequired(
            f"approval {approval_id!r} is not APPROVED; computer control never self-authorizes")
    expected = approval_action(steps)
    if approval.get("requested_action") != expected:
        raise ApprovalRequired(
            f"approval {approval_id!r} is not bound to this exact computer plan")


def _claim_approval(approval_id: str, steps: list[dict], run_id: str,
                    requested_by: str) -> None:
    """Atomically consume an approval once within the local Core process.

    An operator_always approval authorizes one run, not an unlimited reusable
    desktop-control token. A STARTED record consumes it even if the adapter
    later fails; retrying therefore requires a fresh operator decision.
    """
    ref = f"approval:{approval_id}"
    with _CLAIM_LOCK:
        _require_approval(approval_id, steps)
        if any(entry.get("subject") == "computer:run"
               and ref in entry.get("refs", [])
               and str(entry.get("text", "")).startswith("STARTED")
               for entry in journal.entries()):
            raise ApprovalRequired(
                f"approval {approval_id!r} was already consumed by a computer run")
        journal.append(
            "action", "computer:run",
            f"STARTED run={run_id} approval={approval_id} requested_by={requested_by}",
            actor=ACTOR, refs=[ref, f"run:{run_id}"])


class WindowsUIABackend:
    """Windows UI Automation implementation; imported only on the Windows host."""

    def __init__(self) -> None:
        ok, reason = available()
        if not ok:
            raise RuntimeError(f"computer control unavailable: {reason}")
        from pywinauto import Application, Desktop

        self._Application = Application
        self._Desktop = Desktop

    @staticmethod
    def _timeout(step: dict) -> float:
        return float(step.get("timeout_s", DEFAULT_TIMEOUT_S))

    def _window(self, step: dict):
        window = self._Desktop(backend="uia").window(**step["window"])
        window.wait("exists visible enabled ready", timeout=self._timeout(step))
        return window

    def perform(self, step: dict) -> dict:
        action = step["action"]
        if action == "open_app":
            command = subprocess.list2cmdline([step["app"], *step.get("arguments", [])])
            app = self._Application(backend="uia").start(command)
            return {"action": action, "process_id": app.process}

        window = self._window(step)
        if action == "wait_window":
            return {"action": action, "verified": "window exists, visible, enabled, and ready"}
        if action == "focus_window":
            window.set_focus()
            return {"action": action, "verified": "focus requested through UI Automation"}
        if action == "close_window":
            window.close()
            return {"action": action, "verified": "close requested through UI Automation"}

        control = window.child_window(**step["control"])
        control.wait("exists visible enabled ready", timeout=self._timeout(step))
        wrapper = control.wrapper_object()
        if action == "invoke":
            wrapper.invoke()
            return {"action": action, "verified": "UI Automation Invoke pattern completed"}
        if action == "set_text":
            wrapper.set_edit_text(step["text"])
            observed = wrapper.window_text()
            return {"action": action, "verified": observed == step["text"]}
        raise AssertionError(f"validated action was not implemented: {action}")


def execute(steps: object, approval_id: str, backend: ComputerBackend | None = None,
            requested_by: str = "operator", backend_factory=None) -> dict:
    """Execute one approved plan, checking halt before setup and every step."""
    if backend is not None and backend_factory is not None:
        raise ValueError("provide backend or backend_factory, not both")
    problems = validate_steps(steps)
    if problems:
        raise ValueError("; ".join(problems))
    policy.ensure_not_halted()
    run_id = f"computer-{uuid.uuid4().hex[:12]}"
    _claim_approval(approval_id, steps, run_id, requested_by)
    driver = backend or (backend_factory() if backend_factory else WindowsUIABackend())
    results = []
    for index, step in enumerate(steps):
        policy.ensure_not_halted()
        try:
            evidence = driver.perform(step)
        except Exception as exc:
            journal.append(
                "action", f"computer:{step['action']}",
                f"FAILED run={run_id} step={index} approval={approval_id} "
                f"error={type(exc).__name__}: {exc}", actor=ACTOR)
            raise
        results.append(evidence)
        journal.append(
            "action", f"computer:{step['action']}",
            f"DONE run={run_id} step={index} approval={approval_id} "
            f"verification={json.dumps(evidence, ensure_ascii=False, sort_keys=True)}",
            actor=ACTOR)
    journal.append(
        "action", "computer:run",
        f"COMPLETED run={run_id} approval={approval_id} steps={len(results)}",
        actor=ACTOR, refs=[f"approval:{approval_id}", f"run:{run_id}"])
    return {"run_id": run_id, "requested_by": requested_by,
            "approval_id": approval_id, "steps_done": len(results), "results": results}


def _load_steps(path: str) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aletheia Windows control — review draft")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    plan = sub.add_parser("plan"); plan.add_argument("file")
    run = sub.add_parser("run"); run.add_argument("file")
    run.add_argument("--approval", required=True)
    args = parser.parse_args(argv)

    if args.command == "status":
        ok, reason = available()
        print(f"computer: {'experimental' if ok else 'unavailable'} — {reason}")
        print("not wired into Core; no coordinate or visual-click fallback")
        return 0 if ok else 1
    steps = _load_steps(args.file)
    problems = validate_steps(steps)
    if problems:
        print("invalid plan: " + "; ".join(problems), file=sys.stderr)
        return 2
    if args.command == "plan":
        print(json.dumps(steps, indent=2, ensure_ascii=False))
        return 0
    print(json.dumps(execute(steps, args.approval), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
