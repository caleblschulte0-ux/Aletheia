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
from pathlib import Path, PurePosixPath
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
    # 2026-09-02: real apps need more than type-and-press. A hotkey from a
    # SAFE list (navigation, clipboard, undo, find, save — never Enter,
    # Delete, Alt+F4 or anything that closes/submits/sends), and select for
    # a combo box or list item.
    "hotkey": {"action", "window", "keys", "timeout_s"},
    "select": {"action", "window", "control", "value", "timeout_s"},
}
# Hotkeys unattended hands may send, and how pywinauto spells them. Enter,
# Delete, Alt+F4, Ctrl+Enter, Ctrl+W/Q are absent on purpose: each one
# submits, sends, destroys or closes something, which is the committing
# guard's business, and a hotkey has no label to read.
SAFE_HOTKEYS = {
    "ctrl+a": "^a", "ctrl+c": "^c", "ctrl+v": "^v", "ctrl+x": "^x",
    "ctrl+z": "^z", "ctrl+y": "^y", "ctrl+f": "^f", "ctrl+h": "^h",
    "ctrl+s": "^s", "ctrl+shift+s": "^+s", "ctrl+o": "^o", "ctrl+n": "^n",
    "escape": "{ESC}", "tab": "{TAB}", "shift+tab": "+{TAB}",
    "home": "{HOME}", "end": "{END}", "ctrl+home": "^{HOME}", "ctrl+end": "^{END}",
    "pageup": "{PGUP}", "pagedown": "{PGDN}",
    "up": "{UP}", "down": "{DOWN}", "left": "{LEFT}", "right": "{RIGHT}",
    "f3": "{F3}",
}
MAX_VALUE_CHARS = 256
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
        if action == "hotkey":
            keys = step.get("keys")
            if not isinstance(keys, str) or keys.strip().casefold() not in SAFE_HOTKEYS:
                problems.append(
                    f"{label}.keys: {keys!r} is not a safe hotkey; allowed: "
                    f"{', '.join(sorted(SAFE_HOTKEYS))}")
        if action == "select":
            problems += _selector(step.get("control"), f"{label}.control",
                                  CONTROL_SELECTOR_FIELDS)
            value = step.get("value")
            if not isinstance(value, str) or not value.strip():
                problems.append(f"{label}.value: expected a non-empty string")
            elif len(value) > MAX_VALUE_CHARS:
                problems.append(f"{label}.value: exceeds {MAX_VALUE_CHARS} characters")
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


def _quiet(call):
    """A wrapper property read that may fail on a window mid-close."""
    try:
        return call()
    except Exception:
        return None


def _line_endings(text: object) -> str:
    """Text with its line breaks as newlines and no trailing break. The
    verification is still exact in every character a person wrote: a
    control reports the SAME lines with its own break convention (Windows
    11 Notepad answers "\\r" for the "\\n" it was given — the first live
    haiku, 2026-09-02, was on screen in full and failed verification)."""
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


def _normalized(text: object) -> str:
    """Case and whitespace folded: what a person reads, not what UIA stores."""
    return " ".join(str(text or "").casefold().split())


_INLINE_FLAGS = re.compile(r"\(\?([aiLmsux]+)\)")


def _window_selector(selector: dict) -> dict:
    """The selector as handed to UI Automation. A title pattern is matched
    ANYWHERE in the title and without regard to case: pywinauto anchors
    `title_re` at the start, so the planner's "Notepad" could never find
    "Untitled - Notepad" (live, 2026-09-02), and titles differ in case
    between Windows versions ("Save As" / "Save as") and never in meaning.
    A person writing "Notepad" means a window with Notepad in its title.
    This touches window LOOKUP only — the committing-control guard reads
    the live label of the control, which this does not change."""
    out = dict(selector)
    pattern = out.get("title_re")
    if isinstance(pattern, str):
        head = _INLINE_FLAGS.match(pattern)
        flags, rest = (head.group(1), pattern[head.end():]) if head else ("", pattern)
        if "i" not in flags:
            flags += "i"
        if not rest.startswith(".*"):
            rest = ".*" + rest
        out["title_re"] = f"(?{flags}){rest}"
    return out


