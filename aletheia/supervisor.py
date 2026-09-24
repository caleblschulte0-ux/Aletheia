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

from aletheia import autostart, closed, journal, liveness
from aletheia.core import DEFAULT_PORT, RESTART_EXIT_CODE
from aletheia.fleet import REPO_ROOT
from aletheia.proc import run as proc_run

ACTOR = "aletheia-supervisor"
TASK_NAME = "Aletheia"
BACKOFF_START_S = 2.0
BACKOFF_MAX_S = 60.0
STABLE_AFTER_S = 600.0  # this long alive resets the crash backoff

# A CRASH LOOP MUST BE HONEST RATHER THAN SILENT. This loop is very good
# at hiding one: the Core dies, it relaunches, the Core dies, and every
# word of it goes into a journal file nobody reads. From the outside she
# looks up — the process really is there — and every answer is "I couldn't
# reach my Core". He has no way to tell a slow morning from a machine
# that has been restarting the same broken build for an hour.
#
# So: after this many crashes with nothing in between long enough to call
# stable, she says so, once, in words.
CRASH_LOOP_AT = 4
#: How short a life counts towards the loop. Longer than a start-up
#: failure, far shorter than a working session.
CRASH_LOOP_ALIVE_S = 60.0


def _journal(kind: str, subject: str, text: str) -> None:
    """Journal, but never at the cost of the loop.

    2026-08-27: the supervisor died between a Core exit and its next
    relaunch, leaving no line behind. Whatever the immediate cause, an
    immortal loop cannot have a mortal statement in it — and the first
    thing the loop does after every child exit is write to a file that a
    pull, a lock, or a full disk can refuse. Losing a log line is a bad
    day; losing the supervisor is the outage.
    """
    try:
        journal.append(kind, subject, text, actor=ACTOR)
    except Exception:
        pass


def _say_crash_loop(code: int, crashes: int) -> None:
    """Tell him the Core keeps dying. Never at the cost of the loop.

    One notice, deduplicated on the exit code, because a loop that
    notifies per crash is a second kind of storm. It is IMPORTANT on
    purpose: this is not routine reversible work, it is the thing that
    answers him being gone and staying gone.
    """
    try:
        from aletheia import notifications
        notifications.publish(
            "I keep restarting and failing",
            f"The part of me that answers you has died {crashes} times in a "
            f"row within a minute of starting (exit code {code}). I'm still "
            "trying. If this doesn't clear, the last thing that changed is "
            "the place to look.",
            priority="IMPORTANT", source="supervisor",
            about=notifications.FAILED,
            dedupe_key=f"core-crash-loop:{code}")
    except Exception:
        pass


def repair_registration() -> list[str]:
    """Put the always-on tasks back, without being asked. Never raises.

    `install` was the only thing that ever checked this, and `install` is
    something HE runs — so a task that had been disabled, or lost a
    trigger to a Windows update, stayed broken until the next time he
    happened to think of it. Nothing about normal operation should
    require him to remember a command.

    Registering for the current user needs no elevation, so she can
    simply fix it. Returns what was repaired, for the journal.
    """
    if os.name != "nt":
        return []
    fixed = []
    try:
        problems = autostart.doctor()
    except Exception:
        return []
    for spec in autostart.TASKS.values():
        if spec.name not in problems:
            continue
        try:
            ok, detail = autostart.install(spec)
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        _journal("event" if ok else "alert", "supervisor",
                 (f"repaired the always-on registration for {spec.name!r} "
                  f"({'; '.join(problems[spec.name])})") if ok else
                 f"could not repair {spec.name!r}: {detail}")
        if ok:
            fixed.append(spec.name)
    return fixed


def core_alive(port: int = DEFAULT_PORT) -> bool:
    """Is an Aletheia Core already answering on this machine?

    The same patient probe the Core uses before it binds: a 2 s timeout
    read a Core answering in 2.5 s (2026-09-21, under memory load) as
    "down", and the watchdog started a rival that crash-looped.
    """
    from aletheia.core import another_core_answering
    return another_core_answering(port)


