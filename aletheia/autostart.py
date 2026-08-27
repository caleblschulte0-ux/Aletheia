r"""Autostart — the registration that makes Aletheia permanent (Playbook §109).

The supervisor keeps the Core alive for as long as the SUPERVISOR lives.
This module is the layer underneath: what keeps the supervisor itself
alive, across the deaths no parent process can survive — being killed,
the machine sleeping, a power transition, a logon that never comes.

Found live on the operator's PC, 2026-08-27. Aletheia had been registered
as a Windows task with `StopIfGoingOnBatteries`, `DisallowStartIfOnBatteries`,
`ExecutionTimeLimit PT72H`, `RestartCount 0`, and a single at-logon
trigger. At 07:42 the supervisor process aborted (`LastTaskResult`
0x8007042B). He never logged off, so the only trigger that could have
brought her back never fired, and NOTHING was listening for the next six
hours. Every one of those settings is defensible for a batch job and
wrong for a thing whose entire promise is being there.

An always-on task, as a contract:

  * repeating   — a trigger every REPEAT_MINUTES, forever, so any death is
                  repaired in minutes instead of at the next logon
  * unbounded   — no execution time limit; it is meant to never end
  * power-blind — starts on battery, and is not stopped by unplugging
  * restarting  — Windows itself retries a start that fails
  * singular    — MultipleInstances=IgnoreNew, which is what turns the
                  repeating trigger into a WATCHDOG: while the task is
                  still running the extra triggers are ignored, so the
                  repetition can only ever start a REPLACEMENT

`audit()` holds that contract as a pure function over the settings a task
actually has, so `python -m aletheia.autostart doctor` can say which of
them a real machine is currently violating — and so this is testable off
Windows, where CI runs.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from aletheia.fleet import REPO_ROOT
from aletheia.proc import run as proc_run

REPEAT_MINUTES = 5
RESTART_COUNT = 3
RESTART_INTERVAL_MINUTES = 1
# PT0S is how Task Scheduler spells "no limit"; an absent value means the
# same thing. Anything else is a clock counting down to a kill.
UNBOUNDED_LIMITS = {"", "pt0s", "p0d", "none"}


@dataclass(frozen=True)
class TaskSpec:
    key: str
    name: str
    module: str
    description: str


TASKS: dict[str, TaskSpec] = {
    "core": TaskSpec(
        key="core", name="Aletheia", module="aletheia.supervisor",
        description="Aletheia Core supervisor - keeps the personal OS running."),
    "voice": TaskSpec(
        key="voice", name="AletheiaVoice", module="aletheia.voice_room",
        description="Aletheia room voice - local wake word listener."),
}


def _ps_quote(value: str) -> str:
    """A PowerShell single-quoted literal. Doubling is the only escape."""
    return "'" + str(value).replace("'", "''") + "'"


def register_script(spec: TaskSpec, interpreter: str,
                    repo_root: str | os.PathLike = REPO_ROOT,
                    repeat_minutes: int = REPEAT_MINUTES) -> str:
    """The PowerShell that registers `spec` as an always-on task.

    Pure: builds the text, runs nothing. `Register-ScheduledTask` for the
    CURRENT user needs no elevation, which is why this is the primary path
    and `schtasks /Create /SC ONLOGON` (which does) is not.

    The watchdog trigger is a `-Once` trigger with a repetition interval,
    registered alongside the logon trigger. Task Scheduler gives a
    repetition with no explicit duration an indefinite one, which is
    exactly the intent: forever.
    """
    action = (f"$a = New-ScheduledTaskAction -Execute {_ps_quote(interpreter)} "
              f"-Argument {_ps_quote('-m ' + spec.module)} "
              f"-WorkingDirectory {_ps_quote(str(repo_root))}")
    triggers = (
        "$logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME; "
        "$watchdog = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) "
        f"-RepetitionInterval (New-TimeSpan -Minutes {int(repeat_minutes)})"
    )
    settings = (
        "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries "
        "-DontStopIfGoingOnBatteries -StartWhenAvailable -DontStopOnIdleEnd "
        "-ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew "
        f"-RestartCount {int(RESTART_COUNT)} "
        f"-RestartInterval (New-TimeSpan -Minutes {int(RESTART_INTERVAL_MINUTES)})"
    )
    register = (
        f"Register-ScheduledTask -TaskName {_ps_quote(spec.name)} -Action $a "
        f"-Trigger $logon,$watchdog -Settings $s "
        f"-Description {_ps_quote(spec.description)} -Force | Out-Null"
    )
    return "; ".join(["$ErrorActionPreference = 'Stop'", action, triggers,
                      settings, register, "'registered'"])


def read_script(name: str) -> str:
    """PowerShell that reports one task's live settings as compact JSON."""
    quoted = _ps_quote(name)
    missing = _ps_quote('{"exists": false}')
    return (
        "$ErrorActionPreference = 'SilentlyContinue'; "
        f"$t = Get-ScheduledTask -TaskName {quoted}; "
        f"if (-not $t) {{ {missing}; exit 0 }}; "
        f"$i = Get-ScheduledTaskInfo -TaskName {quoted}; "
        "[pscustomobject]@{ exists = $true; state = [string]$t.State; "
        "execute = [string]$t.Actions[0].Execute; "
        "arguments = [string]$t.Actions[0].Arguments; "
        "allow_start_on_batteries = (-not $t.Settings.DisallowStartIfOnBatteries); "
        "keeps_running_on_batteries = (-not $t.Settings.StopIfGoingOnBatteries); "
        "execution_time_limit = [string]$t.Settings.ExecutionTimeLimit; "
        "restart_count = [int64]$t.Settings.RestartCount; "
        "multiple_instances = [string]$t.Settings.MultipleInstances; "
        "start_when_available = [bool]$t.Settings.StartWhenAvailable; "
        "repetition_intervals = @($t.Triggers | ForEach-Object "
        "{ [string]$_.Repetition.Interval } | Where-Object { $_ }); "
        "last_run = [string]$i.LastRunTime; "
        "last_result = [int64]$i.LastTaskResult } | ConvertTo-Json -Compress -Depth 4"
    )


