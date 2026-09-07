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


def _psutil_rows() -> list[dict] | None:
    """Every python process, via psutil. None when psutil is absent.

    TWO PHASES, and the order is the whole optimisation: reading
    `cmdline` opens the process, so asking for it across ~300 processes
    cost 2.5 s. Names are cheap, there are four python processes, and
    only those four need opening — 5 ms warm, 100 ms cold.
    """
    try:
        import psutil
    except Exception:
        return None
    rows = []
    try:
        for proc in psutil.process_iter(["pid", "name"]):
            name = str(proc.info.get("name") or "").casefold()
            if name not in ("python.exe", "pythonw.exe"):
                continue
            try:
                command = " ".join(proc.cmdline())
                megabytes = proc.memory_info().rss // (1024 * 1024)
            except Exception:
                continue        # it exited between the two calls; not an error
            rows.append({"pid": proc.info.get("pid"), "command": command,
                         "mb": megabytes})
    except Exception:
        return None
    return rows


def _powershell_rows() -> list[dict]:
    """The fallback, for a machine without psutil."""
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
        try:
            megabytes = int(row.get("WorkingSetSize") or 0) // (1024 * 1024)
        except (TypeError, ValueError):
            megabytes = 0
        found.append({"pid": row.get("ProcessId"),
                      "command": str(row.get("CommandLine") or ""),
                      "mb": megabytes})
    return found


def processes() -> list[dict]:
    """Every python process on this machine that is a part of Aletheia."""
    rows = _psutil_rows()
    if rows is None:
        rows = _powershell_rows()
    found = []
    for row in rows:
        command = str(row.get("command") or "")
        for key, _what, needle in PARTS:
            if needle in command:
                found.append({"part": key, "pid": row.get("pid"),
                              "mb": row.get("mb", 0),
                              "command": command.strip()})
    return found


