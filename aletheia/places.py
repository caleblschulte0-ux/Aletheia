"""Private place registry and observed travel-time facts.

Saved places support exact/alias resolution. Travel times are stored only when
supplied by a provider/operator with provenance; Aletheia never invents a drive
time from two addresses.
"""
from __future__ import annotations

from pathlib import Path

from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

PLACES_DIR = private_dir("places") / "definitions"
TRAVEL_DIR = private_dir("places") / "travel"


def _path(place_id: str) -> Path:
    return PLACES_DIR / f"{safe_id(place_id, name='place id')}.json"


def create(place_id: str, name: str, *, address: str = "", aliases: list[str] | None = None,
           latitude: float | None = None, longitude: float | None = None,
           provenance: str = "operator") -> dict:
    if _path(place_id).exists():
        raise FileExistsError(place_id)
    if not isinstance(name, str) or not name.strip():
        raise ValueError("place name is required")
    aliases = aliases or []
    if any(not isinstance(x, str) or not x.strip() for x in aliases) or len(set(a.casefold() for a in aliases)) != len(aliases):
        raise ValueError("aliases must be unique non-empty strings")
    if (latitude is None) != (longitude is None):
        raise ValueError("latitude and longitude must be supplied together")
    if latitude is not None and not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("invalid coordinates")
    now = utcnow()
    value = {"version": 1, "id": safe_id(place_id, name="place id"), "name": name.strip(),
             "address": address.strip(), "aliases": aliases, "provenance": provenance,
             "created_at": now, "updated_at": now}
    if latitude is not None:
        value.update({"latitude": latitude, "longitude": longitude})
    write_json_atomic(_path(place_id), value)
    return value


def load(place_id: str) -> dict:
    return read_json(_path(place_id))


def all_places() -> list[dict]:
    if not PLACES_DIR.is_dir():
        return []
    out = []
    for path in sorted(PLACES_DIR.glob("*.json")):
        try:
            out.append(load(path.stem))
        except ValueError:
            continue
    return out


def resolve(query: str) -> dict:
    q = " ".join(query.casefold().split())
    if not q:
        raise ValueError("place query is empty")
    matches = []
    for place in all_places():
        values = [place["id"], place["name"], *place.get("aliases", []), place.get("address", "")]
        if q in {" ".join(str(v).casefold().split()) for v in values if v}:
            matches.append(place)
    if not matches:
        raise KeyError(f"no place matches {query!r}")
    unique = {p["id"]: p for p in matches}
    if len(unique) != 1:
        raise LookupError(f"place {query!r} is ambiguous")
    return next(iter(unique.values()))


def record_travel(origin_id: str, destination_id: str, *, minutes: int,
                  mode: str = "drive", source: str, observed_at: str | None = None) -> dict:
    load(origin_id); load(destination_id)
    if type(minutes) is not int or minutes < 0:
        raise ValueError("minutes must be a non-negative integer")
    if mode not in {"drive", "walk", "bike", "transit", "other"}:
        raise ValueError("unsupported travel mode")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("travel-time provenance is required")
    key = f"{safe_id(origin_id)}--{safe_id(destination_id)}--{mode}"
    value = {"version": 1, "origin": origin_id, "destination": destination_id,
             "mode": mode, "minutes": minutes, "source": source,
             "observed_at": observed_at or utcnow(), "updated_at": utcnow()}
    write_json_atomic(TRAVEL_DIR / f"{key}.json", value)
    return value


def travel_time(origin_id: str, destination_id: str, *, mode: str = "drive") -> dict:
    key = f"{safe_id(origin_id)}--{safe_id(destination_id)}--{mode}"
    return read_json(TRAVEL_DIR / f"{key}.json")