#: The last lines the Core wrote to stderr before it died, kept so the
#: crash line in the journal can say WHY. Live 2026-09-24 the journal held
#: "Core died (exit 4294967295) after 85s" and nothing else: the Core's
#: stderr went to a console nobody was looking at (or, under the hidden
#: logon task, to nowhere), so a crash left no traceback anywhere on disk.
STDERR_TAIL_LINES = 80
CRASH_LOG_NAME = "core-last-crash.log"
_last_stderr: dict = {"lines": []}


def _tee_stderr(stream, keep: list[str]) -> None:
    """Echo the Core's stderr to ours and keep the tail. Never raises."""
    echo = getattr(sys, "stderr", None)
    try:
        for line in iter(stream.readline, ""):
            keep.append(line.rstrip("\r\n"))
            del keep[:-STDERR_TAIL_LINES]
            if echo is not None:
                try:
                    echo.write(line)
                    echo.flush()
                except Exception:
                    pass
    except Exception:
        pass


def _launch_core(cmd: list[str]) -> int:
    """Run the Core to exit, with its stderr TAILED as well as shown.

    stdout still inherits this console (started from start-aletheia.bat he
    is watching it); stderr is piped through a thread that echoes every line
    to our own stderr and keeps the last STDERR_TAIL_LINES for the crash
    line and the crash log.
    """
    import threading
    keep: list[str] = []
    proc = subprocess.Popen(cmd, cwd=str(REPO_ROOT), env=_child_env(),
                            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    pump = threading.Thread(target=_tee_stderr, args=(proc.stderr, keep), daemon=True)
    pump.start()
    code = proc.wait()
    pump.join(timeout=5.0)
    _last_stderr["lines"] = list(keep)
    return code


def last_crash_line() -> str:
    """The most telling line of the Core's last stderr: the exception if
    there was a traceback, else the last non-empty line, else nothing."""
    lines = [l.strip() for l in _last_stderr.get("lines") or [] if l.strip()]
    if not lines:
        return ""
    if any(l.startswith("Traceback") for l in lines):
        for line in reversed(lines):
            if not line.startswith(("File ", "Traceback", "^", "~")) and not line.startswith(" "):
                return line[:200]
    return lines[-1][:200]


def _write_crash_log(code: int, alive_s: float) -> str:
    """The tail on disk, in private state, overwritten each crash. Returns
    the path, or "" when there was nothing to write or nowhere to write it."""
    lines = _last_stderr.get("lines") or []
    if not lines:
        return ""
    try:
        from aletheia import stateio
        path = stateio.private_dir("logs") / CRASH_LOG_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        head = (f"# Core exit {code} after {alive_s:.0f}s at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"
                f" - last {len(lines)} stderr lines\n")
        path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
        return str(path)
    except Exception:
        return ""


def _crash_sentence(code: int, alive_s: float, backoff: float) -> str:
    said = f"Core died (exit {code}) after {alive_s:.0f}s"
    why = last_crash_line()
    if why:
        said += f" - its last words: {why}"
    log = _write_crash_log(code, alive_s)
    if log:
        said += f" (the tail is in {CRASH_LOG_NAME})"
    return said + f" — relaunching in {backoff:.0f}s"


def _child_env() -> dict:
    """The marker telling the Core a supervisor is waiting to relaunch it,
    so on a code update it may exit RESTART_EXIT_CODE instead of having to
    hand itself off (see core.main). Never set this by hand."""
    from aletheia import browser_reasoner
    # The Core is always-on: it must never inherit a foreground lease to
    # open the operator's signed-in ChatGPT, even when the supervisor was
    # itself started from a leased shell.
    return browser_reasoner.drop_lease({**os.environ, "ALETHEIA_SUPERVISED": "1"})


def run_forever(core_args: list[str] | None = None, launch=None,
                sleep=time.sleep, max_runs: int | None = None) -> int:
    """Relaunch the Core until a clean exit. `launch`/`sleep`/`max_runs`
    exist for tests; real life passes none of them."""
    if launch is None and core_alive():
        # a second supervisor must not fight the first for the port. This
        # is also what makes the watchdog trigger safe (autostart.py): a
        # trigger that fires while she is healthy costs one probe and one
        # exit, not a competing Aletheia.
        _journal("event", "supervisor",
                 "another Aletheia is already serving — this one exits")
        print("Aletheia is already running at http://127.0.0.1:8777/ — nothing to do.")
        return 0
    # A CLOSED WINDOW STAYS CLOSED. The watchdog trigger fires every five
    # minutes whatever else is true, so without this check "close her"
    # would mean "she is gone for up to five minutes" — which is not what
    # closing something means.
    if closed.is_closed():
        _journal("event", "supervisor", "closed — not starting")
        print("Aletheia is closed. `python -m aletheia.closed open` to change that.")
        return 0
    cmd = [sys.executable, "-m", "aletheia.core", *(core_args or [])]
    # proc: visible-by-design — the Core INHERITS this console on purpose.
    # Under the hidden logon task the parent is pythonw, so there is no
    # window either way; started from start-aletheia.bat the operator
    # deliberately opened a window to watch the Core, and hiding its output
    # there would be worse than the flashing boxes this rule exists to stop.
    launch = launch or (lambda: _launch_core(cmd))
    backoff = BACKOFF_START_S
    runs = 0
    crashes = 0
    _journal("event", "supervisor", "supervisor up — the Core is now persistent")
    # ...and while she is up, make sure the thing that brings her back is
    # still registered the way it has to be. `launch` is only ever passed
    # by a test, and a test must not shell out to Task Scheduler.
    if launch is None:
        repair_registration()
    while max_runs is None or runs < max_runs:
        runs += 1
        started = time.monotonic()
        try:
            code = launch()
        except KeyboardInterrupt:
            _journal("event", "supervisor", "stopped by operator")
            return 0
        except Exception as exc:
            # OSError spawning the child, a bad interpreter path, a
            # transient Windows failure: all of them are "the Core is not
            # running", which is the one thing this loop exists to fix.
            # Treat it as a crash and back off — never as a reason to stop.
            _journal("alert", "supervisor",
                     f"could not launch the Core ({type(exc).__name__}: {exc}) — "
                     f"retrying in {backoff:.0f}s")
            sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX_S)
            continue
        alive_s = time.monotonic() - started
        if closed.is_closed():
            # She was asked to close while running. Her exit is the answer,
            # not a crash to recover from.
            _journal("event", "supervisor", "closed by operator")
            return 0
        if code == 0:
            _journal("event", "supervisor", "Core exited cleanly — done")
            return 0
        if code == RESTART_EXIT_CODE:
            backoff = BACKOFF_START_S  # a self-update is health, not a crash
            crashes = 0
            _journal("event", "supervisor", "relaunching Core on updated code")
            continue
        if alive_s >= STABLE_AFTER_S:
            backoff = BACKOFF_START_S
        # A run that lasted a real length of time is a crash, not a loop.
        crashes = crashes + 1 if alive_s < CRASH_LOOP_ALIVE_S else 1
        if crashes == CRASH_LOOP_AT:
            _say_crash_loop(code, crashes)
        _journal("event", "supervisor", _crash_sentence(code, alive_s, backoff))
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
    return autostart.interpreter_for(autostart.TASKS["core"])