# The two UI Automation types a text area may carry. A planner that cannot
# see the screen writes "Edit" (the note's example); Windows 11 Notepad's
# area is a "Document". When a control selector names ONLY a type and it is
# one of these, the other is tried too — they are the same thing to the
# person asking, and the selector names no other property that could be
# meant more precisely.
TEXT_ENTRY_TYPES = ("Edit", "Document")


def _control_candidates(selector: dict) -> list[dict]:
    if set(selector) == {"control_type"} and selector["control_type"] in TEXT_ENTRY_TYPES:
        other = next(t for t in TEXT_ENTRY_TYPES if t != selector["control_type"])
        return [dict(selector), {"control_type": other}]
    return [dict(selector)]


def _selector_matches(element, selector: dict) -> bool:
    """Does a UIA element satisfy a window selector? Mirrors what
    pywinauto's own finder checks for the fields a plan may use."""
    text = element.window_text() or ""
    if "title" in selector and text != selector["title"]:
        return False
    if "title_re" in selector and not re.match(selector["title_re"], text):
        return False
    if "class_name" in selector and element.class_name() != selector["class_name"]:
        return False
    if "auto_id" in selector:
        try:
            if element.element_info.automation_id != selector["auto_id"]:
                return False
        except Exception:
            return False
    if "control_type" in selector:
        try:
            if element.element_info.control_type != selector["control_type"]:
                return False
        except Exception:
            return False
    return True


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
        try:
            from pywinauto.findwindows import ElementAmbiguousError
        except Exception:      # a test double without the finder module
            class ElementAmbiguousError(Exception):
                pass
        self._AmbiguousError = ElementAmbiguousError
        # processes this backend started: a tie-breaker when a title names
        # more than one window
        self._opened: set[int] = set()

    @staticmethod
    def _timeout(step: dict) -> float:
        return float(step.get("timeout_s", DEFAULT_TIMEOUT_S))

    def _window(self, step: dict):
        """The window a step names, ready to use.

        Two things the first live Save-as run (2026-09-02) taught, each a
        TimeoutError on a dialog that was plainly on screen:

        - Windows 11 titles its file dialog "Save as"; the plan said
          "Save As". A person does not see the difference, so the title
          pattern is matched case-insensitively (`_window_selector`).
        - Under UI Automation an app's dialog is NOT a top-level window:
          it hangs under its owner (Desktop -> Notepad -> "Save as"), and
          `Desktop.window()` searches only the top level. So when the
          top-level lookup comes up empty the direct children of every
          top-level window are tried too (`_owned_dialog`), and the
          match is anchored by handle so the rest of the step treats it
          like any other window.

        The wait is polled in short slices with HALT re-read between
        them, the same as every other wait here.
        """
        selector = _window_selector(step["window"])
        desktop = self._Desktop(backend="uia")
        condition = "exists visible enabled ready"
        deadline = time.monotonic() + self._timeout(step)
        while True:
            policy.ensure_not_halted()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise self._TimeoutError(
                    f"timed out waiting for UIA condition {condition!r}")
            slice_s = min(WAIT_POLL_S, remaining)
            window = desktop.window(**selector)
            try:
                window.wait(condition, timeout=slice_s)
                return self._anchored(desktop, window)
            except self._TimeoutError:
                pass
            except self._AmbiguousError:
                chosen = self._disambiguate(desktop, selector)
                if chosen is None:
                    raise
                window = desktop.window(handle=chosen)
                try:
                    window.wait(condition, timeout=slice_s)
                    return window
                except self._TimeoutError:
                    continue
            owned = self._owned_dialog(desktop, selector)
            if owned is None:
                continue
            window = desktop.window(handle=owned)
            try:
                window.wait(condition, timeout=slice_s)
                return window
            except self._TimeoutError:
                continue

    def _disambiguate(self, desktop, selector: dict):
        """Two windows carry the title the plan named; which did he mean?

        Live, 2026-09-02: "Open Notepad and write a haiku" a second time,
        with the first haiku's Notepad still open — Windows 11 Notepad
        opened a SECOND window from the same process and "Notepad" matched
        both. A person means the one that just opened, which is the
        active one; failing that, a window of a process this run started;
        failing both, the ambiguity is refused rather than guessed, and
        the plan must say more.
        """
        try:
            matches = list(desktop.windows(**selector))
        except Exception:
            return None
        active = [m for m in matches if _quiet(m.is_active)]
        if len(active) == 1:
            return active[0].handle
        mine = [m for m in matches if _quiet(m.process_id) in self._opened]
        if len(mine) == 1:
            return mine[0].handle
        return None

    @staticmethod
    def _anchored(desktop, window):
        """The found window, re-addressed by its handle. A specification
        resolves its criteria again on EVERY attribute access, so a title
        that changes between the wait and the action (Notepad prefixes
        "*" the moment text changes; a loading app retitles itself) or a
        momentarily incomplete enumeration turns a found window into
        ElementNotFoundError one line later — which is how the 01:18 run
        on 2026-09-02 failed at set_focus after wait_window had passed."""
        try:
            handle = window.handle
        except Exception:
            return window
        return desktop.window(handle=handle) if handle else window

    def _control(self, window, step: dict):
        """The control a step names, ready. Candidates (see
        `_control_candidates`) are tried in turn in short slices until one
        is ready or the step's timeout is spent; HALT is re-read between
        slices."""
        candidates = _control_candidates(step["control"])
        condition = "exists visible enabled ready"
        deadline = time.monotonic() + self._timeout(step)
        while True:
            policy.ensure_not_halted()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise self._TimeoutError(
                    f"timed out waiting for UIA condition {condition!r}")
            for selector in candidates:
                control = window.child_window(**selector)
                try:
                    control.wait(condition, timeout=min(WAIT_POLL_S, remaining))
                    return control
                except self._TimeoutError:
                    continue

    @staticmethod
    def _owned_dialog(desktop, selector: dict):
        """Handle of a dialog owned by a top-level window that matches the
        selector, or None. Direct children only: a walk of every
        descendant of every app (Chrome alone has thousands) would take
        longer than the wait it is meant to shorten."""
        try:
            tops = desktop.windows()
        except Exception:
            return None
        for top in tops:
            try:
                children = top.children(control_type="Window")
            except Exception:
                continue
            for child in children:
                try:
                    if _selector_matches(child, selector):
                        return child.handle
                except Exception:
                    continue
        return None

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
            self._opened.add(app.process)
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
            image = window.capture_as_image()
            if image is None:
                raise RuntimeError(
                    "window screenshots need Pillow (pip install pillow); "
                    "pywinauto's capture_as_image returned nothing without it")
            image.save(str(out), format="PNG")
            if not out.is_file() or out.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
                raise VerificationFailed("window screenshot did not produce a valid PNG")
            return {"action": action, "verified": True, "path": str(out)}
        if action == "close_window":
            window.close()
            self._wait_interruptibly(
                window.wait_not, "exists", self._timeout(step))
            return {"action": action, "verified": "window no longer exists"}
        if action == "hotkey":
            spelled = SAFE_HOTKEYS[step["keys"].strip().casefold()]
            window.set_focus()
            window.type_keys(spelled, set_foreground=True)
            return {"action": action, "verified": f"sent {step['keys']} to the focused window"}

        control = self._control(window, step)
        wrapper = control.wrapper_object()
        if action == "invoke":
            wrapper.invoke()
            return {"action": action, "verified": "UI Automation Invoke pattern completed"}
        if action == "set_text":
            self._set_text(wrapper, step["text"])
            observed = self._read_text(wrapper)
            if _line_endings(observed) != _line_endings(step["text"]):
                raise VerificationFailed(
                    "set_text completed but exact text verification failed")
            return {"action": action, "verified": True}
        if action == "select":
            wanted = step["value"]
            choice = self._choice_on(wrapper, wanted)
            try:
                wrapper.select(choice)
            except Exception as exc:
                raise VerificationFailed(
                    f"control could not select {choice!r} ({type(exc).__name__})") from exc
            observed = self._selected_text(wrapper)
            if _normalized(wanted) not in _normalized(observed):
                raise VerificationFailed(
                    f"select completed but the control now reads {observed[:80]!r}")
            return {"action": action, "verified": True, "selected": choice}
        raise AssertionError(f"validated action was not implemented: {action}")

    @staticmethod
    def _items(wrapper) -> list[str]:
        """The choices a list or combo box offers, read from the control.
        Empty when it cannot be read — the caller then lets the control
        answer for itself."""
        try:
            wrapper.expand()
        except Exception:
            pass
        try:
            names = [c.window_text() for c in wrapper.descendants(control_type="ListItem")]
        except Exception:
            names = []
        finally:
            try:
                wrapper.collapse()
            except Exception:
                pass
        return [n for n in names if isinstance(n, str) and n.strip()]

    @classmethod
    def _choice_on(cls, wrapper, wanted: str) -> str:
        """The item text to hand the control for what the plan asked.

        The first live `select` (2026-09-02) asked for "All files" and the
        Save-as type box holds "All files " — a trailing space no person
        sees. So: the item whose text matches ignoring case and spacing;
        failing that, the ONE item the wanted text is a prefix of ("All
        files" -> "All files (*.*)"). Two matches is a question for the
        operator, not a guess; a prefix that reaches a committing word the
        plan never said ("Sen" -> "Send now") is refused outright, so the
        guard act() ran on the plan's value still covers what is actually
        selected.
        """
        items = cls._items(wrapper)
        if not items:
            return wanted
        key = _normalized(wanted)
        exact = [i for i in items if _normalized(i) == key]
        if len(exact) == 1:
            return exact[0]
        if exact:
            raise VerificationFailed(
                f"{wanted!r} names {len(exact)} identical items on this control")
        prefixed = [i for i in items if _normalized(i).startswith(key)]
        if len(prefixed) > 1:
            raise VerificationFailed(
                f"{wanted!r} is ambiguous on this control: {prefixed[:5]!r}")
        if not prefixed:
            return wanted
        item = prefixed[0]
        hit = committing_label(item)
        if hit and not committing_label(wanted):
            raise VerificationFailed(
                f"{wanted!r} would select {item!r}, which says {hit!r} where the "
                "plan did not; refused")
        return item

    @staticmethod
    def _selected_text(wrapper) -> str:
        for reader in (
            lambda: wrapper.selected_text(),
            lambda: wrapper.get_selection()[0].name,
            lambda: wrapper.window_text(),
        ):
            try:
                value = reader()
            except Exception:
                continue
            if isinstance(value, str) and value:
                return value
        return ""

    def describe_control(self, step: dict) -> dict:
        """What the control a step names actually IS on screen right now.

        act() asks this before an `invoke`: the selector may say
        auto_id "btn7" while the button on screen says "Send", and the
        committing-control guard has to read the label a person would.
        """
        window = self._window(step)
        control = self._control(window, step)
        return self._describe(control.wrapper_object())

    @staticmethod
    def _set_text(wrapper, text: str) -> None:
        """Set a control's full text on both old and new Windows edits.

        Classic Edit controls expose set_edit_text; Windows 11 apps
        (Notepad's RichEditD2DPT Document among them) do not — the first
        live acceptance run died right here with AttributeError. Try the
        edit API, then the UIA Value pattern; both replace the WHOLE
        text, so a wrong target cannot silently append.
        """
        if hasattr(wrapper, "set_edit_text"):
            wrapper.set_edit_text(text)
            return
        try:
            wrapper.iface_value.SetValue(text)
            return
        except Exception as exc:
            raise VerificationFailed(
                "control supports neither the edit API nor the UIA Value "
                f"pattern; refusing keyboard fallback ({type(exc).__name__})") from exc

    @staticmethod
    def _read_text(wrapper) -> str:
        """Read a control's full text back for exact verification."""
        for reader in (
            lambda: wrapper.get_value(),
            lambda: wrapper.iface_value.CurrentValue,
            lambda: wrapper.window_text(),
            lambda: wrapper.iface_text.DocumentRange.GetText(-1),
        ):
            try:
                value = reader()
            except Exception:
                continue
            if isinstance(value, str) and value:
                # Windows 11 Notepad reports a trailing document newline
                return value.rstrip(chr(13) + chr(10))
        return ""


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


