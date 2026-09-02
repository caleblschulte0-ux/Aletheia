"""One goal, a budget, and permission to keep working until it is spent.

The gap this closes, in the operator's own words (2026-09-02): *"If I say,
hey, where are my projects standing? Look at it through all and fix all the
problems — I can do that."* He could not. Not because a gate refused him,
but because nothing in this repo could work on a GOAL. Every capability was
scoped to one small action with one approval attached, and the loop that
repairs code did exactly one repair, in one repository, per scheduled run,
and then returned. Forty job applications meant forty approvals. "Fix all
my projects" meant a trickle nobody would ever mistake for an assistant.

That per-step scoping was the right instinct applied to the wrong things.
It is correct for spending money and for sending mail as him. It is useless
for "read my repositories and fix what is broken", where the effect of
asking every time is that she never does anything at all.

So a MISSION is the unit he actually thinks in: a goal, a budget, and a
deadline, authorized once. Inside it she works without stopping to ask.
The budget is what makes that safe to say yes to — not a promise about her
judgement, but a ceiling that exists whether her judgement is good or not.

Four things a mission is NOT, and each is enforced here rather than
described:

- **It is not new authority.** A mission may only cover capabilities on
  the `MISSION_ALLOWED` list, and `operator_always` is refused outright;
  both are checked at creation AND on every claim, so a mission record
  edited on disk to name `email.send` or `purchase.execute` buys nothing. Ability and
  permission stay separate (§70), and §56 L4 is untouched: spending,
  sending, binding and destructive actions keep asking every single time,
  inside a mission exactly as outside one.
- **It is not open-ended.** A budget with no ceiling is a standing grant
  wearing a costume. Every mission carries a wall-clock deadline and a
  work ceiling, and it ends itself on whichever comes first.
- **It is not unstoppable.** HALT ends a mission mid-flight, re-read
  before every slice, and `stop` is one word.
- **It is not remotely grantable.** Same machine binding as every other
  standing grant (`aletheia.machine_binding`): a mission file arriving
  over git sync is inert, because the signature needs a key that never
  leaves this machine.

The runner is deliberately SLICED. `run_slice()` does a bounded chunk and
returns, so the scheduled task keeps its execution limit, a crash costs
one slice rather than the mission, and progress is durable between them
(§27 — real work outlives the process it started in).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import secrets
import sys

from aletheia import (capabilities, journal, machine_binding, policy,
                      stateio)

ACTOR = "aletheia-mission"
MISSION_PATH = stateio.private_dir("mission") / "current.json"

RUNNING, DONE, STOPPED, EXPIRED, FAILED = (
    "RUNNING", "DONE", "STOPPED", "EXPIRED", "FAILED")
TERMINAL = {DONE, STOPPED, EXPIRED, FAILED}

# What a mission may cover is a POSITIVE allowlist, not a risk-class rule.
#
# The first draft refused anything `high`, which sounds stricter and is
# worse. `code.autonomous` is high — and it cannot merge, reaches nobody
# until a human acts, and is undone by closing a pull request — so that
# rule would have forced a choice between weakening the registry to fit
# the feature (§70's exact prohibition) and special-casing one id in this
# file, which is the same thing wearing a hat.
#
# A named allowlist has neither problem. Adding an id here is a visible
# edit in a reviewed diff, the registry keeps meaning what it means, and
# nothing is covered by accident because something was classified
# generously. Two independent guards, both enforced below:
#
#   1. the id must be in this set, AND
#   2. it must not be operator_always — §56 L4, the actual doctrinal line,
#      which is what refuses spending, sending, booking, phoning, browsing
#      interactively, secret-filling and every destructive action. No
#      budget makes those answerable in advance.
MISSION_ALLOWED = {
    "code.autonomous",   # proposes pull requests; no merge path exists
    "research.answer",   # reads public pages; writes a document; sends nothing
}
REFUSED_POLICY = {"operator_always"}

MAX_HOURS = 12
MAX_ACTIONS = 100
DEFAULT_HOURS = 2
DEFAULT_ACTIONS = 12


class MissionError(RuntimeError):
    pass


class MissionRefused(PermissionError):
    """A mission tried to cover something a mission may not cover."""


# ---- the kinds of goal she can be given -----------------------------------
#
# A kind is a NAME plus the capabilities it spends. Adding one is a
# deliberate edit here, not a string the caller invents: an arbitrary goal
# with an arbitrary capability list is exactly the "grant yourself what you
# need" path §70 exists to prevent.

KINDS: dict[str, dict] = {
    "fix_projects": {
        "summary": "Read every enabled public repository, find real defects "
                   "(open issues, failing CI), and open reviewed pull requests",
        "capabilities": ["code.autonomous"],
        "unit": "pull requests",
    },
    "research": {
        "summary": "Work through a list of questions, answering each from real "
                   "sources and writing up what the sources do not settle",
        "capabilities": ["research.answer"],
        "unit": "questions",
    },
}


def _now(now: dt.datetime | None = None) -> dt.datetime:
    value = now or dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(dt.timezone.utc)


def _parse(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("mission timestamp must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def refuse_forbidden(capability_ids: list[str]) -> None:
    """Refuse a capability a mission may never carry — at creation and spend.

    Checked in both places on purpose. Checking only at creation would mean
    a registry entry re-classified as high-risk tomorrow keeps running under
    a mission authorized today, which is the wrong way round: the registry
    is the source of truth and it is allowed to change its mind.
    """
    reg = capabilities.load_registry()
    known = {c["id"]: c for c in reg["capabilities"]}
    for cid in capability_ids:
        entry = known.get(cid)
        if entry is None:
            raise MissionRefused(
                f"{cid!r} is not in the capability registry — a mission cannot "
                "cover something that does not honestly exist")
        if cid not in MISSION_ALLOWED:
            raise MissionRefused(
                f"{cid!r} is not on the mission allowlist. Covering it is a "
                "reviewed edit to MISSION_ALLOWED, argued on its own merits — "
                "never a consequence of building something that wanted it")
        if entry.get("approval_policy") in REFUSED_POLICY:
            raise MissionRefused(
                f"{cid!r} is {entry['approval_policy']}; no budget makes that "
                "answerable in advance (§56 L4). Spending, sending, booking, "
                "phoning and destructive actions ask every time, inside a "
                "mission exactly as outside one")


def load() -> dict | None:
    if not MISSION_PATH.is_file():
        return None
    try:
        value = stateio.read_json(MISSION_PATH)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _binding_fields(record: dict) -> dict:
    """What the machine signature covers: identity, the approval it leans
    on, the deadline, and every ceiling. Raising a ceiling on disk, moving
    the deadline, or delivering the file from another machine all break it."""
    return {
        "id": record.get("id"),
        "approval_id": record.get("approval_id"),
        "kind": record.get("kind"),
        "expires": record.get("expires"),
        "max_actions": record.get("max_actions"),
        "capabilities": sorted(record.get("capabilities") or []),
    }


def active(*, now: dt.datetime | None = None) -> dict | None:
    """The live mission, or None — with every reason it might not be live.

    Order matters. The machine binding is checked FIRST, before the record
    is trusted for anything at all, because an unbound record is not a
    mission whose budget we should be reading.
    """
    record = load()
    if not record or record.get("state") != RUNNING:
        return None
    if not machine_binding.verify(record, _binding_fields(record)):
        machine_binding.refuse_unbound(
            record, kind="mission",
            restore_command="python -m aletheia.mission start <kind>")
        return None
    try:
        if _parse(record["expires"]) <= _now(now):
            _finish(record, EXPIRED, "the mission's time ran out")
            return None
        if int(record["actions_used"]) >= int(record["max_actions"]):
            _finish(record, DONE, "the mission's work budget was spent")
            return None
        if not policy.is_approved(record["approval_id"]):
            return None
        refuse_forbidden(record.get("capabilities") or [])
    except MissionRefused as exc:
        _finish(record, STOPPED, f"refused: {exc}")
        return None
    except (KeyError, TypeError, ValueError):
        return None
    return record


def start(kind: str, *, hours: int = DEFAULT_HOURS,
          actions: int = DEFAULT_ACTIONS, via: str = "operator-local",
          now: dt.datetime | None = None) -> dict:
    """Authorize one goal, locally, with a budget. This is the operator's
    single decision — the command IS the permission, and dressing it up as
    a separate approval prompt he then answers is ceremony, not safety."""
    spec = KINDS.get(kind)
    if spec is None:
        raise MissionError(
            f"unknown mission kind {kind!r}; known: {', '.join(sorted(KINDS))}")
    if type(hours) is not int or not 1 <= hours <= MAX_HOURS:
        raise ValueError(f"hours must be 1..{MAX_HOURS}")
    if type(actions) is not int or not 1 <= actions <= MAX_ACTIONS:
        raise ValueError(f"actions must be 1..{MAX_ACTIONS}")
    policy.ensure_not_halted()
    refuse_forbidden(spec["capabilities"])

    current = active(now=now)
    if current:
        raise MissionError(
            f"mission {current['id']} is already running ({current['kind']}); "
            "stop it first — two missions competing for one budget is not a "
            "budget")

    stamp = _now(now)
    mission_id = f"m-{stamp.strftime('%Y%m%d-%H%M')}-{secrets.token_hex(3)}"
    approval_id = f"{mission_id}-operator"
    expires = stamp + dt.timedelta(hours=hours)
    policy.request(
        approval_id,
        requested_action=f"mission:{kind}",
        reason=spec["summary"],
        consequence=(
            f"until {expires.strftime('%Y-%m-%dT%H:%M:%SZ')} or "
            f"{actions} {spec['unit']}, whichever comes first, this work "
            "proceeds without asking again; nothing that spends, sends, "
            "binds or destroys is covered, and HALT ends it immediately"),
        reversible=True)
    policy.decide(
        approval_id, "APPROVED", via=via,
        because="the operator authorized this goal and budget at the command line")

    record = {
        "version": 1,
        "id": mission_id,
        "kind": kind,
        "state": RUNNING,
        "goal": spec["summary"],
        "approval_id": approval_id,
        "capabilities": list(spec["capabilities"]),
        "created_at": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "max_actions": actions,
        "actions_used": 0,
        "slices": 0,
        "log": [],
    }
    record["machine_binding"] = machine_binding.sign(_binding_fields(record))
    stateio.write_json_atomic(MISSION_PATH, record)
    journal.append(
        "decision", "mission",
        f"STARTED {mission_id} ({kind}) — budget {hours}h / {actions} "
        f"{spec['unit']}, expires {record['expires']}",
        actor=ACTOR, refs=[f"approval:{approval_id}"])
    return record


def _finish(record: dict, state: str, why: str) -> dict:
    record["state"] = state
    record["ended_at"] = stateio.utcnow()
    record["ended_because"] = why
    stateio.write_json_atomic(MISSION_PATH, record)
    journal.append(
        "decision", "mission",
        f"{state} {record.get('id', '?')} after {record.get('actions_used', 0)}"
        f"/{record.get('max_actions', '?')} — {why}", actor=ACTOR)
    return record


def note(entry: str, *, spent: int = 0) -> dict | None:
    """Record what a slice actually did, and charge it to the budget.

    Progress is durable between slices on purpose: a mission that forgot
    its own history every time the scheduled task restarted would repeat
    itself forever and call that working.
    """
    record = load()
    if not record or record.get("state") != RUNNING:
        return None
    record["actions_used"] = int(record.get("actions_used", 0)) + int(spent)
    record["slices"] = int(record.get("slices", 0)) + 1
    record.setdefault("log", []).append(
        {"at": stateio.utcnow(), "entry": str(entry)[:400], "spent": int(spent)})
    record["log"] = record["log"][-60:]
    stateio.write_json_atomic(MISSION_PATH, record)
    return record


def stop(*, via: str = "operator-local") -> bool:
    """One word. Effective before the next slice."""
    record = load()
    if not record or record.get("state") in TERMINAL:
        return False
    _finish(record, STOPPED, f"stopped by {via}")
    return True


def status(*, now: dt.datetime | None = None) -> dict:
    """What she is working on right now, and how much budget is left.

    Reads the record rather than `active()` so a finished mission still
    reports how it ended — "nothing running" and "it ran out an hour ago
    having opened four pull requests" are different answers.
    """
    record = load()
    if not record:
        return {"running": False, "detail": "no mission has been given"}
    live = active(now=now) is not None
    used, ceiling = int(record.get("actions_used", 0)), int(record.get("max_actions", 0))
    return {
        "running": live,
        "id": record.get("id"),
        "kind": record.get("kind"),
        "goal": record.get("goal"),
        "state": record.get("state"),
        "expires": record.get("expires"),
        "used": used,
        "budget": ceiling,
        "remaining": max(0, ceiling - used),
        "slices": record.get("slices", 0),
        "ended_because": record.get("ended_because"),
        "recent": (record.get("log") or [])[-5:],
    }


def spoken_status(*, now: dt.datetime | None = None) -> str:
    """The same answer, out loud. "Where are my projects standing?" is a
    question he asks the room, not a JSON endpoint."""
    s = status(now=now)
    if not s.get("id"):
        return "I don't have a mission right now."
    if s["running"]:
        return (f"Working on it. {s['used']} of {s['budget']} done, "
                f"{s['remaining']} to go, until {s['expires'][11:16]} UTC.")
    ended = s.get("ended_because") or s.get("state", "").lower()
    return (f"That mission is finished — {s['used']} of {s['budget']} done. "
            f"{ended.capitalize()}.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Give Aletheia one goal and a budget, instead of "
                    "approving every step of it.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_start = sub.add_parser("start", help="authorize a goal locally")
    p_start.add_argument("kind", choices=sorted(KINDS))
    p_start.add_argument("--hours", type=int, default=DEFAULT_HOURS)
    p_start.add_argument("--actions", type=int, default=DEFAULT_ACTIONS)
    sub.add_parser("stop", help="end the running mission now")
    sub.add_parser("status", help="what she is working on and what is left")
    sub.add_parser("kinds", help="the goals she can be given")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "start":
            record = start(args.kind, hours=args.hours, actions=args.actions)
            print(json.dumps(status(), indent=2))
            print(f"\nMission {record['id']} is running. Watch it with "
                  f"`python -m aletheia.mission status`, end it with "
                  f"`python -m aletheia.mission stop`.")
            return 0
        if args.cmd == "stop":
            print("Mission stopped." if stop() else "No mission is running.")
            return 0
        if args.cmd == "kinds":
            for name, spec in sorted(KINDS.items()):
                print(f"{name:16} {spec['summary']}")
            return 0
        print(json.dumps(status(), indent=2))
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
