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


HANDOFF_DIR = private_dir("finance") / "handoffs"


def hand_off(handoff_id: str, *, kind: str, amount: float, currency: str = "USD",
             payee: str, from_account: str | None = None, due: str = "",
             why: str = "") -> dict:
    """Carry a money movement to the boundary and stop there (§143).

    `finance.transact` is NOT_BUILT, and that is a decision rather than a
    backlog item. Bank transfers, bill payments and trades are gated by
    identity checks, step-up authentication and terms that specifically
    forbid automation — §143's list, almost word for word. There the
    boundary IS the mechanism, not an obstacle standing in front of one,
    and an errand that drove his bank's login page would be defeating a
    control that exists for his benefit.

    So this is the other half of that sentence: "carry the task to the
    boundary; minimize Caleb's remaining work." Everything up to the
    moment of authorization — which account, to whom, how much, by when,
    and why he asked — is computed, recorded and surfaced, so what remains
    is him approving a payment he can see in full, not him reconstructing
    it from memory. Nothing here touches an account, and no credential is
    accepted or stored.
    """
    if not isinstance(amount, (int, float)) or amount <= 0:
        raise ValueError("amount must be a positive number")
    if not str(payee).strip():
        raise ValueError("a payee is required — a transfer to nobody is not a task")
    if from_account is not None:
        load_account(from_account)  # refuse an account we have never seen
    value = {
        "version": 1, "id": safe_id(handoff_id, name="handoff id"),
        "kind": kind, "amount": float(amount), "currency": currency,
        "payee": str(payee), "from_account": from_account, "due": due, "why": why,
        "state": "AWAITING_OPERATOR",
        "boundary": ("§143: moving money is identity-checked and deliberately "
                     "closed to automation — this is yours to authorize"),
        "remaining_work": (f"open {payee} or your bank and authorize "
                           f"{currency} {amount:.2f}"),
        "prepared_at": utcnow(),
    }
    write_json_atomic(HANDOFF_DIR / f"{value['id']}.json", value)
    return value


def handoffs(*, pending_only: bool = True) -> list[dict]:
    if not HANDOFF_DIR.is_dir():
        return []
    out = []
    for path in sorted(HANDOFF_DIR.glob("*.json")):
        try:
            value = read_json(path)
        except ValueError:
            continue
        if not pending_only or value.get("state") == "AWAITING_OPERATOR":
            out.append(value)
    return out


def settle(handoff_id: str, *, reference: str) -> dict:
    """He did it himself; record the reference he gives back.

    Evidence, not assumption (§30): a hand-off becomes SETTLED because he
    says so with a confirmation number, never because time passed.
    """
    if not str(reference).strip():
        raise ValueError("a settlement needs the reference he was given")
    path = HANDOFF_DIR / f"{safe_id(handoff_id, name='handoff id')}.json"
    value = read_json(path)
    value["state"] = "SETTLED"
    value["reference"] = str(reference)
    value["settled_at"] = utcnow()
    write_json_atomic(path, value)
    return value


def net_worth(*, currency: str = "USD") -> dict:
    values = [a for a in accounts() if a.get("currency") == currency]
    assets = sum(a["balance"] for a in values if a["kind"] not in {"credit", "loan"})
    liabilities = sum(abs(a["balance"]) for a in values if a["kind"] in {"credit", "loan"})
    return {"currency": currency, "assets": assets, "liabilities": liabilities,
            "net": assets - liabilities, "accounts": len(values), "authority": "read_only_snapshot"}
