"""The policy engine (Playbook §§55–63, Phase 4).

Authority is explicit and separate from ability (§70). This module holds
the three primitives everything acting must respect:

- **Approvals** (§57): durable objects in `state/approvals/`, one JSON
  per request, per `contracts.validate_approval`. PENDING → APPROVED /
  DENIED (/ EXPIRED). Each can be published as a "🔐 Approval required"
  issue; the operator decides by commenting approve/deny (validated to
  the repo owner by `approvals.yml`) or by voice through the intercom.
- **The kill switch** (§62): `halt()` writes `state/policy/halt.json`;
  while it exists, every acting capability refuses (`ensure_not_halted`
  raises). Only an operator `resume` clears it. Fail closed: a corrupt
  halt file counts as halted.
- **Capability gating**: `required_approval(capability_id)` reads the
  capability registry's `approval_policy` — the single declaration of
  what needs whom. `operator_once` callers (the director today) must
  hold an APPROVED approval before acting.

A decision is never silent: every request, decision, halt, and resume is
journaled.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

from aletheia import capabilities, contracts, gh, journal
from aletheia.fleet import REPO_ROOT

def _approvals_dir() -> Path:
    """Where approval objects live: PRIVATE state, not the repository.

    Moved 2026-09-03. An approval records what he authorised, why, what it
    would cost and often his own words — and they were committed to a public
    repository. `ALETHEIA_APPROVALS_DIR` overrides for tooling; the default
    is `state/private/approvals`, which is gitignored.
    """
    override = os.environ.get("ALETHEIA_APPROVALS_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    from aletheia.stateio import private_dir
    return private_dir("approvals")


APPROVALS_DIR = _approvals_dir()
HALT_PATH = REPO_ROOT / "state" / "policy" / "halt.json"
ISSUE_PREFIX = "🔐 Approval required:"


class Halted(RuntimeError):
    """The kill switch is on — nothing acts until the operator resumes."""


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- kill switch ------------------------------------------------------------

def halted() -> dict | None:
    if not HALT_PATH.exists():
        return None
    try:
        return json.loads(HALT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"reason": "halt file unreadable — treating as halted (fail closed)"}


def ensure_not_halted() -> None:
    h = halted()
    if h is not None:
        raise Halted(f"Aletheia is halted ({h.get('reason', 'no reason recorded')}) — "
                     "only an operator resume lifts this")


def halt(reason: str, via: str) -> dict:
    HALT_PATH.parent.mkdir(parents=True, exist_ok=True)
    state = {"halted_at": _now(), "reason": reason or "operator said stop", "via": via}
    HALT_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    journal.append("event", "policy:halt", f"KILL SWITCH ON — {state['reason']}", actor=via)
    return state


def resume(via: str) -> None:
    if HALT_PATH.exists():
        HALT_PATH.unlink()
    journal.append("event", "policy:halt", "kill switch lifted — resuming", actor=via)


# ---- approvals --------------------------------------------------------------

def _path(aid: str) -> Path:
    return APPROVALS_DIR / f"{aid}.json"


def load(aid: str) -> dict:
    return json.loads(_path(aid).read_text(encoding="utf-8"))


def save(approval: dict) -> None:
    problems = contracts.validate_approval(approval)
    if problems:
        raise ValueError("approval violates the contract: " + "; ".join(problems))
    APPROVALS_DIR.mkdir(parents=True, exist_ok=True)
    _path(approval["id"]).write_text(
        json.dumps(approval, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def all_approvals() -> list[dict]:
    if not APPROVALS_DIR.is_dir():
        return []
    out = []
    for f in sorted(APPROVALS_DIR.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return out


def request(aid: str, requested_action: str, reason: str, consequence: str,
            reversible: bool, task: str | None = None,
            capability: str | None = None) -> dict:
    """Ask the operator — unless he has already said yes to this class of thing.

    `capability` is what turns a standing grant from a record into a
    permission. `aletheia.authority` has been able to hold delegated
    authority since the systems layer landed, and nothing consumed it: a
    grant was written and every approval still went to him anyway. This is
    the single place that consumes one, so every caller in the repo gets
    the behaviour and every use leaves a claim receipt.

    A grant can never reach a capability the registry marks high-risk or
    operator_always — `authority.allows` refuses those outright — so
    spending, binding agreements, disclosures and destructive actions keep
    asking him forever, by construction rather than by remembering to
    (§56 L4). Passing `capability` on those calls is still worth doing: it
    puts the capability id in the approval record, which is what an audit
    later actually wants to read.
    """
    if _path(aid).exists():
        return load(aid)  # idempotent — an open request is not re-asked
    approval = {
        "id": aid, "requested_action": requested_action, "reason": reason,
        "consequence": consequence, "reversible": reversible,
        "state": "PENDING", "requested_at": _now(),
    }
    if task:
        approval["task"] = task
    if capability:
        approval["capability"] = capability
    granted = None
    if capability:
        from aletheia import authority  # local: authority reads policy
        try:
            granted = authority.satisfy(capability, aid)
        except Exception:
            granted = None  # a broken grant store authorizes nothing
    if granted:
        approval["state"] = "APPROVED"
        approval["decided_at"] = _now()
        approval["decided_via"] = f"grant:{granted}"
    save(approval)
    if granted:
        journal.append("decision", f"approval:{aid}",
                       f"APPROVED by standing grant {granted} — {requested_action}",
                       actor=f"grant:{granted}")
    else:
        journal.append("event", f"approval:{aid}", f"requested — {requested_action}")
    return approval


def decide(aid: str, decision: str, via: str, because: str = "") -> dict:
    if decision not in ("APPROVED", "DENIED"):
        raise ValueError("decision must be APPROVED or DENIED")
    approval = load(aid)
    if approval["state"] != "PENDING":
        raise ValueError(f"approval {aid!r} is {approval['state']} — already decided")
    approval["state"] = decision
    approval["decided_at"] = _now()
    approval["decided_via"] = via
    save(approval)
    journal.append("decision", f"approval:{aid}",
                   f"{decision}" + (f" — {because}" if because else ""), actor=via)
    return approval


def is_approved(aid: str) -> bool:
    try:
        return load(aid)["state"] == "APPROVED"
    except (OSError, json.JSONDecodeError, KeyError):
        return False


def publish(aid: str, repo_full: str, request_fn=gh.request) -> None:
    """File the approval as an issue so the operator gets a phone-visible
    ask; approvals.yml turns their approve/deny comment into a decision."""
    a = load(aid)
    body = (
        f"**Action:** {a['requested_action']}\n\n"
        f"**Why:** {a['reason']}\n\n"
        f"**Consequence:** {a['consequence']}\n\n"
        f"**Reversible:** {'yes' if a['reversible'] else 'NO'}\n"
        + (f"\n**Task:** `{a['task']}`\n" if a.get("task") else "")
        + "\nComment **approve** or **deny** (repo owner only), or tell Thea."
    )
    request_fn("POST", f"/repos/{repo_full}/issues",
               {"title": f"{ISSUE_PREFIX} {aid} — {a['requested_action'][:60]}",
                "body": body})


def comment_decide(title: str, body: str, via: str) -> str:
    """Parse an issue-comment decision (called by approvals.yml, which has
    already verified the commenter is the repo owner)."""
    if not title.startswith(ISSUE_PREFIX):
        return "not an approval issue"
    aid = title[len(ISSUE_PREFIX):].strip().split(" — ")[0].strip()
    word = body.strip().lower().split()[0] if body.strip() else ""
    if word not in ("approve", "approved", "deny", "denied"):
        return "no decision word — ignoring"
    decision = "APPROVED" if word.startswith("approve") else "DENIED"
    decide(aid, decision, via)
    return f"{aid} -> {decision}"


# ---- capability gating ------------------------------------------------------

def required_approval(capability_id: str) -> str:
    """The registry's declared approval_policy for a capability."""
    return capabilities.get(capability_id)["approval_policy"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Authority: approvals + kill switch.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p_h = sub.add_parser("halt"); p_h.add_argument("--reason", default="")
    sub.add_parser("resume")
    sub.add_parser("list")
    p_d = sub.add_parser("decide")
    p_d.add_argument("id"); p_d.add_argument("decision", choices=["APPROVED", "DENIED"])
    p_d.add_argument("--because", default="")
    p_c = sub.add_parser("comment-decide")
    p_c.add_argument("--title", required=True); p_c.add_argument("--body", required=True)
    p_c.add_argument("--via", default="issue-comment")
    args = ap.parse_args(argv)

    if args.cmd == "status":
        h = halted()
        print(f"HALTED — {h['reason']}" if h else "running")
        pending = [a for a in all_approvals() if a["state"] == "PENDING"]
        print(f"{len(pending)} approval(s) pending")
        return 0
    if args.cmd == "halt":
        halt(args.reason, via="operator-cli"); print("halted")
    elif args.cmd == "resume":
        resume(via="operator-cli"); print("resumed")
    elif args.cmd == "decide":
        decide(args.id, args.decision, via="operator-cli", because=args.because)
        print(f"{args.id} -> {args.decision}")
    elif args.cmd == "comment-decide":
        print(comment_decide(args.title, args.body, args.via))
    else:
        for a in all_approvals():
            print(f"[{a['state']:8}] {a['id']}  {a['requested_action']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
