"""Every time he had to do something a normal person should not - counted.

The seamless brief (2026-09-21) asks for a friction ledger: "every time
Caleb had to do something a normal person shouldn't, record it, and treat
it as a defect." The demand ledger (`aletheia.demand`) counts what he
asked for and could not have; this counts what she made HIM do:

    question    she handed him a question she might have settled herself
    sysadmin    he had to run a command, fix an install, or read a log
    lost        an update or a restart lost something he had given her
    restart     he had to start her, or start her again
    repeat      he had to say the same thing twice

The rule is the same as the demand ledger's: his words are his (private
state, never the repo), it counts and does not conclude, and it forgets
after the window. The difference is what a row means. A demand row is a
capability to build. A friction row is a defect in something already
built: the fix is never "he learns to type the command".

Every writer here has a reader: `python -m aletheia.friction` ranks it,
and "what have I had to do myself" / "what have you been asking me"
answer from it out loud (`quick`).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from aletheia import stateio

ACTOR = "aletheia-friction"

WINDOW_DAYS = 30
MAX_RECORDS = 2_000
PRUNE_BYTES = 400_000
WORDS_CHARS = 200

KINDS = {
    "question": "she asked you something she might have settled herself",
    "sysadmin": "you had to run a command, fix an install, or read a log",
    "lost": "an update or a restart lost something you had given her",
    "restart": "you had to start her, or start her again",
    "repeat": "you had to say the same thing twice",
}


def path():
    return stateio.private_dir("friction") / "ledger.jsonl"


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
                    continue
    except OSError:
        return []
    return out


def _fresh(rows: list[dict], *, days: int = WINDOW_DAYS) -> list[dict]:
    cut = (dt.datetime.now(dt.timezone.utc)
           - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [r for r in rows if str(r.get("at", "")) >= cut]


def record(kind: str, what: str, *, asked: str = "", source: str = "") -> dict | None:
    """One thing he had to do. Never raises: a ledger that can break the
    thing it is measuring is worse than no ledger."""
    kind = str(kind or "").strip().casefold()
    what = " ".join(str(what or "").split())[:WORDS_CHARS]
    if kind not in KINDS or not what:
        return None
    row = {"at": stateio.utcnow(), "kind": kind, "what": what,
           "asked": " ".join(str(asked or "").split())[:WORDS_CHARS],
           "source": str(source or "")[:40]}
    try:
        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        if p.stat().st_size > PRUNE_BYTES:
            kept = _fresh(_load())[-MAX_RECORDS:]
            p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept),
                         encoding="utf-8")
    except OSError:
        return None
    return row


def recent(*, days: int = WINDOW_DAYS, limit: int = 20) -> list[dict]:
    rows = _fresh(_load(), days=days)
    return list(reversed(rows))[:limit]


def ranked(*, days: int = WINDOW_DAYS) -> list[dict]:
    """By kind, most often first, with the latest few in his words."""
    by_kind: dict[str, dict] = {}
    for row in _fresh(_load(), days=days):
        kind = str(row.get("kind") or "")
        held = by_kind.setdefault(kind, {"kind": kind, "means": KINDS.get(kind, kind),
                                         "times": 0, "last": "", "examples": []})
        held["times"] += 1
        held["last"] = max(held["last"], str(row.get("at") or ""))
        what = str(row.get("what") or "")
        if what and what not in held["examples"]:
            held["examples"] = (held["examples"] + [what])[-3:]
    return sorted(by_kind.values(), key=lambda h: (h["times"], h["last"]), reverse=True)


def spoken(*, days: int = WINDOW_DAYS) -> str:
    """"What have I had to do myself?" - out loud, from the ledger."""
    from aletheia import speech
    top = ranked(days=days)
    if not top:
        return ("Nothing I recorded: I haven't asked you anything I should have "
                "settled myself, and you haven't had to fix or restart me.")
    total = sum(h["times"] for h in top)
    said = f"{speech.count_phrase(total, 'time')} in {speech.count_phrase(days, 'day')}: "
    parts = []
    for held in top[:3]:
        lead = {"question": "I asked you something",
                "sysadmin": "you had to fix something yourself",
                "lost": "I lost something you gave me",
                "restart": "you had to start me",
                "repeat": "you had to repeat yourself"}.get(held["kind"], held["means"])
        example = held["examples"][-1] if held["examples"] else ""
        parts.append(f"{lead} {speech.count_phrase(held['times'], 'time')}"
                     + (f", most recently {speech.shorten(example, 90)}" if example else ""))
    return said + "; ".join(parts) + "."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aletheia.friction",
                                     description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("list", help="the ledger, ranked by kind (default)")
    said = sub.add_parser("say", help="the spoken answer")
    said.add_argument("--days", type=int, default=WINDOW_DAYS)
    add = sub.add_parser("record", help="add a row (the bring-up does this on a failure)")
    add.add_argument("kind", choices=sorted(KINDS))
    add.add_argument("what")
    add.add_argument("--source", default="cli")
    args = parser.parse_args(argv)
    if args.cmd == "record":
        row = record(args.kind, args.what, source=args.source)
        print("recorded" if row else "not recorded")
        return 0 if row else 1
    if args.cmd == "say":
        print(spoken(days=args.days))
        return 0
    rows = ranked()
    if not rows:
        print(f"nothing in the last {WINDOW_DAYS} days")
        return 0
    for held in rows:
        print(f"{held['times']:>3}  {held['kind']:<9} {held['means']}")
        for example in held["examples"]:
            print(f"        - {example}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