def _schtasks(argv: list[str]) -> tuple[int, str]:
    proc = proc_run(["schtasks", *argv], capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def install() -> int:
    """Register Aletheia's always-on tasks (Windows only, honest elsewhere).

    Registration used to happen here, as a bare at-logon task. That is the
    shape that failed on 2026-08-27: the supervisor aborted mid-morning,
    the operator never logged off, and the single trigger that could have
    revived her never fired again. The contract now lives in
    `aletheia.autostart` — repeating watchdog, unbounded, power-blind —
    and this command is its front door, for the Core and for the room
    voice, which had never had an installer in code at all.
    """
    if os.name != "nt":
        print("install needs Windows: it registers Scheduled Tasks running\n"
              f'  pythonw -m aletheia.supervisor  (cwd {REPO_ROOT})\n'
              f'  pythonw -m aletheia.voice_room  (cwd {REPO_ROOT})\n'
              "at logon AND every "
              f"{autostart.REPEAT_MINUTES} minutes as a watchdog. "
              "On this OS, run the supervisor directly instead.")
        return 1
    failures = 0
    for spec in autostart.TASKS.values():
        ok, detail = autostart.install(spec)
        print(("  ok  " if ok else "  --  ") + detail)
        if ok:
            _journal("event", "supervisor",
                     f"registered always-on task {spec.name!r} "
                     f"(logon + watchdog every {autostart.REPEAT_MINUTES}m)")
        else:
            failures += 1
    problems = autostart.doctor()
    for name, issues in problems.items():
        print(f"{name} still not always-on:")
        for issue in issues:
            print(f"  - {issue}")
    if failures or problems:
        return 1
    print(f"Aletheia is now permanent: she starts at logon, and any death is "
          f"repaired within {autostart.REPEAT_MINUTES} minutes.")
    if not core_alive():
        # start it NOW too — "returns at next logon" once meant a closed
        # setup window left the wall dead until a reboot
        code, out = _schtasks(["/Run", "/TN", TASK_NAME])
        print("Started in the background." if code == 0
              else f"Could not start it now ({out}) — the watchdog will.")
    return 0


def uninstall() -> int:
    if os.name != "nt":
        print("uninstall needs Windows (schtasks).")
        return 1
    failed = []
    for spec in autostart.TASKS.values():
        code, out = _schtasks(["/Delete", "/F", "/TN", spec.name])
        if code != 0 and "cannot find" not in out.lower():
            failed.append(f"{spec.name}: {out}")
        else:
            _journal("event", "supervisor", f"removed task {spec.name!r}")
    if failed:
        print("could not remove: " + "; ".join(failed))
        return 1
    print("Removed. Aletheia no longer starts by itself.")
    return 0


def status() -> int:
    """Is she up, and is the registration one she can survive inside?

    Two independent questions, deliberately. A task can hold the contract
    perfectly and the process still be dead this second; the Core can be
    answering right now on a registration that will not bring it back
    after the next sleep. Both get printed, and either being wrong is a
    nonzero exit — so this is usable from a check, not just by eye.
    """
    up = core_alive()
    age = liveness.age_seconds()
    beat = ("never" if age is None else f"{liveness.humanize(age)} ago")
    print(f"Core:      {'UP on 127.0.0.1:%d' % DEFAULT_PORT if up else 'DOWN'}"
          f"   (last heartbeat: {beat})")
    problems = autostart.doctor()
    if not problems:
        print(f"Autostart: always-on — logon + watchdog every "
              f"{autostart.REPEAT_MINUTES}m, unbounded, power-blind.")
    else:
        for name, issues in problems.items():
            print(f"Autostart: {name} is NOT always-on:")
            for issue in issues:
                print(f"  - {issue}")
        print("\nfix with: python -m aletheia.supervisor install")
    return 0 if (up and not problems) else 1


def main(argv: list[str] | None = None) -> int:
    # Children are scrubbed in _child_env(); scrub this process too, first
    # thing, so a supervisor started from a leased shell holds nothing to
    # hand on and nothing can read it in between.
    from aletheia import browser_reasoner
    browser_reasoner.drop_lease()
    ap = argparse.ArgumentParser(description="Keep the Aletheia Core running.")
    ap.add_argument("cmd", nargs="?", default="run",
                    choices=["run", "install", "uninstall", "status"])
    args = ap.parse_args(argv)
    journal.use_pc_journal()  # supervisor runs only on the PC
    if args.cmd == "install":
        return install()
    if args.cmd == "uninstall":
        return uninstall()
    if args.cmd == "status":
        return status()
    return run_forever()


if __name__ == "__main__":
    raise SystemExit(main())
