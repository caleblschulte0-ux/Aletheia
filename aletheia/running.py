"""What is running, and one switch for all of it.

The operator: *"i want it to be very clear if any part of aletheia is
running and i want to make it very easy to turn off and on."*

He was right that it was neither. Aletheia is not one process. On this PC
it is three — the supervisor, the Core it keeps alive, and the room voice
listening on its own scheduled task — plus a project loop that wakes on a
timer, three Windows tasks that start them, and TWO separate switches
that mean different things:

  - **closed** (`aletheia.closed`) is the window button. She finishes what
    she is holding and stays shut, and the watchdog does not reopen her.
  - **HALT** (`aletheia.policy`) is the kill switch. She keeps RUNNING and
    refuses to act.

Neither of those is wrong, and this module does not add a third. It adds
the missing thing: one place that answers "is any of this on?" and one
verb for turning it off and back on.

**Closing her now means the microphone too.** Until 2026-09-07 `closed`
was honoured by the Core and the supervisor and by nothing else, so
"close her" stopped the Core, told the watchdog to leave it stopped, and
left the room voice listening and the project loop opening pull requests.
An off switch that reports success and leaves a live microphone in his
room is worse than no off switch, because he believes it.

Reading is free and never changes anything: `status` starts nothing,
stops nothing and writes no journal line.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

# Each part, as (key, what it is, how to recognise its process).
PARTS = (
    ("supervisor", "keeps the Core alive and repairs it", "aletheia.supervisor"),
    ("core", "the wall, the API, the beat", "aletheia.core"),
    ("voice", "the room microphone", "aletheia.voice_room"),
)

# The Windows scheduled tasks that start them at logon.
TASKS = ("Aletheia", "AletheiaVoice", "AletheiaProjects")

# `ConvertTo-Json` serialises the TaskState enum as its NUMBER, so the
# status read "AletheiaVoice 3" — which is precisely the kind of thing
# this module exists to stop printing at him.
TASK_STATE = {0: "unknown", 1: "disabled", 2: "queued",
              3: "ready (starts at logon)", 4: "running"}


def _powershell(script: str) -> str:
    """Never raises: a status command that dies is a status command that
    lies about the thing it could not see."""
    try:
        done = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=25)
        return done.stdout or ""
    except Exception:
        return ""


def processes() -> list[dict]:
    """Every python process on this machine that is a part of Aletheia."""
    out = _powershell(
        "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' or "
        "Name='python.exe'\" | Select-Object ProcessId,CommandLine,"
        "WorkingSetSize | ConvertTo-Json -Compress")
    try:
        rows = json.loads(out) if out.strip() else []
    except json.JSONDecodeError:
        return []
    if isinstance(rows, dict):
        rows = [rows]
    found = []
    for row in rows:
        command = str(row.get("CommandLine") or "")
        for key, _what, needle in PARTS:
            if needle in command:
                try:
                    megabytes = int(row.get("WorkingSetSize") or 0) // (1024 * 1024)
                except (TypeError, ValueError):
                    megabytes = 0
                found.append({"part": key, "pid": row.get("ProcessId"),
                              "mb": megabytes, "command": command.strip()})
    return found


def tasks() -> dict[str, str]:
    """Scheduled task -> state, for the tasks that start her at logon.

    A part can be OFF right now and still set to come back in five
    minutes, which is the difference between "not running" and "off" —
    and the difference he most needs to see.
    """
    out = _powershell(
        "Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object { "
        "$_.TaskName -like 'Aletheia*' } | Select-Object TaskName,State | "
        "ConvertTo-Json -Compress")
    try:
        rows = json.loads(out) if out.strip() else []
    except json.JSONDecodeError:
        return {}
    if isinstance(rows, dict):
        rows = [rows]
    out_states = {}
    for row in rows:
        name = row.get("TaskName")
        if not name:
            continue
        state = row.get("State")
        out_states[str(name)] = TASK_STATE.get(state, str(state))
    return out_states


def snapshot() -> dict:
    """Everything, in one read. Never raises."""
    from aletheia import closed, liveness, policy
    running = processes()
    by_part = {}
    for row in running:
        by_part.setdefault(row["part"], []).append(row)

    try:
        halt = policy.halted()
    except Exception:
        halt = None
    try:
        shut = closed.is_closed()
        why = closed.why() if shut else ""
    except Exception:
        shut, why = False, ""
    try:
        beat_age = liveness.age_seconds()
    except Exception:
        beat_age = None

    parts = []
    for key, what, _needle in PARTS:
        rows = by_part.get(key, [])
        parts.append({"part": key, "what": what, "up": bool(rows),
                      "pids": [r["pid"] for r in rows],
                      "mb": sum(r.get("mb", 0) for r in rows)})
    return {"parts": parts, "tasks": tasks(), "closed": shut,
            "closed_reason": why, "halted": bool(halt),
            "halt_reason": (halt or {}).get("reason", "") if halt else "",
            "heartbeat_age_s": beat_age}


def headline(state: dict) -> str:
    """One line he can act on, before any of the detail."""
    up = [p for p in state["parts"] if p["up"]]
    if state["closed"]:
        if up:
            return (f"CLOSED — but {len(up)} part(s) are still running. "
                    "They stop within a few seconds.")
        return "OFF. She is closed and nothing is running."
    if not up:
        return "OFF. Nothing is running (and she is not marked closed)."
    if state["halted"]:
        return (f"ON but HALTED — {len(up)} of {len(state['parts'])} parts "
                "running, refusing to act.")
    if len(up) == len(state["parts"]):
        return "ON. Everything is running."
    missing = ", ".join(p["part"] for p in state["parts"] if not p["up"])
    return f"PARTLY ON — running, but {missing} is not."


def render(state: dict) -> str:
    lines = [headline(state), ""]
    for part in state["parts"]:
        mark = "on " if part["up"] else "off"
        # The memory too: the room voice holds the speech models in RAM
        # and was sitting on a gigabyte after three days. "What is running"
        # should include what it is costing him to have running.
        detail = ""
        if part["pids"]:
            detail = " — pid " + ", ".join(str(p) for p in part["pids"])
            if part.get("mb"):
                detail += f", {part['mb']} MB"
        lines.append(f"  [{mark}] {part['part']:<11} {part['what']}{detail}")
    age = state.get("heartbeat_age_s")
    if age is not None:
        lines.append(f"\n  last heartbeat: {age:.0f}s ago")
    if state["tasks"]:
        lines.append("\n  starts at logon:")
        for name, task_state in sorted(state["tasks"].items()):
            lines.append(f"    {name:<20} {task_state}")
    if state["closed"]:
        lines.append(f"\n  CLOSED{' — ' + state['closed_reason'] if state['closed_reason'] else ''}"
                     "\n  `python -m aletheia.running on` to open her again.")
    if state["halted"]:
        lines.append(f"\n  HALTED (kill switch){' — ' + state['halt_reason'] if state['halt_reason'] else ''}"
                     "\n  She is running and refusing to act. That is not the "
                     "same as off;\n  `python -m aletheia.policy resume` lifts it.")
    if not state["closed"] and not state["halted"]:
        lines.append("\n  `python -m aletheia.running off` closes her.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="What is running, and one switch for all of it.")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status", help="what is on right now (changes nothing)")
    p_off = sub.add_parser("off", help="close her — every part, and stay shut")
    p_off.add_argument("--reason", default="")
    sub.add_parser("on", help="open her again")
    args = ap.parse_args(argv)

    if args.cmd == "off":
        from aletheia import closed
        closed.close(args.reason)
        print("Closing. The Core finishes what it is holding, the room stops "
              "listening within a couple of seconds, and the watchdog leaves "
              "her shut until you turn her on.")
        return 0
    if args.cmd == "on":
        from aletheia import closed
        if closed.open_again():
            print("Open. She comes back within five minutes, or start the "
                  "Aletheia task to have her now.")
        else:
            print("She was not closed.")
        return 0
    print(render(snapshot()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