# Actions that only LOOK. Splitting the action set by EFFECT is what lets
# an agenda have eyes on the desktop without hands on it: listing windows
# and reading controls changes nothing and can be undone by closing your
# own eyes, while clicking, typing and closing windows can destroy an
# afternoon of somebody's work. The second set keeps its hash-bound
# operator approval; only this set is reachable without one.
OBSERVE_ACTIONS = frozenset({"list_windows", "inspect_controls"})


def observe(steps: object, backend: ComputerBackend | None = None,
            backend_factory=None) -> dict:
    """Look at the desktop. No approval, because nothing changes.

    Refuses any mutating action outright rather than filtering it out
    silently: a caller that asked to click something and was quietly given
    a screenshot instead would report success for work that never happened.
    """
    problems = validate_steps(steps)
    if problems:
        raise ValueError("; ".join(problems))
    for index, step in enumerate(steps):
        action = step.get("action")
        if action not in OBSERVE_ACTIONS:
            raise ApprovalRequired(
                f"step {index + 1} ({action}) changes the desktop, so it needs "
                "an approval bound to the exact plan. Observation covers "
                f"{', '.join(sorted(OBSERVE_ACTIONS))} and nothing else.")
    policy.ensure_not_halted()
    driver = backend or (backend_factory() if backend_factory else WindowsUIABackend())
    results = []
    for step in steps:
        policy.ensure_not_halted()
        results.append({"action": step["action"], "evidence": driver.perform(step)})
    journal.append("action", "computer:observe",
                   f"observed the desktop ({len(results)} step(s))", actor=ACTOR)
    return {"outcome": "observed", "steps": results}


