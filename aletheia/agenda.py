"""Say what you want. She does it. Money is the line, and it is absolute.

The operator, 2026-09-02: *"this needs to be able to take any request I give
it and execute it except no spending money."*

Everything needed for that already existed in pieces. `planner.compile()`
turns plain English into validated command steps; `intercom.execute_command`
runs one; `mission` bounds a goal with a budget. What did not exist was the
join: every compiled plan filed an approval and waited, so "any request"
meant "any request, once you come back and click yes." An assistant you have
to authorize per errand is a form you fill in, not an assistant.

An AGENDA is that join. One plain-English request, compiled, then executed
step by step under a live mission budget, with no further asking.

THE THREE THINGS IT WILL NOT DO, and why each is here rather than assumed:

1. **It cannot spend money.** `MONEY` names every capability that moves
   money or commits to a payment, and it is refused at compile time and
   again before every step. It is not a default, not a setting, and there
   is no flag that turns it off — the operator drew this line himself and
   the code should not offer to redraw it. (Money is also structurally
   absent from the command grammar: purchases and bookings are errands,
   which live behind their own operator_always approvals. The explicit
   refusal is belt to that braces, because "it happens to be unreachable"
   stops being true the moment somebody adds a kind.)

2. **It cannot approve anything — including its own requests.** `approve`
   and `deny` are real command kinds. An agenda that could run them could
   file the approval for the purchase it is forbidden to make and then
   grant it, which converts every other refusal in this file into a
   speed bump. This is the hole the design nearly shipped with.

3. **It cannot touch its own off switch.** `halt` and `resume` are refused
   for the same reason. A kill switch the agent can lift is decoration.

Also refused: `intent` (an agenda that files intents that file intents is a
loop with a budget attached), `rule` (standing proactive rules are authority
that outlives the mission), and `dispatch` (fires workflows in other repos —
outward-facing, and someone else's compute).

What is LEFT is most of what he actually asks for: read anything, research,
remember, remind, plan, file tasks and issues, draft mail, propose meetings,
track projects, check the screen. Drafting mail is included deliberately and
is still safe: `mail.send_approved` delivers only drafts he has approved, so
an agenda can write the letter and never post it.
"""
from __future__ import annotations

import argparse
import json
import sys

from aletheia import (intercom, journal, mission, notifications, planner,
                      policy, stateio)
from aletheia.fleet import load_fleet

ACTOR = "aletheia-agenda"

MAX_REQUEST_CHARS = 1_000
MAX_STEPS = 12

# Capabilities that move money or commit to a payment. Refused at compile
# time and before every step, with no flag that turns it off.
MONEY = {
    "purchase.execute", "finance.transact", "reservation.book",
    "subscription.cancel", "errand.run", "shopping.purchase",
}

# Command kinds an agenda may never run, whatever the plan says.
FORBIDDEN_KINDS = {
    # self-authorization: the hole that would undo every other refusal here
    "approve", "deny",
    # a kill switch the agent can lift is decoration
    "halt", "resume",
    # an agenda that files intents that file intents is a loop with a budget
    "intent",
    # standing proactive rules are authority that outlives this mission
    "rule",
    # fires workflows in other repositories: outward, and someone else's compute
    "dispatch",
}

REFUSAL_REASON = {
    "approve": "an agenda that can approve things can approve its own",
    "deny": "an agenda that can decide approvals can decide its own",
    "halt": "she does not get to touch her own off switch",
    "resume": "she does not get to touch her own off switch",
    "intent": "an agenda filing intents that file intents is a loop",
    "rule": "a standing rule outlives this mission's budget",
    "dispatch": "that runs a workflow in another repository",
}


class AgendaError(RuntimeError):
    pass


class AgendaRefused(PermissionError):
    """The plan wanted something an agenda may never do."""


def refuse_money(capability_ids) -> None:
    """The operator's own line. Absolute, and checked more than once."""
    for cid in capability_ids or []:
        if cid in MONEY:
            raise AgendaRefused(
                f"{cid} spends money. An agenda never does that — ask me for "
                "it directly and it goes through an approval you see")


def screen(plan: planner.Plan) -> tuple[list, list]:
    """Split a compiled plan into what will run and what is refused.

    Returns (runnable, refused) rather than raising on the first problem: he
    asked for one thing, and "I did four of the five steps and here is why
    not the fifth" is a better answer than refusing the lot over a step the
    planner threw in.
    """
    refuse_money(plan.required_capabilities)
    runnable, refused = [], []
    for step in plan.executable:
        kind = step.command["kind"]
        if kind in FORBIDDEN_KINDS:
            refused.append({"step": step.n, "kind": kind,
                            "reason": REFUSAL_REASON.get(kind, "not allowed in an agenda")})
            continue
        runnable.append(step)
    for step in plan.blocked:
        refused.append({"step": step.n, "kind": (step.command or {}).get("kind"),
                        "reason": f"{step.status}: {step.detail}"[:200]})
    return runnable, refused


