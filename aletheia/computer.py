"""Approval-gated Windows computer control (Playbook §§12-13, 121; Phase 7).

A typed action plan, fail-closed policy checks, an accessibility-first Windows
UI Automation backend, and an injectable backend for hermetic tests.  It accepts
no screen coordinates and performs no automatic fallback to visual clicking
(§13: semantic UI elements before pixels, always).

Authority is bound to the PLAN, not to the session: an approval authorizes one
run of one exact step list (sha256), is consumed once, and is re-checked before
setup and before every step, so a halt stops a run mid-plan.

Registered EXPERIMENTAL, and the word is load-bearing: the policy layer above is
verified hermetically, but the Windows backend has never executed on Windows.
`scripts/phase7_accept_notepad.ps1` is the acceptance run that decides whether
this becomes AVAILABLE or gets repaired.

CLI::

    python -m aletheia.computer status
    python -m aletheia.computer plan steps.json
    python -m aletheia.computer run steps.json --approval APPROVAL_ID
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Protocol

from aletheia import journal, policy
from aletheia.fleet import REPO_ROOT


ACTION_FIELDS = {
    "open_app": {"action", "app", "arguments"},
    "list_windows": {"action", "max_results"},
    "wait_window": {"action", "window", "timeout_s"},
    "focus_window": {"action", "window", "timeout_s"},
    "inspect_controls": {"action", "window", "max_results", "timeout_s"},
    "invoke": {"action", "window", "control", "timeout_s"},
    "set_text": {"action", "window", "control", "text", "timeout_s"},
    "screenshot_window": {"action", "window", "filename", "timeout_s"},
    "close_window": {"action", "window", "timeout_s"},
}
WINDOW_SELECTOR_FIELDS = {"title", "title_re", "class_name", "auto_id", "control_type"}
CONTROL_SELECTOR_FIELDS = WINDOW_SELECTOR_FIELDS | {"best_match"}
DEFAULT_TIMEOUT_S = 10.0
MAX_STEPS = 50
MAX_TEXT_CHARS = 20_000
MAX_APP_CHARS = 1_024
MAX_ARGUMENTS = 32
MAX_ARGUMENT_CHARS = 4_096
MAX_SELECTOR_CHARS = 256
MAX_OBSERVATIONS = 200
MAX_FILENAME_CHARS = 120
MAX_PLAN_WAIT_S = 300.0
WAIT_POLL_S = 0.5
CAPTURE_DIR = REPO_ROOT / "cache" / "computer-captures"
ACTOR = "aletheia-computer"
_CLAIM_LOCK = threading.Lock()


class ApprovalRequired(PermissionError):
    """A computer action was attempted without an approved operator decision."""


class VerificationFailed(RuntimeError):
    """The adapter acted but could not verify the requested local outcome."""


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
        elif key in allowed and len(item) > MAX_SELECTOR_CHARS:
            problems.append(
                f"{name}.{key}: exceeds {MAX_SELECTOR_CHARS} characters")
        elif key == "title_re":
            try:
                re.compile(item)
            except re.error as exc:
                problems.append(f"{name}.title_re: invalid regular expression ({exc})")
    return problems


def validate_steps(steps: object) -> list[str]:
    """Validate the complete plan before approval lookup or desktop access."""
    if not isinstance(steps, list) or not steps:
        return ["steps must be a non-empty list"]
    if len(steps) > MAX_STEPS:
        return [f"steps exceeds the maximum of {MAX_STEPS}"]
    problems: list[str] = []
    total_wait_s = 0.0
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
        elif "timeout_s" in ACTION_FIELDS[action]:
            total_wait_s += float(step.get("timeout_s", DEFAULT_TIMEOUT_S))
        if action == "open_app":
            app = step.get("app")
            if not isinstance(app, str) or not app.strip():
                problems.append(f"{label}.app: expected a non-empty executable or path")
            elif len(app) > MAX_APP_CHARS:
                problems.append(f"{label}.app: exceeds {MAX_APP_CHARS} characters")
            elif any(char in app for char in ("\x00", "\r", "\n")):
                problems.append(f"{label}.app: control characters are not accepted")
            args = step.get("arguments", [])
            if not isinstance(args, list) or any(not isinstance(v, str) for v in args):
                problems.append(f"{label}.arguments: expected a list of strings")
            elif len(args) > MAX_ARGUMENTS:
                problems.append(
                    f"{label}.arguments: exceeds the maximum of {MAX_ARGUMENTS}")
            else:
                for arg_index, arg in enumerate(args):
                    if len(arg) > MAX_ARGUMENT_CHARS:
                        problems.append(
                            f"{label}.arguments[{arg_index}]: exceeds "
                            f"{MAX_ARGUMENT_CHARS} characters")
                    if any(char in arg for char in ("\x00", "\r", "\n")):
                        problems.append(
                            f"{label}.arguments[{arg_index}]: control characters "
                            "are not accepted")
        elif action != "list_windows":
            problems += _selector(step.get("window"), f"{label}.window",
                                  WINDOW_SELECTOR_FIELDS)
        if action in ("list_windows", "inspect_controls"):
            maximum = step.get("max_results", 50)
            if (isinstance(maximum, bool) or not isinstance(maximum, int)
                    or not 1 <= maximum <= MAX_OBSERVATIONS):
                problems.append(
                    f"{label}.max_results: expected an integer from 1 to "
                    f"{MAX_OBSERVATIONS}")
        if action in ("invoke", "set_text"):
            problems += _selector(step.get("control"), f"{label}.control",
                                  CONTROL_SELECTOR_FIELDS)
        if action == "set_text":
            if not isinstance(step.get("text"), str):
                problems.append(f"{label}.text: expected a string")
            elif len(step["text"]) > MAX_TEXT_CHARS:
                problems.append(
                    f"{label}.text: exceeds {MAX_TEXT_CHARS} characters")
        if action == "screenshot_window":
            filename = step.get("filename")
            if not isinstance(filename, str) or not filename:
                problems.append(f"{label}.filename: expected a PNG filename")
            elif (len(filename) > MAX_FILENAME_CHARS
                  or Path(filename).name != filename
                  or "/" in filename or "\\" in filename
                  or Path(filename).suffix.lower() != ".png"
                  or any(char in filename for char in ("\x00", "\r", "\n"))):
                problems.append(
                    f"{label}.filename: expected a simple .png basename up to "
                    f"{MAX_FILENAME_CHARS} characters")
    if total_wait_s > MAX_PLAN_WAIT_S:
        problems.append(
            f"plan wait budget {total_wait_s:g}s exceeds {MAX_PLAN_WAIT_S:g}s")
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
        from pywinauto.timings import TimeoutError as UIATimeoutError

        self._Application = Application
        self._Desktop = Desktop
        self._TimeoutError = UIATimeoutError

    @staticmethod
    def _timeout(step: dict) -> float:
        return float(step.get("timeout_s", DEFAULT_TIMEOUT_S))

    def _window(self, step: dict):
        window = self._Desktop(backend="uia").window(**step["window"])
        self._wait_interruptibly(
            window.wait, "exists visible enabled ready", self._timeout(step))
        return window

    def _wait_interruptibly(self, wait_fn, condition: str, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while True:
            policy.ensure_not_halted()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise self._TimeoutError(
                    f"timed out waiting for UIA condition {condition!r}")
            try:
                wait_fn(condition, timeout=min(WAIT_POLL_S, remaining))
                return
            except self._TimeoutError:
                continue

    @staticmethod
    def _describe(wrapper) -> dict:
        def read(method: str, default=None):
            try:
                value = getattr(wrapper, method)()
                return value if isinstance(value, (str, int, bool)) else default
            except Exception:
                return default

        control_type = read("control_type")
        if not control_type:
            try:
                control_type = wrapper.element_info.control_type
            except Exception:
                control_type = None
        return {
            "name": (read("window_text", "") or "")[:MAX_SELECTOR_CHARS],
            "class_name": (read("class_name", "") or "")[:MAX_SELECTOR_CHARS],
            "control_type": control_type,
            "process_id": read("process_id"),
        }

    def perform(self, step: dict) -> dict:
        action = step["action"]
        if action == "open_app":
            command = subprocess.list2cmdline([step["app"], *step.get("arguments", [])])
            app = self._Application(backend="uia").start(command)
            return {"action": action, "process_id": app.process}
        if action == "list_windows":
            maximum = step.get("max_results", 50)
            windows = self._Desktop(backend="uia").windows()[:maximum]
            rows = [self._describe(window) for window in windows]
            return {"action": action, "verified": True,
                    "count": len(rows), "windows": rows}

        window = self._window(step)
        if action == "wait_window":
            return {"action": action, "verified": "window exists, visible, enabled, and ready"}
        if action == "focus_window":
            window.set_focus()
            return {"action": action, "verified": "focus requested through UI Automation"}
        if action == "inspect_controls":
            maximum = step.get("max_results", 50)
            rows = [self._describe(control)
                    for control in window.descendants()[:maximum]]
            return {"action": action, "verified": True,
                    "count": len(rows), "controls": rows}
        if action == "screenshot_window":
            CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
            out = CAPTURE_DIR / step["filename"]
            if out.exists() or out.is_symlink():
                raise FileExistsError(
                    "screenshot target already exists; evidence is never overwritten")
            window.capture_as_image().save(str(out), format="PNG")
            if not out.is_file() or out.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
                raise VerificationFailed("window screenshot did not produce a valid PNG")
            return {"action": action, "verified": True, "path": str(out)}
        if action == "close_window":
            window.close()
            self._wait_interruptibly(
                window.wait_not, "exists", self._timeout(step))
            return {"action": action, "verified": "window no longer exists"}

        control = window.child_window(**step["control"])
        self._wait_interruptibly(
            control.wait, "exists visible enabled ready", self._timeout(step))
        wrapper = control.wrapper_object()
        if action == "invoke":
            wrapper.invoke()
            return {"action": action, "verified": "UI Automation Invoke pattern completed"}
        if action == "set_text":
            wrapper.set_edit_text(step["text"])
            observed = wrapper.window_text()
            if observed != step["text"]:
                raise VerificationFailed(
                    "set_text completed but exact text verification failed")
            return {"action": action, "verified": True}
        raise AssertionError(f"validated action was not implemented: {action}")


def _journal_evidence(evidence: dict) -> dict:
    """Keep verification useful without persisting typed/observed content."""
    safe = {}
    for key in ("action", "verified", "process_id", "count", "path"):
        value = evidence.get(key)
        if isinstance(value, (bool, int, float)) or value is None:
            safe[key] = value
        elif isinstance(value, str):
            safe[key] = value[:256]
    omitted = sorted(set(evidence) - set(safe))
    if omitted:
        safe["redacted_fields"] = omitted
    return safe


def execute(steps: object, approval_id: str, backend: ComputerBackend | None = None,
            requested_by: str = "operator", backend_factory=None) -> dict:
    """Execute one approved plan, checking halt before setup and every step."""
    if backend is not None and backend_factory is not None:
        raise ValueError("provide backend or backend_factory, not both")
    if not isinstance(requested_by, str) or not requested_by.strip():
        raise ValueError("requested_by must be a non-empty string")
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
            if not isinstance(evidence, dict):
                raise VerificationFailed(
                    f"backend returned non-object evidence for {step['action']}")
        except Exception as exc:
            journal.append(
                "action", f"computer:{step['action']}",
                f"FAILED run={run_id} step={index} approval={approval_id} "
                f"error={type(exc).__name__}", actor=ACTOR)
            raise
        results.append(evidence)
        journal_evidence = _journal_evidence(evidence)
        journal.append(
            "action", f"computer:{step['action']}",
            f"DONE run={run_id} step={index} approval={approval_id} "
            f"verification={json.dumps(journal_evidence, ensure_ascii=False, sort_keys=True)}",
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