def _iso8601_minutes(value: str) -> float | None:
    """Minutes in a Task Scheduler duration like 'PT5M' / 'PT1H30M' / 'P1D'."""
    text = str(value or "").strip().upper()
    if not text.startswith("P"):
        return None
    days = hours = minutes = seconds = 0.0
    number = ""
    in_time = False
    for ch in text[1:]:
        if ch == "T":
            in_time = True
            number = ""
        elif ch.isdigit() or ch == ".":
            number += ch
        else:
            try:
                amount = float(number or 0)
            except ValueError:
                return None
            number = ""
            if ch == "D":
                days = amount
            elif ch == "H" and in_time:
                hours = amount
            elif ch == "M":
                # 'M' before the T separator is months; after it, minutes
                if in_time:
                    minutes = amount
                else:
                    days += amount * 30
            elif ch == "S" and in_time:
                seconds = amount
            elif ch == "Y":
                days += amount * 365
            elif ch == "W":
                days += amount * 7
    return days * 1440 + hours * 60 + minutes + seconds / 60


def audit(actual: dict, repeat_minutes: int = REPEAT_MINUTES) -> list[str]:
    """Every way this task's live settings break the always-on contract.

    Pure, so the contract is testable without a Task Scheduler. An empty
    list means the registration is one Aletheia can actually live inside.
    """
    if not actual or not actual.get("exists"):
        return ["not registered at all - nothing brings Aletheia back"]
    problems: list[str] = []
    if str(actual.get("state", "")).lower() == "disabled":
        problems.append("the task is Disabled")
    if not actual.get("allow_start_on_batteries"):
        problems.append("DisallowStartIfOnBatteries: she will not start on battery")
    if not actual.get("keeps_running_on_batteries"):
        problems.append("StopIfGoingOnBatteries: unplugging the machine kills her")
    limit = str(actual.get("execution_time_limit") or "")
    if limit.strip().lower() not in UNBOUNDED_LIMITS:
        problems.append(f"ExecutionTimeLimit {limit}: Windows kills her after that long")
    if int(actual.get("restart_count") or 0) < 1:
        problems.append("RestartCount 0: Windows will not retry a failed start")
    if str(actual.get("multiple_instances") or "") != "IgnoreNew":
        problems.append(
            f"MultipleInstances {actual.get('multiple_instances')!r}: the watchdog "
            "trigger must be ignored while she runs, not start a second Aletheia")
    if not actual.get("start_when_available"):
        problems.append("StartWhenAvailable off: a trigger missed while asleep is lost")
    intervals = [m for m in (_iso8601_minutes(v)
                             for v in (actual.get("repetition_intervals") or []))
                 if m is not None]
    if not intervals:
        problems.append("no repeating trigger: one death and she is gone until the "
                        "next logon - this is exactly the 2026-08-27 outage")
    elif min(intervals) > repeat_minutes:
        problems.append(f"slowest watchdog {min(intervals):.0f}m > {repeat_minutes}m")
    return problems


