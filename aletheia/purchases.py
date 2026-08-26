"""High-risk purchase plans with exact-content operator authorization.

There is deliberately no checkout transport here. Aletheia may prepare a cart,
but spending money remains operator_always: authorization is bound to the hash
of merchant, line items, currency and total. No card/bank data is accepted or
stored by this module.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from aletheia import policy
from aletheia.stateio import create_json_exclusive, private_dir, read_json, safe_id, utcnow, write_json_atomic

PROPOSALS_DIR = private_dir("purchases") / "proposals"
AUTH_DIR = private_dir("purchases") / "authorized"
RESULTS_DIR = private_dir("purchases") / "results"


def _proposal_path(purchase_id: str) -> Path:
    return PROPOSALS_DIR / f"{safe_id(purchase_id, name='purchase id')}.json"


def _auth_path(purchase_id: str) -> Path:
    return AUTH_DIR / f"{safe_id(purchase_id, name='purchase id')}.json"


def _money(value: str) -> Decimal:
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"invalid money amount {value!r}") from exc
    if amount < 0 or amount.as_tuple().exponent < -2:
        raise ValueError("money must be non-negative with at most two decimal places")
    return amount.quantize(Decimal("0.01"))


def _canonical_hash(plan: dict) -> str:
    raw = json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def propose(purchase_id: str, *, merchant: str, items: list[dict], currency: str = "USD",
            expires_at: str | None = None) -> dict:
    safe_id(purchase_id, name="purchase id")
    if not isinstance(merchant, str) or not merchant.strip():
        raise ValueError("merchant is required")
    if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha() or currency.upper() != currency:
        raise ValueError("currency must be a 3-letter uppercase code")
    if not isinstance(items, list) or not items:
        raise ValueError("purchase requires at least one line item")
    normalized = []
    total = Decimal("0.00")
    for index, item in enumerate(items):
        if not isinstance(item, dict) or set(item) != {"description", "quantity", "unit_price"}:
            raise ValueError(f"item {index} must contain description, quantity and unit_price")
        if not isinstance(item["description"], str) or not item["description"].strip():
            raise ValueError(f"item {index} description is required")
        if type(item["quantity"]) is not int or item["quantity"] < 1 or item["quantity"] > 999:
            raise ValueError(f"item {index} quantity must be 1..999")
        unit = _money(item["unit_price"])
        line = unit * item["quantity"]
        total += line
        normalized.append({"description": item["description"].strip(), "quantity": item["quantity"],
                           "unit_price": f"{unit:.2f}", "line_total": f"{line:.2f}"})
    plan = {"merchant": merchant.strip(), "items": normalized, "currency": currency,
            "total": f"{total:.2f}"}
    if expires_at:
        parsed = dt.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("purchase expiry must be timezone-aware")
        if parsed.astimezone(dt.timezone.utc) <= dt.datetime.now(dt.timezone.utc):
            raise ValueError("purchase expiry must be in the future")
        plan["expires_at"] = parsed.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    value = {"version": 1, "id": purchase_id, "plan": plan,
             "plan_sha256": _canonical_hash(plan), "state": "PROPOSED", "created_at": utcnow()}
    write_json_atomic(_proposal_path(purchase_id), value)
    return value


def load_proposal(purchase_id: str) -> dict:
    value = read_json(_proposal_path(purchase_id))
    if value.get("plan_sha256") != _canonical_hash(value.get("plan", {})):
        raise ValueError("purchase proposal hash does not match plan")
    return value


def approval_action(proposal: dict) -> str:
    return f"authorize purchase {proposal['id']} sha256:{proposal['plan_sha256']}"


def authorize(purchase_id: str, approval_id: str) -> dict:
    proposal = load_proposal(purchase_id)
    approval = policy.load(approval_id)
    if approval.get("state") != "APPROVED" or approval.get("requested_action") != approval_action(proposal):
        raise PermissionError("approval is not bound to this exact purchase plan")
    expiry = proposal["plan"].get("expires_at")
    if expiry:
        parsed = dt.datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        if parsed <= dt.datetime.now(dt.timezone.utc):
            raise PermissionError("purchase plan has expired")
    value = {"version": 1, "id": purchase_id, "plan_sha256": proposal["plan_sha256"],
             "approval_id": approval_id, "state": "AUTHORIZED_NOT_EXECUTED", "authorized_at": utcnow()}
    create_json_exclusive(_auth_path(purchase_id), value)
    return value


def execution_envelope(purchase_id: str) -> dict:
    proposal = load_proposal(purchase_id)
    authorization = read_json(_auth_path(purchase_id))
    if authorization.get("plan_sha256") != proposal["plan_sha256"] or authorization.get("state") != "AUTHORIZED_NOT_EXECUTED":
        raise PermissionError("purchase does not have a matching authorization")
    policy.ensure_not_halted()
    return {"purchase_id": purchase_id, "plan": proposal["plan"],
            "plan_sha256": proposal["plan_sha256"], "approval_id": authorization["approval_id"]}


def record_result(purchase_id: str, *, status: str, order_reference: str = "",
                  observed_total: str | None = None) -> dict:
    if status not in {"EXECUTED", "FAILED", "CANCELLED"}:
        raise ValueError("invalid purchase result status")
    proposal = load_proposal(purchase_id)
    read_json(_auth_path(purchase_id))  # must have been authorized
    value = {"version": 1, "id": purchase_id, "status": status,
             "plan_sha256": proposal["plan_sha256"], "recorded_at": utcnow()}
    if order_reference:
        value["order_reference"] = order_reference
    if observed_total is not None:
        observed = _money(observed_total)
        approved = _money(proposal["plan"]["total"])
        value["observed_total"] = f"{observed:.2f}"
        value["total_matches"] = observed == approved
    create_json_exclusive(RESULTS_DIR / f"{safe_id(purchase_id)}.json", value)
    return value
