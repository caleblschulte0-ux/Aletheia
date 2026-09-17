"""Level-3 delegated authority grants with zero defaults.

A standing grant exists only after an explicit APPROVED approval object. Grants
cover exact capability ids, expire, have bounded uses, and can never cover a
registry capability declared high-risk or operator_always. Claim receipts are
exclusive so a bounded grant cannot be double-spent by concurrent workers.

SCOPED GRANTS (2026-09-16, continuity brief III.10 / IV.15). A grant may carry a
`scope`: the thread or recipient it is about, the purposes it covers and what it
may disclose. A scoped grant is signed to this machine (`machine_binding`) and is
spent ONLY by a caller that presents a matching scope context - the generic
`satisfy(capability, action)` every approval site uses never reaches one. A
capability the registry marks `grant_requires_scope` is never covered by an
unscoped grant. No scope ever covers a commitment or money: `scope_allows`
refuses those whatever the grant says.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from aletheia import capabilities, policy
from aletheia.stateio import create_json_exclusive, private_dir, read_json, safe_id, utcnow, write_json_atomic

GRANTS_DIR = private_dir("authority") / "grants"
CLAIMS_DIR = private_dir("authority") / "claims"


def delegable(capability_id: str, reg: dict | None = None) -> bool:
    """May this capability EVER be exercised on standing authority?

    No, if the registry calls it high-risk or operator_always (§56 L4):
    spending, sending, binding and destroying stop for him every time,
    and no grant, agent or descendant of one buys a way around that.

    One predicate, because this rule now gates three different things —
    standing grants, grant creation, and what an agent may be given — and
    three copies of an authority check is three chances to fix two of
    them. Unknown capability raises, which fails CLOSED.

    `reg` is the already-loaded registry, for callers asking about many
    capabilities at once: without it each question re-reads and re-parses
    the whole file, which made one `agents.root_record()` parse a
    130-entry JSON document 130 times.
    """
    entry = capabilities.get(capability_id, reg)
    return (entry["risk_class"] != "high"
            and entry["approval_policy"] != "operator_always")


#: The keys a scope may carry. Anything else is refused, never ignored.
SCOPE_KEYS = frozenset({"thread_id", "recipient", "purposes", "disclose"})


def validate_scope(scope: dict) -> dict:
    """A clean copy of a grant scope, or ValueError. Fails closed on anything odd."""
    if not isinstance(scope, dict):
        raise ValueError("scope must be an object")
    unknown = set(scope) - SCOPE_KEYS
    if unknown:
        raise ValueError(f"scope has unknown keys {sorted(unknown)}")
    thread = str(scope.get("thread_id") or "").strip()
    recipient = str(scope.get("recipient") or "").strip().casefold()
    if not thread and not recipient:
        raise ValueError("a scope names a thread or a recipient; a grant about everyone is not a scope")
    purposes = scope.get("purposes")
    if (not isinstance(purposes, list) or not purposes
            or any(not isinstance(p, str) or not p.strip() for p in purposes)):
        raise ValueError("a scope names the purposes it covers")
    disclose = scope.get("disclose", [])
    if not isinstance(disclose, list) or any(not isinstance(d, str) or not d.strip() for d in disclose):
        raise ValueError("disclose must be a list of named kinds of detail")
    clean = {"purposes": sorted({p.strip() for p in purposes}),
             "disclose": sorted({d.strip() for d in disclose})}
    if thread:
        clean["thread_id"] = thread
    if recipient:
        clean["recipient"] = recipient
    return clean


def scope_allows(scope: dict, context: dict | None) -> tuple[bool, str]:
    """Does a grant's scope cover this one action? (ok, why not). Pure.

    The context is what the CALLER established about the action: which thread,
    which recipient, what purpose, whether it commits him or mentions money,
    and which kinds of detail it would disclose. Anything missing fails closed.
    """
    if not isinstance(context, dict):
        return False, "no scope context was presented"
    if context.get("commitment"):
        return False, "it would commit Caleb to something, and no grant covers that"
    if context.get("money"):
        return False, "it mentions money, and no grant covers that"
    thread = str(context.get("thread_id") or "")
    recipient = str(context.get("recipient") or "").strip().casefold()
    purpose = str(context.get("purpose") or "")
    if not thread or not recipient or not purpose:
        return False, "the action did not say its thread, recipient and purpose"
    if scope.get("thread_id") and scope["thread_id"] != thread:
        return False, "the grant is about a different conversation"
    if scope.get("recipient") and scope["recipient"] != recipient:
        return False, "the grant is about a different person"
    if purpose not in (scope.get("purposes") or []):
        return False, f"the grant does not cover a {purpose}"
    disclosures = context.get("disclosures")
    if not isinstance(disclosures, list):
        return False, "the action did not say what it would disclose"
    beyond = sorted(set(disclosures) - set(scope.get("disclose") or []))
    if beyond:
        return False, "it would disclose " + ", ".join(beyond) + ", which the grant does not name"
    return True, ""


def _binding_fields(grant: dict) -> dict:
    return {k: grant.get(k) for k in ("id", "capability_ids", "approval_id", "expires",
                                      "max_uses", "scope")}


def requires_scope(capability_id: str) -> bool:
    """The registry's word on whether an unscoped grant may cover this. Fails
    closed: an unreadable entry requires a scope."""
    try:
        return bool(capabilities.get(capability_id).get("grant_requires_scope"))
    except Exception:
        return True


def _path(grant_id: str) -> Path:
    return GRANTS_DIR / f"{safe_id(grant_id, name='grant id')}.json"


def _parse(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("expiry must be timezone-aware")
    return parsed


def create(grant_id: str, *, capability_ids: list[str], approval_id: str,
           expires: str, max_uses: int = 100, note: str = "",
           scope: dict | None = None, extra: dict | None = None) -> dict:
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
        if not delegable(cid):
            raise ValueError(f"capability {cid} is not eligible for delegated authority")
        if scope is None and requires_scope(cid):
            raise ValueError(f"capability {cid} may only be granted with a scope")
    now = utcnow()
    value = {"version": 1, "id": safe_id(grant_id, name="grant id"),
             "capability_ids": capability_ids, "approval_id": approval_id,
             "expires": expires, "max_uses": max_uses, "enabled": True,
             "note": note, "created_at": now, "updated_at": now}
    if scope is not None:
        from aletheia import machine_binding
        value["scope"] = validate_scope(scope)
        for key, item in (extra or {}).items():
            if key not in value:
                value[key] = item
        value["machine_binding"] = machine_binding.sign(_binding_fields(value))
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


def allows(grant: dict, capability_id: str, *, now: dt.datetime | None = None,
           scope: dict | None = None) -> bool:
    """`scope` is the caller's context for ONE action. A scoped grant is spent
    only against a context it covers, and only if this machine signed it; an
    unscoped grant never covers a capability that requires a scope."""
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
        capabilities.get(capability_id)
    except KeyError:
        return False
    if "scope" in grant:
        try:
            from aletheia import machine_binding
            clean = validate_scope(grant["scope"])
            if clean != grant["scope"] or not machine_binding.verify(grant, _binding_fields(grant)):
                return False
        except (ValueError, TypeError):
            return False
        if scope is None or not scope_allows(clean, scope)[0]:
            return False
    elif requires_scope(capability_id):
        return False
    return delegable(capability_id)


def claim(grant_id: str, capability_id: str, action_id: str, *, now: dt.datetime | None = None,
          scope: dict | None = None) -> dict:
    grant = load(grant_id)
    if not allows(grant, capability_id, now=now, scope=scope):
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
            *, now: dt.datetime | None = None, scope: dict | None = None) -> str | None:
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
        if not allows(grant, capability_id, now=now, scope=scope):
            continue
        try:
            claim(grant["id"], capability_id, action_id, now=now, scope=scope)
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
