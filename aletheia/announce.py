"""Speaking first (Playbook §144, §19).

Aletheia can surface important facts proactively, but spoken room interruption is
stronger than a visual notification. After live use showed how quickly an
always-listening room can become noisy, spoken announcements are **opt-in by
default**. Notifications remain durable and visible whether or not this mouth is
enabled.

When explicitly enabled, the path stays deliberately quiet:

**It says almost nothing.** Only configured notification priorities are ever
spoken, at most MAX_PER_HOUR of them, never the same one twice, and never while
she is halted. Everything else stays where it was — visible, unspoken.

**It obeys the hour.** Nothing is spoken during quiet hours. A machine that wakes
someone at 3am to say a CI job went red has done more harm than the red job.

**It only ever re-says what is already recorded.** Every announcement comes from
a notification that already exists in the store, so anything spoken can be found
later in the journal and the notification center. She cannot announce something
that is not on the record (§30, §107).

The room microphone loop is intentionally NOT an announcement scheduler. A
future explicit scheduler/provider may call `speak_pending`; merely hearing room
noise must never trigger this module.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from aletheia import journal, notifications, policy, stateio

ACTOR = "aletheia-announce"

CONFIG_FILE = Path.home() / ".aletheia" / "announce.json"
SPOKEN_PRIORITIES = ("URGENT", "IMPORTANT")
MAX_PER_HOUR = 4
DEFAULT_CONFIG = {
    "version": 1,
    "enabled": False,
    "quiet_from": "22:00",
    "quiet_until": "07:30",
    "priorities": list(SPOKEN_PRIORITIES),
    "max_per_hour": MAX_PER_HOUR,
}


def state_path():
    return stateio.private_dir("announce") / "spoken.json"


def load_config(path: Path | None = None) -> dict:
    path = path or CONFIG_FILE
    if not path.exists():
        return dict(DEFAULT_CONFIG)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_CONFIG)  # a broken config is not a louder house
    return validate_config(value)


def validate_config(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("announce config must be an object")
    unknown = set(value) - set(DEFAULT_CONFIG)
    if unknown:
        raise ValueError(f"unknown announce config fields: {sorted(unknown)}")
    merged = {**DEFAULT_CONFIG, **value}
    if not isinstance(merged["enabled"], bool):
        raise ValueError("announce enabled must be boolean")
    for key in ("quiet_from", "quiet_until"):
        if not _parse_clock(merged[key]):
            raise ValueError(f"announce {key} must be HH:MM")
    priorities = merged["priorities"]
    if (not isinstance(priorities, list) or not priorities
            or any(p not in notifications.PRIORITIES for p in priorities)):
        raise ValueError("announce priorities must be known priority names")
    limit = merged["max_per_hour"]
    if type(limit) is not int or not 0 <= limit <= 30:
        raise ValueError("announce max_per_hour must be 0..30")
    return merged


def _parse_clock(value) -> tuple[int, int] | None:
    try:
        hour, minute = str(value).split(":")
        hour, minute = int(hour), int(minute)
    except (AttributeError, TypeError, ValueError):
        return None
    return (hour, minute) if 0 <= hour <= 23 and 0 <= minute <= 59 else None


def in_quiet_hours(config: dict, now: dt.datetime | None = None) -> bool:
    """Is it a time of day when nothing should be said out loud?

    Handles the overnight window, which is the normal shape: 22:00 to
    07:30 spans midnight, so "after start OR before end" is the test.
    """
    now = now or dt.datetime.now()
    start, end = _parse_clock(config["quiet_from"]), _parse_clock(config["quiet_until"])
    if not start or not end:
        return False
    minutes = now.hour * 60 + now.minute
    start_m, end_m = start[0] * 60 + start[1], end[0] * 60 + end[1]
    if start_m == end_m:
        return False
    if start_m < end_m:
        return start_m <= minutes < end_m
    return minutes >= start_m or minutes < end_m


def _spoken_state() -> dict:
    path = state_path()
    if not path.exists():
        return {"version": 1, "spoken": []}
    try:
        return stateio.read_json(path)
    except ValueError:
        return {"version": 1, "spoken": []}


def _record_spoken(notice_id: str, now: dt.datetime) -> None:
    state = _spoken_state()
    entries = [e for e in state.get("spoken", []) if isinstance(e, dict)]
    entries.append({"id": notice_id, "at": now.strftime("%Y-%m-%dT%H:%M:%SZ")})
    state["spoken"] = entries[-200:]
    try:
        stateio.write_json_atomic(state_path(), state)
    except Exception:
        pass


def _recent_count(now: dt.datetime) -> int:
    cutoff = now - dt.timedelta(hours=1)
    count = 0
    for entry in _spoken_state().get("spoken", []):
        try:
            when = dt.datetime.fromisoformat(str(entry["at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError, TypeError):
            continue
        if when.replace(tzinfo=None) >= cutoff.replace(tzinfo=None):
            count += 1
    return count


def _already_spoken(notice_id: str) -> bool:
    return any(e.get("id") == notice_id for e in _spoken_state().get("spoken", []))


def pending(config: dict | None = None,
            now: dt.datetime | None = None) -> list[dict]:
    """Notifications that should be said out loud right now. Usually none."""
    config = config if config is not None else load_config()
    now = now or dt.datetime.now()
    if not config["enabled"] or policy.halted():
        return []
    if in_quiet_hours(config, now):
        return []
    room = config["max_per_hour"] - _recent_count(now)
    if room <= 0:
        return []
    out = []
    for notice in notifications.all_notifications(state="UNREAD"):
        if notice.get("priority") not in config["priorities"]:
            continue
        if _already_spoken(notice["id"]):
            continue
        out.append(notice)
        if len(out) >= room:
            break
    return out


def sentence(notice: dict) -> str:
    """One notification as one spoken line."""
    from aletheia import speech
    title = speech.tidy(speech.strip_ids(str(notice.get("title", "")))).rstrip(".")
    body = speech.tidy(speech.strip_ids(str(notice.get("body", "")))).rstrip(".")
    if body and body.lower() not in title.lower():
        return f"{title}. {body}."
    return f"{title}." if title else ""


def speak_pending(speaker=None, *, config: dict | None = None,
                  now: dt.datetime | None = None) -> list[str]:
    """Say configured proactive lines and remember each before speaking it."""
    now = now or dt.datetime.now()
    said = []
    for notice in pending(config=config, now=now):
        line = sentence(notice)
        if not line:
            continue
        _record_spoken(notice["id"], now)
        try:
            if speaker is not None:
                speaker(line)
            said.append(line)
            journal.append("event", "announce",
                           f"said out loud: {line[:160]}", actor=ACTOR)
        except Exception as exc:
            journal.append("event", "announce",
                           f"could not speak ({type(exc).__name__}); "
                           "the notification is still unread", actor=ACTOR)
    return said


def set_enabled(on: bool, *, via: str = "operator-cli",
                path: Path | None = None) -> dict:
    """Turn speaking-first on or off, and say so in the journal.

    Wiring `speak_pending` into the room was only half the fix: the feature
    is off by default (correctly — she must not start talking at him
    unasked) and until this existed there was NO WAY to turn it on short of
    hand-writing `~/.aletheia/announce.json`. A capability with no
    on-switch is not opt-in, it is unavailable with extra steps.
    """
    path = path or CONFIG_FILE
    config = validate_config({**load_config(path), "enabled": bool(on)})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    journal.append("note", "announce",
                   f"speaking first {'enabled' if on else 'disabled'}", actor=via)
    return config


def set_quiet_hours(start: str, until: str, *, via: str = "operator-cli",
                    path: Path | None = None) -> dict:
    """The window in which she stays silent however urgent it is."""
    path = path or CONFIG_FILE
    config = validate_config({**load_config(path), "quiet_from": start,
                              "quiet_until": until})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    journal.append("note", "announce", f"quiet hours {start}-{until}", actor=via)
    return config


def spoken() -> str:
    """One line for the room or the phone."""
    config = load_config()
    if not config["enabled"]:
        return ("I don't speak up on my own. Say 'start telling me when "
                "something needs me' if you want me to.")
    waiting = len(pending(config))
    quiet = " I'm in quiet hours right now." if in_quiet_hours(config) else ""
    return (f"I speak up for {' and '.join(config['priorities']).lower()} things, "
            f"quiet {config['quiet_from']} to {config['quiet_until']}, at most "
            f"{config['max_per_hour']} an hour.{quiet} "
            f"{waiting} waiting.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="What Aletheia would say unprompted.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("pending", help="the lines she would say now; says nothing")
    sub.add_parser("on", help="let her speak up when something needs him")
    sub.add_parser("off", help="back to answering only when asked")
    quiet = sub.add_parser("quiet", help="set the hours she stays silent")
    quiet.add_argument("start")
    quiet.add_argument("until")
    args = ap.parse_args(argv)
    if args.cmd in ("on", "off"):
        print(json.dumps(set_enabled(args.cmd == "on"), indent=2))
        return 0
    if args.cmd == "quiet":
        print(json.dumps(set_quiet_hours(args.start, args.until), indent=2))
        return 0
    config = load_config()
    if args.cmd == "status":
        print(json.dumps({"config": config,
                          "quiet_now": in_quiet_hours(config),
                          "spoken_last_hour": _recent_count(dt.datetime.now()),
                          "waiting": len(pending(config))}, indent=2))
        return 0
    lines = [sentence(n) for n in pending(config)]
    for line in lines:
        print(line)
    print(f"{len(lines)} line(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
