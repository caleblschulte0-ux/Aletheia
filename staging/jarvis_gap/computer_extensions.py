"""Proposal-only contracts for richer Windows control.

Production ``aletheia.computer`` remains the only executor. This staging module
describes additional actions the Playbook expects without implementing them or
granting authority to run them. Drag/drop remains semantic: no x/y coordinates.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

MAX_STEPS = 40
MAX_SELECTOR_CHARS = 256
MAX_TEXT_CHARS = 20_000
MAX_SCROLL_UNITS = 100
MAX_PATH_CHARS = 2_048
WINDOW_SELECTOR_FIELDS = {"title", "title_re", "class_name", "auto_id", "control_type"}
CONTROL_SELECTOR_FIELDS = WINDOW_SELECTOR_FIELDS | {"best_match"}
HOTKEY_KEYS = {
    "CTRL", "ALT", "SHIFT", "WIN", "A", "C", "V", "X", "Z", "Y", "F", "L",
    "R", "S", "P", "N", "T", "W", "ENTER", "ESC", "TAB", "SPACE", "BACKSPACE",
    "DELETE", "HOME", "END", "PAGEUP", "PAGEDOWN", "UP", "DOWN", "LEFT", "RIGHT",
}
ACTIONS = {"scroll", "hotkey", "drag_drop", "clipboard_write", "choose_file"}
RISK = {
    "scroll": "low", "hotkey": "medium", "drag_drop": "high",
    "clipboard_write": "medium", "choose_file": "high",
}


def _selector(value: object, *, name: str, allowed: set[str]) -> dict:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{name} must be a non-empty selector")
    if any(key in value for key in ("x", "y", "coordinates", "position")):
        raise ValueError(f"{name} may not contain screen coordinates")
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"{name} has unsupported fields {sorted(unknown)}")
    out = {}
    for key, item in value.items():
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{name}.{key} must be a non-empty string")
        if len(item) > MAX_SELECTOR_CHARS:
            raise ValueError(f"{name}.{key} exceeds {MAX_SELECTOR_CHARS} characters")
        out[key] = item.strip()
    return out


def _hotkey(keys: object) -> list[str]:
    if not isinstance(keys, list) or not 1 <= len(keys) <= 4:
        raise ValueError("hotkey.keys must contain 1..4 keys")
    normalized = []
    for key in keys:
        if not isinstance(key, str):
            raise ValueError("hotkey keys must be strings")
        item = key.strip().upper()
        if item not in HOTKEY_KEYS:
            raise ValueError(f"unsupported hotkey key {key!r}")
        if item in normalized:
            raise ValueError("hotkey may not repeat a key")
        normalized.append(item)
    return normalized


def canonicalize_step(step: object) -> dict:
    if not isinstance(step, dict):
        raise ValueError("step must be an object")
    action = step.get("action")
    if action not in ACTIONS:
        raise ValueError(f"unsupported extended action {action!r}")

    if action == "scroll":
        unknown = set(step) - {"action", "window", "control", "direction", "units"}
        if unknown:
            raise ValueError(f"scroll has unsupported fields {sorted(unknown)}")
        direction = step.get("direction")
        if direction not in {"up", "down", "left", "right"}:
            raise ValueError("scroll.direction must be up/down/left/right")
        units = step.get("units", 1)
        if isinstance(units, bool) or not isinstance(units, int) or not 1 <= units <= MAX_SCROLL_UNITS:
            raise ValueError("scroll.units out of bounds")
        out = {"action": action, "direction": direction, "units": units}
        if "window" in step:
            out["window"] = _selector(step["window"], name="scroll.window", allowed=WINDOW_SELECTOR_FIELDS)
        if "control" in step:
            out["control"] = _selector(step["control"], name="scroll.control", allowed=CONTROL_SELECTOR_FIELDS)
        if "window" not in out and "control" not in out:
            raise ValueError("scroll needs a semantic window or control target")
        return out

    if action == "hotkey":
        unknown = set(step) - {"action", "window", "keys"}
        if unknown:
            raise ValueError(f"hotkey has unsupported fields {sorted(unknown)}")
        return {
            "action": action,
            "window": _selector(step.get("window"), name="hotkey.window", allowed=WINDOW_SELECTOR_FIELDS),
            "keys": _hotkey(step.get("keys")),
        }

    if action == "drag_drop":
        unknown = set(step) - {"action", "window", "source", "destination"}
        if unknown:
            raise ValueError(f"drag_drop has unsupported fields {sorted(unknown)}")
        return {
            "action": action,
            "window": _selector(step.get("window"), name="drag_drop.window", allowed=WINDOW_SELECTOR_FIELDS),
            "source": _selector(step.get("source"), name="drag_drop.source", allowed=CONTROL_SELECTOR_FIELDS),
            "destination": _selector(step.get("destination"), name="drag_drop.destination", allowed=CONTROL_SELECTOR_FIELDS),
        }

    if action == "clipboard_write":
        unknown = set(step) - {"action", "text"}
        if unknown:
            raise ValueError(f"clipboard_write has unsupported fields {sorted(unknown)}")
        text = step.get("text")
        if not isinstance(text, str):
            raise ValueError("clipboard_write.text must be a string")
        if len(text) > MAX_TEXT_CHARS or "\x00" in text:
            raise ValueError("clipboard_write.text invalid or too long")
        return {"action": action, "text": text}

    unknown = set(step) - {"action", "window", "control", "path"}
    if unknown:
        raise ValueError(f"choose_file has unsupported fields {sorted(unknown)}")
    path = step.get("path")
    if (not isinstance(path, str) or not path.strip() or len(path) > MAX_PATH_CHARS
            or any(char in path for char in "\x00\r\n")):
        raise ValueError("choose_file.path invalid")
    return {
        "action": action,
        "window": _selector(step.get("window"), name="choose_file.window", allowed=WINDOW_SELECTOR_FIELDS),
        "control": _selector(step.get("control"), name="choose_file.control", allowed=CONTROL_SELECTOR_FIELDS),
        "path": path,
    }


@dataclass(frozen=True)
class ExtendedComputerProposal:
    steps: tuple[dict, ...]
    digest: str
    highest_risk: str

    def as_dict(self) -> dict:
        return {
            "steps": [dict(step) for step in self.steps],
            "sha256": self.digest,
            "highest_risk": self.highest_risk,
            "execution_authority": False,
            "requires_production_policy_review": True,
        }


def propose(steps: object) -> ExtendedComputerProposal:
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise ValueError("steps out of bounds")
    canonical = tuple(canonicalize_step(step) for step in steps)
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    rank = {"low": 1, "medium": 2, "high": 3}
    highest = max((RISK[step["action"]] for step in canonical), key=rank.__getitem__)
    return ExtendedComputerProposal(canonical, digest, highest)
