"""Is Tailscale here, is it signed in, and what is this machine called?

Written 2026-09-02, ten minutes after the operator said "i linked
tailscale": his checklist still read `winget install Tailscale.Tailscale
(not installed yet)` and `apply phone-access` still printed
`<your-tailnet>`. Both were wrong, and wrong in the worst direction —
telling him to redo a step he had just done.

The cause was `shutil.which("tailscale")`: Tailscale's installer does not
put its directory on PATH, so the only check in the repo answered None on
a machine where the daemon was Running. A check that reports "missing" for
"installed but not on PATH" is not a check (§30, §106).

So: find the binary where Windows actually puts it as well as on PATH,
ask the daemon itself, and let the checklist print his real MagicDNS name
in the command he is about to run.

Read-only. Nothing here logs in, logs out, or changes the tailnet.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from aletheia.proc import run

BINARY = "tailscale"
# Where the Windows installer puts it, since it is not put on PATH.
KNOWN_PATHS = (
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale.exe",
    Path(os.environ.get("ProgramW6432", r"C:\Program Files")) / "Tailscale" / "tailscale.exe",
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Tailscale" / "tailscale.exe",
)
TIMEOUT_S = 10.0


def binary() -> str | None:
    """Full path to the tailscale CLI, or None."""
    found = shutil.which(BINARY)
    if found:
        return found
    for candidate in KNOWN_PATHS:
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return None


@dataclass(frozen=True)
class State:
    installed: bool
    running: bool = False          # the daemon is up AND signed in
    backend: str = ""              # Tailscale's own word: Running, NeedsLogin, Stopped…
    dns_name: str = ""             # laptop-x.tailnet.ts.net (no trailing dot)
    detail: str = ""

    @property
    def ready(self) -> bool:
        """Signed in and this machine has a name a certificate can be cut for."""
        return self.running and bool(self.dns_name)


def state(runner=None) -> State:
    """What Tailscale is actually doing on this machine, right now."""
    path = binary()
    if not path:
        return State(False, detail="the tailscale CLI is not installed")
    runner = runner or run
    try:
        proc = runner([path, "status", "--json"], capture_output=True, text=True,
                      timeout=TIMEOUT_S)
    except Exception as exc:      # a broken CLI is not a missing one
        return State(True, detail=f"tailscale status failed: {type(exc).__name__}")
    raw = (getattr(proc, "stdout", "") or "").strip()
    if getattr(proc, "returncode", 1) != 0 or not raw:
        detail = (getattr(proc, "stderr", "") or "").strip()[:120]
        return State(True, detail=detail or "tailscale status returned nothing")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return State(True, detail="tailscale status returned invalid JSON")
    backend = str(payload.get("BackendState") or "")
    self_node = payload.get("Self") or {}
    name = str(self_node.get("DNSName") or "").rstrip(".")
    if not name:
        domains = payload.get("CertDomains") or []
        name = str(domains[0]) if domains else ""
    running = backend == "Running"
    return State(True, running=running, backend=backend, dns_name=name,
                 detail=f"signed in as {name}" if running and name
                 else f"installed; backend is {backend or 'unknown'}")


def cert_command(current: State | None = None) -> str:
    """The `tailscale cert` line to run, with his real machine name when
    it is knowable and an honest placeholder when it is not."""
    current = current or state()
    return f"tailscale cert {current.dns_name or '<this-machine>.<your-tailnet>.ts.net'}"
