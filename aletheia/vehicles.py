"""Private vehicle records and maintenance due calculations.

This is visibility/planning only. It records observed odometer/service facts and
produces due items; booking or purchasing service remains another capability.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

VEHICLES_DIR = private_dir("vehicles") / "records"
SERVICE_DIR = private_dir("vehicles") / "service"


def _path(vehicle_id: str) -> Path:
    return VEHICLES_DIR / f"{safe_id(vehicle_id, name='vehicle id')}.json"


def create(vehicle_id: str, *, name: str, year: int | None = None, make: str = "", model: str = "") -> dict:
    if _path(vehicle_id).exists():
        raise FileExistsError(vehicle_id)
    if not isinstance(name, str) or not name.strip():
        raise ValueError("vehicle name is required")
    if year is not None and (type(year) is not int or year < 1886 or year > 2200):
        raise ValueError("invalid vehicle year")
    now = utcnow()
    value = {"version": 1, "id": safe_id(vehicle_id, name="vehicle id"), "name": name.strip(),
             "year": year, "make": make, "model": model, "odometer": None,
             "created_at": now, "updated_at": now}
    write_json_atomic(_path(vehicle_id), value)
    return value


def load(vehicle_id: str) -> dict:
    return read_json(_path(vehicle_id))


def all_vehicles() -> list[dict]:
    """Every vehicle on record. `due()` needs an id and nothing could list
    them, so "when is the car due?" had no answer even with the data."""
    root = VEHICLES_DIR if "VEHICLES_DIR" in globals() else private_dir("vehicles")
    if not root.is_dir():
        return []
    out = []
    for path in sorted(root.glob("*.json")):
        try:
            out.append(read_json(path))
        except ValueError:
            continue
    return out


def record_odometer(vehicle_id: str, miles: int, *, source: str = "operator") -> dict:
    if type(miles) is not int or miles < 0:
        raise ValueError("odometer must be a non-negative integer")
    value = load(vehicle_id)
    current = value.get("odometer")
    if current is not None and miles < current:
        raise ValueError("odometer cannot move backwards")
    value["odometer"] = miles
    value["odometer_source"] = source
    value["odometer_at"] = utcnow()
    value["updated_at"] = utcnow()
    write_json_atomic(_path(vehicle_id), value)
    return value


def add_service_rule(vehicle_id: str, rule_id: str, *, description: str,
                    every_miles: int | None = None, every_days: int | None = None,
                    last_miles: int | None = None, last_date: str | None = None) -> dict:
    load(vehicle_id); safe_id(rule_id, name="service rule id")
    if every_miles is None and every_days is None:
        raise ValueError("service rule requires a mileage or time interval")
    if every_miles is not None and (type(every_miles) is not int or every_miles < 1):
        raise ValueError("every_miles must be positive")
    if every_days is not None and (type(every_days) is not int or every_days < 1):
        raise ValueError("every_days must be positive")
    if last_date:
        dt.date.fromisoformat(last_date)
    value = {"version": 1, "id": rule_id, "vehicle_id": vehicle_id, "description": description,
             "every_miles": every_miles, "every_days": every_days, "last_miles": last_miles,
             "last_date": last_date, "created_at": utcnow(), "updated_at": utcnow()}
    path = SERVICE_DIR / safe_id(vehicle_id) / f"{rule_id}.json"
    if path.exists():
        raise FileExistsError(rule_id)
    write_json_atomic(path, value)
    return value


def due(vehicle_id: str, *, today: dt.date | None = None) -> list[dict]:
    vehicle = load(vehicle_id)
    today = today or dt.date.today()
    root = SERVICE_DIR / safe_id(vehicle_id)
    if not root.is_dir():
        return []
    out = []
    for path in root.glob("*.json"):
        try:
            rule = read_json(path)
        except ValueError:
            continue
        reasons = []
        if rule.get("every_miles") and vehicle.get("odometer") is not None and rule.get("last_miles") is not None:
            if vehicle["odometer"] >= rule["last_miles"] + rule["every_miles"]:
                reasons.append("mileage")
        if rule.get("every_days") and rule.get("last_date"):
            if today >= dt.date.fromisoformat(rule["last_date"]) + dt.timedelta(days=rule["every_days"]):
                reasons.append("time")
        if reasons:
            out.append({"rule_id": rule["id"], "description": rule["description"], "reasons": reasons})
    return out
