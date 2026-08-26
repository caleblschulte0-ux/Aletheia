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
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from aletheia import journal
from aletheia.core import DEFAULT_PORT, RESTART_EXIT_CODE
from aletheia.fleet import REPO_ROOT

ACTOR = "aletheia-supervisor"
TASK_NAME = "Aletheia"
BACKOFF_START_S = 2.0
BACKOFF_MAX_S = 60.0
STABLE_AFTER_S = 600.0  # this long alive resets the crash backoff


def core_alive(port: int = DEFAULT_PORT) -> bool:
    """Is an Aletheia Core already answering on this machine?"""
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/status", timeout=2):
            return True
    except Exception:
        return False


def _child_env() -> dict:
    """The marker telling the Core a supervisor is waiting to relaunch it,
    so on a code update it may exit RESTART_EXIT_CODE instead of having to
    hand itself off (see core.main). Never set this by hand."""
    return {**os.environ, "ALETHEIA_SUPERVISED": "1"}


def run_forever(core_args: list[str] | None = None, launch=None,
                sleep=time.sleep, max_runs: int | None = None) -> int:
    """Relaunch the Core until a clean exit. `launch`/`sleep`/`max_runs`
    exist for tests; real life passes none of them."""
    if launch is None and core_alive():
        # a second supervisor must not fight the first for the port
        journal.append("event", "supervisor",
                       "another Aletheia is already serving — this one exits",
                       actor=ACTOR)
        print("Aletheia is already running at http://127.0.0.1:8777/ — nothing to do.")
        return 0
    cmd = [sys.executable, "-m", "aletheia.core", *(core_args or [])]
    launch = launch or (lambda: subprocess.run(
        cmd, cwd=str(REPO_ROOT), env=_child_env()).returncode)
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


def windowless_interpreter() -> str:
    r"""The pythonw.exe belonging to THIS interpreter, else this interpreter.

    Never `shutil.which("pythonw")`: PATH order is not version order. On
    the operator's PC an old C:\Python39\pythonw.EXE sits ahead of the
    3.12 that Aletheia actually needs, so the task registered a python
    that `aletheia/__init__` refuses — and because pythonw has no
    console, the refusal was invisible: reboot, dead wall, empty log.
    The running interpreter is 3.10+ by construction (that same import
    check), so its own sibling is the one safe answer.
    """
    exe = Path(sys.executable)
    sibling = exe.with_name("pythonw.exe")
    return str(sibling) if sibling.exists() else str(exe)


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
    action = f'"{windowless_interpreter()}" -m aletheia.supervisor'
    code, out = _schtasks(["/Create", "/F", "/SC", "ONLOGON", "/TN", TASK_NAME,
                           "/TR", f'cmd /c cd /d "{REPO_ROOT}" && {action}'])
    if code != 0:
        print(f"could not register the task: {out}")
        return 1
    journal.append("event", "supervisor",
                   f"installed at-logon task {TASK_NAME!r}", actor=ACTOR)
    print(f"Aletheia now starts at every logon (task {TASK_NAME!r}).")
    if not core_alive():
        # start it NOW too — "returns at next logon" once meant a closed
        # setup window left the wall dead until a reboot
        code, out = _schtasks(["/Run", "/TN", TASK_NAME])
        print("Started in the background." if code == 0
              else f"Could not start it now ({out}) — it will start at next logon.")
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
    journal.use_pc_journal()  # supervisor runs only on the PC
    if args.cmd == "install":
        return install()
    if args.cmd == "uninstall":
        return uninstall()
    return run_forever()


if __name__ == "__main__":
    raise SystemExit(main())
