"""Phase 11 audio router: approval-bound logical audio routing, no raw audio.

This module is the durable/gated control plane for Playbook §26. It does not
pretend this environment can reconfigure the operator's Windows audio stack.
A route plan names physical/virtual endpoints and exact connections. Activation
requires an operator approval bound to the plan sha256, then an injected backend
must prove the exact approved route fingerprints are active. Counts alone are
not verification.

No samples, transcripts, credentials, or driver secrets are persisted. State
under ``state/private/audio`` contains only bounded metadata and observations.
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
    out = {"id": endpoint_id, "kind": kind,
           "label": _text(value.get("label", endpoint_id), "endpoint label", 200)}
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
    monitor = value.get("monitor", False)
    if not isinstance(monitor, bool):
        raise ValueError("route monitor must be boolean")
    return {"source": source, "sink": sink, "monitor": monitor}


def route_fingerprint(route: dict) -> str:
    return "route-" + _canonical_hash({"source": route["source"], "sink": route["sink"],
                                        "monitor": bool(route.get("monitor", False))})[:24]


def route_fingerprints(plan: dict) -> list[str]:
    return sorted(route_fingerprint(route) for route in plan["routes"])


def _reject_direct_cycles(routes: list[dict]) -> None:
    pairs = {(r["source"], r["sink"]) for r in routes}
    if any((sink, source) in pairs for source, sink in pairs):
        raise ValueError("direct audio feedback cycle refused")


def _validate_plan(plan: dict) -> dict:
    if not isinstance(plan, dict) or plan.get("purpose") not in ROUTE_PURPOSES:
        raise ValueError("audio plan purpose is invalid")
    endpoints = plan.get("endpoints")
    routes = plan.get("routes")
    if not isinstance(endpoints, list) or not 1 <= len(endpoints) <= MAX_ENDPOINTS:
        raise ValueError(f"endpoints must contain 1..{MAX_ENDPOINTS} entries")
    if not isinstance(routes, list) or not 1 <= len(routes) <= MAX_ROUTES:
        raise ValueError(f"routes must contain 1..{MAX_ROUTES} entries")
    normalized_endpoints = [normalize_endpoint(e) for e in endpoints]
    endpoint_ids = {e["id"] for e in normalized_endpoints}
    if len(endpoint_ids) != len(normalized_endpoints):
        raise ValueError("audio endpoint ids must be unique")
    normalized_routes = [normalize_route(r, endpoint_ids) for r in routes]
    if len({(r["source"], r["sink"], r["monitor"]) for r in normalized_routes}) != len(normalized_routes):
        raise ValueError("duplicate audio route refused")
    _reject_direct_cycles(normalized_routes)
    value = {"purpose": plan["purpose"], "endpoints": normalized_endpoints,
             "routes": normalized_routes}
    if plan.get("notes"):
        value["notes"] = _text(plan["notes"], "notes", 500)
    return value


def build_plan(plan_id: str, *, purpose: str, endpoints: list[dict], routes: list[dict],
               notes: str = "") -> dict:
    safe_id(plan_id, name="audio plan id")
    plan = _validate_plan({"purpose": purpose, "endpoints": endpoints,
                           "routes": routes, **({"notes": notes} if notes else {})})
    value = {"version": 1, "id": plan_id, "plan": plan,
             "plan_sha256": _canonical_hash(plan), "state": "PROPOSED",
             "created_at": utcnow()}
    if _plan_path(plan_id).exists():
        raise FileExistsError(plan_id)
    write_json_atomic(_plan_path(plan_id), value)
    return value


def load_plan(plan_id: str) -> dict:
    value = read_json(_plan_path(plan_id))
    plan = _validate_plan(value.get("plan"))
    if value.get("plan_sha256") != _canonical_hash(plan) or value.get("plan") != plan:
        raise ValueError("audio plan hash does not match content")
    return value


def approval_action(plan: dict) -> str:
    return f"audio.route:{plan['plan_sha256']}"


def request_activation_approval(plan_id: str, approval_id: str | None = None) -> dict:
    plan = load_plan(plan_id)
    approval_id = approval_id or f"audio-{plan_id}"
    safe_id(approval_id, name="approval id")
    return policy.request(
        approval_id, approval_action(plan),
        reason=f"activate audio route {plan_id} for {plan['plan']['purpose']}",
        consequence="Windows audio inputs/outputs may be redirected until the session is stopped",
        reversible=True, capability="audio.route")


class AudioBackend(Protocol):
    provider_id: str
    def start(self, plan: dict) -> dict: ...
    def observe(self, handle: str) -> dict: ...
    def stop(self, handle: str) -> dict: ...


def _bounded_observation(value: dict) -> dict:
    if not isinstance(value, dict):
        raise RuntimeError("audio backend observation must be an object")
    unknown = set(value) - {"handle", "active", "routes", "detail"}
    if unknown:
        raise RuntimeError(f"audio backend returned unsupported observation fields: {sorted(unknown)}")
    handle = _text(value.get("handle"), "audio backend handle", 128)
    active = value.get("active")
    if not isinstance(active, bool):
        raise RuntimeError("audio backend active must be boolean")
    routes = value.get("routes", [])
    if not isinstance(routes, list) or len(routes) > MAX_ROUTES or any(not isinstance(x, str) for x in routes):
        raise RuntimeError("audio backend routes must be a bounded list of fingerprints")
    if len(set(routes)) != len(routes):
        raise RuntimeError("audio backend returned duplicate route fingerprints")
    return {"handle": handle, "active": active, "routes": sorted(routes),
            "detail": str(value.get("detail", ""))[:500]}


def _require_exact_routes(observed: dict, expected: list[str]) -> None:
    if not observed["active"] or observed["routes"] != sorted(expected):
        raise RuntimeError("audio backend did not verify the exact approved routes as active")


def activate(plan_id: str, approval_id: str, backend: AudioBackend,
             *, session_id: str | None = None) -> dict:
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
    expected = route_fingerprints(plan["plan"])
    policy.ensure_not_halted()
    started = _bounded_observation(backend.start(plan["plan"]))
    try:
        _require_exact_routes(started, expected)
    except RuntimeError:
        try:
            backend.stop(started["handle"])
        except Exception:
            pass
        raise
    value = {"version": 1, "id": session_id, "plan_id": plan_id,
             "plan_sha256": plan["plan_sha256"], "approval_id": approval_id,
             "provider": provider_id, "backend_handle": started["handle"],
             "state": "ACTIVE", "route_fingerprints": expected,
             "observation": started, "started_at": utcnow(), "updated_at": utcnow()}
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
    try:
        if observed["handle"] != value["backend_handle"]:
            raise RuntimeError("audio backend observation handle changed")
        _require_exact_routes(observed, value["route_fingerprints"])
    except RuntimeError:
        value["state"] = "FAILED"
        value["observation"] = observed
        value["updated_at"] = utcnow()
        write_json_atomic(_session_path(session_id), value)
        raise
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
    observed = _bounded_observation(backend.stop(value["backend_handle"]))
    if observed["active"] or observed["routes"]:
        raise RuntimeError("audio backend still reports routes active after stop")
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
    out = []
    for index, raw in enumerate(sd.query_devices()):
        device = raw if isinstance(raw, dict) else dict(raw)
        ins = int(device.get("max_input_channels", 0) or 0)
        outs = int(device.get("max_output_channels", 0) or 0)
        if ins <= 0 and outs <= 0:
            continue
        out.append({"device_index": index,
                    "name": str(device.get("name", f"device-{index}"))[:200],
                    "input_channels": max(0, ins), "output_channels": max(0, outs),
                    "default_samplerate": float(device.get("default_samplerate", 0) or 0)})
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
        routes = route_fingerprints(plan)
        self.sessions[handle] = {"active": True, "routes": routes}
        return {"handle": handle, "active": True, "routes": routes,
                "detail": "fake routes active"}

    def observe(self, handle: str) -> dict:
        state = self.sessions.get(handle)
        if state is None:
            return {"handle": handle, "active": False, "routes": [], "detail": "unknown handle"}
        return {"handle": handle, "active": state["active"],
                "routes": list(state["routes"]), "detail": "fake observation"}

    def stop(self, handle: str) -> dict:
        self.stops += 1
        state = self.sessions.setdefault(handle, {"active": False, "routes": []})
        state["active"] = False
        state["routes"] = []
        return {"handle": handle, "active": False, "routes": [],
                "detail": "fake routes stopped"}
