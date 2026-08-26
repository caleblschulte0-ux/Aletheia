"""Provider-neutral calendar model and deterministic availability engine.

Phase 14 needs reliable time reasoning before any Google/Outlook adapter is
trusted. This module handles aware datetimes, conflicts, buffers, movable-event
metadata, work windows and multi-day free-slot search locally. It does not claim
a live provider.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

CALENDAR_DIR = private_dir("calendar") / "events"
EVENT_STATUSES = {"CONFIRMED", "TENTATIVE", "CANCELLED"}


def parse_time(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid datetime {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("calendar datetimes must include a timezone offset")
    return parsed


def _path(event_id: str) -> Path:
    return CALENDAR_DIR / f"{safe_id(event_id, name='event id')}.json"


def validate(event: dict) -> None:
    for key in ("version", "id", "title", "start", "end", "created_at", "updated_at", "status"):
        if key not in event:
            raise ValueError(f"event missing {key}")
    if event["version"] != 1:
        raise ValueError("unsupported event version")
    safe_id(event["id"], name="event id")
    if not isinstance(event["title"], str) or not event["title"].strip():
        raise ValueError("event title is required")
    start, end = parse_time(event["start"]), parse_time(event["end"])
    if end <= start:
        raise ValueError("event end must be after start")
    if event["status"] not in EVENT_STATUSES:
        raise ValueError("invalid event status")
    attendees = event.get("attendees", [])
    if not isinstance(attendees, list) or any(not isinstance(x, str) or not x.strip() for x in attendees):
        raise ValueError("attendees must be non-empty strings")
    if len(set(attendees)) != len(attendees):
        raise ValueError("attendees must be unique")
    if "priority" in event and (type(event["priority"]) is not int or not 1 <= event["priority"] <= 5):
        raise ValueError("priority must be 1..5")
    if "movable" in event and not isinstance(event["movable"], bool):
        raise ValueError("movable must be boolean")


def save(event: dict) -> dict:
    validate(event)
    write_json_atomic(_path(event["id"]), event)
    return event


def create(event_id: str, title: str, start: str, end: str, *,
           attendees: list[str] | None = None, location: str | None = None,
           source: str = "local", status: str = "CONFIRMED", priority: int = 3,
           movable: bool = False) -> dict:
    path = _path(event_id)
    if path.exists():
        raise FileExistsError(f"event {event_id!r} already exists")
    now = utcnow()
    event = {
        "version": 1, "id": safe_id(event_id, name="event id"), "title": title.strip(),
        "start": start, "end": end, "attendees": attendees or [], "source": source,
        "status": status, "priority": priority, "movable": movable,
        "created_at": now, "updated_at": now,
    }
    if location:
        event["location"] = location
    return save(event)


def load(event_id: str) -> dict:
    event = read_json(_path(event_id))
    validate(event)
    return event


def update(event_id: str, **changes: object) -> dict:
    allowed = {"title", "start", "end", "attendees", "location", "status", "priority", "movable", "source"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"unsupported event fields: {sorted(unknown)}")
    event = load(event_id)
    event.update(changes)
    event["updated_at"] = utcnow()
    return save(event)


def cancel(event_id: str) -> dict:
    return update(event_id, status="CANCELLED")


def all_events() -> list[dict]:
    if not CALENDAR_DIR.is_dir():
        return []
    out = []
    for path in CALENDAR_DIR.glob("*.json"):
        try:
            out.append(load(path.stem))
        except ValueError:
            continue
    return sorted(out, key=lambda e: parse_time(e["start"]).astimezone(dt.timezone.utc))


def overlaps(a_start: dt.datetime, a_end: dt.datetime, b_start: dt.datetime, b_end: dt.datetime) -> bool:
    return a_start < b_end and b_start < a_end


def conflicts(start: str, end: str, *, events: list[dict] | None = None,
              buffer_before: int = 0, buffer_after: int = 0,
              include_tentative: bool = True) -> list[dict]:
    a, b = parse_time(start), parse_time(end)
    if b <= a:
        raise ValueError("end must be after start")
    if buffer_before < 0 or buffer_after < 0:
        raise ValueError("buffers must be non-negative")
    pad_before, pad_after = dt.timedelta(minutes=buffer_before), dt.timedelta(minutes=buffer_after)
    out = []
    for event in all_events() if events is None else events:
        validate(event)
        if event["status"] == "CANCELLED" or (event["status"] == "TENTATIVE" and not include_tentative):
            continue
        e_start = parse_time(event["start"]) - pad_before
        e_end = parse_time(event["end"]) + pad_after
        if overlaps(a, b, e_start, e_end):
            out.append(event)
    return out


def free_slots(day: dt.date, *, duration_minutes: int, timezone: str,
               work_start: dt.time = dt.time(9, 0), work_end: dt.time = dt.time(17, 0),
               events: list[dict] | None = None, buffer_minutes: int = 0,
               step_minutes: int = 15, weekdays: set[int] | None = None) -> list[tuple[str, str]]:
    if duration_minutes <= 0 or step_minutes <= 0 or buffer_minutes < 0:
        raise ValueError("durations/step must be positive and buffer non-negative")
    try:
        tz = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown timezone {timezone!r}") from exc
    if weekdays is not None and day.weekday() not in weekdays:
        return []
    window_start = dt.datetime.combine(day, work_start, tzinfo=tz)
    window_end = dt.datetime.combine(day, work_end, tzinfo=tz)
    if window_end <= window_start:
        raise ValueError("work_end must be after work_start")
    duration = dt.timedelta(minutes=duration_minutes)
    step = dt.timedelta(minutes=step_minutes)
    slots = []
    cursor = window_start
    source = all_events() if events is None else events
    while cursor + duration <= window_end:
        end = cursor + duration
        if not conflicts(cursor.isoformat(), end.isoformat(), events=source,
                         buffer_before=buffer_minutes, buffer_after=buffer_minutes):
            slots.append((cursor.isoformat(), end.isoformat()))
        cursor += step
    return slots


def find_slots(start_day: dt.date, end_day: dt.date, *, duration_minutes: int,
               timezone: str, work_start: dt.time = dt.time(9, 0),
               work_end: dt.time = dt.time(17, 0), events: list[dict] | None = None,
               buffer_minutes: int = 0, step_minutes: int = 15,
               weekdays: set[int] | None = None, limit: int = 20) -> list[tuple[str, str]]:
    if end_day < start_day:
        raise ValueError("end_day must be on or after start_day")
    if limit < 1:
        raise ValueError("limit must be positive")
    source = all_events() if events is None else events
    out: list[tuple[str, str]] = []
    day = start_day
    while day <= end_day and len(out) < limit:
        out.extend(free_slots(day, duration_minutes=duration_minutes, timezone=timezone,
                              work_start=work_start, work_end=work_end, events=source,
                              buffer_minutes=buffer_minutes, step_minutes=step_minutes,
                              weekdays=weekdays))
        day += dt.timedelta(days=1)
    return out[:limit]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aletheia local calendar model")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_new = sub.add_parser("new")
    p_new.add_argument("id"); p_new.add_argument("title"); p_new.add_argument("start"); p_new.add_argument("end")
    p_free = sub.add_parser("free")
    p_free.add_argument("day"); p_free.add_argument("--minutes", type=int, default=30); p_free.add_argument("--tz", required=True)
    sub.add_parser("list")
    args = ap.parse_args(argv)
    if args.cmd == "new":
        print(json.dumps(create(args.id, args.title, args.start, args.end), indent=2))
    elif args.cmd == "free":
        for start, end in free_slots(dt.date.fromisoformat(args.day), duration_minutes=args.minutes, timezone=args.tz):
            print(start, "->", end)
    else:
        for event in all_events():
            print(event["start"], event["title"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
