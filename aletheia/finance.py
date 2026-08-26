"""Private read-only financial visibility model.

Stores provider/operator snapshots for balances, bills and transactions. This
module has no transfer/payment/trade function by design; money movement remains
L4 and requires a separate capability plus approval.
"""
from __future__ import annotations

from pathlib import Path

from aletheia.stateio import create_json_exclusive, private_dir, read_json, safe_id, utcnow, write_json_atomic

ACCOUNTS_DIR = private_dir("finance") / "accounts"
TX_DIR = private_dir("finance") / "transactions"


def _account_path(account_id: str) -> Path:
    return ACCOUNTS_DIR / f"{safe_id(account_id, name='account id')}.json"


def record_account(account_id: str, *, name: str, kind: str, balance: float,
                   currency: str = "USD", source: str, as_of: str | None = None) -> dict:
    if kind not in {"checking", "savings", "credit", "investment", "loan", "cash", "other"}:
        raise ValueError("unsupported account kind")
    if not isinstance(balance, (int, float)):
        raise ValueError("balance must be numeric")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source/provenance is required")
    value = {"version": 1, "id": safe_id(account_id, name="account id"), "name": name,
             "kind": kind, "balance": float(balance), "currency": currency, "source": source,
             "as_of": as_of or utcnow(), "updated_at": utcnow()}
    write_json_atomic(_account_path(account_id), value)
    return value


def load_account(account_id: str) -> dict:
    return read_json(_account_path(account_id))


def accounts() -> list[dict]:
    if not ACCOUNTS_DIR.is_dir():
        return []
    out = []
    for path in sorted(ACCOUNTS_DIR.glob("*.json")):
        try:
            out.append(load_account(path.stem))
        except ValueError:
            continue
    return out


def record_transaction(transaction_id: str, *, account_id: str, amount: float,
                       description: str, occurred_at: str, source: str) -> dict:
    load_account(account_id)
    if not isinstance(amount, (int, float)):
        raise ValueError("amount must be numeric")
    value = {"version": 1, "id": safe_id(transaction_id, name="transaction id"),
             "account_id": account_id, "amount": float(amount), "description": description,
             "occurred_at": occurred_at, "source": source, "recorded_at": utcnow()}
    create_json_exclusive(TX_DIR / safe_id(account_id) / f"{transaction_id}.json", value)
    return value


def net_worth(*, currency: str = "USD") -> dict:
    values = [a for a in accounts() if a.get("currency") == currency]
    assets = sum(a["balance"] for a in values if a["kind"] not in {"credit", "loan"})
    liabilities = sum(abs(a["balance"]) for a in values if a["kind"] in {"credit", "loan"})
    return {"currency": currency, "assets": assets, "liabilities": liabilities,
            "net": assets - liabilities, "accounts": len(values), "authority": "read_only_snapshot"}