# ---- hands (2026-09-02, operator-authorized in his own words) --------------
#
# observe() gave an agenda eyes. This gives it hands, for the dull half of
# desktop work — open the app, put the text in, press Save — under a
# mission budget and with no per-plan approval. What keeps that safe to
# say yes to is not a promise about judgement; it is a line drawn in code:
#
#   - The actions are a POSITIVE list. Closing windows and screenshots are
#     not on it and keep execute()'s hash-bound approval.
#   - A control whose label commits or destroys — Send, Delete, Pay,
#     Purchase, Confirm, Submit, Format, Uninstall, Empty Trash and their
#     obvious siblings — is REFUSED, and the refusal names the approval path.
#     It is never skipped: a plan that ran with the Send removed "succeeds"
#     having not done the thing, and that is the shape of failure that
#     looks like success.
#   - The guard reads the label twice: once from the plan's own selector,
#     before anything runs, and once from the LIVE control on screen just
#     before the click, because a selector can name a button by an id.
#   - A control with no readable label at all is refused too: a guard that
#     cannot read what it is about to press is not a guard.
#   - open_app never launches a shell, an interpreter or a system tool —
#     that would hand back everything aletheia.script's sandbox takes away.
#   - HALT is re-read between every step.

ACT_ACTIONS = frozenset({"open_app", "wait_window", "focus_window", "set_text", "invoke",
                         "hotkey", "select"})

