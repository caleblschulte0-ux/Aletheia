"""Private recurring subscription/obligation visibility.

Tracks recurring charges and renewal/cancellation intent. It never cancels or
pays anything directly; external actions require separate provider capability
and approval.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

SUBS_DIR = private_dir("subscriptions")
STATUSES = {"ACTIVE", "PAUSED", "CANCEL_REQUESTED", "CANCELLED", "UNKNOWN"}


def _path(subscription_id: str) -> Path:
    return SUBS_DIR / f"{safe_id(subscription_id, name='subscription id')}.json"


def create(subscription_id: str, *, merchant: str, amount: float | None = None,
           cadence: str = "monthly", next_charge: str | None = None,
           source: str = "operator") -> dict:
    if _path(subscription_id).exists():
        raise FileExistsError(subscription_id)
    if not isinstance(merchant, str) or not merchant.strip():
        raise ValueError("merchant is required")
    if amount is not None and (not isinstance(amount, (int, float)) or amount < 0):
        raise ValueError("amount must be non-negative")
    if cadence not in {"weekly", "monthly", "quarterly", "annual", "other"}:
        raise ValueError("unsupported cadence")
    if next_charge:
        dt.date.fromisoformat(next_charge)
    now = utcnow()
    value = {"version": 1, "id": safe_id(subscription_id, name="subscription id"),
             "merchant": merchant.strip(), "amount": amount, "cadence": cadence,
             "next_charge": next_charge, "status": "ACTIVE", "source": source,
             "created_at": now, "updated_at": now}
    write_json_atomic(_path(subscription_id), value)
    return value


def load(subscription_id: str) -> dict:
    return read_json(_path(subscription_id))


def all_subscriptions(*, active_only: bool = False) -> list[dict]:
    if not SUBS_DIR.is_dir():
        return []
    out = []
    for path in SUBS_DIR.glob("*.json"):
        try:
            value = load(path.stem)
        except ValueError:
            continue
        if not active_only or value.get("status") == "ACTIVE":
            out.append(value)
    return sorted(out, key=lambda x: (x.get("next_charge") or "9999-12-31", x["merchant"]))


def monthly_equivalent(value: dict) -> float | None:
    amount = value.get("amount")
    if amount is None:
        return None
    return {"weekly": amount * 52 / 12, "monthly": amount, "quarterly": amount / 3,
            "annual": amount / 12, "other": amount}.get(value["cadence"])


def request_cancel(subscription_id: str) -> dict:
    value = load(subscription_id)
    if value["status"] == "CANCELLED":
        return value
    value["status"] = "CANCEL_REQUESTED"
    value["cancel_proposal"] = {"required_capability": "subscription.cancel",
                                "required_approval": "operator_always", "authority": "proposal_only"}
    value["updated_at"] = utcnow()
    write_json_atomic(_path(subscription_id), value)
    return value
