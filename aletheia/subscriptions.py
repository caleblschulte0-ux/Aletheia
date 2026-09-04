"""Private recurring subscription/obligation visibility — and the last mile.

Tracks recurring charges and renewal/cancellation intent. It never spends
anything, and it still cancels nothing on its own authority: the actual
cancelling is a `webtask` run, which stops at the button and waits for
him exactly like every other irreversible thing.

That last part closes a dead end. `request_cancel` used to set
CANCEL_REQUESTED, name the capability `subscription.cancel`, and stop —
and the only way to reach that capability was to hand-type a JSON list of
browser selectors at a command line. So "cancel my gym membership"
produced a record that said CANCEL_REQUESTED forever, with nothing able
to carry it out and nothing saying so. A capability nothing can call is
not a capability.

Two rules it keeps, because a subscription is exactly where they matter:

**A cancellation is marked CANCELLED on the SITE'S OWN confirmation**,
never on "we pressed the button" (§30, §68). A press the site refused
leaves the record CANCEL_REQUESTED and says what the page said.

**It never guesses where to go.** No URL on file is a question for him,
not a search that lands on a page wearing his bank's colours.
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
           url: str = "", source: str = "operator") -> dict:
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
    url = str(url or "").strip()
    if url and not url.startswith(("http://", "https://")):
        raise ValueError("url must be a web address")
    now = utcnow()
    value = {"version": 1, "id": safe_id(subscription_id, name="subscription id"),
             "merchant": merchant.strip(), "amount": amount, "cadence": cadence,
             "next_charge": next_charge, "status": "ACTIVE", "source": source,
             # WHERE it is managed. Without it she has nowhere to go, and
             # guessing is how you end up on a page wearing his bank's
             # colours that somebody else owns.
             "url": url,
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


def set_url(subscription_id: str, url: str) -> dict:
    """Where this one is managed — the answer to the only question she asks."""
    url = str(url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("url must be a web address")
    value = load(subscription_id)
    value["url"] = url
    value["updated_at"] = utcnow()
    write_json_atomic(_path(subscription_id), value)
    return value


def request_cancel(subscription_id: str) -> dict:
    value = load(subscription_id)
    if value["status"] == "CANCELLED":
        return value
    value["status"] = "CANCEL_REQUESTED"
    value["cancel_proposal"] = {"required_capability": "web.task",
                                "required_approval": "operator_always",
                                "authority": "proposal_only"}
    value["updated_at"] = utcnow()
    if not value.get("url"):
        # NAMED, not silent. It sat in CANCEL_REQUESTED forever saying
        # nothing at all about what was stopping it.
        value["blocked_on"] = (
            f"I need the web address of the page where {value['merchant']} is "
            "managed — I will not guess one.")
    write_json_atomic(_path(subscription_id), value)
    return value


def start_cancellation(subscription_id: str, *, runner=None) -> dict:
    """Go to the page and get as far as the button. Presses nothing.

    The sentence is written HERE rather than by a model: a cancellation
    aimed at the wrong merchant is not a thing to leave to phrasing.
    """
    value = load(subscription_id)
    if value["status"] == "CANCELLED":
        return value
    if not value.get("url"):
        return request_cancel(subscription_id)
    if runner is None:
        from aletheia import webtask
        runner = webtask.run
    record = runner(f"Cancel my {value['merchant']} subscription on this page.",
                    start_url=value["url"])
    value["status"] = "CANCEL_REQUESTED"
    value["web_task"] = record.get("id", "")
    value["cancel_state"] = record.get("state", "")
    value["updated_at"] = utcnow()
    value.pop("blocked_on", None)
    write_json_atomic(_path(subscription_id), value)
    return value


def reconcile(*, loader=None) -> list[dict]:
    """Mark it CANCELLED when the SITE says so, never when we pressed.

    A press is an action; whether the merchant accepted it is a different
    question, and a subscription is exactly where answering the second
    with the first costs him real money every month for as long as he
    believes it.
    """
    if loader is None:
        from aletheia import webtask
        loader = webtask.load_run
    changed = []
    for value in all_subscriptions():
        if value.get("status") != "CANCEL_REQUESTED" or not value.get("web_task"):
            continue
        try:
            record = loader(value["web_task"])
        except Exception:
            continue
        state = str(record.get("state", ""))
        if state == value.get("cancel_state"):
            continue
        verdict = str(record.get("result", {}).get("verdict") or "")
        value["cancel_state"] = state
        value["updated_at"] = utcnow()
        if verdict == "confirmed":
            value["status"] = "CANCELLED"
            value["cancelled_at"] = utcnow()
            value["evidence"] = str(
                record.get("result", {}).get("evidence", ""))[:400]
            value.pop("blocked_on", None)
        elif state in ("REJECTED", "COMMITTED"):
            value["blocked_on"] = (
                f"I pressed it and {value['merchant']} did not confirm. "
                + str(record.get("result", {}).get("note", ""))[:200])
        write_json_atomic(_path(value["id"]), value)
        changed.append(value)
    return changed
