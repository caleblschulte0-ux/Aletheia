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

**That corollary holds for the WHOLE journal and not for a search of
it**, and conflating the two produced the worst answer this system has
given. `about()` scores lines against the words of the question, so "did
you save that" — which names nothing searchable — matched none of them,
and the note attached to that empty list told the model an empty list
meant it had not happened. He had said "remember my landlord is Mr
Okafor"; she saved it; she recalled it correctly one turn later; and then
she said "No — the journal's empty, nothing was saved."

A false premise handed to a model comes back as a confident lie, so the
two situations are now told apart and labelled differently: nothing
MATCHED (here is what she has been doing instead) versus nothing THERE.

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
# The furthest back "what did you do on ..." will read. A journal query
# that walks a year of files to answer a spoken question is not a fast
# path, and he does not ask about last March out loud.
MAX_LOOKBACK_HOURS = 24 * 31
MAX_ROWS = 14
TEXT_CHARS = 200
FLOOR = 1.0

# The actors that are HER doing something, as opposed to the operator or
# CI writing a note. "Did you..." is a question about these.
#
# Matched as PREFIXES, which is where this went wrong: the Core journals
# every command it runs as "operator-local-core", and "core" is in this
# list but "operator-local-core" does not START with it. So every single
# thing she did by voice — the most-used path in the whole system — was
# missing from "what did you do today?". She set a reminder and then said
# "Nothing yet today." Found 2026-09-06 by asking her.
# `tests/test_she_remembers_her_own_actions.py` now holds this list
# against the ACTOR constants that actually exist.
# Actor prefixes whose journal lines are things SHE DID, and therefore
# things "what did you do today" must be able to see. A writer missing
# from here is invisible to her own memory: the Core journals as
# `operator-local-core`, and until that prefix was here everything he
# asked for out loud was absent from her account of her own day.
#
# `agents`, `messages` and `teams` are work she does for him — texting
# somebody, creating a worker, running a team. `workspaces` is
# deliberately NOT here: a note a worker writes to itself is not a thing
# she did for him, and listing them back would be her reading her own
# filing out loud.
HERS = ("aletheia", "operator-via", "operator-local", "core", "converse",
        "desktop", "workspace", "agents", "messages", "teams",
        # Pressing pause and writing him a document are things she
        # DID. `documents` slipped past the actor guard because
        # officedocs journalled under a literal rather than a
        # module constant, so a Word document she wrote would not
        # have appeared in her account of her own day.
        "music", "documents",
        # Looking at the actual picture of his screen is a thing she
        # DID, and the one he is most likely to ask her about after
        # the fact - "did you look at my screen?" has to be
        # answerable from her own account of the day.
        "eyes")

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
    # BOTH branches found this in the same week, from opposite ends: "what
    # did I ask you to do yesterday?" matched nothing here — the phrase is
    # "did I ask you", not "did you" — so no journal travelled with the
    # question and she answered "I have no record of yesterday" with the
    # record sitting in the journal. What HE asked her is her past too.
    r"what did i (ask|tell|say|have)|what i asked|"
    r"did i ask|did i tell you|did i say|i asked you|"
    r"yesterday|last night|last week|this week|earlier)\b", re.I)

# A span he named, for the MULTI-DAY ones. A single day goes through
# `on_date` below — a calendar day on his clock, not a rolling window —
# so what is left here is the questions a single date cannot express.
SPAN_HOURS = {"yesterday": 48.0, "last night": 48.0, "this week": 24.0 * 7,
              "last week": 24.0 * 14, "earlier": 24.0}
_SPAN = re.compile(r"\b(yesterday|last night|this week|last week|earlier)\b", re.I)

# He is asking about the day, not about a subject.
_TODAY = re.compile(r"\b(today|so far|this morning|this afternoon|tonight|"
                    r"since (this )?(morning|lunch)|all day)\b", re.I)

# "What went wrong", "did anything fail", "what broke" — a question about
# TROUBLE, which the journal records as alerts and recoveries. None of
# these matched `_PAST` ("did you", "what happened"), so the most natural
# way to ask what is broken travelled with no journal at all.
_TROUBLE = re.compile(
    r"\b(what went wrong|did anything (fail|go wrong|break)|what broke|"
    r"is anything (broken|failing|wrong)|what(?:'s| is)? (broken|failing|wrong)|"
    r"anything (broken|failing|go wrong)|what failed|any (errors|failures|problems))\b",
    re.I)

# ... or about yesterday, which is a DIFFERENT day and not a longer window
# on this one.
_YESTERDAY = re.compile(r"\b(yesterday|last night|yesterday's)\b", re.I)


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


