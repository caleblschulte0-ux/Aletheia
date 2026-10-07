"""His stopwatch: one, started and stopped by voice, read back on demand.

"Start a stopwatch" went to the planner (2026-10-07), and a timer is not
the same thing: a timer counts down to a reminder, a stopwatch counts up
until he says stop. One small record in private state - when it started,
and when it stopped if it has - is all of it.
"""
from __future__ import annotations

import datetime as dt

from aletheia import stateio

ACTIONS = frozenset({"start", "stop", "reset"})


def _path():
    return stateio.private_dir("stopwatch") / "stopwatch.json"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _load() -> dict:
    try:
        return stateio.read_json(_path()) or {}
    except Exception:
        return {}


def _save(value: dict) -> None:
    stateio.write_json_atomic(_path(), value)


def _at(value) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def duration_words(seconds: float) -> str:
    """"1 hour, 4 minutes and 9 seconds" - what a person says."""
    seconds = int(round(max(0.0, seconds)))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    for n, unit in ((hours, "hour"), (minutes, "minute"), (secs, "second")):
        if n:
            parts.append(f"{n} {unit}{'' if n == 1 else 's'}")
    if not parts:
        return "less than a second"
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def elapsed(now: dt.datetime | None = None) -> tuple[float | None, bool]:
    """(seconds on the stopwatch, still running). (None, False) when there is none."""
    held = _load()
    started = _at(held.get("started_at"))
    if started is None:
        return None, False
    stopped = _at(held.get("stopped_at"))
    end = stopped or (now or _now())
    return (end - started).total_seconds(), stopped is None


def act(action: str, now: dt.datetime | None = None) -> str:
    """Start, stop or reset it; the sentence says what happened."""
    now = now or _now()
    if action not in ACTIONS:
        raise ValueError(f"stopwatch action must be one of {sorted(ACTIONS)}")
    seconds, running = elapsed(now)
    if action == "start":
        if running:
            return f"Your stopwatch is already running - {duration_words(seconds)} so far."
        _save({"started_at": now.isoformat()})
        return "Stopwatch started."
    if action == "stop":
        if seconds is None:
            return "There's no stopwatch running. Say \"start a stopwatch\" to start one."
        if not running:
            return f"Your stopwatch is already stopped at {duration_words(seconds)}."
        held = _load()
        held["stopped_at"] = now.isoformat()
        _save(held)
        return f"Stopped at {duration_words(seconds)}."
    if seconds is None:
        return "There's no stopwatch to reset."
    _save({})
    return f"Stopwatch reset - it had {duration_words(seconds)} on it."


def spoken(now: dt.datetime | None = None) -> str:
    """What the stopwatch says right now. Never raises."""
    try:
        seconds, running = elapsed(now)
    except Exception:
        return "I couldn't read the stopwatch just now."
    if seconds is None:
        return "There's no stopwatch running. Say \"start a stopwatch\" to start one."
    if running:
        return f"Your stopwatch is at {duration_words(seconds)}, and still running."
    return f"Your stopwatch stopped at {duration_words(seconds)}."