def _powershell(script: str) -> tuple[int, str]:
    proc = proc_run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                    capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def read_task(name: str) -> dict:
    """Live settings for one task, or {'exists': False}."""
    if os.name != "nt":
        return {"exists": False, "unsupported": "not Windows"}
    code, out = _powershell(read_script(name))
    if code != 0:
        return {"exists": False, "error": out[:400]}
    try:
        return json.loads(out or "{}")
    except json.JSONDecodeError:
        return {"exists": False, "error": f"unparseable task query: {out[:200]}"}


def interpreter_for(spec: TaskSpec) -> str:
    r"""The windowless interpreter to register.

    Deliberately NOT `shutil.which('pythonw')`: PATH order is not version
    order, and on this very PC an old C:\Python39 sits ahead of the 3.12
    Aletheia needs. The running interpreter is 3.10+ by construction (the
    package refuses to import otherwise), so its own sibling is the one
    safe answer.
    """
    exe = Path(sys.executable)
    sibling = exe.with_name("pythonw.exe")
    return str(sibling if sibling.exists() else exe)


def install(spec: TaskSpec, repo_root: str | os.PathLike = REPO_ROOT) -> tuple[bool, str]:
    if os.name != "nt":
        return False, ("needs Windows: would register the always-on task "
                       f"{spec.name!r} running -m {spec.module} in {repo_root}")
    code, out = _powershell(register_script(spec, interpreter_for(spec), repo_root))
    if code != 0:
        return False, out[:400]
    return True, f"{spec.name}: always-on (watchdog every {REPEAT_MINUTES}m)"


def doctor(specs: dict[str, TaskSpec] | None = None) -> dict[str, list[str]]:
    """What each task is currently getting wrong. {} means all healthy."""
    out = {}
    for spec in (specs or TASKS).values():
        problems = audit(read_task(spec.name))
        if problems:
            out[spec.name] = problems
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Register Aletheia's always-on Windows tasks, or audit them.")
    ap.add_argument("cmd", nargs="?", default="doctor",
                    choices=["doctor", "install", "show"])
    ap.add_argument("--only", choices=sorted(TASKS), help="just one task")
    args = ap.parse_args(argv)
    specs = {args.only: TASKS[args.only]} if args.only else TASKS

    if args.cmd == "show":
        for spec in specs.values():
            print(f"== {spec.name}")
            print(json.dumps(read_task(spec.name), indent=2, sort_keys=True))
        return 0
    if args.cmd == "install":
        failed = 0
        for spec in specs.values():
            ok, detail = install(spec)
            print(("  ok  " if ok else "  --  ") + detail)
            failed += 0 if ok else 1
        if failed:
            return 1
    problems = doctor(specs)
    if not problems:
        print("always-on: every task holds the contract "
              f"(watchdog every {REPEAT_MINUTES}m, unbounded, power-blind).")
        return 0
    for name, issues in problems.items():
        print(f"{name}:")
        for issue in issues:
            print(f"  - {issue}")
    print("")
    print("fix with: python -m aletheia.autostart install")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
