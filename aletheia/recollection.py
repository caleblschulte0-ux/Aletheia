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
    r"what are you working on|what have you been|already|"
    # 2026-09-04: "what did I ask you to do yesterday?" matched nothing here,
    # so she answered "I have no record of yesterday" with the record
    # sitting in the journal. What HE asked her is her past too.
    r"what did i (ask|tell|say|have)|what i asked|"
    r"yesterday|last night|last week|this week|earlier)\b", re.I)

# A span he named. "yesterday" is the last two days because his day and the
# journal's UTC day do not line up, and the rows carry their own dates.
SPAN_HOURS = {"yesterday": 48.0, "last night": 48.0, "this week": 24.0 * 7,
              "last week": 24.0 * 14, "earlier": 24.0}
_SPAN = re.compile(r"\b(yesterday|last night|this week|last week|earlier)\b", re.I)

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


DID_KINDS = ("action", "decision", "recovery")
# What HE said to her is journaled as a note by an operator-* actor; a span
# question ("what did I ask you yesterday?") wants those rows too.
SAID_KINDS = DID_KINDS + ("note",)


def day(hours: float = TODAY_HOURS, *, limit: int = MAX_ROWS,
        kinds: tuple = DID_KINDS) -> list[dict]:
    """What she has been doing, newest last. For "what did you do today?".

    Her own actions and decisions only: the journal also carries events and
    notes that are things happening TO her, and a list padded with those
    reads like activity she did not perform. `kinds` widens that for a
    span question, where his own asks (notes) are the point.
    """
    rows = [e for e in _recent(hours)
            if e.get("kind") in kinds
            and any(e.get("actor", "").startswith(a) for a in HERS)]
    return [_row(e) for e in rows[-limit:]]


def _local_date(ts: str) -> str:
    """The operator's calendar date for a UTC stamp — the grouping key for
    "yesterday". `_local()` renders "Thu 14:04" for people, which is not a
    key: every minute became its own day and Friday sorted before Thursday."""
    try:
        from aletheia import localtime
        return localtime.parse_utc(ts).astimezone(localtime.operator_tz()).date().isoformat()
    except Exception:
        return str(ts)[:10]


def per_day(hours: float, *, per_day: int = MAX_ROWS,
            kinds: tuple = SAID_KINDS) -> list[dict]:
    """Up to `per_day` rows from EACH local day in the window, oldest day
    first. `day()` keeps the newest N rows of the whole window, which is
    right for "today" and wrong for "yesterday": one busy afternoon pushes
    the day he asked about out of the list entirely (2026-09-04 — the
    48-hour window held yesterday's rows and she reported it empty)."""
    kept: dict[str, list[dict]] = {}
    for entry in _recent(hours):
        if entry.get("kind") not in kinds:
            continue
        if not any(entry.get("actor", "").startswith(a) for a in HERS):
            continue
        day_key = _local_date(entry.get("ts", ""))
        kept.setdefault(day_key, []).append(entry)
    out: list[dict] = []
    for day_key in sorted(kept):
        rows = kept[day_key]
        # keep the first and the last of a busy day rather than only its tail
        if len(rows) > per_day:
            half = per_day // 2
            rows = rows[:half] + rows[-(per_day - half):]
        out.extend(_row(e) for e in rows)
    return out


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
    span = _SPAN.search(text)
    if span:
        # A question shaped by a DAY, not a subject: "what did I ask you
        # yesterday?" has no topic word for `about()` to match, so it found
        # nothing and she said the journal was empty while the day's rows sat
        # there (2026-09-04). A span gets the whole window, unfiltered, with
        # the older entries first so "yesterday" reads in order.
        hours = SPAN_HOURS[span.group(1).casefold()]
        rows = per_day(hours, kinds=SAID_KINDS)
        return {"asked_about": f"the last {int(hours)} hours", "hours": hours,
                "journal": rows,
                "note": ("This is the journal for that span, oldest first, her "
                         "actions and his asks. If it is empty, nothing was "
                         "recorded — say so; do not fill it in. Each row carries "
                         "its own timestamp; read the dates before answering "
                         "which day a thing happened on.")}
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
