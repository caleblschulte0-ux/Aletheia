"""The microphone is OFF until he turns it on, every time.

The operator, 2026-09-07, in his own words: *"i don't want an always on
microphone. And if I do want that, that'll be a button I press within
Aletheia once she's turned on. That it should not be a default
feature."*

Until now `AletheiaVoice` was a logon-triggered scheduled task with a
five-minute watchdog, so a microphone in his room opened itself when he
signed in and reopened itself if it ever stopped. That is a default this
system had no business having, whatever it was listening for.

WHAT THIS CHANGES. The room process still exists and the watchdog still
exists — pressing the button should start listening in seconds, not
after a reboot. What changes is that `voice_room` opens no microphone
unless this switch says he turned it on.

THE SWITCH DOES NOT SURVIVE A RESTART, and that is the point rather than
an oversight. A durable "on" would be the always-on microphone again by
a slower route: he enables it once in October and every logon after that
opens the mic by itself. So the record carries the BOOT it was made in,
and a flag from a previous boot is stale and reads as off. "On until you
close her or restart the machine" is a promise that can be kept.

FAIL CLOSED, EVERYWHERE. An unreadable file, an unparseable record, a
boot id this platform will not give up — every one of them reads as OFF.
The safe mistake for a microphone is not listening.

THE ASYMMETRY, which is the same one the kill switch uses. Turning it ON
is deliberate and cannot be done by voice: the microphone is off, so
there is nothing to hear the request, and a microphone that can enable
itself by being spoken to is not a microphone that is off. Turning it
OFF is allowed from anywhere, always, including by voice while she is
listening — because a stop that needs a ceremony arrives too late.

Machine-local and private, like `closed`: this is a fact about a room in
his house at a moment, not a fact about the fleet, and it must never
sync to another machine and open a microphone he is not standing next to.
"""
from __future__ import annotations

import argparse
import sys

from aletheia import journal, stateio

ACTOR = "aletheia-ears"


def marker():
    return stateio.private_dir("runtime") / "listening.json"


def _boot_id() -> str:
    """Something that changes when the machine restarts, or "" if unknown.

    Unknown is not a problem to route around: the caller treats it as a
    stale flag, so a platform that will not say when it booted gets a
    microphone that stays off. That is the correct direction to fail.
    """
    try:
        if sys.platform == "win32":
            import ctypes
            millis = ctypes.windll.kernel32.GetTickCount64()
            import time
            # Rounded to ten seconds: the arithmetic drifts by a tick or
            # two between calls and an exact match would call every read
            # a different boot.
            return str(int((time.time() - millis / 1000.0) // 10))
        with open("/proc/uptime", encoding="utf-8") as fh:
            import time
            up = float(fh.read().split()[0])
            return str(int((time.time() - up) // 10))
    except Exception:
        return ""


def state() -> dict:
    """The record as written, or an empty one. Never raises."""
    try:
        value = stateio.read_json(marker())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def listening() -> bool:
    """Is the microphone allowed to be open right now?

    Cheap and safe to call in a loop. Every failure is a False: an
    unreadable marker, a record from a previous boot, a platform that
    cannot tell us which boot this is.
    """
    record = state()
    if not record.get("on"):
        return False
    boot = _boot_id()
    if not boot:
        return False                      # cannot prove it is this boot
    return record.get("boot") == boot


# What the room is started as. `pythonw` so no console window opens in
# his face — the same way the supervisor runs everything else.
ROOM_MODULE = "aletheia.voice_room"


def room_is_running() -> bool:
    """Is a listener process alive? Never raises."""
    try:
        import subprocess
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -Filter \"Name like 'pythonw%'\" "
             "| Where-Object { $_.CommandLine -match 'voice_room' } "
             "| Measure-Object).Count"],
            capture_output=True, text=True, timeout=15)
        return (out.stdout or "0").strip().splitlines()[-1].strip() not in ("", "0")
    except Exception:
        return False


def start_room() -> tuple[bool, str]:
    """Start the listener. (started, what happened) — never raises.

    A button that sets a flag and starts nothing is not a button: on a
    machine where the scheduled task is disabled, pressing MIC would
    have written a file and produced silence.
    """
    import subprocess
    import sys
    from pathlib import Path
    if room_is_running():
        return True, "already listening"
    try:
        pythonw = str(Path(sys.executable).with_name("pythonw.exe"))
        if not Path(pythonw).exists():
            pythonw = sys.executable
        subprocess.Popen(
            [pythonw, "-m", ROOM_MODULE],
            cwd=str(stateio.REPO_ROOT) if hasattr(stateio, "REPO_ROOT") else None,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True)
        return True, "listener started"
    except Exception as exc:
        # Honest: the flag is on and the process is not, which he needs
        # to be told rather than left to discover by talking to a room
        # that is not listening.
        return False, f"could not start the listener ({type(exc).__name__})"


def stop_room() -> tuple[bool, str]:
    """Stop the listener. Always allowed, never raises."""
    try:
        import subprocess
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name like 'pythonw%'\" "
             "| Where-Object { $_.CommandLine -match 'voice_room' } "
             "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
            capture_output=True, text=True, timeout=20)
        return True, "listener stopped"
    except Exception as exc:
        return False, f"could not stop the listener ({type(exc).__name__})"


def turn_on(via: str = "operator") -> dict:
    """He pressed the button. Deliberate, and only for this boot.

    `via` is recorded because "who opened the microphone" is exactly the
    question worth being able to answer later.
    """
    boot = _boot_id()
    record = {"on": True, "boot": boot, "at": stateio.utcnow(),
              "via": str(via)[:80]}
    stateio.write_json_atomic(marker(), record)
    journal.append("event", "voice:ears",
                   f"microphone opened by {via} (this boot only)", actor=ACTOR)
    return record


def turn_off(via: str = "operator") -> dict:
    """Always allowed, from anywhere, including while she is listening."""
    record = {"on": False, "at": stateio.utcnow(), "via": str(via)[:80]}
    stateio.write_json_atomic(marker(), record)
    journal.append("event", "voice:ears", f"microphone closed by {via}",
                   actor=ACTOR)
    return record


def spoken() -> str:
    """Read out loud, or shown on the wall. Says WHY, not just which way."""
    if listening():
        record = state()
        who = record.get("via") or "you"
        return f"The microphone is on — you opened it ({who}). It closes when " \
               "she closes or the machine restarts."
    record = state()
    if record.get("on"):
        # On, but from a previous boot: say so rather than "off", because
        # he did turn it on and has a right to know why it is not.
        return ("The microphone is off — you opened it before the machine "
                "restarted, and it does not carry over.")
    return "The microphone is off. Nothing is listening until you turn it on."


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="The room microphone. Off unless you turn it on.")
    ap.add_argument("cmd", nargs="?", choices=("on", "off", "status"),
                    default="status")
    ap.add_argument("--via", default="cli")
    args = ap.parse_args(argv)
    if args.cmd == "on":
        turn_on(via=args.via)
        print(spoken())
        print("Start the room now with: pythonw -m aletheia.voice_room")
    elif args.cmd == "off":
        turn_off(via=args.via)
        print(spoken())
    else:
        print(spoken())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
