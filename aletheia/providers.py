"""Runtime provider observations and deterministic candidate routing.

The capability registry declares providers; this module records what is actually
reachable *here and now*. Observations are local/private because availability
can differ by machine. Routing only chooses among explicitly supplied declared
candidates and never promotes an unavailable capability or invents a provider.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from aletheia import capabilities
from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

OBSERVATIONS_DIR = private_dir("providers")
STATUSES = {"AVAILABLE", "DEGRADED", "UNAVAILABLE", "UNVERIFIED"}
RANK = {"AVAILABLE": 0, "DEGRADED": 1, "UNAVAILABLE": 2, "UNVERIFIED": 3}


def _path(provider_id: str) -> Path:
    safe = provider_id.replace(".", "-").replace("_", "-")
    return OBSERVATIONS_DIR / f"{safe_id(safe, name='provider state id')}.json"


def _parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("provider timestamps must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def declared(provider_id: str, registry: dict) -> dict:
    for provider in registry.get("providers", []):
        if provider.get("id") == provider_id:
            return provider
    raise KeyError(f"provider {provider_id!r} is not declared")


def observe(provider_id: str, *, status: str, latency_ms: int | None = None,
            reason: str = "", registry: dict | None = None) -> dict:
    registry = registry or capabilities.load_registry()
    provider = declared(provider_id, registry)
    if status not in STATUSES:
        raise ValueError(f"status must be one of {sorted(STATUSES)}")
    if latency_ms is not None and (type(latency_ms) is not int or latency_ms < 0):
        raise ValueError("latency_ms must be a non-negative integer")
    value = {"version": 1, "provider_id": provider_id, "provider_kind": provider["kind"],
             "status": status, "observed_at": utcnow()}
    if latency_ms is not None:
        value["latency_ms"] = latency_ms
    if reason:
        value["reason"] = reason
    write_json_atomic(_path(provider_id), value)
    return value


def load(provider_id: str) -> dict:
    value = read_json(_path(provider_id))
    if value.get("status") not in STATUSES or value.get("provider_id") != provider_id:
        raise ValueError("invalid provider observation")
    _parse_time(value["observed_at"])
    return value


def is_fresh(observation: dict, *, now: dt.datetime | None = None,
             max_age_minutes: int = 10) -> bool:
    if max_age_minutes < 1:
        raise ValueError("max_age_minutes must be positive")
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    age = now.astimezone(dt.timezone.utc) - _parse_time(observation["observed_at"])
    return dt.timedelta(0) <= age <= dt.timedelta(minutes=max_age_minutes)


def select(candidate_ids: list[str], *, registry: dict | None = None,
           allow_degraded: bool = False, max_age_minutes: int = 10,
           now: dt.datetime | None = None) -> dict:
    """Choose a currently observed candidate or fail closed.

    Candidate order is a final stable tie-breaker after status and latency.
    """
    if not candidate_ids or len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("candidate_ids must be unique and non-empty")
    registry = registry or capabilities.load_registry()
    rows = []
    for position, provider_id in enumerate(candidate_ids):
        declared(provider_id, registry)
        try:
            observation = load(provider_id)
        except ValueError:
            continue
        if not is_fresh(observation, now=now, max_age_minutes=max_age_minutes):
            continue
        if observation["status"] == "AVAILABLE" or (allow_degraded and observation["status"] == "DEGRADED"):
            rows.append((RANK[observation["status"]], observation.get("latency_ms", 10**12), position,
                         provider_id, observation))
    if not rows:
        raise LookupError("no fresh eligible provider observation")
    rows.sort(key=lambda row: row[:3])
    _, _, _, provider_id, observation = rows[0]
    return {"provider_id": provider_id, "observation": observation}