def tasks() -> dict[str, str]:
    """Scheduled task -> state, for the tasks that start her at logon.

    A part can be OFF right now and still set to come back in five
    minutes, which is the difference between "not running" and "off" —
    and the difference he most needs to see.

    `schtasks.exe` by NAME rather than `Get-ScheduledTask | Where-Object`:
    the cmdlet enumerates every task on the machine and cost 6.9 s, and
    the native binary answers about three named ones in 0.6 s. It also
    reports the state in WORDS, so there is no enum number to translate.
    """
    found = {}
    for name in TASKS:
        try:
            done = subprocess.run(
                ["schtasks.exe", "/query", "/TN", name, "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=20)
        except Exception:
            continue
        if done.returncode != 0 or not (done.stdout or "").strip():
            continue            # a task that is not registered is not an error
        first = done.stdout.strip().splitlines()[0]
        fields = [f.strip().strip('"') for f in first.split('","')]
        if len(fields) >= 3:
            state = fields[-1].strip('"').casefold()
            found[name] = {"ready": "ready (starts at logon)"}.get(state, state)
    if found:
        return found
    return _powershell_tasks()


def _powershell_tasks() -> dict[str, str]:
    """The fallback. `ConvertTo-Json` serialises TaskState as its NUMBER,
    so this read "AletheiaVoice 3" — which is precisely the sort of thing
    this module exists to stop showing him."""
    out = _powershell(
        "Get-ScheduledTask -TaskName " + ",".join(f"'{t}'" for t in TASKS)
        + " -ErrorAction SilentlyContinue | Select-Object TaskName,State | "
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
        out_states[str(name)] = TASK_STATE.get(row.get("State"),
                                               str(row.get("State")))
    return out_states


def version() -> dict:
    """Which code is checked out, and whether she started before it.

    STALENESS IS MEASURED AGAINST THE CODE, not against the commit: a
    commit that only touches docs or tests changes nothing she runs, and
    saying "restart me" for one would train him to ignore the line. The
    signal is the newest mtime under `aletheia/`, compared with the moment
    she started.

    Every field is optional. Outside a git checkout, or before the start
    stamp existed, the honest answer is that she does not know — never a
    guess about which code is running.
    """
    from aletheia import liveness
    from aletheia.fleet import REPO_ROOT

    def git(*args):
        try:
            done = subprocess.run(["git", *args], capture_output=True,
                                  text=True, cwd=str(REPO_ROOT), timeout=15)
            return done.stdout.strip() if done.returncode == 0 else ""
        except Exception:
            return ""

    started, newest_file, stale = running_old_code()
    # THE STALENESS THAT ACTUALLY BIT HIM. A file changing on disk is
    # caught by the supervisor, which relaunches within minutes. Nothing
    # catches a CHECKOUT that is behind the remote: on 2026-09-07 this
    # tree was ninety commits behind, three days old, with every part
    # healthy and no disk change to notice — and a clock question took 26
    # seconds because the process predated the fast lane.
    #
    # Counted against the last fetch, never fetching here: a status read
    # must not touch the network.
    behind = ""
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    for remote in (f"origin/{branch}", "origin/main"):
        counted = git("rev-list", "--count", f"HEAD..{remote}")
        if counted.isdigit() and int(counted):
            behind = f"{counted} commits behind {remote}"
            break
    return {"behind": behind,
            "branch": branch,
            "commit": git("rev-parse", "--short", "HEAD"),
            "subject": git("log", "-1", "--format=%s")[:80],
            "started_at": started,
            "newest_code": newest_file,
            "running_old_code": stale}


def running_old_code() -> tuple:
    """(started_at, newest changed file, is she behind) — no subprocess.

    A few file stats, so the WARNING can always be on while the git
    identity is paid only when he asks for it. Measured against the CODE
    rather than against the last commit: a commit touching only docs or
    tests changes nothing she runs, and crying "restart me" for one would
    teach him to ignore the line.
    """
    from aletheia import liveness
    from aletheia.fleet import REPO_ROOT
    started = (liveness.last() or {}).get("started_at")
    newest, newest_file = 0.0, ""
    try:
        for path in (REPO_ROOT / "aletheia").glob("*.py"):
            stamp = path.stat().st_mtime
            if stamp > newest:
                newest, newest_file = stamp, path.name
    except Exception:
        return started, "", None
    if not started or not newest:
        return started, newest_file, None    # she cannot honestly say
    try:
        began = liveness._parse_ts(started).timestamp()
    except Exception:
        return started, newest_file, None
    return started, newest_file, newest > began


def version_words(info: dict) -> str:
    """One sentence about which code she is running."""
    where = info.get("branch") or "?"
    commit = info.get("commit") or "?"
    said = f"On {where} at {commit}"
    if info.get("behind"):
        said += f" — {info['behind']}, so this is not the newest code there is"
    subject = info.get("subject")
    if subject:
        said += f" — {subject}"
    if info.get("running_old_code"):
        said += (f". I started BEFORE the current code was written "
                 f"({info.get('newest_code')} is newer than I am), so I am "
                 "running an older copy — restart me to pick it up.")
    elif info.get("running_old_code") is False:
        said += ". This is the code I am running."
    return said


def snapshot(include_tasks: bool = True) -> dict:
    """Everything, in one read. Never raises.

    `include_tasks=False` skips the scheduled-task query, which is the
    slow half (0.6 s against ~5 ms for the rest). `headline` never uses
    it, so anything that just wants "is she on?" — the spoken answer, the
    fast lane — should not pay for it.
    """
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
    _started, newest_file, stale = running_old_code()
    return {"parts": parts, "tasks": tasks() if include_tasks else {},
            "running_old_code": stale, "newest_code": newest_file, "closed": shut,
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
        if state.get("running_old_code"):
            return ("ON, but running OLDER CODE than is checked out — "
                    "restart her to pick it up.")
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
    if state.get("running_old_code"):
        lines.append(
            f"\n  RUNNING OLDER CODE — {state.get('newest_code') or 'a module'} "
            "changed after she started.\n  She keeps running the copy she "
            "loaded; restart her to pick the new one up.")
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
