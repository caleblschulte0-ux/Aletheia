"""Saying yes once (Playbook §56 L3, §70).

`authority.py` could hold delegated authority since the systems layer, and
`policy.request` has consumed it since yesterday. Nobody has ever created
a grant, because creating one meant: request an approval object, approve
it, then call `authority.create` with capability ids, an ISO expiry and a
use count. That is a correct API and an impossible ask, so in practice she
asked about everything, every time.

This is the front door. `python -m aletheia.standing on` sets up the
ordinary case in one command: the routine tier, for a month, bounded by
uses, with the approval it requires created and decided in the same
breath — because the operator typing the command IS the operator giving
the permission, and pretending otherwise is ceremony rather than safety.

What it cannot do is the point:

**It only ever covers the routine tier.** Reminders, tasks, plans, notes,
contacts, watchers — local, reversible, reaching nobody. Anything that
spends, sends, publishes, books or binds keeps `intent.execute`, which is
operator_always, and `authority.allows` refuses to grant a high-risk or
operator_always capability at spend time as well as at creation time
(§56 L4). A grant edited on disk to name `email.send` still buys nothing.

**It expires and it runs out.** A standing permission with no end is one
nobody remembers giving. Default: 30 days, 500 uses, revocable by one
word, and every single use leaves a claim receipt.

`status` answers the question he should be able to ask at any moment —
"what can you do right now without asking me?" — from the registry and
the live grants, never from memory.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from aletheia import authority, capabilities, intercom, journal, policy

ACTOR = "aletheia-standing"

# The one tier a grant may cover. Named explicitly rather than computed, so
# widening it is a visible edit someone has to justify (§70).
ROUTINE_CAPABILITY = "intent.execute.routine"
GRANT_ID = "standing-routine"
DEFAULT_DAYS = 30
DEFAULT_USES = 500

# THE SECOND GRANT: sending the applications she has filled. His ruling,
# 2026-09-23, in his words: "Yes, this can apply to jobs without my
# permission. In fact, that's like kind of the whole point of it." The beat
# (`runtime.send_approved_applications`) has spent a grant over this
# capability since 2026-09-12 - and nothing had ever CREATED one, so every
# filled application sat waiting for a tap and 82 were waiting the night
# he said this. `application.submit` is `registry_grant` in the registry,
# which is what makes it grantable at all; `authority.allows` still
# refuses anything high-risk or operator_always, and part-time work and a
# job only her own model judged realistic still wait for his own yes
# (`apply_run.waits_for_his_ok`) whatever this grant says.
JOBS_CAPABILITY = "application.submit"
# And the account a site wants before it will take one. His words, the
# morning of 2026-09-23: "Yeah, it can make its own accounts. I don't give a
# shit." Five "press 'Create Account'" approvals were on his page when he
# said it. `account.create` is `registry_grant` in the registry since that
# ruling; the general browser's job missions spend this grant on the act
# their held button is (`jobs_grant`), never on `web.commit` itself.
JOBS_CAPABILITIES = (JOBS_CAPABILITY, "account.create")
JOBS_GRANT_ID = "standing-jobs"
DEFAULT_JOB_DAYS = 365
DEFAULT_JOB_USES = 10_000


def _expiry(days: int) -> str:
    return (dt.datetime.now(dt.timezone.utc)
            + dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def active() -> dict | None:
    """The live routine grant, or None."""
    for grant in authority.active_grants():
        if ROUTINE_CAPABILITY in grant.get("capability_ids", []):
            return grant
    return None


def enable(*, days: int = DEFAULT_DAYS, uses: int = DEFAULT_USES,
           via: str = "operator") -> dict:
    """Grant standing authority over the routine tier.

    The approval this needs is created and decided here, by the operator
    running the command. `authority.create` still refuses outright if the
    capability is high-risk or operator_always, so this cannot be turned
    into a way to grant something it should not.
    """
    if not 1 <= int(days) <= 365:
        raise ValueError("days must be 1..365 — a permission with no end is "
                         "one nobody remembers giving")
    existing = active()
    if existing:
        return existing
    approval_id = f"{GRANT_ID}-{dt.date.today().isoformat()}"
    policy.request(
        approval_id,
        requested_action=f"standing authority over {ROUTINE_CAPABILITY}",
        reason=("stop asking about plans that only touch this machine and can "
                "be undone"),
        consequence=("routine plans run without a decision for "
                     f"{days} days or {uses} uses, whichever comes first; "
                     "anything that sends, spends, publishes or books still asks"),
        reversible=True)
    policy.decide(approval_id, "APPROVED", via=via,
                  because="granted at the command line by the operator")
    grant = authority.create(
        f"{GRANT_ID}-{dt.date.today().isoformat()}"[:60],
        capability_ids=[ROUTINE_CAPABILITY], approval_id=approval_id,
        expires=_expiry(int(days)), max_uses=int(uses),
        note="routine tier: local, reversible, reaches nobody")
    journal.append("decision", "authority",
                   f"standing authority granted over {ROUTINE_CAPABILITY} "
                   f"for {days} days / {uses} uses", actor=ACTOR)
    return grant


def jobs_active() -> dict | None:
    """The live grant over sending applications, or None."""
    for grant in authority.active_grants():
        if JOBS_CAPABILITY in grant.get("capability_ids", []):
            return grant
    return None


def jobs_enable(*, days: int = DEFAULT_JOB_DAYS, uses: int = DEFAULT_JOB_USES,
                via: str = "operator", quote: str = "") -> dict:
    """Send filled applications without a tap, on his say-so at the keyboard.

    `quote` is his own words, kept on the approval: a grant is a thing he
    gave, and the record should say what he said when he gave it.
    """
    if not 1 <= int(days) <= 365:
        raise ValueError("days must be 1..365 - a permission with no end is "
                         "one nobody remembers giving")
    existing = jobs_active()
    if existing and all(cid in existing.get("capability_ids", []) for cid in JOBS_CAPABILITIES):
        return existing
    if existing:
        # A grant from before accounts were hers: replaced, not widened in
        # place - a grant is a thing he gave, and this is a new one he gave.
        authority.revoke(existing["id"])
        journal.append("decision", "authority",
                       f"standing authority over {JOBS_CAPABILITY} replaced by one that also covers "
                       "account.create" + (f" - his words: {quote}" if quote else ""), actor=ACTOR)
    # Unique per grant, not per day: revoking and re-granting on the same
    # day collided on "already decided".
    import uuid
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    approval_id = f"{JOBS_GRANT_ID}-{stamp}"
    policy.request(
        approval_id,
        requested_action=f"standing authority over {', '.join(JOBS_CAPABILITIES)}",
        reason="send the applications she has filled, and make the account a site wants first, "
               "without asking each time",
        consequence=(f"applications she has filled go out under his name without a tap for "
                     f"{days} days or {uses} uses, whichever comes first, and an account a job site "
                     "wants before it will take one is made in his name; part-time, contract, "
                     "temporary and internship work, and a job only her own model judged "
                     "realistic, still wait for his own yes"),
        reversible=True)
    policy.decide(approval_id, "APPROVED", via=via,
                  because=("granted at the command line by the operator"
                           + (f" - his words: {quote}" if quote else "")))
    grant = authority.create(
        approval_id[:60], capability_ids=list(JOBS_CAPABILITIES), approval_id=approval_id,
        expires=_expiry(int(days)), max_uses=int(uses),
        note="jobs: send filled applications, and make the accounts sites want, without a tap"
             + (f" - his words: {quote}" if quote else ""))
    journal.append("decision", "authority",
                   f"standing authority granted over {', '.join(JOBS_CAPABILITIES)} for {days} days / "
                   f"{uses} uses" + (f" - his words: {quote}" if quote else ""), actor=ACTOR)
    return grant


def jobs_disable(via: str = "operator") -> bool:
    grant = jobs_active()
    if not grant:
        return False
    authority.revoke(grant["id"])
    journal.append("decision", "authority",
                   f"standing authority over {JOBS_CAPABILITY} revoked", actor=via)
    return True


def jobs_status() -> dict:
    """Whether she may send applications without a tap right now, and how much
    of that permission is left - so "why is this waiting on me" has an answer."""
    grant = jobs_active()
    used = len(authority._claims(grant["id"])) if grant else 0
    return {"granted": bool(grant),
            "accounts": bool(grant) and "account.create" in grant.get("capability_ids", []),
            "expires": grant.get("expires") if grant else None,
            "uses_left": (grant["max_uses"] - used) if grant else 0,
            "command": "python -m aletheia.standing jobs on"}


def jobs_spoken() -> str:
    from aletheia import speech
    state = jobs_status()
    if not state["granted"]:
        return ("I ask you before every application I send. At your keyboard, "
                "'python -m aletheia.standing jobs on' lets me send them without asking.")
    accounts = (" and make the accounts sites want" if state["accounts"]
                else "; an account a site wants still waits for your yes - 'python -m aletheia.standing "
                     "jobs on' again lets me make it")
    return (f"I send the applications I fill{accounts} without asking - {state['uses_left']} left, "
            f"until {speech.humanize_time(state['expires'])}. Part-time or contract work "
            "still waits for your own yes.")


def disable(via: str = "operator") -> bool:
    """Revoke it. One word, effective on the next request."""
    grant = active()
    if not grant:
        return False
    authority.revoke(grant["id"])
    journal.append("decision", "authority",
                   f"standing authority over {ROUTINE_CAPABILITY} revoked",
                   actor=via)
    return True


def status() -> dict:
    """What she can do right now without asking — from the registry, live."""
    grant = active()
    used = len(authority._claims(grant["id"])) if grant else 0
    reg = capabilities.load_registry()
    by_id = {c["id"]: c for c in reg["capabilities"]}

    def sayable(tier_name):
        return sorted(k for k in intercom.KIND_ARGS
                      if intercom.tier(k) == tier_name)

    return {
        "granted": bool(grant),
        "expires": grant.get("expires") if grant else None,
        "uses_left": (grant["max_uses"] - used) if grant else 0,
        "without_asking": {
            "always": sayable(intercom.TIER_READ),
            "while_granted": sayable(intercom.TIER_ROUTINE) if grant else [],
        },
        "always_asks": sayable(intercom.TIER_WORLD),
        "never_grantable": sorted(
            c["id"] for c in reg["capabilities"]
            if c["status"] == "AVAILABLE"
            and (c["risk_class"] == "high" or c["approval_policy"] == "operator_always")),
    }


def spoken() -> str:
    """The answer to "what can you do without asking me?", out loud."""
    from aletheia import speech
    state = status()
    reads = len(state["without_asking"]["always"])
    if not state["granted"]:
        return (f"I answer {reads} kinds of question without asking, and I ask "
                "you about everything else. Say 'grant standing authority' and "
                "I'll stop asking about reminders, tasks and notes too.")
    routine = len(state["without_asking"]["while_granted"])
    return (f"I handle {reads + routine} kinds of thing without asking — "
            f"questions, reminders, tasks, notes. I still ask you about "
            f"{speech.count_phrase(len(state['always_asks']), 'thing')}: "
            "anything that sends, spends, publishes or books. "
            f"{state['uses_left']} uses left, until "
            f"{speech.humanize_time(state['expires'])}.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Standing authority over the routine tier.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    on = sub.add_parser("on", help="stop asking about routine plans")
    on.add_argument("--days", type=int, default=DEFAULT_DAYS)
    on.add_argument("--uses", type=int, default=DEFAULT_USES)
    sub.add_parser("off", help="revoke it")
    sub.add_parser("status", help="what she can do without asking")
    jobs = sub.add_parser("jobs", help="sending the applications she fills")
    jobs.add_argument("what", choices=("on", "off", "status"))
    jobs.add_argument("--days", type=int, default=DEFAULT_JOB_DAYS)
    jobs.add_argument("--uses", type=int, default=DEFAULT_JOB_USES)
    jobs.add_argument("--quote", default="", help="his own words, kept on the approval")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "jobs":
            if args.what == "on":
                grant = jobs_enable(days=args.days, uses=args.uses, quote=args.quote)
                print(f"Granted until {grant['expires']} ({grant['max_uses']} uses).")
            elif args.what == "off":
                print("Revoked." if jobs_disable() else "There was no jobs grant.")
            else:
                print(json.dumps(jobs_status(), indent=2))
            print(jobs_spoken())
            return 0
        if args.cmd == "on":
            grant = enable(days=args.days, uses=args.uses)
            print(f"Granted until {grant['expires']} ({grant['max_uses']} uses).")
            print(spoken())
            return 0
        if args.cmd == "off":
            print("Revoked." if disable() else "There was no standing grant.")
            return 0
        print(json.dumps(status(), indent=2))
        print()
        print(spoken())
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
