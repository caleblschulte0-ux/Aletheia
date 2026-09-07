"""Answers she already has, given at the speed of a file read.

Measured 2026-09-05 on the operator's own subscription: a `claude -p`
call costs ~3.6 SECONDS whether the answer is one word or nine thousand
characters, because the cost is the round trip and not the thinking. The
CLI binary itself starts in 0.01s, so none of that is his computer.

And every request paid it at least twice. "Are you halted?" went to the
PLANNER to be told it was a question, and then to `converse` to be
answered — seven seconds of silence for a boolean that is sitting in a
file on the same disk.

So: a deterministic first pass. If the sentence is one of the handful
she can answer from her own stores, she answers it now and no model runs
at all.

TWO RULES, and the second one is the important one.

**Every answer comes from a real store.** `presence.snapshot`, the
capability registry, the journal. Never a canned string, never a guess —
the same rule as everywhere else here (§104, §106). If the store is
empty the answer says so.

**When in doubt it says nothing.** Returning None sends the sentence to
the planner, which is slower and much better at ambiguity. A fast wrong
answer is far worse than a slow right one, so the patterns are narrow on
purpose: they match the way a person asks these five things and decline
everything else. It is a shortcut, not a replacement.
"""
from __future__ import annotations

import re

MAX_QUESTION = 200


def _tidy(text: str) -> str:
    """Normalise for matching — including the filler nobody means anything by.

    Every pattern here is anchored, so "so what did you do today" and "uh
    are you halted" missed the fast lane entirely and paid a full planner
    round trip. `voice._without_preamble` is the same rule at the other
    door; both use it so the two doors cannot disagree about what counts
    as filler.
    """
    text = " ".join(str(text or "").split()).strip().rstrip("?.! ").casefold()
    try:
        from aletheia.voice import _without_preamble
        return _without_preamble(text)
    except Exception:
        return text


# Each is (name, pattern). Anchored, because "tell me about the halt
# behaviour in the docs" is not "are you halted".
PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("halted", re.compile(
        r"^(?:are|r) (?:you|u) (?:halted|stopped|paused|off|frozen)$"
        r"|^(?:are|r) (?:you|u) (?:running|on|up|working|alive|awake)$"
        r"|^is the kill switch (?:on|off)$|^(?:are|r) (?:you|u) ok$")),
    ("waiting", re.compile(
        r"^what(?:'s| is|s)? waiting(?: on| for)? me$"
        r"|^what(?:'s| is|s)? waiting$"
        r"|^(?:is there )?anything (?:waiting )?for me$"
        r"|^(?:do )?(?:you )?need anything(?: from me)?$"
        r"|^what needs me$|^anything i need to (?:do|see|look at)$"
        r"|^what(?:'s| is|s)? on my plate$")),
    ("doing", re.compile(
        r"^what (?:are|r) (?:you|u) (?:doing|working on|up to)$"
        r"|^what(?:'s| is|s)? (?:happening|going on|the status)$"
        r"|^status$|^how(?:'s| is) it going$")),
    ("today", re.compile(
        r"^what (?:did|have) (?:you|u) (?:do|done)(?: today)?$"
        r"|^what have (?:you|u) been doing$"
        r"|^what did (?:you|u) get done(?: today)?$"
        # "Show me the journal" went to the planner, which compiled
        # `recall` and answered "I don't have anything remembered about
        # 'journal entries'" — a lookup in the wrong store.
        r"|^(?:show me |read me )?(?:the |your )?journal$"
        r"|^what(?:'s| is|s)? in (?:the |your )?journal$")),
    # "What did you do yesterday" is one journal read and she was paying a
    # round trip for it. Deliberately NOT "what did I ask you to do
    # yesterday": that asks for HIS instructions, and her journal also
    # holds scheduled work nobody asked for, so the fast lane would be
    # answering a near-miss. That one keeps the model, which now gets the
    # right day's journal to answer from (`recollection.for_question`).
    ("yesterday", re.compile(
        r"^what (?:did|have) (?:you|u) (?:do|done|get done|been doing) yesterday$"
        r"|^what (?:did|have) (?:you|u) (?:do|done) last night$"
        r"|^what happened yesterday$")),
    ("can_you", re.compile(
        r"^(?:can|could) (?:you|u) (?P<what>.{3,120})$"
        r"|^(?:are|r) (?:you|u) able to (?P<what2>.{3,120})$"
        r"|^do (?:you|u) know how to (?P<what3>.{3,120})$")),
)


def match(question: str) -> tuple[str, str] | None:
    """(which answer, the captured remainder) — or None to think properly."""
    text = _tidy(question)
    if not text or len(text) > MAX_QUESTION:
        return None
    for name, pattern in PATTERNS:
        found = pattern.match(text)
        if not found:
            continue
        captured = found.groupdict()
        rest = next((captured[k] for k in ("what", "what2", "what3")
                     if captured.get(k)), "")
        return name, rest
    return None


def _halted() -> str:
    from aletheia import policy
    halt = policy.halted()
    if not halt:
        return "No, I'm running."
    reason = str(halt.get("reason") or "").strip()
    return "Yes, I'm halted" + (f" — {reason}." if reason else ".")