COMMITTING_PATTERN = re.compile(
    r"\b(?:send|delete|pay|purchase|buy|confirm|submit|format|uninstall|"
    r"empty\s+(?:the\s+)?(?:trash|recycle\s+bin)|check\s*out|place\s+order|"
    r"sign|post|publish|remove|erase|wipe|reset|share|transfer|order)\b",
    re.IGNORECASE)

# Programs unattended hands never start. Each is a way to run arbitrary
# commands or change the machine, which is exactly what the sandbox in
# aletheia.script exists to make impossible for generated code.
FORBIDDEN_APPS = frozenset({
    "cmd", "powershell", "pwsh", "wt", "bash", "sh", "wsl", "python", "pythonw",
    "py", "wscript", "cscript", "mshta", "regedit", "reg", "diskpart", "format",
    "rundll32", "msiexec", "wmic", "schtasks", "sc", "net", "net1", "netsh",
    "bcdedit", "cipher", "takeown", "icacls", "vssadmin", "wevtutil", "certutil",
    "bitsadmin", "curl", "wget", "ssh", "telnet", "control", "shutdown",
})


class CommittingControl(ApprovalRequired):
    """A control whose label commits or destroys; act() bounces it to execute()."""


def committing_label(text: str) -> str | None:
    """The committing word in a label, or None."""
    match = COMMITTING_PATTERN.search(str(text or ""))
    return match.group(0) if match else None


