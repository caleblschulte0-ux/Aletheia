"""Provider boundary for live calendars without pretending a live adapter exists.

The local calendar model already owns deterministic time reasoning. This module
adds the seam a Google/Outlook adapter must satisfy: normalized events, bounded
window sync, explicit conflict handling, and hash-bound write plans. There is no
network provider here. `InMemoryCalendarProvider` is a hermetic fake for tests.

Calendar writes are world-touching actions. A write plan is therefore bound to
an operator approval by sha256 of its exact canonical content. The provider is
not called until the approval matches, the kill switch is clear, and the plan
validates. Provider return data is normalized and compared with the requested
state before the action is called verified.
"""
from __future__ import annotations

import hashlib
import json
from typing import Protocol

from aletheia import calendar, policy
from aletheia.stateio import utcnow

ACTIONS = {"CREATE", "UPDATE", "CANCEL"}
REMOTE_STATUSES = {"CONFIRMED", "TENTATIVE", "CANCELLED"}


def _hash(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_event(value: dict) -> dict:
    """Normalize one provider event into the subset Aletheia trusts."""
    if not isinstance(value, dict):
        raise ValueError("provider event must be an object")
    required = {"external_id", "title", "start", "end"}
    missing = required - value.keys()
    if missing:
        raise ValueError(f"provider event missing {sorted(missing)}")
    external_id = str(value["external_id"]).strip()
    title = str(value["title"]).strip()
    if not external_id or not title:
        raise ValueError("provider external_id/title are required")
    start = calendar.parse_time(value["start"])
    end = calendar.parse_time(value["end"])
    if end <= start:
        raise ValueError("provider event end must be after start")
    status = value.get("status", "CONFIRMED")
    if status not in REMOTE_STATUSES:
        raise ValueError("invalid provider event status")
    attendees = value.get("attendees", [])
    if not isinstance(attendees, list) or any(not isinstance(x, str) or not x.strip() for x in attendees):
        raise ValueError("provider attendees must be strings")
    out = {
        "external_id": external_id,
        "title": title,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "status": status,
        "attendees": list(dict.fromkeys(attendees)),
    }
    for key in ("location", "etag", "updated_at"):
        if value.get(key) is not None:
            out[key] = str(value[key])
    return out


class CalendarProvider(Protocol):
    provider_id: str

    def list_events(self, start: str, end: str) -> list[dict]: ...
    def create_event(self, event: dict) -> dict: ...
    def update_event(self, external_id: str, event: dict) -> dict: ...
    def cancel_event(self, external_id: str) -> dict: ...


def _local_id(provider_id: str, external_id: str) -> str:
    digest = hashlib.sha256(f"{provider_id}:{external_id}".encode()).hexdigest()[:20]
    return f"cal-{provider_id.replace('.', '-')[:24]}-{digest}"[:60]


def _provider_event(local: dict, provider_id: str, external_id: str) -> bool:
    return local.get("provider_id") == provider_id and local.get("external_id") == external_id


def _upsert_remote(provider_id: str, remote: dict) -> tuple[dict, str]:
    remote = normalize_event(remote)
    existing = next((e for e in calendar.all_events()
                     if _provider_event(e, provider_id, remote["external_id"])), None)
    if existing and existing.get("provider_dirty"):
        return existing, "CONFLICT_LOCAL_DIRTY"
    now = utcnow()
    if existing:
        value = dict(existing)
        action = "UPDATED"
    else:
        value = {
            "version": 1,
            "id": _local_id(provider_id, remote["external_id"]),
            "created_at": now,
            "priority": 3,
            "movable": False,
        }
        action = "CREATED"
    value.update({
        "title": remote["title"],
        "start": remote["start"],
        "end": remote["end"],
        "attendees": remote.get("attendees", []),
        "status": remote["status"],
        "source": f"provider:{provider_id}",
        "provider_id": provider_id,
        "external_id": remote["external_id"],
        "provider_etag": remote.get("etag", ""),
        "provider_updated_at": remote.get("updated_at", ""),
        "provider_dirty": False,
        "synced_at": now,
        "updated_at": now,
    })
    if remote.get("location"):
        value["location"] = remote["location"]
    elif "location" in value:
        value.pop("location")
    calendar.save(value)
    return value, action


def sync_window(provider: CalendarProvider, start: str, end: str, *,
                authoritative: bool = False) -> dict:
    """Import one bounded provider window.

    `authoritative=False` is intentionally the default: absence from a paged or
    filtered provider response must not cancel a local event. When a real adapter
    can prove the response is a complete window it may set authoritative=True;
    only provider-owned, non-dirty events inside that exact window are then
    tombstoned as CANCELLED.
    """
    a, b = calendar.parse_time(start), calendar.parse_time(end)
    if b <= a:
        raise ValueError("sync window end must be after start")
    provider_id = str(getattr(provider, "provider_id", "")).strip()
    if not provider_id:
        raise ValueError("calendar provider must declare provider_id")
    remote_values = [normalize_event(v) for v in provider.list_events(a.isoformat(), b.isoformat())]
    if len({v["external_id"] for v in remote_values}) != len(remote_values):
        raise ValueError("provider returned duplicate external ids")
    actions, conflicts = [], []
    seen = set()
    for remote in remote_values:
        seen.add(remote["external_id"])
        local, action = _upsert_remote(provider_id, remote)
        item = {"external_id": remote["external_id"], "local_id": local["id"], "action": action}
        (conflicts if action.startswith("CONFLICT") else actions).append(item)
    if authoritative:
        for local in calendar.all_events():
            if local.get("provider_id") != provider_id or local.get("provider_dirty"):
                continue
            when = calendar.parse_time(local["start"])
            if a <= when < b and local.get("external_id") not in seen and local["status"] != "CANCELLED":
                local = dict(local)
                local["status"] = "CANCELLED"
                local["updated_at"] = utcnow()
                local["synced_at"] = utcnow()
                calendar.save(local)
                actions.append({"external_id": local["external_id"], "local_id": local["id"],
                                "action": "CANCELLED_MISSING_REMOTE"})
    return {"provider": provider_id, "window": {"start": a.isoformat(), "end": b.isoformat()},
            "remote_count": len(remote_values), "actions": actions, "conflicts": conflicts}


def build_write_plan(action: str, provider_id: str, *, event: dict | None = None,
                     external_id: str | None = None) -> dict:
    action = action.upper()
    if action not in ACTIONS:
        raise ValueError(f"calendar action must be one of {sorted(ACTIONS)}")
    if not isinstance(provider_id, str) or not provider_id.strip():
        raise ValueError("provider_id is required")
    plan = {"version": 1, "action": action, "provider_id": provider_id.strip()}
    if action in {"UPDATE", "CANCEL"}:
        if not isinstance(external_id, str) or not external_id.strip():
            raise ValueError(f"{action} requires external_id")
        plan["external_id"] = external_id.strip()
    if action in {"CREATE", "UPDATE"}:
        if not isinstance(event, dict):
            raise ValueError(f"{action} requires event")
        # A write request has no remote id yet on CREATE; validate calendar facts
        # independently from provider-return metadata.
        candidate = {
            "external_id": external_id or "pending-create",
            "title": event.get("title"), "start": event.get("start"), "end": event.get("end"),
            "status": event.get("status", "CONFIRMED"), "attendees": event.get("attendees", []),
        }
        if event.get("location") is not None:
            candidate["location"] = event["location"]
        normalized = normalize_event(candidate)
        normalized.pop("external_id", None)
        plan["event"] = normalized
    plan["sha256"] = _hash({k: v for k, v in plan.items() if k != "sha256"})
    return plan


def request_write_approval(approval_id: str, plan: dict, *, reason: str = "calendar change") -> dict:
    expected = _hash({k: v for k, v in plan.items() if k != "sha256"})
    if plan.get("sha256") != expected:
        raise ValueError("calendar write plan hash mismatch")
    return policy.request(
        approval_id,
        f"calendar.write:{expected}",
        reason=reason,
        consequence="a live external calendar is changed",
        reversible=plan["action"] != "CREATE",
    )


def execute_write_plan(plan: dict, approval_id: str, provider: CalendarProvider) -> dict:
    policy.ensure_not_halted()
    expected = _hash({k: v for k, v in plan.items() if k != "sha256"})
    if plan.get("sha256") != expected:
        raise ValueError("calendar write plan hash mismatch")
    approval = policy.load(approval_id)
    if approval.get("state") != "APPROVED" or approval.get("requested_action") != f"calendar.write:{expected}":
        raise PermissionError("calendar write approval does not match the exact plan")
    if getattr(provider, "provider_id", None) != plan.get("provider_id"):
        raise ValueError("provider does not match write plan")
    action = plan["action"]
    if action == "CREATE":
        observed = provider.create_event(dict(plan["event"]))
    elif action == "UPDATE":
        observed = provider.update_event(plan["external_id"], dict(plan["event"]))
    elif action == "CANCEL":
        observed = provider.cancel_event(plan["external_id"])
    else:
        raise ValueError("unsupported calendar write action")
    normalized = normalize_event(observed)
    if action in {"CREATE", "UPDATE"}:
        requested = plan["event"]
        for key in ("title", "start", "end", "status", "attendees"):
            if normalized.get(key) != requested.get(key):
                raise RuntimeError(f"provider verification failed for {key}")
    elif normalized["status"] != "CANCELLED":
        raise RuntimeError("provider did not verify cancellation")
    local, sync_action = _upsert_remote(plan["provider_id"], normalized)
    return {"outcome": "VERIFIED", "provider": plan["provider_id"],
            "external_id": normalized["external_id"], "local_id": local["id"],
            "sync_action": sync_action, "plan_sha256": expected}


class InMemoryCalendarProvider:
    """Hermetic provider for tests; never used as evidence of a live account."""
    def __init__(self, provider_id: str = "fake.calendar", events: list[dict] | None = None):
        self.provider_id = provider_id
        self._events = {normalize_event(e)["external_id"]: normalize_event(e) for e in (events or [])}
        self._next = 1

    def list_events(self, start: str, end: str) -> list[dict]:
        a, b = calendar.parse_time(start), calendar.parse_time(end)
        return [dict(e) for e in self._events.values()
                if a <= calendar.parse_time(e["start"]) < b]

    def create_event(self, event: dict) -> dict:
        external_id = f"fake-{self._next}"
        self._next += 1
        value = normalize_event({"external_id": external_id, **event})
        self._events[external_id] = value
        return dict(value)

    def update_event(self, external_id: str, event: dict) -> dict:
        if external_id not in self._events:
            raise KeyError(external_id)
        value = normalize_event({"external_id": external_id, **event})
        self._events[external_id] = value
        return dict(value)

    def cancel_event(self, external_id: str) -> dict:
        if external_id not in self._events:
            raise KeyError(external_id)
        value = dict(self._events[external_id])
        value["status"] = "CANCELLED"
        self._events[external_id] = value
        return dict(value)
