"""Letting her use his ChatGPT subscription, without a shell.

His ruling: *"Yes it can use chatgpt as a secondary worker but no api key
it has to use my subscription."*

All of it was already built. `browser_reasoner` drives his signed-in
ChatGPT session through the real browser, and `reasoning_gateway` already
knows to reach for it. It was switched off, and the only way to switch it
on was to set an environment variable in a foreground shell — which is
why it looked like a missing feature rather than a closed tap.

WHAT THE ENVIRONMENT VARIABLE WAS PROTECTING, because it matters and it
is kept. The always-on side must never QUIETLY drive his personal
ChatGPT account: the Core, the supervisor, the project loop and the room
each drop the lease from their own environment as their first statement,
and the supervisor strips it from every child it starts. An unattended
process that inherited a lease from a shell he opened last Tuesday is
exactly the thing that design refuses.

WHAT CHANGES, AND WHY IT IS STILL THAT. A lease he GRANTS is not a lease
something inherited. This is the same shape as the microphone:

  - off by default;
  - granted deliberately, by him, from a surface he is looking at;
  - stamped with the boot, so a restart revokes it — a durable "on" is
    the silent always-on the design refuses, by a slower route;
  - time-boxed on top of that, because "I said yes on Tuesday" should
    not still be true on Friday;
  - revocable instantly, from anywhere, like every stop in this system;
  - journaled, so "when did she use my ChatGPT account" has an answer.

The environment variable still works and still wins: a foreground shell
that sets it is unchanged. This is an additional door, not a replacement,
and both of them are explicit.
"""
from __future__ import annotations

import argparse

from aletheia import journal, stateio

ACTOR = "aletheia-second-opinion"

# How long a grant lasts before he has to mean it again. Long enough for
# an afternoon of real work, short enough that a forgotten yes expires
# on its own.
DEFAULT_HOURS = 8
MAX_HOURS = 24


def marker():
    return stateio.private_dir("runtime") / "chatgpt-lease.json"


def _boot_id() -> str:
    """Whatever `ears` uses, so a restart means the same thing to both."""
    try:
        from aletheia import ears
        return ears._boot_id()
    except Exception:
        return ""


def state() -> dict:
    try:
        value = stateio.read_json(marker())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def granted() -> bool:
    """May this machine use his ChatGPT session right now?

    Every failure is a False: unreadable, expired, a different boot, a
    platform that cannot say which boot it is. The safe mistake for
    somebody's personal account is not touching it.
    """
    record = state()
    if not record.get("on"):
        return False
    boot = _boot_id()
    if not boot or record.get("boot") != boot:
        return False
    try:
        import datetime as dt
        until = dt.datetime.fromisoformat(str(record.get("until")))
        if until.tzinfo is None:
            until = until.replace(tzinfo=dt.timezone.utc)
        return dt.datetime.now(dt.timezone.utc) < until
    except Exception:
        return False


def grant(hours: int = DEFAULT_HOURS, via: str = "operator") -> dict:
    """He said yes. For this boot, for this long, and no longer."""
    import datetime as dt
    hours = max(1, min(int(hours or DEFAULT_HOURS), MAX_HOURS))
    until = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=hours)
    record = {"on": True, "boot": _boot_id(), "hours": hours,
              "until": until.isoformat(), "at": stateio.utcnow(),
              "via": str(via)[:80]}
    stateio.write_json_atomic(marker(), record)
    journal.append("decision", "chatgpt:lease",
                   f"ChatGPT worker allowed for {hours}h by {via} "
                   "(this boot only)", actor=ACTOR)
    return record


def revoke(via: str = "operator") -> dict:
    """Always allowed, from anywhere, immediately."""
    record = {"on": False, "at": stateio.utcnow(), "via": str(via)[:80]}
    stateio.write_json_atomic(marker(), record)
    journal.append("decision", "chatgpt:lease", f"ChatGPT worker stopped by {via}",
                   actor=ACTOR)
    return record


def spoken() -> str:
    if granted():
        record = state()
        return (f"I can use your ChatGPT for another "
                f"{_hours_left(record)}. Say stop using ChatGPT to end it.")
    record = state()
    if record.get("on"):
        return ("Not right now — that permission ended when the machine "
                "restarted or the time ran out. Say use ChatGPT to give it "
                "to me again.")
    return ("I'm not using your ChatGPT account. Say use ChatGPT and I'll "
            "ask it for a second opinion when it's worth one.")


def _hours_left(record: dict) -> str:
    try:
        import datetime as dt
        until = dt.datetime.fromisoformat(str(record.get("until")))
        if until.tzinfo is None:
            until = until.replace(tzinfo=dt.timezone.utc)
        left = until - dt.datetime.now(dt.timezone.utc)
        # ROUNDED UP. Granting eight hours and being told "another 7"
        # reads as though a whole hour went missing between the sentence
        # and the answer, which is how a person decides a machine is
        # lying to them about small things.
        import math
        hours = math.ceil(left.total_seconds() / 3600)
        if hours >= 1:
            return f"{hours} hour" + ("" if hours == 1 else "s")
        return f"{max(1, math.ceil(left.total_seconds() / 60))} minutes"
    except Exception:
        return "a while"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Let her use your ChatGPT subscription as a second worker.")
    ap.add_argument("cmd", nargs="?", choices=("on", "off", "status"),
                    default="status")
    ap.add_argument("--hours", type=int, default=DEFAULT_HOURS)
    ap.add_argument("--via", default="cli")
    args = ap.parse_args(argv)
    if args.cmd == "on":
        grant(args.hours, via=args.via)
    elif args.cmd == "off":
        revoke(via=args.via)
    print(spoken())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