def _control_label(control: dict) -> str:
    """Every human-readable thing a control selector says about its target."""
    parts = []
    for key in ("title", "best_match", "auto_id", "title_re"):
        value = control.get(key)
        if isinstance(value, str) and value.strip():
            if key == "title_re":
                # read the words out of the pattern; metacharacters are not a label
                value = re.sub(r"[\\^$.*+?()\[\]{}|]", " ", value)
            parts.append(value)
    return " ".join(parts).strip()


def _app_name(app: str) -> str:
    """The bare program name, however the path was spelled.

    Backslashes are normalized FIRST because `Path` only treats them as
    separators on Windows: on a POSIX runner
    `Path(r"C:\\Windows\\System32\\cmd.exe").name` is the entire string, so
    the FORBIDDEN_APPS check silently missed every full Windows path and
    this guard meant something different in CI than on the operator's PC.
    A security check has to mean the same thing wherever it is evaluated.
    (Found by test_a_shell_is_never_opened, which was red on the branch.)
    """
    raw = app.strip().strip('"').replace("\\", "/")
    name = PurePosixPath(raw).name.casefold()
    return name[:-4] if name.endswith((".exe", ".com", ".bat", ".cmd")) else name


def check_act_plan(steps: list[dict]) -> None:
    """Refuse, BEFORE anything runs, any step unattended hands may not take.

    Raises ApprovalRequired naming the step and the approval path. Called
    by act() and by the intercom's grammar gate, so a planner sees the
    refusal as a refusal rather than discovering it with a window open.
    """
    approval_path = ("it needs an approval bound to this exact plan: "
                     "python -m aletheia.computer request <plan.json> "
                     "--approval-id <id>, then run <plan.json> --approval <id>")
    for index, step in enumerate(steps):
        action = step.get("action")
        if action not in ACT_ACTIONS:
            raise ApprovalRequired(
                f"step {index + 1} ({action}) is not something unattended hands do; "
                f"they cover {', '.join(sorted(ACT_ACTIONS))} and nothing else — "
                + approval_path)
        if action == "open_app" and _app_name(str(step.get("app", ""))) in FORBIDDEN_APPS:
            raise ApprovalRequired(
                f"step {index + 1} would start {step.get('app')!r}, a shell, "
                "interpreter or system tool; unattended hands never open one — "
                + approval_path)
        if action == "select":
            # A menu or list entry can commit as surely as a button can.
            hit = committing_label(str(step.get("value", "")))
            if hit:
                raise CommittingControl(
                    f"step {index + 1} would select {step.get('value')!r}, which matches "
                    f"the committing/destructive pattern ({hit!r}); refused rather than "
                    "skipped — " + approval_path)
            continue
        if action != "invoke":
            continue
        label = _control_label(step.get("control") or {})
        if not label:
            raise CommittingControl(
                f"step {index + 1} (invoke) names its control by "
                f"{sorted(step.get('control') or {})} only, with no readable label, "
                "so the committing-control guard cannot read what it would press — "
                + approval_path)
        hit = committing_label(label)
        if hit:
            raise CommittingControl(
                f"step {index + 1} would press {label!r}, which matches the "
                f"committing/destructive pattern ({hit!r}). Unattended hands never "
                "press that; refused rather than skipped, because a plan that ran "
                "without it would report success for a thing not done — "
                + approval_path)


