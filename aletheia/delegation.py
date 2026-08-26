"""Scoped delegated authority proposals and content-bound activation.

This is the foundation for Playbook Level-3 standing authority. A grant cannot
activate itself: the operator must approve a request bound to the SHA-256 of the
exact scope. The kill switch always wins, operator_always capabilities are never
delegable here, high-risk capabilities are never delegable, and grants expire.

Activation/revocation records are intentionally shared repo state so every
executor can reach the same authority decision. Proposals are private runtime
state because they may contain operator-specific action prefixes.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

from aletheia import capabilities, contracts, policy
from aletheia.fleet import REPO_ROOT
from aletheia.stateio import create_json_exclusive, private_dir, read_json, safe_id, utcnow, write_json_atomic

PROPOSALS_DIR = private_dir("delegations") / "proposals"
ACTIVE_DIR = REPO_ROOT / "state" / "authority" / "delegations"
REVOKED_DIR = REPO_ROOT / "state" / "authority" / "revoked"
RISK_ORDER = {"read": 0, "low": 1, "medium": 2, "high": 3}
MAX_TTL = dt.timedelta(days=30)


def _parse_time(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid delegation timestamp {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("delegation timestamps must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def _canonical_hash(scope: dict) -> str:
    raw = json.dumps(scope, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _proposal_path(grant_id: str) -> Path:
    return PROPOSALS_DIR / f"{safe_id(grant_id, name='grant id')}.json"


def _active_path(grant_id: str) -> Path:
    return ACTIVE_DIR / f"{safe_id(grant_id, name='grant id')}.json"


def _revoked_path(grant_id: str) -> Path:
    return REVOKED_DIR / f"{safe_id(grant_id, name='grant id')}.json"


def propose(grant_id: str, *, capability_id: str, expires_at: str,
            action_prefix: str | None = None, max_risk: str | None = None,
            registry: dict | None = None, now: dt.datetime | None = None) -> dict:
    safe_id(grant_id, name="grant id")
    registry = registry or capabilities.load_registry()
    capability = capabilities.get(capability_id, registry)
    if capability["risk_class"] == "high" or capability["approval_policy"] == "operator_always":
        raise PermissionError(f"{capability_id} is not eligible for standing delegation")
    max_risk = max_risk or capability["risk_class"]
    if max_risk not in contracts.RISK_CLASSES or max_risk == "high":
        raise ValueError("delegation max_risk must be read, low, or medium")
    if RISK_ORDER[capability["risk_class"]] > RISK_ORDER[max_risk]:
        raise ValueError("max_risk is below the capability's current risk")
    if capability["risk_class"] == "medium" and not action_prefix:
        raise ValueError("medium-risk delegation requires a non-empty action_prefix")
    if action_prefix is not None and (not isinstance(action_prefix, str) or not action_prefix.strip()):
        raise ValueError("action_prefix must be a non-empty string when provided")
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    expiry = _parse_time(expires_at)
    now_utc = now.astimezone(dt.timezone.utc)
    if expiry <= now_utc:
        raise ValueError("delegation expiry must be in the future")
    if expiry - now_utc > MAX_TTL:
        raise ValueError("delegation may not exceed 30 days; renew with a fresh approval")
    scope = {"capability_id": capability_id, "max_risk": max_risk,
             "expires_at": expiry.strftime("%Y-%m-%dT%H:%M:%SZ")}
    if action_prefix:
        scope["action_prefix"] = action_prefix
    value = {"version": 1, "id": grant_id, "scope": scope,
             "scope_sha256": _canonical_hash(scope), "state": "PROPOSED",
             "created_at": utcnow()}
    write_json_atomic(_proposal_path(grant_id), value)
    return value


def load_proposal(grant_id: str) -> dict:
    return read_json(_proposal_path(grant_id))


def approval_action(proposal: dict) -> str:
    return f"activate delegation {proposal['id']} sha256:{proposal['scope_sha256']}"


def activate(grant_id: str, approval_id: str) -> dict:
    if _revoked_path(grant_id).exists():
        raise PermissionError("grant id has been revoked and cannot be reused")
    proposal = load_proposal(grant_id)
    if proposal.get("scope_sha256") != _canonical_hash(proposal.get("scope", {})):
        raise ValueError("delegation proposal hash does not match scope")
    approval = policy.load(approval_id)
    expected = approval_action(proposal)
    if approval.get("state") != "APPROVED" or approval.get("requested_action") != expected:
        raise PermissionError("approval is not APPROVED and bound to this exact delegation scope")
    if _parse_time(proposal["scope"]["expires_at"]) <= dt.datetime.now(dt.timezone.utc):
        raise PermissionError("delegation proposal expired before activation")
    active = {"version": 1, "id": proposal["id"], "scope": proposal["scope"],
              "scope_sha256": proposal["scope_sha256"], "approval_id": approval_id,
              "state": "ACTIVE", "activated_at": utcnow()}
    create_json_exclusive(_active_path(grant_id), active)
    return active


def load(grant_id: str) -> dict:
    return read_json(_active_path(grant_id))


def revoke(grant_id: str, *, reason: str, actor: str = "operator") -> dict:
    safe_id(grant_id, name="grant id")
    value = {"version": 1, "id": grant_id, "reason": reason or "revoked",
             "actor": actor, "revoked_at": utcnow()}
    try:
        create_json_exclusive(_revoked_path(grant_id), value)
    except FileExistsError:
        return read_json(_revoked_path(grant_id))
    return value


def allows(grant_id: str, *, capability_id: str, action: str,
           registry: dict | None = None, now: dt.datetime | None = None) -> bool:
    """Return whether this grant covers the request. Never grants by exception."""
    policy.ensure_not_halted()
    if _revoked_path(grant_id).exists():
        return False
    try:
        grant = load(grant_id)
    except ValueError:
        return False
    if grant.get("state") != "ACTIVE" or grant.get("scope_sha256") != _canonical_hash(grant.get("scope", {})):
        return False
    scope = grant["scope"]
    if scope.get("capability_id") != capability_id:
        return False
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if _parse_time(scope["expires_at"]) <= now.astimezone(dt.timezone.utc):
        return False
    registry = registry or capabilities.load_registry()
    try:
        capability = capabilities.get(capability_id, registry)
    except KeyError:
        return False
    if capability["risk_class"] == "high" or capability["approval_policy"] == "operator_always":
        return False
    if RISK_ORDER[capability["risk_class"]] > RISK_ORDER.get(scope.get("max_risk"), -1):
        return False
    prefix = scope.get("action_prefix")
    if prefix and not action.startswith(prefix):
        return False
    return True
