"""Conversation contract for an approved Aletheia phone call.

Phone V0 may use ChatGPT Voice, a future local model, or another reviewed voice
provider. The model provider must not define the call's authority. This module
turns the already-approved ``calls.py`` envelope into a bounded conversation
brief whose hash is tied to the approved call-plan hash.

It contains no dialer and no model integration. It exists so every future voice
bridge receives the same identity disclosure, purpose, allowed disclosures,
forbidden topics, success condition, time budget, and escalation rules.
"""
from __future__ import annotations

import hashlib
import json

from aletheia import calls

CONDUCT = [
    "Identify yourself as Aletheia, an AI assistant calling on behalf of the operator before substantive conversation.",
    "Never claim to be the operator or a human.",
    "Do not disclose information outside allowed_disclosures.",
    "Do not discuss forbidden_topics; offer operator handoff when needed.",
    "Do not agree to payments, contracts, legal terms, medical consent, or other high-impact commitments unless a separate approved capability explicitly authorizes that exact action.",
    "If the requested result cannot be achieved within the approved boundaries, report the blocker instead of inventing permission.",
]


def _hash(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build(call_id: str) -> dict:
    """Return the voice-provider brief for an already-authorized call."""
    envelope = calls.execution_envelope(call_id)
    plan = envelope["plan"]
    if plan.get("identity_disclosure") != calls.IDENTITY_DISCLOSURE:
        raise ValueError("call identity disclosure does not match the conduct contract")
    brief = {
        "version": 1,
        "call_id": call_id,
        "call_plan_sha256": envelope["plan_sha256"],
        "identity_disclosure": calls.IDENTITY_DISCLOSURE,
        "purpose": plan["purpose"],
        "contact_ref": plan["contact_ref"],
        "allowed_disclosures": list(plan.get("allowed_disclosures", [])),
        "forbidden_topics": list(plan.get("forbidden_topics", [])),
        "max_minutes": plan["max_minutes"],
        "conduct": list(CONDUCT),
    }
    if plan.get("success_condition"):
        brief["success_condition"] = plan["success_condition"]
    brief["brief_sha256"] = _hash({k: v for k, v in brief.items() if k != "brief_sha256"})
    return brief


def validate(brief: dict, call_id: str) -> dict:
    """Verify a provider-bound brief still matches the approved call plan."""
    if not isinstance(brief, dict):
        raise ValueError("phone conversation brief must be an object")
    expected = build(call_id)
    if brief.get("brief_sha256") != expected["brief_sha256"]:
        raise ValueError("phone conversation brief hash does not match approved call plan")
    if brief != expected:
        raise ValueError("phone conversation brief content drifted after approval")
    return expected


def provider_prompt(brief: dict, call_id: str) -> str:
    """Render bounded instructions for a voice provider after validation.

    The prompt is generated from approved structured data; callers cannot inject
    extra authority through an arbitrary free-form system prompt here.
    """
    value = validate(brief, call_id)
    allowed = ", ".join(value["allowed_disclosures"]) or "none beyond what is necessary to identify the purpose"
    forbidden = ", ".join(value["forbidden_topics"]) or "none specifically listed; normal policy still applies"
    success = value.get("success_condition", "collect the relevant result and report it back")
    conduct = "\n".join(f"- {line}" for line in value["conduct"])
    return (
        f"You are Aletheia handling approved call {value['call_id']}.\n"
        f"Open with exactly this identity disclosure: {value['identity_disclosure']}\n"
        f"Purpose: {value['purpose']}\n"
        f"Success condition: {success}\n"
        f"Allowed disclosures: {allowed}\n"
        f"Forbidden topics: {forbidden}\n"
        f"Maximum call duration: {value['max_minutes']} minutes.\n"
        "Conduct rules:\n" + conduct
    )
