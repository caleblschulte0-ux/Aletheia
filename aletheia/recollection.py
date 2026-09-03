"""What she actually did — answered from the journal, not from memory.

This is the other half of `self_knowledge`. That one answers "can you?"
from the registry; this one answers "did you?", "what did you do today?",
"why is the trader paused?", "when did you last talk to Brant?" from the
append-only journal.

It matters for two reasons that pull in opposite directions.

The first is that it is the thing no other assistant can do at all. A chat
assistant elsewhere has no history with him — every conversation starts
from nothing, and "what were you working on this morning?" is not a
question it can even parse as being about itself. Aletheia has journaled
every action she has ever taken. Until now she could not read a line of
it, which meant the single most valuable body of knowledge in the system
was invisible to the half of her he talks to.

The second is that without it she would CONFABULATE, and confidently. Ask
a language model "did you send that email?" with no evidence attached and
it will produce a plausible sentence, because producing plausible
sentences is what it does. There is no failure here that looks like a
failure: a made-up "yes, I sent it at 2:15" is indistinguishable from a
true one until he checks his sent folder.

So the rule this module exists to make enforceable is: SHE MAY ONLY SAY
SHE DID SOMETHING IF THE JOURNAL SAYS SHE DID. And its corollary, which
is only sound because the journal is append-only and every action writes
to it: absence is evidence. If it is not there, it did not happen — or it
happened without being recorded, which is itself worth saying out loud.

Retrieval, like `self_knowledge`: no model call, no network, offline, in
the prompt-building path of every question.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys

from aletheia import journal

# How far back a question reaches by default. A week covers "did you ever",
# "the other day" and "last night" without turning every question into a
# scan of the whole history.
DEFAULT_HOURS = 24 * 7
TODAY_HOURS = 24
MAX_ROWS = 14
TEXT_CHARS = 200
FLOOR = 1.0

# The actors that are HER doing something, as opposed to the operator or
# CI writing a note. "Did you..." is a question about these.
HERS = ("aletheia", "operator-via", "core", "converse", "desktop", "workspace")

STOP = frozenset("""
a an and are as at be by can could did do does for from get give go had has
have he her him his how i if in into is it its me my not of on or our she
should so that the their them then there these they this to us was we what
when where which who will with would you your yours am about all any ever
just really actually thing things today yesterday morning evening night
last ago time times again ok okay yeah yes no
""".split())

# A question about her own past. Deliberately generous: attaching a few
# journal lines to a question that was not about them costs a little
# prompt; missing one turns into a confabulated answer.
_PAST = re.compile(
    r"\b(did you|have you|had you|were you|was that|what did you|"
    r"when did|why did|what happened|what have you|what were you|"
    r"what did we|did we|last time|so far today|"
    r"what are you working on|what have you been|already)\b", re.I)

# He is asking about the day, not about a subject.
_TODAY = re.compile(r"\b(today|so far|this morning|this afternoon|tonight|"
                    r"since (this )?(morning|lunch)|all day)\b", re.I)


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", str(text).casefold()) if w]


def _terms(question: str) -> set[str]:
    return {w for w in _words(question) if w not in STOP and len(w) > 2}


def _local(ts: str) -> str:
    """His clock. A journal in UTC answering "what did you do this morning"
    is off by the exact amount that makes the answer wrong."""
    try:
        from aletheia import localtime
        return (localtime.parse_utc(ts).astimezone(localtime.operator_tz())
                .strftime("%a %H:%M"))
    except Exception:
        return str(ts)[:16]


def _row(entry: dict) -> dict:
    return {"at": _local(entry.get("ts", "")),
            "kind": entry.get("kind", ""),
            "who": entry.get("actor", ""),
            "what": f"{entry.get('subject', '')}: {entry.get('text', '')}"[:TEXT_CHARS]}


def _recent(hours: float) -> list[dict]:
    try:
        return journal.since(hours)
    except Exception:
        return []          # a journal she cannot read makes her say so


def day(hours: float = TODAY_HOURS, *, limit: int = MAX_ROWS) -> list[dict]:
    """What she has been doing, newest last. For "what did you do today?".

    Her own actions and decisions only: the journal also carries events and
    notes that are things happening TO her, and a list padded with those
    reads like activity she did not perform.
    """
    rows = [e for e in _recent(hours)
            if e.get("kind") in ("action", "decision", "recovery")
            and any(e.get("actor", "").startswith(a) for a in HERS)]
    return [_row(e) for e in rows[-limit:]]


def about(question: str, *, hours: float = DEFAULT_HOURS,
          limit: int = MAX_ROWS) -> list[dict]:
    """Journal lines this question is about. Possibly none — which is an
    answer, not a failure."""
    terms = _terms(question)
    if not terms:
        return []
    scored = []
    for entry in _recent(hours):
        haystack = set(_words(entry.get("subject", "")) +
                       _words(entry.get("text", "")))
        hits = sum(1.0 for t in terms if t in haystack)
        # An alert or a decision is more likely to be what he is asking
        # about than the hundredth routine action of the day.
        if entry.get("kind") in ("alert", "decision", "recovery"):
            hits *= 1.4
        if hits >= FLOOR:
            scored.append((hits, entry.get("ts", ""), entry))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    chosen = [entry for _hits, _ts, entry in scored[:limit]]
    chosen.sort(key=lambda e: e.get("ts", ""))
    return [_row(e) for e in chosen]


def for_question(question: str) -> dict:
    """What should travel with THIS question. Empty when it is not about her
    past — and empty-with-a-statement when it is and nothing is there."""
    text = str(question or "")
    if not _PAST.search(text):
        return {}
    if _TODAY.search(text):
        rows = day()
        return {"asked_about": "her day", "hours": TODAY_HOURS,
                "journal": rows,
                "note": ("This is the journal, which every action writes to. "
                         "If it is empty she has done nothing recorded in that "
                         "window — say so; do not fill it in.")}
    rows = about(text)
    return {"asked_about": "her past", "hours": DEFAULT_HOURS, "journal": rows,
            "note": ("Only say she did something if a line above says she did. "
                     "The journal is append-only and every action writes to it, "
                     "so nothing here means it did not happen — or happened "
                     "without being recorded, which is worth saying plainly. "
                     "Never invent a time, a recipient or an outcome.")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="What she actually did.")
    ap.add_argument("question", nargs="?", help="omit for today")
    ap.add_argument("--hours", type=float, default=None)
    args = ap.parse_args(argv)
    if not args.question:
        print(json.dumps(day(args.hours or TODAY_HOURS), indent=2,
                         ensure_ascii=False))
        return 0
    out = for_question(args.question)
    if args.hours and out:
        out["journal"] = about(args.question, hours=args.hours)
    print(json.dumps(out or {"asked_about": "not her past"}, indent=2,
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
