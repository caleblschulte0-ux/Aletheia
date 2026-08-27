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
