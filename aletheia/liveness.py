"""Liveness — proof that Aletheia was ON, and a number for how long she wasn't.

Rule zero applied to uptime. The 2026-08-27 outage was not that the Core
died; processes die. It is that NOTHING NOTICED: the supervisor went with
it, so no line reached the journal, the wall kept rendering the pulse it
already had, and the operator learned about it six hours later by asking.
A personal OS whose defining property is being there cannot discover its
own absence by conversation.

So the Core stamps a heartbeat every beat. Anything may then ask "is she
up?" without probing a port, and — the part that matters — the NEXT start
reads the stamp it left behind, measures the gap it just came back from,
and says so in the journal and on the event bus. Downtime stops being a
silence and becomes a fact with a duration attached, which watchers and
the proactive rules can act on like any other event.

Private by default (`state/private/`): a heartbeat is PC run-truth, and
the repo already learned what committing one every beat costs — 193
heartbeat pushes to main in a single day.
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from aletheia import stateio

# How long a heartbeat stays believable. The Core beats every
# SYNC_INTERVAL_S (60s); three missed beats is a process that is gone,
# not a process that is busy.
STALE_AFTER_S = 300.0

# Below this, a gap is a restart, not an outage: a self-update relaunch
# costs a few seconds and should not cry wolf in the journal every time
# a merge lands on main.
OUTAGE_AFTER_S = 180.0


def _parse_ts(text: str) -> dt.datetime:
    """UTC datetime from a stamp Aletheia wrote. Tolerates the two shapes
    the stores use (second and microsecond precision), both 'Z'-suffixed."""
    parsed = dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def heartbeat_path() -> Path:
    return stateio.private_dir("liveness") / "heartbeat.json"


# When THIS process came up, set once by `note_start`. Module state
# rather than a file read on every beat: the Core is the only thing that
# beats (core.py:384, and note_start at startup), so the process that
# stamps the heartbeat is always the process the stamp is about.
_STARTED_AT: str | None = None


def beat(actor: str = "core", port: int | None = None,
         path: Path | None = None) -> dict:
    """Stamp 'I am alive, now'. Never raises: a heartbeat that could not be
    written must not take down the process it exists to watch over."""
    entry = {"ts": stateio.utcnow(), "actor": actor, "pid": os.getpid()}
    if port is not None:
        entry["port"] = port
    if _STARTED_AT:
        entry["started_at"] = _STARTED_AT
    try:
        stateio.write_json_atomic(path or heartbeat_path(), entry)
    except Exception:
        pass
    return entry


def last(path: Path | None = None) -> dict | None:
    p = path or heartbeat_path()
    if not p.exists():
        return None
    try:
        return stateio.read_json(p)
    except ValueError:
        return None  # a torn or hand-edited heartbeat is no heartbeat


def age_seconds(now: str | None = None, path: Path | None = None) -> float | None:
    """Seconds since the last heartbeat, or None if there has never been one."""
    entry = last(path)
    if not entry or not entry.get("ts"):
        return None
    try:
        then = _parse_ts(entry["ts"])
        current = _parse_ts(now or stateio.utcnow())
    except (ValueError, TypeError):
        return None
    return max(0.0, (current - then).total_seconds())


def uptime_seconds(now: str | None = None,
                   path: Path | None = None) -> float | None:
    """How long she has been up, or None when she cannot honestly say.

    The mirror of the outage measurement above, and it was missing: she
    could tell him to the second how long she had been GONE and had no
    answer at all for how long she had been here. "How long have you been
    up" is the first thing anybody asks a machine whose whole promise is
    being on.

    None, never a guess, in three cases that all mean "I do not know":
    no heartbeat at all, a heartbeat from before this was recorded, and a
    STALE one — a stamp from a process that has since died says when it
    started, not that it is still running.
    """
    entry = last(path)
    started = (entry or {}).get("started_at")
    if not started:
        return None
    if not alive(now, path):
        return None
    try:
        current = _parse_ts(now or stateio.utcnow())
        return max(0.0, (current - _parse_ts(started)).total_seconds())
    except (ValueError, TypeError):
        return None


def spoken_duration(seconds: float) -> str:
    """`humanize` writes "3.2h", which is right on a wall and wrong in a
    room. This is the same number as something a person would say."""
    if seconds < 90:
        whole = int(round(seconds))
        return "a second" if whole == 1 else f"{whole} seconds"
    minutes = seconds / 60.0
    if minutes < 60:
        whole = int(round(minutes))
        return "a minute" if whole == 1 else f"{whole} minutes"
    hours = minutes / 60.0
    if hours < 24:
        whole = int(hours)
        rest = int(round((hours - whole) * 60))
        if rest in (0, 60):
            whole += 1 if rest == 60 else 0
            return "an hour" if whole == 1 else f"{whole} hours"
        return (f"{whole} hour{'s' if whole != 1 else ''} "
                f"and {rest} minute{'s' if rest != 1 else ''}")
    days = hours / 24.0
    whole = int(days)
    return "a day" if whole == 1 else f"{whole} days"


def alive(now: str | None = None, path: Path | None = None) -> bool:
    age = age_seconds(now, path)
    return age is not None and age < STALE_AFTER_S


def humanize(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds / 60:.0f}m"
    if seconds < 172800:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


def note_start(actor: str = "core", port: int | None = None,
               now: str | None = None, path: Path | None = None) -> float | None:
    """Call this ONCE as the process comes up, before the first beat.

    Returns the outage it just ended (seconds), or None when the gap was a
    restart rather than an absence. An outage is journaled and emitted on
    the bus so the same watcher/proactive path that handles mail and fleet
    health also handles 'she was gone'.
    """
    gap = age_seconds(now, path)
    global _STARTED_AT
    _STARTED_AT = now or stateio.utcnow()
    beat(actor=actor, port=port, path=path)
    if gap is None or gap < OUTAGE_AFTER_S:
        return None
    pretty = humanize(gap)
    try:
        from aletheia import journal
        journal.append("alert", "core:liveness",
                       f"Aletheia was down for {pretty} — back up now "
                       f"({gap:.0f}s since the last heartbeat).",
                       actor="aletheia-liveness")
    except Exception:
        pass
    try:
        from aletheia import events
        events.emit("core.outage_ended", "core:aletheia",
                    f"Aletheia was down for {pretty}", source="core",
                    attributes={"downtime_seconds": round(gap, 1),
                                "downtime_human": pretty})
    except Exception:
        pass  # the journal line above is the record; the bus is best-effort
    return gap
