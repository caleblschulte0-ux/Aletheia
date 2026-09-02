"""Local standing grant for bounded unattended code-change PRs.

The grant is deliberately narrower than workstation trust: it permits a local
worker to prepare reviewed pull requests for PUBLIC repositories owned by the
fleet owner. It never permits default-branch writes/merges, private-repository
code export, secrets, workflows, or protected governance/safety edits.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import secrets
import sys
from pathlib import Path

from aletheia import journal, policy, stateio
from aletheia import machine_binding
from aletheia.fleet import load_fleet

ACTOR = "aletheia-code-trust"
GRANT_PATH = stateio.private_dir("code-trust") / "grant.json"
CLAIMS_DIR = stateio.private_dir("code-trust") / "claims"
DEFAULT_DAYS = 30
DEFAULT_PRS = 25
MAX_DAYS = 90
MAX_PRS = 200


class CodeTrustRequired(PermissionError):
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


def _binding_fields(grant: dict) -> dict:
    """Exactly what the machine binding covers — identity, the approval it
    leans on, expiry, and every limit. Tampering with any of them (or
    delivering the file from elsewhere) invalidates the signature."""
    return {
        "id": grant.get("id"),
        "approval_id": grant.get("approval_id"),
        "expires": grant.get("expires"),
        "max_prs": grant.get("max_prs"),
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
            grant, kind="standing code-work trust", restore_command="python -m aletheia.code_trust on")
        return None
    try:
        if _parse_time(grant["expires"]) <= _now(now):
            return None
        if not policy.is_approved(grant["approval_id"]):
            return None
        maximum = int(grant["max_prs"])
        if not 1 <= maximum <= MAX_PRS:
            return None
        if len(_claims(grant["id"])) >= maximum:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return grant


def enable(*, days: int = DEFAULT_DAYS, max_prs: int = DEFAULT_PRS,
           via: str = "operator-local", now: dt.datetime | None = None) -> dict:
    if type(days) is not int or not 1 <= days <= MAX_DAYS:
        raise ValueError(f"days must be 1..{MAX_DAYS}")
    if type(max_prs) is not int or not 1 <= max_prs <= MAX_PRS:
        raise ValueError(f"max_prs must be 1..{MAX_PRS}")
    # HALT is the kill switch, and minting standing authority is the one
    # thing an installer does that outlives the installer. Three activation
    # scripts call this unconditionally, so a re-run while halted would have
    # handed back standing authority the operator had just stopped
    # (2026-09-01 Windows lifecycle review). Refuse instead: resume first,
    # deliberately, then enable.
    policy.ensure_not_halted()
    owner = str(load_fleet().get("owner") or "").strip()
    if not owner:
        raise ValueError("fleet owner is not configured")

    stamp = _now(now)
    grant_id = f"ct-{stamp.strftime('%Y%m%d-%H%M')}-{secrets.token_hex(3)}"
    approval_id = f"{grant_id}-operator"
    expires = stamp + dt.timedelta(days=days)
    policy.request(
        approval_id,
        requested_action=f"code.trust:{grant_id}",
        reason="standing local permission to prepare model-reviewed code pull requests",
        consequence=(
            f"until {expires.strftime('%Y-%m-%dT%H:%M:%SZ')} or {max_prs} attempts, "
            f"Aletheia may prepare reviewed PR branches for PUBLIC repos owned by {owner}; "
            "default-branch writes/merges, private repo code, secrets, workflows and "
            "protected governance/safety paths remain refused"
        ),
        reversible=True,
    )
    policy.decide(
        approval_id, "APPROVED", via=via,
        because="operator explicitly enabled bounded reviewed code-PR work locally",
    )
    record = {
        "version": 1, "id": grant_id, "enabled": True,
        "approval_id": approval_id, "owner": owner,
        "created_at": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "max_prs": max_prs,
        "scope": (
            "public owner repos; branch+independent-review+PR only; no default-branch "
            "merge/write, private code export, secrets, workflows or protected paths"
        ),
    }
    # bind to THIS machine before it is written: an identical file
    # appearing on another machine (or arriving over git) cannot carry a
    # signature made with this machine's key, so active() refuses it.
    record["machine_binding"] = machine_binding.sign(_binding_fields(record))
    stateio.write_json_atomic(GRANT_PATH, record)
    journal.append(
        "decision", "code:trust",
        f"ENABLED {grant_id} until {record['expires']} / {max_prs} PR attempts",
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
    journal.append("decision", "code:trust", f"DISABLED {grant.get('id', '?')}", actor=via)
    return True


def claim(*, repo_full_name: str, private: bool, task_id: str) -> dict:
    """Consume one attempt before repository code is sent to a subscription model."""
    grant = active()
    if not grant:
        raise CodeTrustRequired(
            "no active local code-work grant — run `python -m aletheia.code_trust on` locally"
        )
    policy.ensure_not_halted()
    if private:
        raise CodeTrustRequired("unattended model coding is disabled for private repositories")
    repo = str(repo_full_name or "").strip()
    if "/" not in repo or repo.split("/", 1)[0].casefold() != str(grant["owner"]).casefold():
        raise CodeTrustRequired("code-work grant only covers repositories owned by the fleet owner")
    task = stateio.safe_id(task_id, name="code task id")
    root = CLAIMS_DIR / stateio.safe_id(grant["id"], name="grant id")
    root.mkdir(parents=True, exist_ok=True)
    maximum = int(grant["max_prs"])
    for slot in range(1, maximum + 1):
        record = {
            "version": 1, "grant_id": grant["id"], "slot": slot,
            "repo": repo, "task_id": task, "claimed_at": stateio.utcnow(),
        }
        try:
            stateio.create_json_exclusive(root / f"{slot:05d}.json", record)
        except FileExistsError:
            continue
        journal.append(
            "decision", "code:trust",
            f"CLAIM {grant['id']} slot {slot} for {repo} task {task}",
            actor=ACTOR, refs=[f"approval:{grant['approval_id']}"],
        )
        return record
    raise CodeTrustRequired("code-work grant PR-attempt budget is exhausted")


def claims_since(*, hours: int = 24, now: dt.datetime | None = None) -> int:
    if type(hours) is not int or not 1 <= hours <= 24 * 30:
        raise ValueError("hours must be 1..720")
    grant = load()
    if not grant or not grant.get("id"):
        return 0
    cutoff = _now(now) - dt.timedelta(hours=hours)
    count = 0
    for path in _claims(grant["id"]):
        try:
            row = stateio.read_json(path)
            stamp = _parse_time(row["claimed_at"])
        except (ValueError, KeyError, TypeError):
            continue
        if stamp >= cutoff:
            count += 1
    return count


def status(*, now: dt.datetime | None = None) -> dict:
    grant = load()
    live = active(now=now)
    used = len(_claims(grant["id"])) if grant and grant.get("id") else 0
    maximum = int(grant.get("max_prs", 0)) if grant else 0
    return {
        "active": bool(live), "id": grant.get("id") if grant else None,
        "expires": grant.get("expires") if grant else None,
        "owner": grant.get("owner") if grant else None,
        "used": used, "max_prs": maximum, "prs_left": max(0, maximum - used),
        "scope": grant.get("scope") if grant else None,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Local permission for reviewed autonomous code PRs.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    on = sub.add_parser("on")
    on.add_argument("--days", type=int, default=DEFAULT_DAYS)
    on.add_argument("--prs", type=int, default=DEFAULT_PRS)
    sub.add_parser("off")
    sub.add_parser("status")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "on":
            enable(days=args.days, max_prs=args.prs)
            print(json.dumps(status(), indent=2))
            print("Reviewed public-repo PR work enabled locally; default-branch merges remain disabled.")
            return 0
        if args.cmd == "off":
            print("Code-work grant disabled." if disable() else "No active grant.")
            return 0
        print(json.dumps(status(), indent=2))
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
