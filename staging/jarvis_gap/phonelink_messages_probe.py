"""Privacy-safe, read-only Phone Link messaging feasibility probe.

Before building a brittle GUI sender, first answer a smaller factual question:
does the operator's current Phone Link/iPhone pairing expose a Messages surface
to Windows UI Automation at all? This probe emits only capability facts. It does
not return contact names, message previews, or arbitrary UI labels, and the only
backend actions it may request are list_windows and inspect_controls.

Running this module is not required for staging tests. A future supervised
Windows check can inject production ``computer.WindowsUIABackend`` after review.
"""
from __future__ import annotations

from collections import Counter

READ_ONLY_ACTIONS = frozenset({"list_windows", "inspect_controls"})
MAX_CONTROLS = 300
PHONE_LINK_TITLES = ("phone link", "microsoft phone link")
MESSAGE_WORDS = frozenset({"messages", "message", "new message"})
SEND_WORDS = frozenset({"send", "send message"})


def _perform(backend, step: dict) -> dict:
    action = step.get("action")
    if action not in READ_ONLY_ACTIONS:
        raise PermissionError(f"Phone Link probe is read-only; refused {action!r}")
    result = backend.perform(step)
    if not isinstance(result, dict):
        raise ValueError("Phone Link probe backend returned a non-object")
    return result


def _name(control: dict) -> str:
    value = control.get("name")
    return " ".join(value.casefold().split()) if isinstance(value, str) else ""


def probe(backend, *, title_hints: tuple[str, ...] = PHONE_LINK_TITLES) -> dict:
    windows = _perform(backend, {"action": "list_windows", "max_results": 30})
    rows = windows.get("windows")
    if not isinstance(rows, list):
        raise ValueError("list_windows response is missing windows")
    hints = tuple(h.casefold().strip() for h in title_hints if h.strip())
    candidates = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("name") or "").casefold()
        if any(h in title for h in hints):
            pid = row.get("process_id")
            if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
                candidates.append(pid)
    candidates = list(dict.fromkeys(candidates))
    if not candidates:
        return {
            "window_found": False,
            "messages_surface": False,
            "send_control_visible": False,
            "control_types": {},
            "privacy": "arbitrary labels omitted",
        }
    if len(candidates) != 1:
        return {
            "window_found": True,
            "ambiguous_windows": len(candidates),
            "messages_surface": False,
            "send_control_visible": False,
            "control_types": {},
            "privacy": "arbitrary labels omitted",
        }
    inspected = _perform(backend, {
        "action": "inspect_controls",
        "window": {"process_id": candidates[0]},
        "max_results": MAX_CONTROLS,
    })
    controls = inspected.get("controls")
    if not isinstance(controls, list):
        raise ValueError("inspect_controls response is missing controls")
    type_counts: Counter[str] = Counter()
    messages_surface = False
    send_visible = False
    for control in controls[:MAX_CONTROLS]:
        if not isinstance(control, dict):
            continue
        control_type = str(control.get("control_type") or "")[:80]
        if control_type:
            type_counts[control_type] += 1
        name = _name(control)
        if name in MESSAGE_WORDS:
            messages_surface = True
        if name in SEND_WORDS:
            send_visible = True
    return {
        "window_found": True,
        "messages_surface": messages_surface,
        "send_control_visible": send_visible,
        "control_types": dict(sorted(type_counts.items())),
        "privacy": "arbitrary labels omitted",
    }
