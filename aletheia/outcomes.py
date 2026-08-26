"""Action records and evidence-backed verification.

A capability invocation is not success merely because no exception was raised.
This module records attempts separately from verification and implements the
Playbook ActionRecord vocabulary without executing code from evidence.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

ACTIONS_DIR = private_dir("actions")
TERMINAL = {"VERIFIED", "FAILED_TERMINAL", "CANCELLED"}
ATTEMPT_OUTCOMES = {"SUCCEEDED", "FAILED_RETRYABLE", "FAILED_TERMINAL"}
EVIDENCE_KINDS = {"equals", "contains", "exists", "truthy"}


def _path(action_id: str) -> Path:
    return ACTIONS_DIR / f"{safe_id(action_id, name='action id')}.json"


def _canonical_hash(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate(value: dict) -> None:
    required = {"version", "id", "capability", "provider", "requested_by", "intent",
                "plan", "plan_sha256", "status", "attempts", "evidence", "created_at", "updated_at"}
    missing = required - value.keys()
    if missing:
        raise ValueError(f"action record missing {sorted(missing)}")
    if value["version"] != 1:
        raise ValueError("unsupported action record version")
    safe_id(value["id"], name="action id")
    if value["plan_sha256"] != _canonical_hash(value["plan"]):
        raise ValueError("action plan hash does not match plan")
    if value["status"] not in {"STARTED", "AWAITING_VERIFICATION", "VERIFIED",
                               "FAILED_RETRYABLE", "FAILED_TERMINAL", "CANCELLED"}:
        raise ValueError("invalid action status")
    if not isinstance(value["attempts"], list) or not isinstance(value["evidence"], list):
        raise ValueError("attempts and evidence must be lists")


def start(action_id: str, *, capability: str, provider: str, intent: str, plan: dict,
          requested_by: str = "operator", approval_id: str | None = None,
          policy_decision: str | None = None, reversible: bool | None = None,
          inputs_summary: str = "", data_disclosed: list[str] | None = None) -> dict:
    path = _path(action_id)
    if path.exists():
        raise FileExistsError(action_id)
    value = {
        "version": 1, "id": safe_id(action_id, name="action id"), "capability": capability,
        "provider": provider, "requested_by": requested_by, "intent": intent, "plan": plan,
        "plan_sha256": _canonical_hash(plan), "status": "STARTED", "attempts": [], "evidence": [],
        "inputs_summary": inputs_summary, "data_disclosed": data_disclosed or [],
        "created_at": utcnow(), "updated_at": utcnow(),
    }
    if approval_id:
        value["approval_id"] = approval_id
    if policy_decision is not None:
        value["policy_decision"] = policy_decision
    if reversible is not None:
        value["reversible"] = reversible
    validate(value)
    write_json_atomic(path, value)
    return value


def load(action_id: str) -> dict:
    value = read_json(_path(action_id))
    validate(value)
    return value


def all_actions() -> list[dict]:
    if not ACTIONS_DIR.is_dir():
        return []
    out = []
    for path in sorted(ACTIONS_DIR.glob("*.json")):
        try:
            out.append(load(path.stem))
        except ValueError:
            continue
    return sorted(out, key=lambda x: x["created_at"], reverse=True)


def add_attempt(action_id: str, *, outcome: str, note: str = "", result_summary: str = "") -> dict:
    if outcome not in ATTEMPT_OUTCOMES:
        raise ValueError("invalid attempt outcome")
    value = load(action_id)
    if value["status"] in TERMINAL:
        raise ValueError("action already terminal")
    value["attempts"].append({"at": utcnow(), "outcome": outcome, "note": note})
    value["status"] = "AWAITING_VERIFICATION" if outcome == "SUCCEEDED" else outcome
    if result_summary:
        value["result"] = result_summary
    value["updated_at"] = utcnow()
    validate(value)
    write_json_atomic(_path(action_id), value)
    return value


def add_evidence(action_id: str, evidence_id: str, *, kind: str, observed: object,
                 expected: object | None = None, source: str = "local") -> dict:
    safe_id(evidence_id, name="evidence id")
    if kind not in EVIDENCE_KINDS:
        raise ValueError("unsupported evidence kind")
    value = load(action_id)
    if value["status"] in TERMINAL:
        raise ValueError("action already terminal")
    if any(e.get("id") == evidence_id for e in value["evidence"]):
        raise FileExistsError(evidence_id)
    evidence = {"id": evidence_id, "kind": kind, "observed": observed,
                "source": source, "recorded_at": utcnow()}
    if expected is not None:
        evidence["expected"] = expected
    value["evidence"].append(evidence)
    value["updated_at"] = utcnow()
    validate(value)
    write_json_atomic(_path(action_id), value)
    return evidence


def evidence_passes(evidence: dict) -> bool:
    kind = evidence.get("kind")
    observed = evidence.get("observed")
    expected = evidence.get("expected")
    if kind == "equals":
        return observed == expected
    if kind == "contains":
        try:
            return expected in observed
        except (TypeError, ValueError):
            return False
    if kind == "exists":
        return observed is not None
    if kind == "truthy":
        return bool(observed)
    return False


def verify(action_id: str, *, require_all: bool = True) -> dict:
    value = load(action_id)
    if value["status"] != "AWAITING_VERIFICATION":
        raise ValueError("action is not awaiting verification")
    if not value["evidence"]:
        raise ValueError("verification requires evidence")
    checks = [evidence_passes(e) for e in value["evidence"]]
    passed = all(checks) if require_all else any(checks)
    value["status"] = "VERIFIED" if passed else "FAILED_RETRYABLE"
    value["verified_at"] = utcnow()
    value["verification"] = {"passed": passed, "checks": checks, "require_all": require_all}
    value["updated_at"] = utcnow()
    validate(value)
    write_json_atomic(_path(action_id), value)
    return value


def cancel(action_id: str, reason: str) -> dict:
    value = load(action_id)
    if value["status"] in TERMINAL:
        return value
    value["status"] = "CANCELLED"
    value["result"] = reason
    value["updated_at"] = utcnow()
    validate(value)
    write_json_atomic(_path(action_id), value)
    return value
