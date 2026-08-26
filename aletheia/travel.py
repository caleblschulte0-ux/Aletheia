"""Private travel itinerary and reservation-linking core.

Itineraries organize observed bookings, places and timing. Search/booking remain
separate capabilities, so an itinerary never implies a reservation exists.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

TRIPS_DIR = private_dir("travel")
KINDS = {"flight", "hotel", "car", "activity", "meal", "transit", "note"}


def _path(trip_id: str) -> Path:
    return TRIPS_DIR / f"{safe_id(trip_id, name='trip id')}.json"


def create(trip_id: str, *, title: str, start_date: str, end_date: str,
           timezone: str = "UTC") -> dict:
    if _path(trip_id).exists():
        raise FileExistsError(trip_id)
    start, end = dt.date.fromisoformat(start_date), dt.date.fromisoformat(end_date)
    if end < start:
        raise ValueError("trip end date must be on/after start")
    now = utcnow()
    value = {"version": 1, "id": safe_id(trip_id, name="trip id"), "title": title,
             "start_date": start_date, "end_date": end_date, "timezone": timezone,
             "items": [], "created_at": now, "updated_at": now}
    write_json_atomic(_path(trip_id), value)
    return value


def load(trip_id: str) -> dict:
    return read_json(_path(trip_id))


def add_item(trip_id: str, item_id: str, *, kind: str, title: str,
            start: str | None = None, end: str | None = None,
            confirmation: str | None = None, source: str = "operator",
            details: dict | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError("invalid itinerary item kind")
    safe_id(item_id, name="item id")
    value = load(trip_id)
    if any(item["id"] == item_id for item in value["items"]):
        raise FileExistsError(item_id)
    for timestamp in (start, end):
        if timestamp:
            parsed = dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("itinerary timestamps must be timezone-aware")
    if start and end and dt.datetime.fromisoformat(end.replace("Z", "+00:00")) <= dt.datetime.fromisoformat(start.replace("Z", "+00:00")):
        raise ValueError("item end must be after start")
    item = {"id": item_id, "kind": kind, "title": title, "start": start, "end": end,
            "source": source, "details": details or {}, "recorded_at": utcnow()}
    if confirmation:
        item["confirmation"] = confirmation
    value["items"].append(item)
    value["items"].sort(key=lambda x: x.get("start") or "9999")
    value["updated_at"] = utcnow()
    write_json_atomic(_path(trip_id), value)
    return item


def gaps(trip_id: str) -> list[str]:
    value = load(trip_id)
    kinds = {item["kind"] for item in value["items"]}
    missing = []
    if "hotel" not in kinds and (dt.date.fromisoformat(value["end_date"]) > dt.date.fromisoformat(value["start_date"])):
        missing.append("lodging not recorded")
    if not ({"flight", "car", "transit"} & kinds):
        missing.append("transportation not recorded")
    return missing
