"""The supervisor — Aletheia as a thing that is simply always on.

    python -m aletheia.supervisor            # run the Core forever
    python -m aletheia.supervisor install    # start at every Windows logon
    python -m aletheia.supervisor uninstall

The Core process is deliberately mortal: it exits RESTART_EXIT_CODE when
its sync loop pulls new code (self-update) and can die like any process.
This loop is the immortal half: relaunch immediately on a restart exit,
relaunch with bounded backoff on a crash, stop only on Ctrl+C or a clean
exit. The pair means a merge to main lands on the PC within about a
minute of the next sync beat, with no human touching anything.

`install` registers a Windows Scheduled Task that runs this supervisor
hidden at every logon (pythonw, no console window). Not Windows — it
says exactly what it would have done and exits nonzero, never pretending
(§106).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from aletheia import journal
from aletheia.core import RESTART_EXIT_CODE
from aletheia.fleet import REPO_ROOT

ACTOR = "aletheia-supervisor"
TASK_NAME = "Aletheia"
BACKOFF_START_S = 2.0
BACKOFF_MAX_S = 60.0
STABLE_AFTER_S = 600.0  # this long alive resets the crash backoff


def run_forever(core_args: list[str] | None = None, launch=None,
                sleep=time.sleep, max_runs: int | None = None) -> int:
    """Relaunch the Core until a clean exit. `launch`/`sleep`/`max_runs`
    exist for tests; real life passes none of them."""
    cmd = [sys.executable, "-m", "aletheia.core", *(core_args or [])]
    launch = launch or (lambda: subprocess.run(cmd, cwd=str(REPO_ROOT)).returncode)
    backoff = BACKOFF_START_S
    runs = 0
    journal.append("event", "supervisor", "supervisor up — the Core is now persistent",
                   actor=ACTOR)
    while max_runs is None or runs < max_runs:
        runs += 1
        started = time.monotonic()
        try:
            code = launch()
        except KeyboardInterrupt:
            journal.append("event", "supervisor", "stopped by operator", actor=ACTOR)
            return 0
        alive_s = time.monotonic() - started
        if code == 0:
            journal.append("event", "supervisor", "Core exited cleanly — done", actor=ACTOR)
            return 0
        if code == RESTART_EXIT_CODE:
            backoff = BACKOFF_START_S  # a self-update is health, not a crash
            journal.append("event", "supervisor",
                           "relaunching Core on updated code", actor=ACTOR)
            continue
        if alive_s >= STABLE_AFTER_S:
            backoff = BACKOFF_START_S
        journal.append("event", "supervisor",
                       f"Core died (exit {code}) after {alive_s:.0f}s — "
                       f"relaunching in {backoff:.0f}s", actor=ACTOR)
        sleep(backoff)
        backoff = min(backoff * 2, BACKOFF_MAX_S)
    return 1  # only reachable in tests via max_runs


def _schtasks(argv: list[str]) -> tuple[int, str]:
    proc = subprocess.run(["schtasks", *argv], capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def install() -> int:
    """Register the hidden at-logon task (Windows only, honest elsewhere)."""
    if os.name != "nt":
        print("install needs Windows: it registers a Scheduled Task running\n"
              f'  pythonw -m aletheia.supervisor  (cwd {REPO_ROOT})\n'
              "at every logon. On this OS, run the supervisor directly instead.")
        return 1
    pyw = shutil.which("pythonw") or sys.executable
    action = f'"{pyw}" -m aletheia.supervisor'
    code, out = _schtasks(["/Create", "/F", "/SC", "ONLOGON", "/TN", TASK_NAME,
                           "/TR", f'cmd /c cd /d "{REPO_ROOT}" && {action}'])
    if code != 0:
        print(f"could not register the task: {out}")
        return 1
    journal.append("event", "supervisor",
                   f"installed at-logon task {TASK_NAME!r}", actor=ACTOR)
    print(f"Aletheia now starts at every logon (task {TASK_NAME!r}).\n"
          "Start it right now with:  schtasks /Run /TN " + TASK_NAME)
    return 0


def uninstall() -> int:
    if os.name != "nt":
        print("uninstall needs Windows (schtasks).")
        return 1
    code, out = _schtasks(["/Delete", "/F", "/TN", TASK_NAME])
    if code != 0:
        print(f"could not remove the task: {out}")
        return 1
    journal.append("event", "supervisor",
                   f"removed at-logon task {TASK_NAME!r}", actor=ACTOR)
    print("Removed. Aletheia no longer starts at logon.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Keep the Aletheia Core running.")
    ap.add_argument("cmd", nargs="?", default="run",
                    choices=["run", "install", "uninstall"])
    args = ap.parse_args(argv)
    if args.cmd == "install":
        return install()
    if args.cmd == "uninstall":
        return uninstall()
    return run_forever()


if __name__ == "__main__":
    raise SystemExit(main())
