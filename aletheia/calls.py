"""Approval-bound phone-call plans for future Phone V0 executors.

This module cannot dial. It defines exactly what a future audio/call adapter is
allowed to attempt: who to call, why, disclosure boundaries and time budget.
Every plan identifies Aletheia as an AI assistant and requires an operator
approval bound to the exact plan hash before an execution envelope exists.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from aletheia import policy
from aletheia.stateio import create_json_exclusive, private_dir, read_json, safe_id, utcnow, write_json_atomic

PLANS_DIR = private_dir("calls") / "plans"
AUTH_DIR = private_dir("calls") / "authorized"
RESULTS_DIR = private_dir("calls") / "results"
IDENTITY_DISCLOSURE = "This is Aletheia, an AI assistant calling on behalf of the operator."


def _plan_path(call_id: str) -> Path:
    return PLANS_DIR / f"{safe_id(call_id, name='call id')}.json"


def _auth_path(call_id: str) -> Path:
    return AUTH_DIR / f"{safe_id(call_id, name='call id')}.json"


def _hash(plan: dict) -> str:
    raw = json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _clean_list(values: list[str] | None, name: str) -> list[str]:
    values = values or []
    if not isinstance(values, list) or len(values) > 30 or any(not isinstance(v, str) or not v.strip() for v in values):
        raise ValueError(f"{name} must contain at most 30 non-empty strings")
    return [v.strip() for v in values]


def propose(call_id: str, *, contact_ref: str, purpose: str,
            allowed_disclosures: list[str] | None = None,
            forbidden_topics: list[str] | None = None,
            success_condition: str = "", max_minutes: int = 10) -> dict:
    safe_id(call_id, name="call id")
    if not isinstance(contact_ref, str) or not contact_ref.strip():
        raise ValueError("contact_ref is required")
    if not isinstance(purpose, str) or not purpose.strip():
        raise ValueError("call purpose is required")
    if type(max_minutes) is not int or not 1 <= max_minutes <= 60:
        raise ValueError("max_minutes must be 1..60")
    if success_condition and (not isinstance(success_condition, str) or not success_condition.strip()):
        raise ValueError("success_condition must be a string")
    plan = {"contact_ref": contact_ref.strip(), "purpose": purpose.strip(),
            "identity_disclosure": IDENTITY_DISCLOSURE,
            "allowed_disclosures": _clean_list(allowed_disclosures, "allowed_disclosures"),
            "forbidden_topics": _clean_list(forbidden_topics, "forbidden_topics"),
            "max_minutes": max_minutes}
    if success_condition:
        plan["success_condition"] = success_condition.strip()
    value = {"version": 1, "id": call_id, "plan": plan, "plan_sha256": _hash(plan),
             "state": "PROPOSED", "created_at": utcnow()}
    write_json_atomic(_plan_path(call_id), value)
    return value


def load_plan(call_id: str) -> dict:
    value = read_json(_plan_path(call_id))
    if value.get("plan_sha256") != _hash(value.get("plan", {})):
        raise ValueError("call plan hash does not match content")
    if value.get("plan", {}).get("identity_disclosure") != IDENTITY_DISCLOSURE:
        raise ValueError("call plan identity disclosure was altered")
    return value


def approval_action(plan: dict) -> str:
    return f"authorize call {plan['id']} sha256:{plan['plan_sha256']}"


def authorize(call_id: str, approval_id: str) -> dict:
    plan = load_plan(call_id)
    approval = policy.load(approval_id)
    if approval.get("state") != "APPROVED" or approval.get("requested_action") != approval_action(plan):
        raise PermissionError("approval is not bound to this exact call plan")
    value = {"version": 1, "id": call_id, "plan_sha256": plan["plan_sha256"],
             "approval_id": approval_id, "state": "AUTHORIZED_NOT_DIALED", "authorized_at": utcnow()}
    create_json_exclusive(_auth_path(call_id), value)
    return value


def execution_envelope(call_id: str) -> dict:
    policy.ensure_not_halted()
    plan = load_plan(call_id)
    authorization = read_json(_auth_path(call_id))
    if authorization.get("state") != "AUTHORIZED_NOT_DIALED" or authorization.get("plan_sha256") != plan["plan_sha256"]:
        raise PermissionError("call authorization does not match current plan")
    return {"call_id": call_id, "plan": plan["plan"], "plan_sha256": plan["plan_sha256"],
            "approval_id": authorization["approval_id"]}


def record_outcome(call_id: str, *, status: str, summary: str,
                   verified: bool = False) -> dict:
    if status not in {"COMPLETED", "NO_ANSWER", "BUSY", "FAILED", "CANCELLED"}:
        raise ValueError("invalid call outcome")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("call outcome summary is required")
    plan = load_plan(call_id)
    read_json(_auth_path(call_id))
    value = {"version": 1, "id": call_id, "status": status, "summary": summary.strip(),
             "verified": bool(verified), "plan_sha256": plan["plan_sha256"], "recorded_at": utcnow()}
    create_json_exclusive(RESULTS_DIR / f"{safe_id(call_id)}.json", value)
    return value
