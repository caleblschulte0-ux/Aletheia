"""Level-3 delegated authority grants with zero defaults.

A standing grant exists only after an explicit APPROVED approval object. Grants
cover exact capability ids, expire, have bounded uses, and can never cover a
registry capability declared high-risk or operator_always. Claim receipts are
exclusive so a bounded grant cannot be double-spent by concurrent workers.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from aletheia import capabilities, policy
from aletheia.stateio import create_json_exclusive, private_dir, read_json, safe_id, utcnow, write_json_atomic

GRANTS_DIR = private_dir("authority") / "grants"
CLAIMS_DIR = private_dir("authority") / "claims"


def _path(grant_id: str) -> Path:
    return GRANTS_DIR / f"{safe_id(grant_id, name='grant id')}.json"


def _parse(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("expiry must be timezone-aware")
    return parsed


def create(grant_id: str, *, capability_ids: list[str], approval_id: str,
           expires: str, max_uses: int = 100, note: str = "") -> dict:
    if _path(grant_id).exists():
        raise FileExistsError(grant_id)
    if not policy.is_approved(approval_id):
        raise PermissionError("standing authority requires an approved operator approval")
    if not capability_ids or len(set(capability_ids)) != len(capability_ids):
        raise ValueError("capability_ids must be unique and non-empty")
    if type(max_uses) is not int or not 1 <= max_uses <= 10_000:
        raise ValueError("max_uses must be 1..10000")
    expiry = _parse(expires)
    if expiry <= dt.datetime.now(dt.timezone.utc):
        raise ValueError("grant must expire in the future")
    for cid in capability_ids:
        entry = capabilities.get(cid)
        if entry["risk_class"] == "high" or entry["approval_policy"] == "operator_always":
            raise ValueError(f"capability {cid} is not eligible for delegated authority")
    now = utcnow()
    value = {"version": 1, "id": safe_id(grant_id, name="grant id"),
             "capability_ids": capability_ids, "approval_id": approval_id,
             "expires": expires, "max_uses": max_uses, "enabled": True,
             "note": note, "created_at": now, "updated_at": now}
    write_json_atomic(_path(grant_id), value)
    return value


def load(grant_id: str) -> dict:
    return read_json(_path(grant_id))


def _claims(grant_id: str) -> list[dict]:
    root = CLAIMS_DIR / safe_id(grant_id, name="grant id")
    if not root.is_dir():
        return []
    out = []
    for path in root.glob("*.json"):
        try:
            out.append(read_json(path))
        except ValueError:
            continue
    return out


def allows(grant: dict, capability_id: str, *, now: dt.datetime | None = None) -> bool:
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not grant.get("enabled") or capability_id not in grant.get("capability_ids", []):
        return False
    if _parse(grant["expires"]).astimezone(dt.timezone.utc) <= now.astimezone(dt.timezone.utc):
        return False
    if len(_claims(grant["id"])) >= grant["max_uses"]:
        return False
    try:
        entry = capabilities.get(capability_id)
    except KeyError:
        return False
    return entry["risk_class"] != "high" and entry["approval_policy"] != "operator_always"


def claim(grant_id: str, capability_id: str, action_id: str, *, now: dt.datetime | None = None) -> dict:
    grant = load(grant_id)
    if not allows(grant, capability_id, now=now):
        raise PermissionError("delegated authority does not cover this action")
    safe_id(action_id, name="action id")
    receipt = {"version": 1, "grant_id": grant_id, "capability_id": capability_id,
               "action_id": action_id, "claimed_at": utcnow()}
    create_json_exclusive(CLAIMS_DIR / safe_id(grant_id) / f"{action_id}.json", receipt)
    return receipt


def active_grants(*, now: dt.datetime | None = None) -> list[dict]:
    """Every grant that is currently capable of authorizing anything."""
    if not GRANTS_DIR.is_dir():
        return []
    out = []
    for path in sorted(GRANTS_DIR.glob("*.json")):
        try:
            grant = read_json(path)
        except ValueError:
            continue  # a corrupt grant is not authority
        if not grant.get("enabled"):
            continue
        try:
            if _parse(grant["expires"]).astimezone(dt.timezone.utc) <= (
                    now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc):
                continue
        except (KeyError, ValueError):
            continue
        out.append(grant)
    return out


def satisfy(capability_id: str, action_id: str,
            *, now: dt.datetime | None = None) -> str | None:
    """Spend a standing grant on this action, or return None.

    THE CONSUMER. Until 2026-08-27 this module could record delegated
    authority and nothing anywhere would ever act on it: grants were
    written, `allows()` was tested, and every approval still went to the
    operator. A grant nobody consumes is a promise, not a permission.

    What it does NOT do is as important. `allows()` refuses any capability
    the registry marks high-risk or operator_always, so no grant can ever
    reach spending, a binding agreement, a disclosure or a destructive
    action (§56 L4) — those keep asking him, forever, by construction.
    The claim receipt is written exclusively, so a bounded grant cannot be
    double-spent by two workers racing on the same beat.
    """
    for grant in active_grants(now=now):
        if not allows(grant, capability_id, now=now):
            continue
        try:
            claim(grant["id"], capability_id, action_id, now=now)
        except (PermissionError, FileExistsError, OSError, ValueError):
            continue  # exhausted or already claimed: try the next grant
        return grant["id"]
    return None


def revoke(grant_id: str) -> dict:
    grant = load(grant_id)
    grant["enabled"] = False
    grant["updated_at"] = utcnow()
    write_json_atomic(_path(grant_id), grant)
    return grant
