"""Provider-neutral room/device registry for Phase 18 foundations.

A device record describes identity and declared abilities only. It does not
claim the hardware is reachable. Live provider state must later be observed by
a Home Assistant or equivalent adapter before any capability is AVAILABLE.
Room/device identity is private runtime state by default.
"""
from __future__ import annotations

from pathlib import Path

from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

DEVICES_DIR = private_dir("devices")
KINDS = {"light", "switch", "media", "thermostat", "sensor", "lock", "shade", "other"}
STATUSES = {"UNVERIFIED", "ONLINE", "OFFLINE"}


def _path(device_id: str) -> Path:
    return DEVICES_DIR / f"{safe_id(device_id, name='device id')}.json"


def validate(device: dict) -> None:
    required = {"version", "id", "name", "kind", "room", "provider", "external_id",
                "abilities", "status", "created_at", "updated_at"}
    missing = required - device.keys()
    if missing:
        raise ValueError(f"device missing {sorted(missing)}")
    if device["version"] != 1:
        raise ValueError("unsupported device version")
    safe_id(device["id"], name="device id")
    if device["kind"] not in KINDS:
        raise ValueError("invalid device kind")
    if device["status"] not in STATUSES:
        raise ValueError("invalid device status")
    for key in ("name", "room", "provider", "external_id"):
        if not isinstance(device[key], str) or not device[key].strip():
            raise ValueError(f"{key} is required")
    abilities = device["abilities"]
    if not isinstance(abilities, list) or not abilities or any(not isinstance(x, str) or not x.strip() for x in abilities):
        raise ValueError("abilities must be non-empty strings")
    if len(set(abilities)) != len(abilities):
        raise ValueError("abilities must be unique")
    if "observed_state" in device and not isinstance(device["observed_state"], dict):
        raise ValueError("observed_state must be an object")


def register(device_id: str, *, name: str, kind: str, room: str,
             provider: str, external_id: str, abilities: list[str]) -> dict:
    if _path(device_id).exists():
        raise FileExistsError(device_id)
    value = {"version": 1, "id": safe_id(device_id, name="device id"), "name": name,
             "kind": kind, "room": room, "provider": provider, "external_id": external_id,
             "abilities": abilities, "status": "UNVERIFIED", "created_at": utcnow(),
             "updated_at": utcnow()}
    validate(value)
    write_json_atomic(_path(device_id), value)
    return value


def load(device_id: str) -> dict:
    value = read_json(_path(device_id))
    validate(value)
    return value


def mark_observed(device_id: str, *, online: bool, observed_state: dict) -> dict:
    if not isinstance(online, bool):
        raise ValueError("online must be boolean")
    if not isinstance(observed_state, dict):
        raise ValueError("observed_state must be an object")
    value = load(device_id)
    value["status"] = "ONLINE" if online else "OFFLINE"
    value["observed_state"] = observed_state
    value["observed_at"] = utcnow()
    value["updated_at"] = utcnow()
    validate(value)
    write_json_atomic(_path(device_id), value)
    return value


def all_devices() -> list[dict]:
    """Every registered device, valid ones only.

    A provider adapter needs the whole registry, not one room: `hass.observe`
    refreshes reachability for everything the hub knows about.
    """
    if not DEVICES_DIR.is_dir():
        return []
    out = []
    for path in DEVICES_DIR.glob("*.json"):
        try:
            value = read_json(path)
            validate(value)
        except ValueError:
            continue  # a malformed record is not a device
        out.append(value)
    return sorted(out, key=lambda d: d["id"])


def in_room(room: str) -> list[dict]:
    if not isinstance(room, str) or not room.strip():
        raise ValueError("room is required")
    if not DEVICES_DIR.is_dir():
        return []
    out = []
    for path in DEVICES_DIR.glob("*.json"):
        try:
            value = read_json(path)
            validate(value)
        except ValueError:
            continue
        if value["room"].casefold() == room.casefold():
            out.append(value)
    return sorted(out, key=lambda d: d["id"])


def require_ability(device: dict, ability: str) -> None:
    validate(device)
    if ability not in device["abilities"]:
        raise ValueError(f"device {device['id']!r} does not declare ability {ability!r}")
    if device["status"] != "ONLINE":
        raise RuntimeError(f"device {device['id']!r} is not verified online")
