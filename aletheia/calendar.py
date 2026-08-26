"""Provider-neutral calendar model and deterministic availability engine.

Phase 14 needs reliable time reasoning before any Google/Outlook adapter is
trusted. This module handles aware datetimes, conflicts, buffers, work windows,
and free-slot calculation entirely locally. It does not claim a live provider.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from aletheia.fleet import REPO_ROOT
from aletheia.stateio import read_json, safe_id, utcnow, write_json_atomic

CALENDAR_DIR = REPO_ROOT / "state" / "calendar" / "events"


def parse_time(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid datetime {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("calendar datetimes must include a timezone offset")
    return parsed


def _path(event_id: str) -> Path:
    return CALENDAR_DIR / f"{safe_id(event_id, name='event id')}.json"


def validate(event: dict) -> None:
    for key in ("version", "id", "title", "start", "end", "created_at", "updated_at"):
        if key not in event:
            raise ValueError(f"event missing {key}")
    if event["version"] != 1:
        raise ValueError("unsupported event version")
    safe_id(event["id"], name="event id")
    start, end = parse_time(event["start"]), parse_time(event["end"])
    if end <= start:
        raise ValueError("event end must be after start")
    attendees = event.get("attendees", [])
    if not isinstance(attendees, list) or any(not isinstance(x, str) or not x for x in attendees):
        raise ValueError("attendees must be non-empty strings")


def save(event: dict) -> dict:
    validate(event)
    write_json_atomic(_path(event["id"]), event)
    return event


def create(event_id: str, title: str, start: str, end: str, *,
           attendees: list[str] | None = None, location: str | None = None,
           source: str = "local") -> dict:
    path = _path(event_id)
    if path.exists():
        raise FileExistsError(f"event {event_id!r} already exists")
    now = utcnow()
    event = {
        "version": 1, "id": event_id, "title": title.strip(), "start": start, "end": end,
        "attendees": attendees or [], "source": source, "created_at": now, "updated_at": now,
    }
    if location:
        event["location"] = location
    return save(event)


def all_events() -> list[dict]:
    if not CALENDAR_DIR.is_dir():
        return []
    out = []
    for path in CALENDAR_DIR.glob("*.json"):
        try:
            event = read_json(path); validate(event); out.append(event)
        except ValueError:
            continue
    return sorted(out, key=lambda e: parse_time(e["start"]))


def overlaps(a_start: dt.datetime, a_end: dt.datetime, b_start: dt.datetime, b_end: dt.datetime) -> bool:
    return a_start < b_end and b_start < a_end


def conflicts(start: str, end: str, *, events: list[dict] | None = None,
              buffer_before: int = 0, buffer_after: int = 0) -> list[dict]:
    a, b = parse_time(start), parse_time(end)
    if b <= a:
        raise ValueError("end must be after start")
    pad_before, pad_after = dt.timedelta(minutes=buffer_before), dt.timedelta(minutes=buffer_after)
    out = []
    for event in all_events() if events is None else events:
        e_start = parse_time(event["start"]) - pad_before
        e_end = parse_time(event["end"]) + pad_after
        if overlaps(a, b, e_start, e_end):
            out.append(event)
    return out


def free_slots(day: dt.date, *, duration_minutes: int, timezone: str,
               work_start: dt.time = dt.time(9, 0), work_end: dt.time = dt.time(17, 0),
               events: list[dict] | None = None, buffer_minutes: int = 0,
               step_minutes: int = 15) -> list[tuple[str, str]]:
    if duration_minutes <= 0 or step_minutes <= 0 or buffer_minutes < 0:
        raise ValueError("durations/step must be positive and buffer non-negative")
    tz = ZoneInfo(timezone)
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aletheia local calendar model")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_new = sub.add_parser("new"); p_new.add_argument("id"); p_new.add_argument("title"); p_new.add_argument("start"); p_new.add_argument("end")
    p_free = sub.add_parser("free"); p_free.add_argument("day"); p_free.add_argument("--minutes", type=int, default=30); p_free.add_argument("--tz", required=True)
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
