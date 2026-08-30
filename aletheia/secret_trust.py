"""Local standing grant for bounded API-credential operations.

The public GitHub intercom may carry selectors, hostnames and secret *aliases*,
never plaintext credentials. This grant is the local operator decision that
allows Aletheia to create/capture an API credential into the Windows DPAPI
vault, or use an already-stored alias on a host that alias is explicitly bound
to.

It is intentionally narrower than general workstation trust. It cannot be
enabled remotely and it grants no password/2FA/payment/destructive/revoke/
rotate/account-security authority.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import secrets
import sys
from pathlib import Path

from aletheia import journal, policy, stateio

ACTOR = "aletheia-secret-trust"
GRANT_PATH = stateio.private_dir("secret-trust") / "grant.json"
CLAIMS_DIR = stateio.private_dir("secret-trust") / "claims"
DEFAULT_DAYS = 30
DEFAULT_ACTIONS = 50
MAX_DAYS = 90
MAX_ACTIONS = 500


class SecretTrustRequired(PermissionError):
    pass


def _now(now: dt.datetime | None = None) -> dt.datetime:
    value = now or dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(dt.timezone.utc)


def _parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("grant timestamp must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def _claims(grant_id: str) -> list[Path]:
    root = CLAIMS_DIR / stateio.safe_id(grant_id, name="grant id")
    return sorted(root.glob("*.json")) if root.is_dir() else []


def load() -> dict | None:
    if not GRANT_PATH.is_file():
        return None
    try:
        value = stateio.read_json(GRANT_PATH)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def active(*, now: dt.datetime | None = None) -> dict | None:
    grant = load()
    if not grant or not grant.get("enabled"):
        return None
    try:
        if _parse_time(grant["expires"]) <= _now(now):
            return None
        if not policy.is_approved(grant["approval_id"]):
            return None
        maximum = int(grant["max_actions"])
        if not 1 <= maximum <= MAX_ACTIONS:
            return None
        if len(_claims(grant["id"])) >= maximum:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return grant


def enable(*, days: int = DEFAULT_DAYS, max_actions: int = DEFAULT_ACTIONS,
           via: str = "operator-local", now: dt.datetime | None = None) -> dict:
    """Enable locally; there is deliberately no intercom route for this."""
    if type(days) is not int or not 1 <= days <= MAX_DAYS:
        raise ValueError(f"days must be 1..{MAX_DAYS}")
    if type(max_actions) is not int or not 1 <= max_actions <= MAX_ACTIONS:
        raise ValueError(f"max_actions must be 1..{MAX_ACTIONS}")

    stamp = _now(now)
    grant_id = f"st-{stamp.strftime('%Y%m%d-%H%M')}-{secrets.token_hex(3)}"
    approval_id = f"{grant_id}-operator"
    expires = stamp + dt.timedelta(days=days)
    policy.request(
        approval_id,
        requested_action=f"secret.trust:{grant_id}",
        reason=(
            "standing local permission for bounded API-key create/capture/use "
            "operations with plaintext confined to the PC"
        ),
        consequence=(
            f"until {expires.strftime('%Y-%m-%dT%H:%M:%SZ')} or {max_actions} "
            "operations, Aletheia may create/capture API credentials into the "
            "local DPAPI vault and fill host-bound aliases; passwords, 2FA, "
            "payments, deletion/revocation/rotation and account security remain refused"
        ),
        reversible=True,
    )
    policy.decide(
        approval_id, "APPROVED", via=via,
        because="operator explicitly enabled bounded API-credential work locally",
    )
    record = {
        "version": 1,
        "id": grant_id,
        "enabled": True,
        "approval_id": approval_id,
        "created_at": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "max_actions": max_actions,
        "scope": (
            "API-key create/capture/use only; plaintext local; no passwords/2FA/"
            "payment/destructive/revoke/rotate/account-security authority"
        ),
    }
    stateio.write_json_atomic(GRANT_PATH, record)
    journal.append(
        "decision", "secret:trust",
        f"ENABLED {grant_id} until {record['expires']} / {max_actions} actions",
        actor=ACTOR, refs=[f"approval:{approval_id}"],
    )
    return record


def disable(*, via: str = "operator-local") -> bool:
    grant = load()
    if not grant or not grant.get("enabled"):
        return False
    grant["enabled"] = False
    grant["disabled_at"] = stateio.utcnow()
    stateio.write_json_atomic(GRANT_PATH, grant)
    journal.append(
        "decision", "secret:trust", f"DISABLED {grant.get('id', '?')}", actor=via
    )
    return True


def claim(kind: str, *, host: str, alias: str) -> dict:
    """Consume one operation slot before a credential action touches the browser."""
    grant = active()
    if not grant:
        raise SecretTrustRequired(
            "no active local API-credential grant — run `python -m aletheia.secret_trust on` locally"
        )
    policy.ensure_not_halted()
    root = CLAIMS_DIR / stateio.safe_id(grant["id"], name="grant id")
    root.mkdir(parents=True, exist_ok=True)
    maximum = int(grant["max_actions"])
    for slot in range(1, maximum + 1):
        record = {
            "version": 1,
            "grant_id": grant["id"],
            "slot": slot,
            "kind": str(kind)[:80],
            "host": str(host).casefold()[:253],
            "alias": stateio.safe_id(alias, name="secret alias"),
            "claimed_at": stateio.utcnow(),
        }
        try:
            stateio.create_json_exclusive(root / f"{slot:05d}.json", record)
        except FileExistsError:
            continue
        return record
    raise SecretTrustRequired("API-credential grant action budget is exhausted")


def status(*, now: dt.datetime | None = None) -> dict:
    grant = load()
    live = active(now=now)
    used = len(_claims(grant["id"])) if grant and grant.get("id") else 0
    maximum = int(grant.get("max_actions", 0)) if grant else 0
    return {
        "active": bool(live),
        "id": grant.get("id") if grant else None,
        "expires": grant.get("expires") if grant else None,
        "used": used,
        "max_actions": maximum,
        "actions_left": max(0, maximum - used),
        "scope": grant.get("scope") if grant else None,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Local bounded permission for API credential create/capture/use."
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    on = sub.add_parser("on")
    on.add_argument("--days", type=int, default=DEFAULT_DAYS)
    on.add_argument("--actions", type=int, default=DEFAULT_ACTIONS)
    sub.add_parser("off")
    sub.add_parser("status")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "on":
            enable(days=args.days, max_actions=args.actions)
            print(json.dumps(status(), indent=2))
            print(
                "API-credential work enabled locally. Password/2FA/payment/"
                "destructive/revoke/rotate boundaries are unchanged."
            )
            return 0
        if args.cmd == "off":
            print("API-credential work disabled." if disable() else "No active grant.")
            return 0
        print(json.dumps(status(), indent=2))
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
