"""Subprocess helpers that never flash a console window on Windows.

Why this module exists (2026-08-27, found by the operator, not by a test):
the Core's sync loop shells out to `git` every 60 seconds. Under the
supervisor's hidden scheduled task the parent is `pythonw.exe`, which has
no console — so Windows gave every short-lived child its OWN console
window. The operator watched black boxes titled
`C:\\Program Files\\Git\\cmd\\git.exe` pop up on his desktop all day and
reasonably asked what had infected his computer.

Ambient software must be *ambient*. Any helper process Aletheia spawns
for its own bookkeeping — git, schtasks, powershell — goes through
`run()` here, which adds CREATE_NO_WINDOW on Windows and is a plain
passthrough everywhere else.

NOT for processes the operator is meant to see or interact with (the
Core itself under a visible console, a browser, an app being driven).
Those inherit their parent's console on purpose.
"""
from __future__ import annotations

import os
import subprocess

# 0x08000000 on Windows; 0 elsewhere so the flag is a harmless no-op.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def hidden_flags(existing: int = 0) -> int:
    """Creation flags for a background helper. CREATE_NO_WINDOW is mutually
    exclusive with DETACHED_PROCESS/CREATE_NEW_CONSOLE, so a caller that
    already asked for one of those keeps what it has."""
    exclusive = (getattr(subprocess, "DETACHED_PROCESS", 0)
                 | getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
    if existing & exclusive:
        return existing
    return existing | NO_WINDOW


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """subprocess.run for Aletheia's own bookkeeping — windowless on Windows."""
    kwargs["creationflags"] = hidden_flags(kwargs.get("creationflags", 0))
    return subprocess.run(cmd, **kwargs)


def popen(cmd: list[str], **kwargs) -> subprocess.Popen:
    """Interruptible background helper, with the same no-window guarantee.

    Use this when the caller must retain the child handle (for example, so
    room speech can be cut off when the operator talks over it).
    """
    kwargs["creationflags"] = hidden_flags(kwargs.get("creationflags", 0))
    return subprocess.Popen(cmd, **kwargs)


def run_tree(cmd: list[str], timeout_s: float, *, input: str | None = None,
             **kwargs) -> subprocess.CompletedProcess:
    """Windowless run with a time limit that takes the WHOLE tree down.

    `subprocess.run(timeout=)` kills only the direct child; a python process
    driving Chrome leaves Chrome behind, still holding the browser profile.
    Raises subprocess.TimeoutExpired after the tree is gone.

    `input` is written to the child's stdin, the way `subprocess.run` takes
    it: a prompt too long for a Windows command line travels there.
    """
    kwargs.setdefault("stdout", subprocess.PIPE)
    kwargs.setdefault("stderr", subprocess.PIPE)
    kwargs.setdefault("text", True)
    kwargs.setdefault("encoding", "utf-8")
    kwargs.setdefault("errors", "replace")
    if input is not None:
        kwargs.setdefault("stdin", subprocess.PIPE)
    kwargs["creationflags"] = hidden_flags(kwargs.get("creationflags", 0))
    child = subprocess.Popen(cmd, **kwargs)
    try:
        out, err = child.communicate(input=input, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        kill_tree(child.pid)
        try:
            child.communicate(timeout=15)
        except Exception:
            pass
        raise
    return subprocess.CompletedProcess(cmd, child.returncode, out, err)


def pid_alive(pid, *, needle: str = "") -> bool | None:
    """Is `pid` a running process? True, False, or None when it cannot tell.

    WITHOUT A SUBPROCESS. Live 2026-09-13 the browser lock asked `tasklist`
    this question once a second from a windowless process, every waiter got
    its own console tab, and he woke to Windows Terminal opening and closing
    them three and four at a time until he restarted the machine. A question
    this cheap is answered by the operating system directly.

    `needle`, when given, must appear in the process's command line. Windows
    reuses pids, so "some process has that number" is not "our campaign is
    still running": a pid whose command line does not name what we started
    is reported dead.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    try:
        import psutil
    except Exception:
        psutil = None
    if psutil is not None:
        try:
            process = psutil.Process(pid)
            if process.status() == psutil.STATUS_ZOMBIE:
                return False
            if needle:
                try:
                    return needle in " ".join(process.cmdline())
                except (psutil.AccessDenied, psutil.ZombieProcess):
                    return None
            return True
        except psutil.NoSuchProcess:
            return False
        except Exception:
            return None
    if needle:
        return None                     # alive or not, it cannot be named
    if os.name == "nt":
        try:
            import ctypes
            kernel = ctypes.windll.kernel32
            handle = kernel.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            try:
                code = ctypes.c_ulong()
                if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return None
                return code.value == 259                     # STILL_ACTIVE
            finally:
                kernel.CloseHandle(handle)
        except Exception:
            return None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return None


def kill_tree(pid) -> None:
    """Kill a process AND everything it started. Never raises.

    Killing only the python process leaves its Chrome behind, still holding
    the profile, and the next session to open that profile dies with
    TargetClosedError — which is how one hung submit became a night of
    failures.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return
    try:
        import psutil
        try:
            parent = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return
        for child in parent.children(recursive=True):
            try:
                child.kill()
            except Exception:
                pass
        try:
            parent.kill()
        except Exception:
            pass
        return
    except ImportError:
        pass
    except Exception:
        return
    try:
        if os.name == "nt":
            run(["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True, timeout=20)
        else:
            os.kill(pid, 9)
    except Exception:
        pass
