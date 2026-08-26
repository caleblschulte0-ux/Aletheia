"""Persistent "handle it" orchestration above capabilities, below authority.

A handle request is an outcome Aletheia is trying to achieve. It can carry
multiple candidate paths, choose the first path whose capabilities are actually
AVAILABLE, materialize missing-capability work when none is ready, wait on the
outside world, schedule bounded retries, and require evidence before completion.

This module never executes an external action and never bypasses policy. A
candidate command remains a proposal to the existing intercom/Core gates. A
fallback can change *how* Aletheia tries to reach the goal; it cannot turn a
missing permission into permission.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from aletheia import composition, context, gaps, recovery
from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

REQUESTS_DIR = private_dir("handler") / "requests"
STATES = {
    "BLOCKED_CAPABILITY", "READY", "WAITING_EXTERNAL", "RETRY_SCHEDULED",
    "AWAITING_VERIFICATION", "COMPLETED", "FAILED_TERMINAL", "CANCELLED",
}
ATTEMPT_OUTCOMES = {"SUCCEEDED", "FAILED", "WAITING_EXTERNAL"}


def _path(request_id: str) -> Path:
    return REQUESTS_DIR / f"{safe_id(request_id, name='request id')}.json"


def _parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("handler timestamps must be timezone-aware")
    return parsed


def _candidate(value: dict, index: int) -> dict:
    if not isinstance(value, dict):
        raise ValueError("candidate path must be an object")
    cid = value.get("id") or f"path-{index}"
    safe_id(cid, name="candidate id")
    required = value.get("required_capabilities", [])
    if not isinstance(required, list) or any(not isinstance(x, str) or not x for x in required):
        raise ValueError("candidate required_capabilities must be capability ids")
    if len(set(required)) != len(required):
        raise ValueError("candidate required_capabilities must be unique")
    command = value.get("command")
    if command is not None and (not isinstance(command, dict) or not isinstance(command.get("kind"), str)):
        raise ValueError("candidate command must be an object with kind")
    out = {"id": cid, "required_capabilities": required}
    if command is not None:
        out["command"] = command
    if value.get("recipe"):
        out["recipe"] = str(value["recipe"])
    if value.get("note"):
        out["note"] = str(value["note"])
    return out


def _assess_candidates(candidates: list[dict], registry: dict | None) -> list[dict]:
    assessed = []
    for candidate in candidates:
        report = gaps.assess(candidate["required_capabilities"], registry=registry)
        assessed.append({**candidate, "assessment": report})
    return assessed


def _choose(assessed: list[dict]) -> dict:
    ready = [c for c in assessed if c["assessment"]["satisfied"]]
    if ready:
        return ready[0]
    # No path is ready. Choose the least-blocked path only to decide which
    # capability gap work to materialize; ties preserve operator-authored order.
    return min(assessed, key=lambda c: (
        len(c["assessment"]["blocked"]) + len(c["assessment"]["unknown"]),
        assessed.index(c),
    ))


def resolve_references(references: list[dict] | None) -> list[dict]:
    """Resolve bounded recent referents; ambiguity is an error, never a guess."""
    out = []
    for ref in references or []:
        if not isinstance(ref, dict):
            raise ValueError("context reference must be an object")
        kind = ref.get("kind")
        label = ref.get("label")
        resolved = context.resolve(kind=kind, label=label)
        out.append({"kind": resolved["kind"], "value": resolved["value"],
                    "label": resolved.get("label", ""), "reference_id": resolved["id"]})
    return out


def create(request_id: str, *, intent: str, required_capabilities: list[str] | None = None,
           command: dict | None = None, candidates: list[dict] | None = None,
           recipe: str | None = None, references: list[dict] | None = None,
           registry: dict | None = None, materialize_gaps: bool = True,
           max_attempts: int = 3) -> dict:
    if _path(request_id).exists():
        raise FileExistsError(request_id)
    if not isinstance(intent, str) or not intent.strip():
        raise ValueError("intent is required")
    if type(max_attempts) is not int or not 1 <= max_attempts <= 20:
        raise ValueError("max_attempts must be 1..20")
    paths = list(candidates or [])
    if recipe:
        plan = composition.plan(recipe, registry=registry)
        paths.insert(0, {"id": f"recipe-{recipe.replace('.', '-')}", "recipe": recipe,
                         "required_capabilities": [s["capability"] for s in plan["steps"]],
                         **({"command": command} if command else {})})
    if not paths:
        paths = [{"id": "primary", "required_capabilities": required_capabilities or [],
                  **({"command": command} if command is not None else {})}]
    paths = [_candidate(v, i + 1) for i, v in enumerate(paths)]
    assessed = _assess_candidates(paths, registry)
    selected = _choose(assessed)
    work = []
    if not selected["assessment"]["satisfied"] and materialize_gaps:
        work = gaps.materialize(selected["required_capabilities"], registry=registry)
    now = utcnow()
    value = {
        "version": 2, "id": safe_id(request_id, name="request id"), "intent": intent.strip(),
        "candidates": paths, "selected_path": selected["id"],
        "required_capabilities": selected["required_capabilities"],
        "assessment": selected["assessment"],
        "state": "READY" if selected["assessment"]["satisfied"] else "BLOCKED_CAPABILITY",
        "gap_tasks": [t["id"] for t in work], "attempts": [], "max_attempts": max_attempts,
        "context": resolve_references(references), "created_at": now, "updated_at": now,
    }
    if selected.get("command") is not None:
        value["command_proposal"] = selected["command"]
    write_json_atomic(_path(request_id), value)
    return value


def load(request_id: str) -> dict:
    return read_json(_path(request_id))


def all_requests() -> list[dict]:
    if not REQUESTS_DIR.is_dir():
        return []
    out = []
    for path in sorted(REQUESTS_DIR.glob("*.json")):
        try: out.append(load(path.stem))
        except ValueError: continue
    return sorted(out, key=lambda x: x.get("updated_at", ""), reverse=True)


def refresh(request_id: str, *, registry: dict | None = None,
            materialize_gaps: bool = True, now: dt.datetime | None = None) -> dict:
    value = load(request_id)
    if value["state"] in {"COMPLETED", "CANCELLED", "FAILED_TERMINAL", "AWAITING_VERIFICATION", "WAITING_EXTERNAL"}:
        return value
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if value["state"] == "RETRY_SCHEDULED":
        due = _parse_time(value["next_retry_at"])
        if now.astimezone(dt.timezone.utc) < due.astimezone(dt.timezone.utc):
            return value
    candidates = value.get("candidates") or [{"id":"primary","required_capabilities":value.get("required_capabilities",[]),
                                                **({"command":value["command_proposal"]} if value.get("command_proposal") else {})}]
    assessed = _assess_candidates([_candidate(c, i + 1) for i, c in enumerate(candidates)], registry)
    selected = _choose(assessed)
    value["selected_path"] = selected["id"]
    value["required_capabilities"] = selected["required_capabilities"]
    value["assessment"] = selected["assessment"]
    if selected.get("command") is not None: value["command_proposal"] = selected["command"]
    else: value.pop("command_proposal", None)
    if selected["assessment"]["satisfied"]:
        value["state"] = "READY"
        value.pop("next_retry_at", None)
    else:
        value["state"] = "BLOCKED_CAPABILITY"
        if materialize_gaps:
            work = gaps.materialize(selected["required_capabilities"], registry=registry)
            value["gap_tasks"] = sorted(set(value.get("gap_tasks", [])) | {t["id"] for t in work})
    value["updated_at"] = utcnow(); write_json_atomic(_path(request_id), value); return value


def record_attempt(request_id: str, *, outcome: str, failure_code: str = "",
                   note: str = "", evidence: str = "", now: dt.datetime | None = None) -> dict:
    if outcome not in ATTEMPT_OUTCOMES:
        raise ValueError(f"outcome must be one of {sorted(ATTEMPT_OUTCOMES)}")
    value = load(request_id)
    if value["state"] != "READY":
        raise ValueError("request is not ready for an attempt")
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    attempt = {"n": len(value.get("attempts", [])) + 1, "at": now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "outcome": outcome, "note": note}
    if failure_code: attempt["failure_code"] = failure_code
    if evidence: attempt["evidence"] = evidence
    value.setdefault("attempts", []).append(attempt)
    if outcome == "SUCCEEDED":
        if evidence.strip():
            value["state"] = "COMPLETED"; value["evidence"] = evidence.strip(); value["completed_at"] = utcnow()
        else:
            value["state"] = "AWAITING_VERIFICATION"
    elif outcome == "WAITING_EXTERNAL":
        value["state"] = "WAITING_EXTERNAL"
    else:
        if not failure_code:
            raise ValueError("FAILED attempt requires failure_code")
        step = recovery.next_step(failure_code=failure_code, attempts=len(value["attempts"]),
                                  max_attempts=value.get("max_attempts", 3), now=now,
                                  jitter_key=value["id"])
        value["recovery"] = step
        if step["decision"] == "RETRY":
            value["state"] = "RETRY_SCHEDULED"; value["next_retry_at"] = step["due_at"]
        else:
            value["state"] = "FAILED_TERMINAL"; value["failed_at"] = utcnow()
    value["updated_at"] = utcnow(); write_json_atomic(_path(request_id), value); return value


def verify(request_id: str, *, evidence: str) -> dict:
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError("verification requires evidence")
    value = load(request_id)
    if value["state"] != "AWAITING_VERIFICATION":
        raise ValueError("request is not awaiting verification")
    value["state"] = "COMPLETED"; value["evidence"] = evidence.strip(); value["completed_at"] = utcnow(); value["updated_at"] = utcnow()
    write_json_atomic(_path(request_id), value); return value


def resume_external(request_id: str, *, evidence: str = "") -> dict:
    value = load(request_id)
    if value["state"] != "WAITING_EXTERNAL":
        raise ValueError("request is not waiting on an external result")
    if evidence.strip():
        value["state"] = "COMPLETED"; value["evidence"] = evidence.strip(); value["completed_at"] = utcnow()
    else:
        value["state"] = "READY"
    value["updated_at"] = utcnow(); write_json_atomic(_path(request_id), value); return value


def complete(request_id: str, *, evidence: str) -> dict:
    value = load(request_id)
    if value["state"] == "AWAITING_VERIFICATION":
        return verify(request_id, evidence=evidence)
    if value["state"] != "READY":
        raise ValueError("request is not ready for completion")
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError("completion requires evidence")
    value["state"] = "COMPLETED"; value["evidence"] = evidence.strip(); value["completed_at"] = utcnow(); value["updated_at"] = utcnow()
    write_json_atomic(_path(request_id), value); return value


def reconcile_all(*, registry: dict | None = None, now: dt.datetime | None = None) -> list[dict]:
    actions = []
    for before in all_requests():
        if before["state"] in {"COMPLETED", "CANCELLED", "FAILED_TERMINAL", "AWAITING_VERIFICATION", "WAITING_EXTERNAL"}:
            continue
        after = refresh(before["id"], registry=registry, now=now)
        if after["state"] != before["state"] or after.get("selected_path") != before.get("selected_path"):
            actions.append({"request": before["id"], "from": before["state"], "to": after["state"],
                            "selected_path": after.get("selected_path")})
    return actions


def cancel(request_id: str, *, reason: str) -> dict:
    value = load(request_id)
    if value["state"] == "COMPLETED":
        raise ValueError("completed request cannot be cancelled")
    value["state"] = "CANCELLED"; value["cancel_reason"] = reason; value["updated_at"] = utcnow()
    write_json_atomic(_path(request_id), value); return value
