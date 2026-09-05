"""What he keeps asking for and cannot have — counted, in his own words.

Rule zero says: found it, can fix it, fix it. That works inside one
session and dissolves between them. A gap named on Tuesday and a gap
named on Friday are the same gap, and nothing in the system knew that:
`gaps.materialize` files a build task the first time and then quietly
does nothing, so a capability he has asked for eleven times and one he
mentioned once look identical on the task list forever.

So this counts. Every time a plan comes back with a GAP step, or a "can
you...?" turns out to be about something not AVAILABLE, the ask is
recorded with HIS OWN WORDS and the capability it wanted. Ranked, that is
a roadmap nobody wrote: not what an agent guessed would be useful, not
what a plan file said in July — what he actually tried to do and could
not.

Three things it is careful about.

**His words are his.** The record lives in private state, never the repo,
and keeps a short quote because "he asked for this eleven times" is an
argument and "he asked for `message.send` eleven times" is a statistic.

**It counts, it does not conclude.** Frequency is evidence of demand, not
proof of priority — a thing asked once in anger may matter more than a
thing asked weekly out of habit. This ranks; a person decides.

**It is bounded and it forgets.** An ask from four months ago is history,
not demand. The window is what makes the number mean "lately".
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from aletheia import stateio

ACTOR = "aletheia-demand"

WINDOW_DAYS = 90
MAX_RECORDS = 2_000
# Roughly MAX_RECORDS lines; the ledger is pruned when it passes this.
PRUNE_BYTES = 400_000
QUOTE_CHARS = 140
# How many distinct askings before it stops being noise and starts being a
# pattern worth putting in front of him.
NOTABLE = 3


def path():
    return stateio.private_dir("demand") / "asks.jsonl"


def _load() -> list[dict]:
    p = path()
    if not p.is_file():
        return []
    out = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue          # one bad line is not a broken ledger
    except OSError:
        return []
    return out


def _fresh(rows: list[dict], *, days: int = WINDOW_DAYS) -> list[dict]:
    cut = (dt.datetime.now(dt.timezone.utc)
           - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [r for r in rows if str(r.get("at", "")) >= cut]


def record(capability: str, asked: str, *, status: str = "",
           source: str = "planner") -> dict | None:
    """One ask that could not be served. Never raises: a ledger that can
    break a request is worse than no ledger."""
    capability = str(capability or "").strip()
    if not capability:
        return None
    row = {"at": stateio.utcnow(), "capability": capability,
           "status": str(status or "")[:40], "source": str(source)[:24],
           "asked": " ".join(str(asked or "").split())[:QUOTE_CHARS]}
    try:
        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)
        # APPEND, then prune when it has actually grown. Rewriting the whole
        # ledger on every ask was the first version and it is quadratic:
        # correct, and slower with every ask he makes, which is the wrong
        # direction for a file whose whole point is that he keeps asking.
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        if p.stat().st_size > PRUNE_BYTES:
            rows = _fresh(_load())[-MAX_RECORDS:]
            p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                                 for r in rows), encoding="utf-8")
    except Exception:
        return None
    return row


def record_plan(plan, request: str) -> list[str]:
    """Every capability a compiled plan wanted and did not have."""
    wanted = []
    for step in getattr(plan, "steps", []):
        if getattr(step, "status", "") == "GAP" and getattr(step, "capability", None):
            if record(step.capability, request, status="GAP", source="planner"):
                wanted.append(step.capability)
    return wanted


# Why a real attempt stopped short. The planner's GAP is "she has no verb
# for this"; these are "she has the verb, went and did it, and hit a wall"
# — which is a different and better signal, because he had already
# committed to the thing when it failed.
STOPPED = {
    "NEEDS_YOU": "asked him something she could not answer herself",
    "OUT_OF_STEPS": "ran out of steps before finishing",
    "NEEDS_SIGN_IN": "the site wanted an account",
    "NEEDS_YOUR_EYES": "a human check she must not defeat",
    "REFUSED": "refused it",
}


def record_attempt(capability: str, asked: str, state: str, *,
                   detail: str = "", source: str = "attempt") -> dict | None:
    """A real attempt that stopped short of finishing.

    The ledger only ever heard about failures to PLAN — a "can you…?"
    with no AVAILABLE match, a compiled plan with a GAP step. It never
    heard about failures to DO, which is the signal that matters most:
    the difference between "she has no verb for this" and "she went, she
    tried, and the site wanted an account" is the difference between a
    guess about what to build and a fact about what he could not have.
    """
    why = STOPPED.get(str(state or ""))
    if why is None:
        return None            # DONE and AWAITING_YOU are not failures
    return record(capability, asked, status=str(state), source=source)


def ranked(*, days: int = WINDOW_DAYS, limit: int = 12) -> list[dict]:
    """What he has been asking for, most-asked first."""
    rows = _fresh(_load(), days=days)
    by_id: dict[str, dict] = {}
    for row in rows:
        cid = row["capability"]
        held = by_id.setdefault(cid, {"capability": cid, "times": 0,
                                      "first": row["at"], "last": row["at"],
                                      "status": row.get("status", ""),
                                      "reasons": {}, "in_his_words": []})
        held["times"] += 1
        held["last"] = max(held["last"], row["at"])
        held["first"] = min(held["first"], row["at"])
        # WHY, not just how often. "web.task, eleven times" is a number;
        # "seven wanted a sign-in and four ran out of steps" is two
        # different things to build, and only one of them is a budget.
        reason = row.get("status") or ""
        if reason:
            held.setdefault("reasons", {})
            held["reasons"][reason] = held["reasons"].get(reason, 0) + 1
        if row.get("asked") and row["asked"] not in held["in_his_words"]:
            held["in_his_words"] = (held["in_his_words"] + [row["asked"]])[-3:]
    out = sorted(by_id.values(), key=lambda h: (h["times"], h["last"]),
                 reverse=True)
    return out[:limit]


def notable(*, days: int = WINDOW_DAYS) -> list[dict]:
    """Only the ones asked often enough to be a pattern rather than a day."""
    return [h for h in ranked(days=days) if h["times"] >= NOTABLE]


def spoken() -> str:
    top = notable()
    if not top:
        return "Nothing you have asked for repeatedly is missing."
    lead = top[0]
    rest = len(top) - 1
    return (f"The thing you keep asking for and I cannot do is "
            f"{lead['capability']} — {lead['times']} times"
            + (f" ({why(lead)})" if why(lead) else "")
            + (f", and {rest} other{'s' if rest != 1 else ''} like it." if rest
               else "."))


# What a stop MEANS, for a person rather than a state machine. The ledger
# is read to decide what to build, and "NEEDS_SIGN_IN x7" is a decision
# ("she needs a way through login walls") that "web.task x11" is not.
IN_ENGLISH = {
    "NEEDS_SIGN_IN": "wanted a sign-in",
    "NEEDS_YOUR_EYES": "hit a human check",
    "OUT_OF_STEPS": "ran out of steps",
    "NEEDS_YOU": "needed an answer from you",
    "REFUSED": "was refused",
    "GAP": "had no verb for it",
}


def why(row: dict) -> str:
    """"7 wanted a sign-in, 4 ran out of steps" — most common first."""
    counts = row.get("reasons") or {}
    if not counts:
        return ""
    parts = [f"{n} {IN_ENGLISH.get(k, k.lower())}"
             for k, n in sorted(counts.items(), key=lambda kv: -kv[1])]
    return ", ".join(parts[:3])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="What he keeps asking for and cannot have.")
    ap.add_argument("--days", type=int, default=WINDOW_DAYS)
    ap.add_argument("--all", action="store_true",
                    help="include one-off asks, not just repeated ones")
    args = ap.parse_args(argv)
    rows = (ranked(days=args.days) if args.all else notable(days=args.days))
    if not rows:
        print("nothing recorded in that window", file=sys.stderr)
        return 0
    for row in rows:
        print(f"{row['times']:>3}x  {row['capability']:<28} "
              f"{row['status']:<20} last {row['last'][:10]}")
        for quote in row["in_his_words"]:
            print(f"        “{quote}”")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