def run(request: str, *, fleet: dict | None = None, executor=None,
        require_mission: bool = True) -> dict:
    """One plain-English request, compiled and carried out.

    `require_mission` is True in production: executing without asking is
    something a live budget authorizes, not something this function decides.
    The CLI can pass False for a single request the operator is watching,
    which is the same trust as him typing the command himself.
    """
    request = str(request or "").strip()
    if not request or len(request) > MAX_REQUEST_CHARS:
        raise ValueError(f"request must be 1..{MAX_REQUEST_CHARS} characters")
    policy.ensure_not_halted()
    live = mission.covers("agenda.execute")
    if require_mission and not live:
        running = mission.active()
        if running:
            raise AgendaError(
                f"the running mission is {running['kind']!r}, which does not "
                "cover agendas — `python -m aletheia.mission stop`, then "
                "`python -m aletheia.mission start anything`")
        raise AgendaError(
            "no mission is running. `python -m aletheia.mission start anything` "
            "authorizes a budget; without one, every request is approved "
            "individually, which is the thing an agenda exists to avoid")

    fleet = fleet or load_fleet()
    executor = executor or intercom.execute_command
    plan = planner.compile(request, fleet=fleet)
    runnable, refused = screen(plan)
    if len(runnable) > MAX_STEPS:
        raise AgendaError(
            f"that compiles to {len(runnable)} steps; break it into smaller "
            f"asks (the ceiling is {MAX_STEPS} per request)")
    if not runnable:
        return _finish(request, plan, [], refused,
                       "nothing in that plan was something I can carry out")

    done = []
    for step in runnable:
        # Re-read both between every step. A twenty-minute agenda that
        # checked the kill switch once at the top would keep going for
        # nineteen minutes after he said stop.
        policy.ensure_not_halted()
        if require_mission and not mission.covers("agenda.execute"):
            refused.append({"step": step.n, "kind": step.command["kind"],
                            "reason": "the mission's budget ran out mid-plan"})
            break
        refuse_money([step.capability] if step.capability else [])
        try:
            result = executor(step.command, fleet)
            # intercom.execute_command answers with a detail LINE, the way
            # every channel expects; a test double may answer with a
            # receipt dict. Both are receipts and neither shape is a
            # failure — the first live agenda (2026-09-02) marked every
            # string answer "failed" by calling .get() on it.
            if isinstance(result, dict):
                outcome = str(result.get("outcome") or "done")
                detail = str(result.get("detail") or "")
            else:
                outcome, detail = "done", str(result or "")
            done.append({"step": step.n, "kind": step.command["kind"],
                         "outcome": outcome, "detail": detail[:300]})
        except policy.Halted:
            raise
        except intercom.Unavailable as exc:
            # A missing tool is neither her refusal nor her mistake; say
            # which tool, so the next step is an install and not a rerun.
            done.append({"step": step.n, "kind": step.command["kind"],
                         "outcome": "unavailable", "detail": str(exc)[:300]})
        except Exception as exc:
            # One bad step does not abandon the rest: he asked for an
            # outcome, and stopping dead on step two of five delivers less
            # than carrying on and telling him what failed.
            done.append({"step": step.n, "kind": step.command["kind"],
                         "outcome": "failed", "detail": f"{type(exc).__name__}: {exc}"[:300]})
    return _finish(request, plan, done, refused)


def _finish(request: str, plan: planner.Plan, done: list, refused: list,
            note: str = "") -> dict:
    ok = [d for d in done if d["outcome"] not in ("failed", "unavailable")]
    record = {
        "request": request,
        "summary": plan.summary or request,
        "ran": done,
        "refused": refused,
        "succeeded": len(ok),
        "failed": len(done) - len(ok),
        "note": note,
        "at": stateio.utcnow(),
    }
    mission.note(f"agenda: {request[:90]} — {len(ok)} step(s)", spent=1)
    journal.append(
        "action", "agenda",
        f"{request[:100]} — {len(ok)} done, {len(done) - len(ok)} failed, "
        f"{len(refused)} refused", actor=ACTOR)
    try:
        notifications.publish(
            f"Did: {request[:70]}", spoken(record)[:400],
            priority="NORMAL", source="agenda",
            dedupe_key=f"agenda:{record['at']}:{request[:40]}")
    except Exception:
        pass
    return record


def spoken(record: dict) -> str:
    """What she says back. Refusals are said out loud, never swallowed —
    he needs to know the difference between "done" and "mostly done"."""
    if record.get("note"):
        parts = [record["note"] + "."]
    elif not record["ran"]:
        parts = ["I did not get anything done on that."]
    else:
        parts = [f"Done — {record['succeeded']} step"
                 f"{'s' if record['succeeded'] != 1 else ''}."]
    if record["failed"]:
        parts.append(f"{record['failed']} failed.")
    if record["refused"]:
        first = record["refused"][0]["reason"]
        parts.append(f"I would not do {len(record['refused'])} of them: {first}.")
    return " ".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Say what you want; she does it. Never spends money.")
    ap.add_argument("request")
    ap.add_argument("--no-mission", action="store_true",
                    help="run one request without a mission budget — for when "
                         "you are watching it happen")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        record = run(args.request, require_mission=not args.no_mission)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(record, indent=2))
    else:
        print(spoken(record))
        for entry in record["ran"]:
            print(f"  {entry['step']}. {entry['kind']}: {entry['outcome']}"
                  + (f" — {entry['detail']}" if entry["detail"] else ""))
        for entry in record["refused"]:
            print(f"  {entry['step']}. {entry['kind']} REFUSED — {entry['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
