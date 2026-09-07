"""Private shopping workflow: requirements -> candidates -> selection -> purchase proposal.

No purchase is executed here. The final proposal explicitly requires an
operator approval and a separate provider capability, preserving Playbook L4.
"""
from __future__ import annotations

from pathlib import Path

from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

SHOP_DIR = private_dir("shopping")
STATES = {"RESEARCHING", "SELECTED", "PURCHASE_PROPOSED", "ORDERED", "CANCELLED"}


def _path(workflow_id: str) -> Path:
    return SHOP_DIR / f"{safe_id(workflow_id, name='shopping id')}.json"


def create(workflow_id: str, *, need: str, budget: float | None = None,
           constraints: list[str] | None = None) -> dict:
    if _path(workflow_id).exists():
        raise FileExistsError(workflow_id)
    if not isinstance(need, str) or not need.strip():
        raise ValueError("need is required")
    if budget is not None and (not isinstance(budget, (int, float)) or budget < 0):
        raise ValueError("budget must be non-negative")
    now = utcnow()
    value = {"version": 1, "id": safe_id(workflow_id, name="shopping id"), "need": need.strip(),
             "budget": budget, "constraints": constraints or [], "candidates": [], "state": "RESEARCHING",
             "created_at": now, "updated_at": now}
    write_json_atomic(_path(workflow_id), value)
    return value


def load(workflow_id: str) -> dict:
    return read_json(_path(workflow_id))


def all_workflows() -> list[dict]:
    """Everything on the list, oldest first.

    There was no way to READ this back. She answered "add milk to my
    shopping list" with "Added to the shopping list: milk." and, one turn
    later, "I don't have a shopping list stored anywhere I can check" —
    the same flat contradiction the journal produced before
    `recollection.HER_DOING` was fixed, in a different store.
    """
    if not SHOP_DIR.is_dir():
        return []
    out = []
    for path in sorted(SHOP_DIR.glob("*.json")):
        try:
            out.append(load(path.stem))
        except (ValueError, OSError):
            continue
    out.sort(key=lambda w: str(w.get("created_at") or ""))
    return out


def cancel(workflow_id: str) -> dict:
    """Take something off the list. Kept, not deleted, like every other
    reversible thing here — "put it back" stays possible."""
    value = load(workflow_id)
    value["state"] = "CANCELLED"
    value["updated_at"] = utcnow()
    write_json_atomic(_path(workflow_id), value)
    return value


def add_candidate(workflow_id: str, candidate_id: str, *, title: str, price: float | None,
                  source: str, facts: dict | None = None) -> dict:
    value = load(workflow_id)
    if value["state"] != "RESEARCHING":
        raise ValueError("candidates can only be added while researching")
    safe_id(candidate_id, name="candidate id")
    if any(c["id"] == candidate_id for c in value["candidates"]):
        raise FileExistsError(candidate_id)
    if price is not None and (not isinstance(price, (int, float)) or price < 0):
        raise ValueError("price must be non-negative")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("candidate source is required")
    candidate = {"id": candidate_id, "title": title, "price": price, "source": source,
                 "facts": facts or {}, "recorded_at": utcnow()}
    value["candidates"].append(candidate)
    value["updated_at"] = utcnow()
    write_json_atomic(_path(workflow_id), value)
    return candidate


def select(workflow_id: str, candidate_id: str) -> dict:
    value = load(workflow_id)
    candidate = next((c for c in value["candidates"] if c["id"] == candidate_id), None)
    if candidate is None:
        raise KeyError(candidate_id)
    if value.get("budget") is not None and candidate.get("price") is not None and candidate["price"] > value["budget"]:
        raise ValueError("selected candidate exceeds recorded budget")
    value["selected"] = candidate_id
    value["state"] = "SELECTED"
    value["updated_at"] = utcnow()
    write_json_atomic(_path(workflow_id), value)
    return value


def propose_purchase(workflow_id: str) -> dict:
    value = load(workflow_id)
    if value["state"] != "SELECTED":
        raise ValueError("select a candidate before proposing purchase")
    candidate = next(c for c in value["candidates"] if c["id"] == value["selected"])
    proposal = {"workflow_id": workflow_id, "candidate": candidate,
                "required_approval": "operator_always", "required_capability": "purchase.execute",
                "authority": "proposal_only"}
    value["state"] = "PURCHASE_PROPOSED"
    value["purchase_proposal"] = proposal
    value["updated_at"] = utcnow()
    write_json_atomic(_path(workflow_id), value)
    return proposal
