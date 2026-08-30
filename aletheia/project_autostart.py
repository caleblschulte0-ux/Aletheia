r"""Windows Scheduled Task for the bounded project repair loop.

Unlike Core/voice, project repair is a batch cycle. It runs once at logon and
then every 30 minutes, with MultipleInstances=IgnoreNew so a slow model review
never overlaps the next cycle. The task has no shell script authority of its own;
it only invokes ``pythonw -m aletheia.project_loop once``.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from aletheia.autostart import _iso8601_minutes, _ps_quote, interpreter_for, TaskSpec
from aletheia.fleet import REPO_ROOT
from aletheia.proc import run as proc_run

TASK_NAME = "AletheiaProjects"
REPEAT_MINUTES = 30
EXECUTION_LIMIT_MINUTES = 20
SPEC = TaskSpec(
    key="projects", name=TASK_NAME, module="aletheia.project_loop once",
    description="Aletheia bounded project scan/review/PR cycle.",
)


def register_script(interpreter: str, repo_root: str | os.PathLike = REPO_ROOT,
                    repeat_minutes: int = REPEAT_MINUTES) -> str:
    action = (
        f"$a = New-ScheduledTaskAction -Execute {_ps_quote(interpreter)} "
        f"-Argument {_ps_quote('-m ' + SPEC.module)} "
        f"-WorkingDirectory {_ps_quote(str(repo_root))}"
    )
    triggers = (
        "$logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME; "
        "$repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) "
        f"-RepetitionInterval (New-TimeSpan -Minutes {int(repeat_minutes)})"
    )
    settings = (
        "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries "
        "-DontStopIfGoingOnBatteries -StartWhenAvailable -DontStopOnIdleEnd "
        f"-ExecutionTimeLimit (New-TimeSpan -Minutes {EXECUTION_LIMIT_MINUTES}) "
        "-MultipleInstances IgnoreNew -RestartCount 1 "
        "-RestartInterval (New-TimeSpan -Minutes 2)"
    )
    register = (
        f"Register-ScheduledTask -TaskName {_ps_quote(SPEC.name)} -Action $a "
        f"-Trigger $logon,$repeat -Settings $s -Description {_ps_quote(SPEC.description)} "
        "-Force | Out-Null"
    )
    return "; ".join(["$ErrorActionPreference = 'Stop'", action, triggers,
                      settings, register, "'registered'"])


def read_script() -> str:
    name = _ps_quote(TASK_NAME)
    missing = _ps_quote('{"exists": false}')
    return (
        "$ErrorActionPreference = 'SilentlyContinue'; "
        f"$t = Get-ScheduledTask -TaskName {name}; "
        f"if (-not $t) {{ {missing}; exit 0 }}; "
        f"$i = Get-ScheduledTaskInfo -TaskName {name}; "
        "[pscustomobject]@{ exists = $true; state = [string]$t.State; "
        "execute = [string]$t.Actions[0].Execute; arguments = [string]$t.Actions[0].Arguments; "
        "multiple_instances = [string]$t.Settings.MultipleInstances; "
        "allow_start_on_batteries = (-not $t.Settings.DisallowStartIfOnBatteries); "
        "keeps_running_on_batteries = (-not $t.Settings.StopIfGoingOnBatteries); "
        "start_when_available = [bool]$t.Settings.StartWhenAvailable; "
        "execution_time_limit = [string]$t.Settings.ExecutionTimeLimit; "
        "repetition_intervals = @($t.Triggers | ForEach-Object { [string]$_.Repetition.Interval } | "
        "Where-Object { $_ }); last_run = [string]$i.LastRunTime; "
        "last_result = [int64]$i.LastTaskResult } | ConvertTo-Json -Compress -Depth 4"
    )


def audit(actual: dict, repeat_minutes: int = REPEAT_MINUTES) -> list[str]:
    if not actual or not actual.get("exists"):
        return ["project loop is not registered"]
    problems = []
    if str(actual.get("state") or "").casefold() == "disabled":
        problems.append("project loop task is Disabled")
    if str(actual.get("multiple_instances") or "") != "IgnoreNew":
        problems.append("project loop must use MultipleInstances=IgnoreNew")
    if not actual.get("allow_start_on_batteries") or not actual.get("keeps_running_on_batteries"):
        problems.append("project loop task must remain available on battery")
    if not actual.get("start_when_available"):
        problems.append("project loop must StartWhenAvailable after sleep")
    args = str(actual.get("arguments") or "")
    if "-m aletheia.project_loop once" not in args:
        problems.append("project loop task points at the wrong module/command")
    intervals = [m for m in (_iso8601_minutes(v) for v in actual.get("repetition_intervals") or [])
                 if m is not None]
    if not intervals or min(intervals) > repeat_minutes:
        problems.append(f"project loop has no <= {repeat_minutes}m repeating trigger")
    return problems


def _powershell(script: str) -> tuple[int, str]:
    proc = proc_run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                    capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def read_task() -> dict:
    if os.name != "nt":
        return {"exists": False, "unsupported": "not Windows"}
    code, out = _powershell(read_script())
    if code != 0:
        return {"exists": False, "error": out[:400]}
    try:
        return json.loads(out or "{}")
    except json.JSONDecodeError:
        return {"exists": False, "error": "unparseable Scheduled Task state"}


def install(repo_root: str | os.PathLike = REPO_ROOT) -> tuple[bool, str]:
    if os.name != "nt":
        return False, "project-loop scheduling needs Windows"
    code, out = _powershell(register_script(interpreter_for(SPEC), repo_root))
    if code != 0:
        return False, out[:400]
    problems = audit(read_task())
    if problems:
        return False, "; ".join(problems)
    return True, f"{TASK_NAME}: every {REPEAT_MINUTES}m, non-overlapping"


def start() -> tuple[bool, str]:
    if os.name != "nt":
        return False, "project-loop scheduling needs Windows"
    code, out = _powershell(f"Start-ScheduledTask -TaskName {_ps_quote(TASK_NAME)}")
    return (code == 0, "started" if code == 0 else out[:400])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Install/check Aletheia's project-loop Scheduled Task.")
    ap.add_argument("cmd", choices=["install", "status", "start"])
    args = ap.parse_args(argv)
    if args.cmd == "install":
        ok, detail = install(); print(detail); return 0 if ok else 1
    if args.cmd == "start":
        ok, detail = start(); print(detail); return 0 if ok else 1
    actual = read_task()
    problems = audit(actual)
    print(json.dumps({"healthy": not problems, "problems": problems, "task": actual}, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
