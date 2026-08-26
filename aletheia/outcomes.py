"""Action records and evidence-backed verification.

A capability invocation is not success merely because no exception was raised.
This module records attempts separately from verification and supports a small,
data-only set of evidence checks. It never executes shell/code from evidence.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from aletheia.fleet import REPO_ROOT
from aletheia.stateio import read_json, safe_id, utcnow, write_json_atomic

ACTIONS_DIR = REPO_ROOT / "state" / "actions"


def _path(action_id: str) -> Path:
    return ACTIONS_DIR / f"{safe_id(action_id, name='action id')}.json"


def start(action_id: str, *, capability: str, intent: str, plan: dict,
          approval_id: str | None = None) -> dict:
    path = _path(action_id)
    if path.exists():
        raise FileExistsError(action_id)
    canonical = json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    value = {"version": 1, "id": action_id, "capability": capability, "intent": intent,
             "plan": plan, "plan_sha256": hashlib.sha256(canonical).hexdigest(), "status": "STARTED",
             "attempts": [], "evidence": [], "created_at": utcnow(), "updated_at": utcnow()}
    if approval_id:
        value["approval_id"] = approval_id
    write_json_atomic(path, value)
    return value


def load(action_id: str) -> dict:
    return read_json(_path(action_id))


def add_attempt(action_id: str, *, outcome: str, note: str = "") -> dict:
    if outcome not in {"SUCCEEDED", "FAILED_RETRYABLE", "FAILED_TERMINAL"}:
        raise ValueError("invalid attempt outcome")
    value = load(action_id)
    if value["status"] in {"VERIFIED", "FAILED_TERMINAL"}:
        raise ValueError("action already terminal")
    value["attempts"].append({"at": utcnow(), "outcome": outcome, "note": note})
    value["status"] = "AWAITING_VERIFICATION" if outcome == "SUCCEEDED" else outcome
    value["updated_at"] = utcnow()
    write_json_atomic(_path(action_id), value)
    return value


def add_evidence(action_id: str, evidence_id: str, *, kind: str, observed: object,
                 expected: object | None = None, source: str = "local") -> dict:
    safe_id(evidence_id, name="evidence id")
    if kind not in {"equals", "contains", "exists", "truthy"}:
        raise ValueError("unsupported evidence kind")
    value = load(action_id)
    evidence = {"id": evidence_id, "kind": kind, "observed": observed,
                "source": source, "recorded_at": utcnow()}
    if expected is not None:
        evidence["expected"] = expected
    if any(e["id"] == evidence_id for e in value["evidence"]):
        raise FileExistsError(evidence_id)
    value["evidence"].append(evidence)
    value["updated_at"] = utcnow()
    write_json_atomic(_path(action_id), value)
    return evidence


def evidence_passes(e: dict) -> bool:
    kind = e["kind"]
    observed = e.get("observed")
    expected = e.get("expected")
    if kind == "equals":
        return observed == expected
    if kind == "contains":
        try:
            return expected in observed
        except TypeError:
            return False
    if kind == "exists":
        return observed is not None
    return bool(observed)


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
    write_json_atomic(_path(action_id), value)
    return value
