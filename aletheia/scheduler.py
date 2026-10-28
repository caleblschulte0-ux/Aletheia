"""Durable, execution-agnostic schedules with idempotent due receipts.

The scheduler decides *when* work is due; it never grants authority. A due
command must still pass through the existing capability and policy gates.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aletheia.stateio import create_json_exclusive, private_dir, read_json, safe_id, utcnow, write_json_atomic

SCHEDULE_DIR = private_dir("schedules") / "definitions"
RECEIPT_DIR = private_dir("schedules") / "receipts"
KINDS = {"once", "interval", "daily", "weekly", "monthly", "yearly"}


def _path(schedule_id: str) -> Path:
    return SCHEDULE_DIR / f"{safe_id(schedule_id, name='schedule id')}.json"


def _parse(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid schedule time {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("schedule times must be timezone-aware")
    return parsed


def _clock(value: str) -> tuple[int, int]:
    try:
        hour, minute = map(int, value.split(":"))
        dt.time(hour, minute)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("time must be HH:MM") from exc
    return hour, minute


def validate(spec: dict) -> None:
    for key in ("version", "id", "kind", "command", "created_at", "enabled"):
        if key not in spec:
            raise ValueError(f"schedule missing {key}")
    if spec["version"] != 1 or spec["kind"] not in KINDS:
        raise ValueError("unsupported schedule version/kind")
    safe_id(spec["id"], name="schedule id")
    if not isinstance(spec["enabled"], bool):
        raise ValueError("enabled must be boolean")
    if not isinstance(spec["command"], dict) or not isinstance(spec["command"].get("kind"), str):
        raise ValueError("command must be an object with kind")
    kind = spec["kind"]
    if kind == "once":
        if "at" not in spec:
            raise ValueError("once schedule requires at")
        _parse(spec["at"])
    elif kind == "interval":
        if not isinstance(spec.get("every_minutes"), int) or spec["every_minutes"] < 1:
            raise ValueError("interval requires every_minutes >= 1")
        if "anchor" not in spec:
            raise ValueError("interval schedule requires anchor")
        _parse(spec["anchor"])
        if "hours" in spec:
            # "Every hour during work hours": only the occurrences inside the
            # window, in his timezone, on the weekdays named (all when none are).
            hours = spec["hours"]
            if not isinstance(hours, list) or len(hours) != 2 or _clock(hours[0]) >= _clock(hours[1]):
                raise ValueError("interval hours must be [start HH:MM, end HH:MM] with start before end")
            try:
                ZoneInfo(spec.get("timezone", ""))
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError("interval hours require a valid timezone") from exc
            days = spec.get("weekdays")
            if days is not None and (not isinstance(days, list) or not days
                                     or any(type(d) is not int or d not in range(7) for d in days)):
                raise ValueError("interval weekdays must be a non-empty list of 0..6")
    else:
        try:
            ZoneInfo(spec.get("timezone", ""))
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("daily/weekly schedule requires valid timezone") from exc
        _clock(spec.get("time", ""))
        if kind in ("monthly", "yearly"):
            day = spec.get("monthday")
            if type(day) is not int or not 1 <= day <= 31:
                raise ValueError(f"{kind} monthday must be 1..31")
        if kind == "yearly":
            # "Every year on our anniversary" (2026-10-28): one day of one month.
            month = spec.get("month")
            if type(month) is not int or not 1 <= month <= 12:
                raise ValueError("yearly month must be 1..12")
        if kind == "weekly":
            days = spec.get("weekdays")
            if not isinstance(days, list) or not days or any(type(d) is not int or d not in range(7) for d in days):
                raise ValueError("weekly weekdays must be a non-empty list of 0..6")
            if len(set(days)) != len(days):
                raise ValueError("weekly weekdays must be unique")


def save(spec: dict) -> dict:
    validate(spec)
    write_json_atomic(_path(spec["id"]), spec)
    return spec


def load(schedule_id: str) -> dict:
    spec = read_json(_path(schedule_id))
    validate(spec)
    return spec


def create(schedule_id: str, command: dict, *, kind: str, at: str | None = None,
           every_minutes: int | None = None, anchor: str | None = None,
           timezone: str | None = None, time: str | None = None,
           weekdays: list[int] | None = None, monthday: int | None = None,
           hours: list[str] | None = None, month: int | None = None) -> dict:
    if _path(schedule_id).exists():
        raise FileExistsError(f"schedule {schedule_id!r} exists")
    spec = {"version": 1, "id": safe_id(schedule_id, name="schedule id"), "kind": kind,
            "command": command, "enabled": True, "created_at": utcnow(), "updated_at": utcnow()}
    if at is not None:
        spec["at"] = at
    if every_minutes is not None:
        spec["every_minutes"] = every_minutes
    if anchor is not None:
        spec["anchor"] = anchor
    if timezone is not None:
        spec["timezone"] = timezone
    if time is not None:
        spec["time"] = time
    if weekdays is not None:
        spec["weekdays"] = weekdays
    if monthday is not None:
        spec["monthday"] = monthday
    if month is not None:
        spec["month"] = month
    if hours is not None:
        spec["hours"] = hours
    return save(spec)


def _month_day(year: int, month: int, monthday: int) -> dt.date:
    """That day of that month, or its last day when the month is shorter:
    "the 31st of every month" is the 30th in April, never skipped."""
    import calendar
    return dt.date(year, month, min(monthday, calendar.monthrange(year, month)[1]))


def _months_from(day: dt.date, offset: int) -> tuple[int, int]:
    index = day.year * 12 + day.month - 1 + offset
    return index // 12, index % 12 + 1


def _in_hours(spec: dict, at: dt.datetime) -> bool:
    """Whether an interval occurrence falls inside its window, if it has one."""
    if "hours" not in spec:
        return True
    local = at.astimezone(ZoneInfo(spec["timezone"]))
    days = spec.get("weekdays")
    if days is not None and local.weekday() not in days:
        return False
    start, end = _clock(spec["hours"][0]), _clock(spec["hours"][1])
    return start <= (local.hour, local.minute) <= end


def _next_window_start(spec: dict, after: dt.datetime) -> dt.datetime:
    """The first moment of the window that opens after `after`."""
    tz = ZoneInfo(spec["timezone"])
    local = after.astimezone(tz)
    hour, minute = _clock(spec["hours"][0])
    days = spec.get("weekdays")
    for offset in range(0, 8):
        day = local.date() + dt.timedelta(days=offset)
        if days is not None and day.weekday() not in days:
            continue
        start = dt.datetime.combine(day, dt.time(hour, minute), tzinfo=tz)
        if start > local:
            return start.astimezone(dt.timezone.utc)
    return after + dt.timedelta(days=8)


def set_enabled(schedule_id: str, enabled: bool) -> dict:
    spec = load(schedule_id)
    spec["enabled"] = bool(enabled)
    spec["updated_at"] = utcnow()
    return save(spec)


def occurrence_at_or_before(spec: dict, now: dt.datetime) -> dt.datetime | None:
    """The latest occurrence due by `now`. A repeating schedule never owes one
    from before it existed: "remind me every day at 8 to take my vitamins",
    said at 10 pm, went off at once for the 8 am that had already passed
    (2026-10-28), and a monthly one made on the 28th went off for the 1st."""
    at = _occurrence_at_or_before(spec, now)
    # A one-off has its own time, and an interval its own anchor to start from.
    if at is None or spec["kind"] in ("once", "interval"):
        return at
    try:
        born = _parse(str(spec.get("created_at") or ""))
    except ValueError:
        return at
    return None if at < born else at


def _occurrence_at_or_before(spec: dict, now: dt.datetime) -> dt.datetime | None:
    validate(spec)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not spec["enabled"]:
        return None
    kind = spec["kind"]
    if kind == "once":
        at = _parse(spec["at"])
        return at if at <= now else None
    if kind == "interval":
        anchor = _parse(spec["anchor"])
        if anchor > now:
            return None
        seconds = (now - anchor).total_seconds()
        period = spec["every_minutes"] * 60
        latest = anchor + dt.timedelta(seconds=(int(seconds) // period) * period)
        return latest if _in_hours(spec, latest) else None
    tz = ZoneInfo(spec["timezone"])
    local_now = now.astimezone(tz)
    hour, minute = _clock(spec["time"])
    if kind == "yearly":
        for year in (local_now.year, local_now.year - 1):
            candidate = dt.datetime.combine(_month_day(year, spec["month"], spec["monthday"]),
                                            dt.time(hour, minute), tzinfo=tz)
            if candidate <= local_now:
                return candidate.astimezone(dt.timezone.utc)
        return None
    if kind == "monthly":
        for offset in range(0, -3, -1):
            year, month = _months_from(local_now.date(), offset)
            candidate = dt.datetime.combine(_month_day(year, month, spec["monthday"]),
                                            dt.time(hour, minute), tzinfo=tz)
            if candidate <= local_now:
                return candidate.astimezone(dt.timezone.utc)
        return None
    for offset in range(0, 8):
        candidate_day = local_now.date() - dt.timedelta(days=offset)
        if kind == "weekly" and candidate_day.weekday() not in spec["weekdays"]:
            continue
        candidate = dt.datetime.combine(candidate_day, dt.time(hour, minute), tzinfo=tz)
        if candidate <= local_now:
            return candidate.astimezone(dt.timezone.utc)
    return None


def _skipped(spec: dict, occurrence: dt.datetime) -> bool:
    """One occurrence he asked to skip ("skip tomorrow's pill reminder"):
    the schedule stays on and only that one does not go off."""
    stamp = occurrence.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M")
    return stamp in [str(s)[:16] for s in spec.get("skips") or []]


def skip_once(schedule_id: str, occurrence: dt.datetime) -> dict:
    """Mark one coming occurrence of a repeating schedule as skipped."""
    spec = load(schedule_id)
    stamp = occurrence.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M")
    skips = [str(s) for s in spec.get("skips") or [] if str(s)[:16] != stamp]
    spec["skips"] = (skips + [stamp])[-20:]
    spec["updated_at"] = utcnow()
    return save(spec)


def unskip(schedule_id: str) -> dict:
    spec = load(schedule_id)
    spec.pop("skips", None)
    spec["updated_at"] = utcnow()
    return save(spec)


def next_occurrence(spec: dict, after: dt.datetime) -> dt.datetime | None:
    at = _next_occurrence(spec, after)
    for _ in range(20):
        if at is None or not _skipped(spec, at):
            return at
        at = _next_occurrence(spec, at)
    return at


def _next_occurrence(spec: dict, after: dt.datetime) -> dt.datetime | None:
    validate(spec)
    if after.tzinfo is None or after.utcoffset() is None:
        raise ValueError("after must be timezone-aware")
    if not spec["enabled"]:
        return None
    if spec["kind"] == "once":
        at = _parse(spec["at"])
        return at if at > after else None
    if spec["kind"] == "interval":
        anchor = _parse(spec["anchor"])
        period = dt.timedelta(minutes=spec["every_minutes"])
        def following(moment: dt.datetime) -> dt.datetime:
            if moment < anchor:
                return anchor
            periods = int((moment - anchor).total_seconds() // period.total_seconds()) + 1
            return anchor + periods * period
        at = following(after)
        for _ in range(16):
            if _in_hours(spec, at):
                return at
            # Outside the window: the first one once it opens again.
            at = following(_next_window_start(spec, at) - dt.timedelta(microseconds=1))
        return None
    tz = ZoneInfo(spec["timezone"])
    local = after.astimezone(tz)
    hour, minute = _clock(spec["time"])
    if spec["kind"] == "yearly":
        for year in (local.year, local.year + 1):
            candidate = dt.datetime.combine(_month_day(year, spec["month"], spec["monthday"]),
                                            dt.time(hour, minute), tzinfo=tz)
            if candidate > local:
                return candidate.astimezone(dt.timezone.utc)
        return None
    if spec["kind"] == "monthly":
        for offset in range(0, 3):
            year, month = _months_from(local.date(), offset)
            candidate = dt.datetime.combine(_month_day(year, month, spec["monthday"]),
                                            dt.time(hour, minute), tzinfo=tz)
            if candidate > local:
                return candidate.astimezone(dt.timezone.utc)
        return None
    for offset in range(0, 8):
        day = local.date() + dt.timedelta(days=offset)
        if spec["kind"] == "weekly" and day.weekday() not in spec["weekdays"]:
            continue
        candidate = dt.datetime.combine(day, dt.time(hour, minute), tzinfo=tz)
        if candidate > local:
            return candidate.astimezone(dt.timezone.utc)
    return None


def _receipt_path(schedule_id: str, occurrence: dt.datetime) -> Path:
    stamp = occurrence.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return RECEIPT_DIR / safe_id(schedule_id, name="schedule id") / f"{stamp}.json"


def claim_due(spec: dict, *, now: dt.datetime | None = None) -> dict | None:
    now = now or dt.datetime.now(dt.timezone.utc)
    occurrence = occurrence_at_or_before(spec, now)
    if occurrence is None or _skipped(spec, occurrence):
        return None
    path = _receipt_path(spec["id"], occurrence)
    receipt = {"version": 1, "schedule_id": spec["id"], "occurrence": occurrence.isoformat(),
               "claimed_at": utcnow(), "command": spec["command"]}
    try:
        create_json_exclusive(path, receipt)
    except FileExistsError:
        return None
    return receipt


def all_schedules() -> list[dict]:
    if not SCHEDULE_DIR.is_dir():
        return []
    out = []
    for path in sorted(SCHEDULE_DIR.glob("*.json")):
        try:
            out.append(load(path.stem))
        except ValueError:
            continue
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aletheia durable schedules")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("due")
    args = ap.parse_args(argv)
    if args.cmd == "list":
        for spec in all_schedules():
            print(f"{spec['id']:28} {spec['kind']:8} {spec['command'].get('kind')}")
    else:
        for spec in all_schedules():
            receipt = claim_due(spec)
            if receipt:
                print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