# Journal subjects whose tail is an intercom KIND, so the receipt can be
# turned back into the sentence a person would have said.
RECEIPT_SUBJECTS = ("core:", "intercom:")

# Subjects that name their own kind rather than carrying it in the tail.
# Without these, "what did you do today" answered
# "memory:people.landlord: set people.landlord = "Mr Okafor" (explicit)".
SUBJECT_KINDS = {"memory": "remember", "task": "task_new"}

# Subjects whose text is already a finished sentence. Prefixing those with
# the subject gives "planner: Did it: Remember the landlord's name" — a
# label on something that did not need one. `repo:aletheia` DOES need its
# prefix, which is why this is a list rather than a rule.
SPEAKS_FOR_ITSELF = ("planner", "intent", "scheduling", "applications")


def _row(entry: dict) -> dict:
    """One journal line as something she could say out loud.

    It used to be `f"{subject}: {text}"`, which answered "what did you do
    today?" with "core:remind_at: done — reminder remind-386c2036 set for
    2026-09-06T15:00:00-05:00 — 'call the dentist'". Every part of that
    is true and none of it is speech; `speech.spoken_receipt` exists for
    exactly this and was not being asked.
    """
    from aletheia import speech
    subject = str(entry.get("subject", ""))
    text = str(entry.get("text", ""))
    head = subject.split(":")[0]
    if head in SUBJECT_KINDS:
        said = speech.spoken_receipt(SUBJECT_KINDS[head], text)
        what = said if said != text else speech.tidy(speech.strip_ids(text))
    elif subject.startswith(RECEIPT_SUBJECTS):
        # `core.run_command` journals "<outcome> — <detail>". "Done" adds
        # nothing to a list of things she did; "refused" or "error" is the
        # whole point of the line, so only the success word is dropped.
        body = text[len("done — "):] if text.startswith("done — ") else text
        what = speech.spoken_receipt(subject.split(":")[-1], body)
    else:
        said = speech.tidy(speech.strip_ids(text))
        what = (said if not subject or head in SPEAKS_FOR_ITSELF
                else f"{subject}: {said}")
    return {"at": _local(entry.get("ts", "")),
            "kind": entry.get("kind", ""),
            "who": entry.get("actor", ""),
            "what": what[:TEXT_CHARS]}


def _read_journal(hours: float) -> tuple[list[dict], bool]:
    """(entries, readable). A journal she CANNOT READ is not an empty one.

    `_recent` swallowed the exception and returned [], so an unreadable
    journal and a genuinely quiet week produced the same answer — "she has
    done nothing". Those are different facts and only one of them is about
    him.
    """
    try:
        return journal.since(hours), True
    except Exception:
        return [], False


def _recent(hours: float) -> list[dict]:
    return _read_journal(hours)[0]


# Journal kinds that are HER doing something, as opposed to something
# happening to her.
#
# This was ("action", "decision", "recovery") — and `memory.remember`
# journals as "note" while `tasks.create` journals as "task", so the two
# things she does most often on his instruction were both invisible.
# Found 2026-09-06: he said "remember my landlord is Mr Okafor", she saved
# it, recalled it correctly one turn later, and then answered "did you
# save that?" with "No — the journal's empty. Nothing I did shows as
# saved."
#
# `alert` and `event` stay out because they really are things that
# happened TO her. `brief` stays out because it is a scheduled artefact
# rather than work he asked for, and it would head the list every single
# day.
HER_DOING = ("action", "decision", "recovery", "note", "task", "plan")


# Talking is not doing. `converse` journals every answer it gives, so
# once "note" counted as work, "what did you do today?" started listing
# her own previous replies back at him — including the text of the answer
# to the question before this one.
NOT_DOING_SUBJECTS = ("converse",)

# Exact subjects that record what she SAID rather than what she did.
# `core.run_command` journals "<outcome> — <detail>", and for an `intent`
# the detail IS the spoken reply — so "what did you do today" listed her
# own previous answers back at him, including the answer to the question
# before this one. Anything the intent really executed is journaled by
# `planner` under its own subject, so nothing is lost here.
SAID_NOT_DID = ("core:intent", "core:screen_ask", "core:brief",
                # One act, two writers. The task store journals
                # "created — call the plumber" and the command path
                # journals "task t1 queued"; the store's line names the
                # thing, the command's line names its id, and she was
                # saying both — "Added a task: call the plumber; Added a
                # task: t1". Same for memory, whose own line reads
                # "Noted: landlord is Mr Okafor".
                "core:task_new", "core:task_status", "core:remember")