def act(steps: object, backend: ComputerBackend | None = None,
        backend_factory=None, requested_by: str = "agenda") -> dict:
    """Do something on the desktop without a per-plan approval.

    The whole plan is checked before the first step runs; a forbidden step
    anywhere refuses the plan whole. Between steps HALT is re-read, and
    before every click the control's LIVE label is read and checked again.
    """
    if backend is not None and backend_factory is not None:
        raise ValueError("provide backend or backend_factory, not both")
    if not isinstance(requested_by, str) or not requested_by.strip():
        raise ValueError("requested_by must be a non-empty string")
    problems = validate_steps(steps)
    if problems:
        raise ValueError("; ".join(problems))
    check_act_plan(steps)
    policy.ensure_not_halted()
    run_id = f"hands-{uuid.uuid4().hex[:12]}"
    journal.append("action", "computer:act",
                   f"STARTED run={run_id} requested_by={requested_by} steps={len(steps)}",
                   actor=ACTOR, refs=[f"run:{run_id}"])
    driver = backend or (backend_factory() if backend_factory else WindowsUIABackend())
    results = []
    for index, step in enumerate(steps):
        policy.ensure_not_halted()
        if step["action"] == "invoke":
            describe = getattr(driver, "describe_control", None)
            if callable(describe):
                live = describe(step)
                name = str((live or {}).get("name") or "")
                hit = committing_label(name)
                if hit:
                    journal.append(
                        "action", "computer:act",
                        f"REFUSED run={run_id} step={index} the control on screen is "
                        f"labelled {name[:60]!r} ({hit!r}); stopped after {len(results)} step(s)",
                        actor=ACTOR, refs=[f"run:{run_id}"])
                    raise CommittingControl(
                        f"step {index + 1}: the control on screen is labelled {name!r}, "
                        f"which matches the committing/destructive pattern ({hit!r}). "
                        f"Stopped after {len(results)} step(s); nothing was pressed. "
                        "Pressing it needs an approval bound to this exact plan "
                        "(python -m aletheia.computer request/run).")
        try:
            evidence = driver.perform(step)
            if not isinstance(evidence, dict):
                raise VerificationFailed(
                    f"backend returned non-object evidence for {step['action']}")
        except Exception as exc:
            journal.append(
                "action", f"computer:{step['action']}",
                f"FAILED run={run_id} step={index} error={type(exc).__name__}",
                actor=ACTOR, refs=[f"run:{run_id}"])
            raise
        results.append(evidence)
        journal.append(
            "action", f"computer:{step['action']}",
            f"DONE run={run_id} step={index} "
            f"verification={json.dumps(_journal_evidence(evidence), ensure_ascii=False, sort_keys=True)}",
            actor=ACTOR, refs=[f"run:{run_id}"])
    journal.append("action", "computer:act",
                   f"COMPLETED run={run_id} steps={len(results)}",
                   actor=ACTOR, refs=[f"run:{run_id}"])
    return {"run_id": run_id, "requested_by": requested_by,
            "steps_done": len(results), "results": results}


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
    req = sub.add_parser("request",
                         help="file the durable approval for a validated plan")
    req.add_argument("file"); req.add_argument("--approval-id", required=True)
    req.add_argument("--why", default="Verify the Windows UI Automation adapter")
    req.add_argument("--consequence",
                     default="An unsaved window remains open; nothing is saved or submitted")
    run = sub.add_parser("run"); run.add_argument("file")
    run.add_argument("--approval", required=True)
    hands = sub.add_parser(
        "act", help="unattended hands: open/focus/type/press, committing controls refused")
    hands.add_argument("file")
    args = parser.parse_args(argv)

    if args.command == "status":
        ok, reason = available()
        print(f"computer: {'experimental' if ok else 'unavailable'} — {reason}")
        print("Core route: POST /api/computer; no coordinate or visual-click fallback")
        return 0 if ok else 1
    steps = _load_steps(args.file)
    problems = validate_steps(steps)
    if problems:
        print("invalid plan: " + "; ".join(problems), file=sys.stderr)
        return 2
    if args.command == "plan":
        print(json.dumps(steps, indent=2, ensure_ascii=False))
        return 0
    if args.command == "act":
        try:
            print(json.dumps(act(steps, requested_by="operator-cli"),
                             indent=2, ensure_ascii=False))
        except ApprovalRequired as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 3
        return 0
    if args.command == "request":
        # was a PowerShell here-string piped to python -c; PowerShell 5.1
        # mangles multiline -c args (first live run: SyntaxError, truncated)
        from aletheia import policy
        approval = policy.request(
            args.approval_id, approval_action(steps), args.why,
            args.consequence, reversible=True)
        print(json.dumps(approval, indent=2, ensure_ascii=False))
        return 0
    print(json.dumps(execute(steps, args.approval), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
