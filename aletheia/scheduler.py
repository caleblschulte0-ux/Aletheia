"""Durable, execution-agnostic schedules with idempotent due receipts.

The scheduler decides *when* work is due; it never decides whether that work is
authorized. Executing a due item must still pass through the existing policy
and capability gates. Separating those concerns prevents a timer from becoming
an authority bypass.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from aletheia.fleet import REPO_ROOT
from aletheia.stateio import create_json_exclusive, read_json, safe_id, utcnow, write_json_atomic

SCHEDULE_DIR = REPO_ROOT / "state" / "schedules" / "definitions"
RECEIPT_DIR = REPO_ROOT / "state" / "schedules" / "receipts"


def _path(schedule_id: str) -> Path:
    return SCHEDULE_DIR / f"{safe_id(schedule_id, name='schedule id')}.json"


def _parse(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("schedule times must be timezone-aware")
    return parsed


def validate(spec: dict) -> None:
    for key in ("version", "id", "kind", "command", "created_at", "enabled"):
        if key not in spec:
            raise ValueError(f"schedule missing {key}")
    if spec["version"] != 1 or spec["kind"] not in {"once", "interval", "daily", "weekly"}:
        raise ValueError("unsupported schedule version/kind")
    safe_id(spec["id"], name="schedule id")
    if not isinstance(spec["command"], dict) or not spec["command"].get("kind"):
        raise ValueError("command must be an object with kind")
    if spec["kind"] == "once":
        _parse(spec["at"])
    elif spec["kind"] == "interval":
        if not isinstance(spec.get("every_minutes"), int) or spec["every_minutes"] < 1:
            raise ValueError("interval requires every_minutes >= 1")
        _parse(spec["anchor"])
    else:
        ZoneInfo(spec["timezone"])
        hour, minute = map(int, spec["time"].split(":"))
        dt.time(hour, minute)
        if spec["kind"] == "weekly":
            days = spec.get("weekdays")
            if not isinstance(days, list) or not days or any(d not in range(7) for d in days):
                raise ValueError("weekly weekdays must be a non-empty list of 0..6")


def save(spec: dict) -> dict:
    validate(spec); write_json_atomic(_path(spec["id"]), spec); return spec


def create(schedule_id: str, command: dict, *, kind: str, at: str | None = None,
           every_minutes: int | None = None, anchor: str | None = None,
           timezone: str | None = None, time: str | None = None,
           weekdays: list[int] | None = None) -> dict:
    if _path(schedule_id).exists():
        raise FileExistsError(f"schedule {schedule_id!r} exists")
    spec = {"version": 1, "id": schedule_id, "kind": kind, "command": command,
            "enabled": True, "created_at": utcnow()}
    if at is not None: spec["at"] = at
    if every_minutes is not None: spec["every_minutes"] = every_minutes
    if anchor is not None: spec["anchor"] = anchor
    if timezone is not None: spec["timezone"] = timezone
    if time is not None: spec["time"] = time
    if weekdays is not None: spec["weekdays"] = weekdays
    return save(spec)


def occurrence_at_or_before(spec: dict, now: dt.datetime) -> dt.datetime | None:
    validate(spec)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not spec["enabled"]:
        return None
    kind = spec["kind"]
    if kind == "once":
        at = _parse(spec["at"]); return at if at <= now else None
    if kind == "interval":
        anchor = _parse(spec["anchor"])
        if anchor > now: return None
        minutes = int((now - anchor).total_seconds() // 60)
        return anchor + dt.timedelta(minutes=(minutes // spec["every_minutes"]) * spec["every_minutes"])
    tz = ZoneInfo(spec["timezone"])
    local_now = now.astimezone(tz)
    hour, minute = map(int, spec["time"].split(":"))
    day = local_now.date()
    for offset in range(0, 8):
        candidate_day = day - dt.timedelta(days=offset)
        if kind == "weekly" and candidate_day.weekday() not in spec["weekdays"]:
            continue
        candidate = dt.datetime.combine(candidate_day, dt.time(hour, minute), tzinfo=tz)
        if candidate <= local_now:
            return candidate.astimezone(dt.timezone.utc)
    return None


def _receipt_path(schedule_id: str, occurrence: dt.datetime) -> Path:
    stamp = occurrence.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return RECEIPT_DIR / safe_id(schedule_id, name="schedule id") / f"{stamp}.json"


def claim_due(spec: dict, *, now: dt.datetime | None = None) -> dict | None:
    now = now or dt.datetime.now(dt.timezone.utc)
    occurrence = occurrence_at_or_before(spec, now)
    if occurrence is None:
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
    if not SCHEDULE_DIR.is_dir(): return []
    out=[]
    for p in sorted(SCHEDULE_DIR.glob("*.json")):
        try:
            spec=read_json(p); validate(spec); out.append(spec)
        except ValueError: continue
    return out


def main(argv: list[str] | None = None) -> int:
    ap=argparse.ArgumentParser(description="Aletheia durable schedules")
    sub=ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list"); sub.add_parser("due")
    args=ap.parse_args(argv)
    if args.cmd=="list":
        for s in all_schedules(): print(f"{s['id']:28} {s['kind']:8} {s['command'].get('kind')}")
    else:
        for s in all_schedules():
            receipt=claim_due(s)
            if receipt: print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