def _waiting() -> str:
    from aletheia import presence, speech
    now = presence.snapshot()
    if now.get("halted"):
        return _halted() + " Nothing runs until you resume me."
    waiting = list(now.get("waiting_on_you") or [])
    notices = list(now.get("notifications") or [])
    if not waiting and not notices:
        return "Nothing is waiting on you."
    parts = []
    if waiting:
        first = waiting[0]
        # `presence` calls it `label` and it is already a sentence a person
        # wrote — asking for `reason` here got "something" every time.
        what = str(first.get("label") or first.get("reason") or "one of them")
        parts.append(f"{len(waiting)} waiting on you — the first is {what[:110]}")
    if notices:
        # SAY WHAT THEY ARE. A reminder fired correctly, on time, and the
        # answer to "what's waiting on me" was "1 thing I wanted to tell
        # you about" — the answer to "how many", when he asked what.
        said = speech.and_list([str(n.get("says") or n.get("title") or "")[:90]
                                for n in notices[:3]])
        more = f", and {len(notices) - 3} more" if len(notices) > 3 else ""
        parts.append(said + more if said else
                     f"{speech.count_phrase(len(notices), 'thing')} "
                     "I wanted to tell you about")
    return ". ".join(parts) + "."


def _doing() -> str:
    from aletheia import presence, speech
    now = presence.snapshot()
    headline = str(now.get("headline") or "").strip()
    if headline:
        return headline
    working = list(now.get("working") or [])
    if working:
        # `presence` names this field `what`. Guessing `description` here
        # produced "Working on 2 thing(s): ; " — punctuation with nothing
        # in it, which is exactly the confident nonsense this module is
        # supposed to be too careful to say.
        return "Working on " + speech.and_list(
            [str(w.get("what") or "")[:60] for w in working[:3]]) + "."
    return "Nothing in flight right now."


def _on_day(days_ago: int) -> list[dict]:
    """Her journal for one calendar day on HIS clock, newest last."""
    import datetime as dt
    from aletheia import localtime, recollection
    tz = localtime.operator_tz()
    date = (dt.datetime.now(tz) - dt.timedelta(days=days_ago)).strftime("%Y-%m-%d")
    return recollection.on_date(date)


def _listed(rows: list[dict], when: str) -> str:
    from aletheia import speech
    # Each line is already a finished sentence; joining them with "; "
    # after a full stop gives "call the dentist.; email dana."
    lines = [str(r.get("what") or "").strip().rstrip(".")[:90] for r in rows[-3:]]
    return (f"{speech.count_phrase(len(rows), 'thing')} {when}. Most recent: "
            + "; ".join(lines))


def _today() -> str:
    # A CALENDAR day, not the last 24 hours. Asked at nine in the morning,
    # a rolling window is mostly yesterday — and it would report the same
    # evening twice, once here and once under "yesterday".
    rows = _on_day(0)
    if not rows:
        return "Nothing yet today."
    return _listed(rows, "today")


def _yesterday() -> str:
    rows = _on_day(1)
    if not rows:
        return "Nothing in the journal for yesterday."
    return _listed(rows, "yesterday")


def _can_you(what: str) -> str | None:
    from aletheia import self_knowledge
    found = self_knowledge.for_question(what)
    matches = list(found.get("matches") or [])
    if not matches:
        return None                 # let the planner try; it is better at this
    best = matches[0]
    status = str(best.get("status") or "")
    name = str(best.get("what_it_is") or best.get("capability") or "")
    if status != "AVAILABLE":
        # THE LEDGER STILL HEARS IT. `converse` records a "can you...?"
        # whose best match is not AVAILABLE, and this path now answers
        # some of those before `converse` ever runs. A shortcut that
        # silently stops feeding the demand ledger would make the thing he
        # asks for most often look like the thing he stopped asking for.
        try:
            from aletheia import demand
            demand.record(str(best.get("capability") or ""), what,
                          status=status, source="quick")
        except Exception:
            pass
    if status == "AVAILABLE":
        return f"Yes — {name}."
    if status in ("EXPERIMENTAL", "DEGRADED"):
        return f"Yes, but it is {status.lower()}: {name}."
    if status == "NEEDS_CONFIGURATION":
        step = (list(best.get("to_turn_it_on") or []) or [""])[0]
        return (f"Not yet — {name} needs setting up first."
                + (f" {str(step)[:160]}" if step else ""))
    return f"No. {name} is {status.replace('_', ' ').lower()}."


ANSWERS = {"halted": lambda rest: _halted(),
           "waiting": lambda rest: _waiting(),
           "doing": lambda rest: _doing(),
           "today": lambda rest: _today(),
           "yesterday": lambda rest: _yesterday(),
           "can_you": _can_you}


def answer(question: str) -> str | None:
    """An answer from her own stores, or None to go and think.

    Never raises. A fast path that can break a request is worse than no
    fast path — the slow one was working.
    """
    try:
        found = match(question)
        if not found:
            return None
        name, rest = found
        said = ANSWERS[name](rest)
        # `str(None)` is the four-character string "None", which is truthy
        # and would have been spoken out loud as an answer.
        if said is None:
            return None
        return str(said).strip() or None
    except Exception:
        return None
