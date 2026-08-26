"""Provider-neutral room/device registry for Phase 18 foundations.

A device record describes identity and declared abilities only. It does not
claim the hardware is reachable. Live provider state must later be observed by
a Home Assistant or equivalent adapter before any capability is AVAILABLE.
"""
from __future__ import annotations

from pathlib import Path

from aletheia.fleet import REPO_ROOT
from aletheia.stateio import read_json, safe_id, utcnow, write_json_atomic

DEVICES_DIR = REPO_ROOT / "state" / "devices"
KINDS = {"light", "switch", "media", "thermostat", "sensor", "lock", "shade", "other"}


def _path(device_id: str) -> Path:
    return DEVICES_DIR / f"{safe_id(device_id, name='device id')}.json"


def register(device_id: str, *, name: str, kind: str, room: str,
             provider: str, external_id: str, abilities: list[str]) -> dict:
    if kind not in KINDS:
        raise ValueError("invalid device kind")
    if not abilities or len(set(abilities)) != len(abilities):
        raise ValueError("abilities must be unique and non-empty")
    if _path(device_id).exists():
        raise FileExistsError(device_id)
    value = {"version": 1, "id": device_id, "name": name, "kind": kind, "room": room,
             "provider": provider, "external_id": external_id, "abilities": abilities,
             "status": "UNVERIFIED", "created_at": utcnow(), "updated_at": utcnow()}
    write_json_atomic(_path(device_id), value)
    return value


def load(device_id: str) -> dict:
    return read_json(_path(device_id))


def mark_observed(device_id: str, *, online: bool, observed_state: dict) -> dict:
    value = load(device_id)
    value["status"] = "ONLINE" if online else "OFFLINE"
    value["observed_state"] = observed_state
    value["observed_at"] = utcnow()
    value["updated_at"] = utcnow()
    write_json_atomic(_path(device_id), value)
    return value


def in_room(room: str) -> list[dict]:
    if not DEVICES_DIR.is_dir():
        return []
    out = []
    for p in DEVICES_DIR.glob("*.json"):
        try:
            value = read_json(p)
        except ValueError:
            continue
        if value.get("room", "").casefold() == room.casefold():
            out.append(value)
    return sorted(out, key=lambda d: d["id"])


def require_ability(device: dict, ability: str) -> None:
    if ability not in device.get("abilities", []):
        raise ValueError(f"device {device.get('id')!r} does not declare ability {ability!r}")
    if device.get("status") != "ONLINE":
        raise RuntimeError(f"device {device.get('id')!r} is not verified online")
