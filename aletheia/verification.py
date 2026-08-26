"""Capability-aware ActionRecord helpers.

`outcomes.py` is the durable evidence store. This module adds one missing
piece: capability-specific verification profiles that distinguish execution
proof from outcome proof. A successful API/UI call is recorded as an attempt;
it is only auto-VERIFIED when the capability's low-level result is itself the
promised outcome (for example computer UIA read-back or a provider-confirmed
calendar write). Email send, browser interaction, schedule dispatch and agent
delegation deliberately remain AWAITING_VERIFICATION after execution.
"""
from __future__ import annotations

import hashlib
import json
import uuid

from aletheia import outcomes

PROFILES = {
    "computer.control": {"auto_verify_execution": True,"execution_evidence": "backend read-back/step verification","outcome_evidence": "the approved desktop plan itself is the bounded outcome"},
    "calendar.write": {"auto_verify_execution": True,"execution_evidence": "provider returned normalized state matching the approved plan","outcome_evidence": "provider state matches requested calendar state"},
    "browser.interact": {"auto_verify_execution": False,"execution_evidence": "approved browser steps completed","outcome_evidence": "site state proves the user's intended result"},
    "email.send": {"auto_verify_execution": False,"execution_evidence": "SMTP accepted the message and local exactly-once receipt exists","outcome_evidence": "delivery/receipt evidence or another independently observed result"},
    "automation.execute": {"auto_verify_execution": False,"execution_evidence": "occurrence claimed exactly once and command returned done","outcome_evidence": "the scheduled command's intended external result is independently observed"},
    "agent.delegate": {"auto_verify_execution": False,"execution_evidence": "work order created and task parked WAITING_EXTERNAL","outcome_evidence": "worker completes the task with evidence accepted by the orchestrator"},
}


def profile(capability: str) -> dict:
    return dict(PROFILES.get(capability, {"auto_verify_execution": False,"execution_evidence": "capability returned without exception","outcome_evidence": "independent evidence of the intended result"}))


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_action_id(capability: str, *, seed: object | None = None) -> str:
    prefix = capability.replace(".", "-")[:30]
    suffix = _digest(seed)[:16] if seed is not None else uuid.uuid4().hex[:16]
    return f"verify-{prefix}-{suffix}"[:64]


def begin(capability: str, *, provider: str, intent: str, plan: dict,
          requested_by: str = "operator", approval_id: str | None = None,
          policy_decision: str | None = None, reversible: bool | None = None,
          inputs_summary: str = "", data_disclosed: list[str] | None = None,
          action_id: str | None = None) -> dict:
    action_id = action_id or new_action_id(capability)
    try:
        existing = outcomes.load(action_id)
    except (FileNotFoundError, ValueError):
        existing = None
    if existing is not None:
        if existing["capability"] != capability or existing["plan_sha256"] != _digest(plan):
            raise ValueError("existing verification action does not match requested plan")
        return existing
    return outcomes.start(action_id, capability=capability, provider=provider, intent=intent, plan=plan,
                          requested_by=requested_by, approval_id=approval_id,
                          policy_decision=policy_decision, reversible=reversible,
                          inputs_summary=inputs_summary, data_disclosed=data_disclosed)


def record_execution(action_id: str, *, succeeded: bool, result_summary: str,
                     evidence: list[dict] | None = None,
                     failure_terminal: bool = False,
                     auto_verify: bool | None = None) -> dict:
    value = outcomes.load(action_id)
    if value["status"] in outcomes.TERMINAL:
        return value
    if value["status"] in {"STARTED", "FAILED_RETRYABLE"}:
        outcomes.add_attempt(action_id,
            outcome="SUCCEEDED" if succeeded else ("FAILED_TERMINAL" if failure_terminal else "FAILED_RETRYABLE"),
            result_summary=result_summary)
    if not succeeded:
        return outcomes.load(action_id)
    for item in evidence or []:
        eid = item.get("id") or f"ev-{len(outcomes.load(action_id)['evidence']) + 1}"
        current = outcomes.load(action_id)
        if any(e.get("id") == eid for e in current["evidence"]):
            continue
        outcomes.add_evidence(action_id, eid, kind=item["kind"], observed=item.get("observed"),
                              expected=item.get("expected"), source=item.get("source", "local"))
    current = outcomes.load(action_id)
    should_verify = profile(current["capability"])["auto_verify_execution"] if auto_verify is None else auto_verify
    if should_verify and current["status"] == "AWAITING_VERIFICATION" and current["evidence"]:
        return outcomes.verify(action_id)
    return current


def execution_record(capability: str, *, provider: str, intent: str, plan: dict,
                     succeeded: bool, result_summary: str,
                     evidence: list[dict] | None = None,
                     requested_by: str = "operator", approval_id: str | None = None,
                     policy_decision: str | None = None, reversible: bool | None = None,
                     inputs_summary: str = "", data_disclosed: list[str] | None = None,
                     action_id: str | None = None,
                     auto_verify: bool | None = None,
                     failure_terminal: bool = False) -> dict:
    record = begin(capability, provider=provider, intent=intent, plan=plan,
                   requested_by=requested_by, approval_id=approval_id,
                   policy_decision=policy_decision, reversible=reversible,
                   inputs_summary=inputs_summary, data_disclosed=data_disclosed,
                   action_id=action_id)
    return record_execution(record["id"], succeeded=succeeded, result_summary=result_summary,
                            evidence=evidence, auto_verify=auto_verify,
                            failure_terminal=failure_terminal)
