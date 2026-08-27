"""Phase 11 audio router: approval-bound logical audio routing, no raw audio.

The playbook's Audio Router (§26) should understand physical/virtual inputs and
outputs, monitoring, mute state, and the route needed by Phone V0.  This module
builds the durable/gated control plane without pretending this environment can
reconfigure the operator's Windows audio stack.

A route plan says *which logical endpoints connect*.  Activating it is a
meaningful local side effect, so an operator approval is bound to the sha256 of
the exact plan.  The backend is injected: ``InMemoryAudioBackend`` is only a
hermetic test double; ``sounddevice_inventory`` can enumerate devices but does
not claim to route them.  A future Windows backend (VB-CABLE/VoiceMeeter,
WASAPI, or another reviewed provider) can implement ``AudioBackend`` without
changing the policy contract.

Privacy: no samples, transcripts, credentials, or device driver secrets are
persisted.  State under ``state/private/audio`` contains endpoint metadata,
plan hashes, lifecycle state, and bounded observations only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

from aletheia import policy
from aletheia.stateio import (create_json_exclusive, private_dir, read_json,
                              safe_id, utcnow, write_json_atomic)

BASE_DIR = private_dir("audio")
PLANS_DIR = BASE_DIR / "plans"
SESSIONS_DIR = BASE_DIR / "sessions"

ENDPOINT_KINDS = {"physical_input", "physical_output", "virtual_input", "virtual_output"}
ROUTE_PURPOSES = {"voice_assistant", "phone_bridge", "monitor", "media", "other"}
SESSION_STATES = {"ACTIVE", "STOPPED", "FAILED"}
MAX_ENDPOINTS = 32
MAX_ROUTES = 32


def _canonical_hash(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _plan_path(plan_id: str) -> Path:
    return PLANS_DIR / f"{safe_id(plan_id, name='audio plan id')}.json"


def _session_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{safe_id(session_id, name='audio session id')}.json"


def _text(value: object, name: str, max_len: int = 200) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    value = value.strip()
    if len(value) > max_len:
        raise ValueError(f"{name} exceeds {max_len} characters")
    return value


def normalize_endpoint(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("audio endpoint must be an object")
    endpoint_id = safe_id(_text(value.get("id"), "endpoint id", 128), name="endpoint id")
    kind = value.get("kind")
    if kind not in ENDPOINT_KINDS:
        raise ValueError(f"endpoint kind must be one of {sorted(ENDPOINT_KINDS)}")
    out = {
        "id": endpoint_id,
        "kind": kind,
        "label": _text(value.get("label", endpoint_id), "endpoint label", 200),
    }
    if "device_index" in value:
        if type(value["device_index"]) is not int or value["device_index"] < 0:
            raise ValueError("device_index must be a non-negative integer")
        out["device_index"] = value["device_index"]
    if "provider_ref" in value:
        out["provider_ref"] = _text(value["provider_ref"], "provider_ref", 256)
    return out


def normalize_route(value: dict, endpoint_ids: set[str]) -> dict:
    if not isinstance(value, dict):
        raise ValueError("audio route must be an object")
    source = safe_id(_text(value.get("source"), "route source", 128), name="route source")
    sink = safe_id(_text(value.get("sink"), "route sink", 128), name="route sink")
    if source not in endpoint_ids or sink not in endpoint_ids:
        raise ValueError("route source/sink must name declared endpoints")
    if source == sink:
        raise ValueError("audio route cannot feed an endpoint into itself")
    out = {"source": source, "sink": sink}
    if "monitor" in value:
        if not isinstance(value["monitor"], bool):
            raise ValueError("route monitor must be boolean")
        out["monitor"] = value["monitor"]
    else:
        out["monitor"] = False
    return out


def _reject_direct_cycles(routes: list[dict]) -> None:
    pairs = {(r["source"], r["sink"]) for r in routes}
    for source, sink in pairs:
        if (sink, source) in pairs:
            raise ValueError("direct audio feedback cycle refused")


def build_plan(plan_id: str, *, purpose: str, endpoints: list[dict], routes: list[dict],
               notes: str = "") -> dict:
    safe_id(plan_id, name="audio plan id")
    if purpose not in ROUTE_PURPOSES:
        raise ValueError(f"purpose must be one of {sorted(ROUTE_PURPOSES)}")
    if not isinstance(endpoints, list) or not 1 <= len(endpoints) <= MAX_ENDPOINTS:
        raise ValueError(f"endpoints must contain 1..{MAX_ENDPOINTS} entries")
    if not isinstance(routes, list) or not 1 <= len(routes) <= MAX_ROUTES:
        raise ValueError(f"routes must contain 1..{MAX_ROUTES} entries")
    normalized_endpoints = [normalize_endpoint(e) for e in endpoints]
    endpoint_ids = {e["id"] for e in normalized_endpoints}
    if len(endpoint_ids) != len(normalized_endpoints):
        raise ValueError("audio endpoint ids must be unique")
    normalized_routes = [normalize_route(r, endpoint_ids) for r in routes]
    if len({(r["source"], r["sink"]) for r in normalized_routes}) != len(normalized_routes):
        raise ValueError("duplicate audio route refused")
    _reject_direct_cycles(normalized_routes)
    plan = {
        "purpose": purpose,
        "endpoints": normalized_endpoints,
        "routes": normalized_routes,
    }
    if notes:
        plan["notes"] = _text(notes, "notes", 500)
    value = {
        "version": 1,
        "id": plan_id,
        "plan": plan,
        "plan_sha256": _canonical_hash(plan),
        "state": "PROPOSED",
        "created_at": utcnow(),
    }
    if _plan_path(plan_id).exists():
        raise FileExistsError(plan_id)
    write_json_atomic(_plan_path(plan_id), value)
    return value


def load_plan(plan_id: str) -> dict:
    value = read_json(_plan_path(plan_id))
    plan = value.get("plan")
    if not isinstance(plan, dict) or value.get("plan_sha256") != _canonical_hash(plan):
        raise ValueError("audio plan hash does not match content")
    # Re-run structural validation without rewriting the durable plan.
    normalized_endpoints = [normalize_endpoint(e) for e in plan.get("endpoints", [])]
    endpoint_ids = {e["id"] for e in normalized_endpoints}
    normalized_routes = [normalize_route(r, endpoint_ids) for r in plan.get("routes", [])]
    if len(endpoint_ids) != len(normalized_endpoints):
        raise ValueError("audio endpoint ids must be unique")
    if len({(r["source"], r["sink"]) for r in normalized_routes}) != len(normalized_routes):
        raise ValueError("duplicate audio route refused")
    _reject_direct_cycles(normalized_routes)
    if plan.get("purpose") not in ROUTE_PURPOSES:
        raise ValueError("audio plan purpose is invalid")
    return value


def approval_action(plan: dict) -> str:
    return f"audio.route:{plan['plan_sha256']}"


def request_activation_approval(plan_id: str, approval_id: str | None = None) -> dict:
    plan = load_plan(plan_id)
    approval_id = approval_id or f"audio-{plan_id}"
    safe_id(approval_id, name="approval id")
    return policy.request(
        approval_id,
        approval_action(plan),
        reason=f"activate audio route {plan_id} for {plan['plan']['purpose']}",
        consequence="Windows audio inputs/outputs may be redirected until the session is stopped",
        reversible=True,
    )


class AudioBackend(Protocol):
    """Provider seam. Implementations must not infer approval or policy."""
    provider_id: str
    def start(self, plan: dict) -> dict: ...
    def observe(self, handle: str) -> dict: ...
    def stop(self, handle: str) -> dict: ...


def _bounded_observation(value: dict) -> dict:
    if not isinstance(value, dict):
        raise RuntimeError("audio backend observation must be an object")
    allowed = {"handle", "active", "route_count", "detail"}
    unknown = set(value) - allowed
    if unknown:
        raise RuntimeError(f"audio backend returned unsupported observation fields: {sorted(unknown)}")
    handle = _text(value.get("handle"), "audio backend handle", 128)
    active = value.get("active")
    if not isinstance(active, bool):
        raise RuntimeError("audio backend active must be boolean")
    route_count = value.get("route_count", 0)
    if type(route_count) is not int or route_count < 0 or route_count > MAX_ROUTES:
        raise RuntimeError("audio backend route_count is invalid")
    detail = str(value.get("detail", ""))[:500]
    return {"handle": handle, "active": active, "route_count": route_count, "detail": detail}


def activate(plan_id: str, approval_id: str, backend: AudioBackend,
             *, session_id: str | None = None) -> dict:
    """Activate one exact approved route plan through an injected backend."""
    policy.ensure_not_halted()
    plan = load_plan(plan_id)
    approval = policy.load(approval_id)
    if approval.get("state") != "APPROVED" or approval.get("requested_action") != approval_action(plan):
        raise PermissionError("audio route approval does not match the exact plan")
    provider_id = _text(getattr(backend, "provider_id", ""), "audio backend provider_id", 128)
    session_id = session_id or f"audio-{plan_id}"
    safe_id(session_id, name="audio session id")
    path = _session_path(session_id)
    if path.exists():
        existing = read_json(path)
        if existing.get("plan_sha256") != plan["plan_sha256"]:
            raise FileExistsError(f"audio session {session_id!r} already belongs to another plan")
        if existing.get("state") == "ACTIVE":
            return existing
        raise ValueError("stopped/failed audio session ids cannot be reused")
    # Re-check halt immediately before the provider side effect.
    policy.ensure_not_halted()
    started = _bounded_observation(backend.start(plan["plan"]))
    if not started["active"] or started["route_count"] != len(plan["plan"]["routes"]):
        try:
            backend.stop(started["handle"])
        except Exception:
            pass
        raise RuntimeError("audio backend did not verify every approved route as active")
    value = {
        "version": 1,
        "id": session_id,
        "plan_id": plan_id,
        "plan_sha256": plan["plan_sha256"],
        "approval_id": approval_id,
        "provider": provider_id,
        "backend_handle": started["handle"],
        "state": "ACTIVE",
        "route_count": started["route_count"],
        "observation": started,
        "started_at": utcnow(),
        "updated_at": utcnow(),
    }
    create_json_exclusive(path, value)
    return value


def load_session(session_id: str) -> dict:
    value = read_json(_session_path(session_id))
    if value.get("state") not in SESSION_STATES:
        raise ValueError("audio session has invalid state")
    return value


def verify_active(session_id: str, backend: AudioBackend) -> dict:
    policy.ensure_not_halted()
    value = load_session(session_id)
    if value["state"] != "ACTIVE":
        raise RuntimeError("audio session is not active")
    if getattr(backend, "provider_id", None) != value.get("provider"):
        raise ValueError("audio backend does not match session provider")
    observed = _bounded_observation(backend.observe(value["backend_handle"]))
    if observed["handle"] != value["backend_handle"]:
        raise RuntimeError("audio backend observation handle changed")
    if not observed["active"] or observed["route_count"] != value["route_count"]:
        value["state"] = "FAILED"
        value["observation"] = observed
        value["updated_at"] = utcnow()
        write_json_atomic(_session_path(session_id), value)
        raise RuntimeError("audio route is no longer verified active")
    value["observation"] = observed
    value["updated_at"] = utcnow()
    write_json_atomic(_session_path(session_id), value)
    return value


def stop(session_id: str, backend: AudioBackend) -> dict:
    value = load_session(session_id)
    if value["state"] == "STOPPED":
        return value
    if getattr(backend, "provider_id", None) != value.get("provider"):
        raise ValueError("audio backend does not match session provider")
    # Halt never prevents cleanup. Stopping a route reduces authority/exposure.
    observed = _bounded_observation(backend.stop(value["backend_handle"]))
    if observed["active"]:
        raise RuntimeError("audio backend still reports route active after stop")
    value["state"] = "STOPPED"
    value["observation"] = observed
    value["stopped_at"] = utcnow()
    value["updated_at"] = utcnow()
    write_json_atomic(_session_path(session_id), value)
    return value


def sounddevice_inventory() -> list[dict]:
    """Enumerate audio devices only; this is NOT a routing backend."""
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("sounddevice is not installed") from exc
    devices = sd.query_devices()
    out = []
    for index, device in enumerate(devices):
        if not isinstance(device, dict):
            device = dict(device)
        ins = int(device.get("max_input_channels", 0) or 0)
        outs = int(device.get("max_output_channels", 0) or 0)
        if ins <= 0 and outs <= 0:
            continue
        out.append({
            "device_index": index,
            "name": str(device.get("name", f"device-{index}"))[:200],
            "input_channels": max(0, ins),
            "output_channels": max(0, outs),
            "default_samplerate": float(device.get("default_samplerate", 0) or 0),
        })
    return out


class InMemoryAudioBackend:
    """Deterministic fake used only for hermetic tests and simulations."""
    provider_id = "fake.audio"

    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}
        self.starts = 0
        self.stops = 0

    def start(self, plan: dict) -> dict:
        self.starts += 1
        handle = f"fake-route-{self.starts}"
        self.sessions[handle] = {"active": True, "route_count": len(plan["routes"])}
        return {"handle": handle, "active": True,
                "route_count": len(plan["routes"]), "detail": "fake routes active"}

    def observe(self, handle: str) -> dict:
        state = self.sessions.get(handle)
        if state is None:
            return {"handle": handle, "active": False, "route_count": 0, "detail": "unknown handle"}
        return {"handle": handle, "active": state["active"],
                "route_count": state["route_count"], "detail": "fake observation"}

    def stop(self, handle: str) -> dict:
        self.stops += 1
        state = self.sessions.setdefault(handle, {"active": False, "route_count": 0})
        state["active"] = False
        return {"handle": handle, "active": False,
                "route_count": state["route_count"], "detail": "fake routes stopped"}