def _something_she_did(entry: dict) -> bool:
    subject = str(entry.get("subject", ""))
    return (entry.get("kind") in HER_DOING
            and subject.split(":")[0] not in NOT_DOING_SUBJECTS
            and subject not in SAID_NOT_DID
            and any(str(entry.get("actor", "")).startswith(a) for a in HERS))


# One act, journaled by two writers, is still one act. "Add a task to call
# the plumber" writes `task:<id>` from the task store AND `core:task_new`
# from the command path, and both render to the same sentence — so she
# answered "2 things today: added a task; added a task."
#
# Adjacent AND same rendered minute, because two genuinely separate
# identical actions later in the day are two things he did ask for.


def _once_each(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        if out and out[-1]["what"] == row["what"] and out[-1]["at"] == row["at"]:
            continue
        out.append(row)
    return out


DID_KINDS = ("action", "decision", "recovery")
# What HE said to her is journaled as a note by an operator-* actor; a span
# question ("what did I ask you yesterday?") wants those rows too.
SAID_KINDS = DID_KINDS + ("note",)


def day(hours: float = TODAY_HOURS, *, limit: int = MAX_ROWS) -> list[dict]:
    """What she has been doing, newest last. For "what did you do today?".

    Filtered by KIND and by ACTOR: the journal also carries events and
    alerts, which are things happening TO her, and a list padded with
    those reads like activity she did not perform.
    """
    rows = [e for e in _read_journal(hours)[0] if _something_she_did(e)]
    return _once_each([_row(e) for e in rows])[-limit:]


def on_date(date: str, *, limit: int = MAX_ROWS) -> list[dict]:
    """What she did on ONE CALENDAR DAY, in his timezone.

    "What did you do yesterday" is not a rolling window: asked at nine in
    the morning, the last 24 hours are mostly yesterday, and answering
    from them would list the same evening twice — once as today and once
    as yesterday. A day is a day on his clock, so the filter is the local
    DATE and the read window is only wide enough to contain it.

    This exists because she answered "what did I ask you to do yesterday"
    with "Want me to check the journal directly for entries from
    2026-09-05?" — offering to read a file she can read, which is a round
    trip and an admission of helplessness for something she already has.
    """
    from aletheia import localtime
    want = str(date or "").strip()[:10]
    try:
        tz = localtime.operator_tz()
        start = dt.datetime.strptime(want, "%Y-%m-%d").replace(tzinfo=tz)
        hours = (dt.datetime.now(tz) - start).total_seconds() / 3600.0 + 1.0
    except Exception:
        return []
    if hours <= 0 or hours > MAX_LOOKBACK_HOURS:
        return []
    rows = [e for e in _read_journal(hours)[0]
            if _something_she_did(e) and _local_date(e.get("ts", "")) == want]
    return _once_each([_row(e) for e in rows])[-limit:]


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


MATCHED = ("These journal lines match the question. Only say she did "
           "something if a line says she did. Never invent a time, a "
           "recipient or an outcome.")

UNMATCHED = ("NOTHING IN THE JOURNAL MATCHED THE WORDS OF THE QUESTION, so "
             "this is simply what she has done recently — it is not an "
             "answer to the question by itself. Do NOT say the journal is "
             "empty or that nothing happened: it is not empty, it just does "
             "not mention those words. Read the lines and see whether one of "
             "them is what he means; if none is, say you cannot find a record "
             "of that specific thing.")

NOTHING_AT_ALL = (
    "The journal really is empty for this window. It is append-only and "
    "every action writes to it, so this means it did not happen — or it "
    "happened without being recorded, which is worth saying plainly. Say "
    "so; do not fill it in. Never invent a time, a recipient or an outcome.")

UNREADABLE = (
    "The journal could not be READ — this is not an empty journal and it is "
    "not evidence that nothing happened. Say that you cannot check right "
    "now. Never invent a time, a recipient or an outcome.")


TROUBLE_KINDS = ("alert", "recovery")

TROUBLE_NOTE = (
    "These are the ALERTS and RECOVERIES in her journal — what actually "
    "went wrong and what came back. An empty list means nothing was "
    "recorded as a fault in that window; say that plainly rather than "
    "hunting for something to worry him with, and never invent a failure.")


def trouble(*, hours: float = DEFAULT_HOURS, limit: int = MAX_ROWS) -> list[dict]:
    """What went wrong lately, newest last."""
    rows = [e for e in _read_journal(hours)[0]
            if e.get("kind") in TROUBLE_KINDS]
    return _once_each([_row(e) for e in rows])[-limit:]


def window_words(hours: float) -> str:
    """"168" is a number she read out loud. This is what a person says.

    "The last 168 hours show no alerts" was a real answer. The context
    carries the number for arithmetic and this for the sentence.
    """
    hours = float(hours or 0)
    if hours <= 1:
        return "the last hour"
    if hours < 24:
        return f"the last {int(round(hours))} hours"
    days = hours / 24.0
    if days <= 1:
        return "the last day"
    if days < 7:
        return f"the last {int(round(days))} days"
    if 6.5 <= days <= 7.5:
        return "the last week"
    weeks = days / 7.0
    if weeks < 4.5:
        return f"the last {int(round(weeks))} weeks"
    return f"the last {int(round(days / 30.0))} months"


def for_question(question: str) -> dict:
    """What should travel with THIS question. Empty when it is not about her
    past — and empty-with-a-statement when it is and nothing is there."""
    text = str(question or "")
    if _TROUBLE.search(text):
        rows = trouble()
        readable = _read_journal(DEFAULT_HOURS)[1]
        return {"asked_about": "what went wrong", "hours": DEFAULT_HOURS,
                "window": window_words(DEFAULT_HOURS),
                "journal": rows, "readable": readable,
                "note": TROUBLE_NOTE if readable else UNREADABLE}
    if not _PAST.search(text):
        return {}
    if _YESTERDAY.search(text) and not _TODAY.search(text):
        import datetime as dt
        from aletheia import localtime
        tz = localtime.operator_tz()
        date = (dt.datetime.now(tz) - dt.timedelta(days=1)).strftime("%Y-%m-%d")
        rows = on_date(date)
        readable = _read_journal(TODAY_HOURS * 2)[1]
        return {"asked_about": f"her day on {date}", "date": date,
                "journal": rows, "readable": readable,
                "note": ((f"This is everything she did on {date}, his clock, "
                          "read from the journal every action writes to. "
                          "Answer from it. If it is empty, say nothing was "
                          "recorded that day rather than offering to go and "
                          "look — this IS the look.")
                         if readable else UNREADABLE)}
    if _TODAY.search(text):
        rows = day()
        readable = _read_journal(TODAY_HOURS)[1]
        return {"asked_about": "her day", "hours": TODAY_HOURS,
                "window": "today",
                "journal": rows, "readable": readable,
                "note": (("This is the journal, which every action writes to. "
                          "If it is empty she has done nothing recorded in "
                          "that window — say so; do not fill it in. Never "
                          "invent a time, a recipient or an outcome.")
                         if readable else UNREADABLE)}
    span = _SPAN.search(text)
    if span:
        # A question shaped by a SPAN, not a subject: "what did I ask you
        # last week?" has no topic word for `about()` to match, so it found
        # nothing and she said the journal was empty while the rows sat
        # there (2026-09-04). Single days are handled above by `on_date`;
        # this is what a single date cannot express.
        hours = SPAN_HOURS[span.group(1).casefold()]
        rows = per_day(hours, kinds=SAID_KINDS)
        return {"asked_about": f"the last {int(hours)} hours", "hours": hours,
                "window": window_words(hours),
                "journal": rows, "readable": _read_journal(hours)[1],
                "note": ("This is the journal for that span, oldest first, her "
                         "actions and his asks. If it is empty, nothing was "
                         "recorded — say so; do not fill it in. Each row carries "
                         "its own timestamp; read the dates before answering "
                         "which day a thing happened on.")}
    rows = about(text)
    if rows:
        return {"asked_about": "her past", "hours": DEFAULT_HOURS,
                "window": window_words(DEFAULT_HOURS),
                "journal": rows, "matched": True, "note": MATCHED}
    # NOTHING MATCHED IS NOT NOTHING HAPPENED.
    #
    # `about` scores journal lines against the WORDS of the question, so
    # "did you save that" — which names nothing — matched no lines, and the
    # note below then told the model that an empty list meant it did not
    # happen. He said "remember my landlord is Mr Okafor", she saved it,
    # recalled it correctly one turn later, and answered "did you save
    # that?" with "No — the journal's empty. Nothing was saved."
    #
    # A false premise handed to a model comes back as a confident lie. So a
    # question that matches nothing gets what she has actually been doing,
    # and a note that says which of the two situations this is.
    entries, readable = _read_journal(DEFAULT_HOURS)
    recent = [r for r in entries if _something_she_did(r)]
    rows = _once_each([_row(e) for e in recent])[-MAX_ROWS:]
    if rows:
        note = UNMATCHED
    else:
        note = NOTHING_AT_ALL if readable else UNREADABLE
    return {"asked_about": "her past", "hours": DEFAULT_HOURS,
            "window": window_words(DEFAULT_HOURS), "journal": rows,
            "matched": False, "readable": readable, "note": note}


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
