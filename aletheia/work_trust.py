"""Standing local grant for routine workstation work.

A Work Session is intentionally short-lived. This module is the one-time local
operator decision that lets an operator-quote-bound request open a fresh bounded
Work Session automatically instead of requiring `work_session on` every day.

The grant does NOT widen Work Session's action set. It only authorizes creating
another session with the same hard-coded browser/desktop safety boundary. Secret,
authentication, payment, destructive, account-security, shell/admin and other
refused actions remain refused.

The grant is private local state. It cannot be enabled through the public GitHub
intercom command bus; the only CLI enable path must be run on the Windows PC.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import secrets
import sys

from aletheia import journal, policy, stateio, work_session
from aletheia import machine_binding

ACTOR = "aletheia-work-trust"
GRANT_PATH = stateio.private_dir("work-trust") / "grant.json"
DEFAULT_DAYS = 30
DEFAULT_SESSION_HOURS = 8
DEFAULT_SESSION_ACTIONS = 250
MAX_DAYS = 90


class WorkTrustError(PermissionError):
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


def load() -> dict | None:
    if not GRANT_PATH.is_file():
        return None
    try:
        value = stateio.read_json(GRANT_PATH)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _binding_fields(grant: dict) -> dict:
    """Exactly what the machine binding covers — identity, the approval it
    leans on, expiry, and every limit. Tampering with any of them (or
    delivering the file from elsewhere) invalidates the signature."""
    return {
        "id": grant.get("id"),
        "approval_id": grant.get("approval_id"),
        "expires": grant.get("expires"),
        "session_hours": grant.get("session_hours"),
        "session_actions": grant.get("session_actions"),
    }


def active(*, now: dt.datetime | None = None) -> dict | None:
    grant = load()
    if not grant or not grant.get("enabled"):
        return None
    # A grant is only valid on the machine that minted it. See
    # aletheia/machine_binding.py: without this, a grant plus its
    # (already public) approval could both arrive over git sync.
    if not machine_binding.verify(grant, _binding_fields(grant)):
        machine_binding.refuse_unbound(
            grant, kind="standing workstation trust", restore_command="python -m aletheia.work_trust on")
        return None
    try:
        if _parse_time(grant["expires"]) <= _now(now):
            return None
        if not policy.is_approved(grant["approval_id"]):
            return None
        hours = int(grant["session_hours"])
        actions = int(grant["session_actions"])
        if not 1 <= hours <= work_session.MAX_HOURS:
            return None
        if not 1 <= actions <= work_session.MAX_ACTIONS:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return grant


def enable(*, days: int = DEFAULT_DAYS,
           session_hours: int = DEFAULT_SESSION_HOURS,
           session_actions: int = DEFAULT_SESSION_ACTIONS,
           via: str = "operator-local",
           now: dt.datetime | None = None) -> dict:
    """Create/replace a standing grant after an explicit local operator action."""
    if type(days) is not int or not 1 <= days <= MAX_DAYS:
        raise ValueError(f"days must be 1..{MAX_DAYS}")
    if type(session_hours) is not int or not 1 <= session_hours <= work_session.MAX_HOURS:
        raise ValueError(f"session_hours must be 1..{work_session.MAX_HOURS}")
    if type(session_actions) is not int or not 1 <= session_actions <= work_session.MAX_ACTIONS:
        raise ValueError(f"session_actions must be 1..{work_session.MAX_ACTIONS}")

    # HALT is the kill switch, and minting standing authority is the one
    # thing an installer does that outlives the installer. Three activation
    # scripts call this unconditionally, so a re-run while halted would have
    # handed back standing authority the operator had just stopped
    # (2026-09-01 Windows lifecycle review). Refuse instead: resume first,
    # deliberately, then enable.
    policy.ensure_not_halted()
    stamp = _now(now)
    grant_id = f"wt-{stamp.strftime('%Y%m%d-%H%M')}-{secrets.token_hex(3)}"
    approval_id = f"{grant_id}-operator"
    expires = stamp + dt.timedelta(days=days)
    policy.request(
        approval_id,
        requested_action=f"work.trust:{grant_id}",
        reason=(
            "standing local permission to auto-open bounded routine Work Sessions "
            "for requests already bound to the operator's words"
        ),
        consequence=(
            f"until {expires.strftime('%Y-%m-%dT%H:%M:%SZ')}, eligible requests may "
            f"open {session_hours}h/{session_actions}-action Work Sessions; the Work "
            "Session safety classifier/live guards remain unchanged"
        ),
        reversible=True,
    )
    policy.decide(
        approval_id, "APPROVED", via=via,
        because="operator explicitly enabled standing routine workstation access locally",
    )
    record = {
        "version": 1,
        "id": grant_id,
        "enabled": True,
        "approval_id": approval_id,
        "created_at": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session_hours": session_hours,
        "session_actions": session_actions,
        "scope": (
            "auto-open routine Work Sessions only; no secret/auth/payment/destructive/"
            "account-security/shell-admin authority"
        ),
    }
    # bind to THIS machine before it is written: an identical file
    # appearing on another machine (or arriving over git) cannot carry a
    # signature made with this machine's key, so active() refuses it.
    record["machine_binding"] = machine_binding.sign(_binding_fields(record))
    stateio.write_json_atomic(GRANT_PATH, record)
    journal.append(
        "decision", "work:trust",
        f"ENABLED {grant_id} until {record['expires']} -> {session_hours}h/{session_actions} action sessions",
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
        "decision", "work:trust", f"DISABLED {grant.get('id', '?')}", actor=via
    )
    return True


def status(*, now: dt.datetime | None = None) -> dict:
    grant = load()
    live = active(now=now)
    return {
        "active": bool(live),
        "id": grant.get("id") if grant else None,
        "expires": grant.get("expires") if grant else None,
        "session_hours": grant.get("session_hours") if grant else None,
        "session_actions": grant.get("session_actions") if grant else None,
        "scope": grant.get("scope") if grant else None,
    }


def ensure_session(*, now: dt.datetime | None = None) -> dict | None:
    """Return a live Work Session, opening one only under an active local grant."""
    current = work_session.active(now=now)
    if current:
        return current
    grant = active(now=now)
    if not grant:
        return None
    policy.ensure_not_halted()
    session = work_session.open_session(
        hours=int(grant["session_hours"]),
        max_actions=int(grant["session_actions"]),
        via=f"work-trust:{grant['id']}",
        now=now,
    )
    journal.append(
        "decision", "work:trust",
        f"{grant['id']} auto-opened Work Session {session['id']}",
        actor=ACTOR,
        refs=[f"approval:{grant['approval_id']}", f"approval:{session['approval_id']}"],
    )
    return session


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Local standing permission to auto-open bounded routine Work Sessions."
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    on = sub.add_parser("on", help="enable standing routine workstation access locally")
    on.add_argument("--days", type=int, default=DEFAULT_DAYS)
    on.add_argument("--hours", type=int, default=DEFAULT_SESSION_HOURS)
    on.add_argument("--actions", type=int, default=DEFAULT_SESSION_ACTIONS)
    sub.add_parser("off", help="disable standing workstation access")
    sub.add_parser("status", help="show standing grant metadata")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "on":
            enable(days=args.days, session_hours=args.hours, session_actions=args.actions)
            print(json.dumps(status(), indent=2))
            print(
                "Standing routine workstation access enabled locally. "
                "Sensitive/auth/payment/destructive/admin boundaries are unchanged."
            )
            return 0
        if args.cmd == "off":
            print("Standing workstation access disabled." if disable() else "No active grant.")
            return 0
        print(json.dumps(status(), indent=2))
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
