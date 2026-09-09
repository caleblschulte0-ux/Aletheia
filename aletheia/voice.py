"""Voice on the wall — the page hears "Thea, …" and Aletheia acts.

The browser does the ears and the mouth (Web Speech API — the operator's
own browser, no API keys, §6). This module is the understanding: it maps
a spoken transcript onto the SAME command grammar and gates as every
other channel — nothing here can do anything the intercom can't.

Deliberately deterministic (§104 — no hallucinated capability): a fixed
set of spoken forms maps to command kinds; anything unrecognized is
journaled as a note and says so out loud, never guessed into an action.
A brain-backed interpreter can replace `interpret` later without
touching the gates, because the output is only ever a command object.

`interpret(transcript)` -> {"command": {...} | None, "say": str | None}
  command: to execute through core.run_command (validation, halt, journal)
  say:     spoken directly when no command is needed (status questions)
"""
from __future__ import annotations

import re

from aletheia import capabilities, policy, speech, tasks

WAKE_WORDS = ("thea", "theia", "tia", "althea", "aletheia")


def strip_wake_word(text: str) -> str:
    t = text.strip()
    for w in WAKE_WORDS:
        if t.lower().startswith(w):
            rest = t[len(w):].lstrip(" ,.!?:;")
            return rest
    return t


# What people put in front of a sentence without meaning anything by it.
# Every pattern below is anchored at the start, so a single emoji or an
# "uh" decided whether "remind me at 4 to celebrate" was the instant
# deterministic verb or a five-second planner round trip that then asked
# for an approval the direct path would not have needed. A decoration
# should not change what she does.
FILLER = re.compile(
    r"^(?:[^\w\s]+\s*)*"                    # leading emoji or punctuation
    r"(?:(?:uh+|um+|er+|hmm+|ok|okay|so|well|hey|yo|please|right|"
    r"i mean|like)\b[,\s]*)*",
    re.UNICODE)


def _without_preamble(low: str) -> str:
    """Drop leading filler and decoration — never anything that carries meaning.

    Conservative on purpose: if stripping would leave nothing, the sentence
    WAS the filler ("uh", "ok") and is handed back untouched so the
    ordinary "I didn't get that" path still sees it.
    """
    stripped = FILLER.sub("", low, count=1).lstrip(" ,.!?:;-").strip()
    return stripped or low


# A dot does not make a web address. "read notes.md" was compiled into
# `browse_read https://notes.md/` and came back
# "net::ERR_TUNNEL_CONNECTION_FAILED" — she tried to visit his file.
#
# Whitelisting the endings that really are top-level domains is the safe
# direction: an unusual one falls through to the planner, which is slower
# and can still do the right thing. Blacklisting file extensions is not,
# because `.md` `.sh` `.it` `.co` `.io` `.me` `.tv` are all both.
TLDS = frozenset("""
com org net edu gov mil int io ai dev app co uk us ca au de fr es it nl se
no fi dk pl ru jp cn in br mx za ch at be pt gr ie nz cz hu ro tv me sh gg
xyz online site tech store blog cloud page live news info biz eu tel
""".split())


def _spoken_url(tail: str) -> str | None:
    """'example dot com' -> https://example.com; 'github.com' passes through.

    Returns None for anything that is not recognisably a web address, so
    the caller can let the planner have it.
    """
    t = tail.strip().rstrip(".?!").lower()
    if not t:
        return None
    t = re.sub(r"\s+dot\s+", ".", t)
    t = re.sub(r"\s+slash\s+", "/", t)
    if "." not in t:
        return None
    t = t.replace(" ", "")
    if t.startswith(("http://", "https://")):
        return t
    host = t.split("/", 1)[0].split(":", 1)[0].split("?", 1)[0]
    if "." not in host or host.rsplit(".", 1)[-1] not in TLDS:
        return None
    return "https://" + t


def _is_bare_hour(text: str) -> bool:
    """Did he give an hour with no am/pm — "at 3" rather than "at 3 pm"?

    Both readings are live for anything he says without am or pm, not
    only for a bare digit: "quarter past eight" at nine in the evening is
    a quarter past eight TONIGHT to a person, and reading it as tomorrow
    morning is the same 12-hour error as "at 3" meaning 03:00. Noon and
    midnight name one hour each and are never ambiguous.
    """
    t = " ".join(str(text or "").lower().replace(".", "").split())
    if not t or t in ("noon", "midday", "midnight"):
        return False
    return "am" not in t.split() and "pm" not in t.split()


# The hours as people say them out loud, and the two names for a time
# that carry no number at all. "Remind me at NOON to eat" came back "I
# couldn't parse the time 'noon'".
_SPOKEN_HOURS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                 "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                 "eleven": 11, "twelve": 12, "midday": 12, "noon": 12,
                 "midnight": 0}


def _spoken_time(text: str) -> str | None:
    """'8 am' / '8:30 pm' / '20:15' / 'half past six' / 'noon' -> 'HH:MM'."""
    t = " ".join(text.strip().lower().replace(".", "").split())
    if t.startswith("about ") or t.startswith("around "):
        t = t.split(" ", 1)[1]
    # "quarter past eight", "half past six", "quarter to nine" — said far
    # more often than "08:15", and none of them parsed.
    m = re.fullmatch(r"(quarter|half|\d{1,2}|ten|twenty|five)\s+(past|to)\s+"
                     r"([a-z]+|\d{1,2})\s*(am|pm)?", t)
    if m:
        minutes = {"quarter": 15, "half": 30, "ten": 10, "twenty": 20,
                   "five": 5}.get(m.group(1))
        if minutes is None:
            minutes = int(m.group(1)) if m.group(1).isdigit() else None
        hour = (int(m.group(3)) if m.group(3).isdigit()
                else _SPOKEN_HOURS.get(m.group(3)))
        if minutes is None or hour is None or not (0 <= hour <= 23):
            return None
        if m.group(2) == "to":
            hour, minutes = (hour - 1) % 24, 60 - minutes
        if m.group(4) == "pm" and hour < 12:
            hour += 12
        if m.group(4) == "am" and hour == 12:
            hour = 0
        return f"{hour % 24:02d}:{minutes:02d}"
    named = re.fullmatch(r"([a-z]+)\s*(am|pm)?", t)
    if named and named.group(1) in _SPOKEN_HOURS:
        hour = _SPOKEN_HOURS[named.group(1)]
        if named.group(2) == "pm" and hour < 12:
            hour += 12
        if named.group(2) == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:00"
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if m.group(3) == "pm" and hour != 12:
        hour += 12
    if m.group(3) == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday")


def _spoken_day(text: str) -> str | None:
    """'today' / 'tomorrow' / 'friday' / '2026-08-27' -> ISO date, else None.

    Weekday names are how people name days out loud, and every one of
    them used to come back "I couldn't parse the day". "Next friday" is
    deliberately NOT handled here: in English it means this coming Friday
    to some people and the one after to others, and quietly picking one
    is the same class of mistake as dropping "afternoon" — so
    `interpret` asks instead.
    """
    import datetime as dt
    t = text.strip().lower().rstrip(".?!")
    t = t[5:].strip() if t.startswith("this ") else t
    today = dt.date.today()
    if t in ("today", ""):
        return today.isoformat()
    if t == "tomorrow":
        return (today + dt.timedelta(days=1)).isoformat()
    if t in WEEKDAYS:
        ahead = (WEEKDAYS.index(t) - today.weekday()) % 7
        return (today + dt.timedelta(days=ahead)).isoformat()
    try:
        return dt.date.fromisoformat(t).isoformat()
    except ValueError:
        return None


# Nobody means three in the morning. A bare hour with no am/pm is the
# most common way a person says a time out loud, and resolving it
# literally put "remind me at 3", said at a quarter to nine in the
# morning, at 03:00 TOMORROW — eighteen hours late and in the middle of
# the night. So a bare hour never lands before this hour of the morning;
# an explicit "3 am" still does, because then he said it.
EARLIEST_BARE_HOUR = 6


# The words he actually uses for a stretch of a day.
DAY_PARTS = ("morning", "afternoon", "evening", "tonight")


def _spoken_when(text: str) -> tuple[str | None, str | None]:
    """"tomorrow afternoon" -> (that date, "afternoon"). Either may be None.

    A day and a part of it arrive in one breath and were being parsed as
    if only the day existed, so "am I free tomorrow afternoon" was
    answered with nine o'clock in the morning.
    """
    words = str(text or "").strip().lower().rstrip(".?!").split()
    part = None
    if words and words[-1] in DAY_PARTS:
        part = words.pop()
        if part == "tonight":
            words = words or ["today"]
    day = _spoken_day(" ".join(words) if words else "today")
    return day, part


def _split_deadline(text: str) -> tuple[str, str]:
    """"renew my passport by friday" -> ("renew my passport", "2026-09-11").

    He said a deadline and it became prose. `task_new` has always taken
    one, and `tasks.due` surfaces it on the beat — so "renew the
    registration by Friday" WAS just a sentence in a file, which is the
    exact difference between a task list and a graveyard.

    Returns the description unchanged when there is no deadline in it, and
    when the words after "by" are not a day — "sort the photos by date"
    must not acquire one.
    """
    m = re.search(r"^(.*?)[,\s]+(?:by|before|due(?: on)?)\s+(.+)$", text)
    if not m:
        return text, ""
    rest, when = m.group(1).strip(), m.group(2).strip()
    if not rest:
        return text, ""
    at = re.search(r"^(.*?)\s+at\s+(.+)$", when)
    day = _spoken_day(at.group(1) if at else when)
    if not day:
        return text, ""
    if at:
        hhmm = _spoken_time(at.group(2))
        if hhmm:
            return rest, f"{day}T{hhmm}:00"
    return rest, day


def _ordinal(day: int) -> str:
    """1 -> '1st'. Said out loud, so "the 1th" is not an option."""
    if 11 <= day % 100 <= 13:
        return f"{day}th"
    return f"{day}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th') }".replace(" ", "")


def _ambiguous_next_weekday(text: str) -> str | None:
    """The one phrase worth asking about rather than guessing.

    "Next Friday" means the coming Friday to half the people who say it
    and the one after to the other half. Picking silently is how she
    confirms the wrong thing confidently, which is the failure that costs
    trust fastest.
    """
    import datetime as dt
    words = str(text or "").strip().lower().rstrip(".?!").split()
    if len(words) < 2 or words[0] != "next" or words[1] not in WEEKDAYS:
        return None
    today = dt.date.today()
    ahead = (WEEKDAYS.index(words[1]) - today.weekday()) % 7 or 7
    soon = today + dt.timedelta(days=ahead)
    later = soon + dt.timedelta(days=7)
    name = words[1].capitalize()
    return (f"Which {name} — the {_ordinal(soon.day)}, "
            f"or the week after on the {_ordinal(later.day)}?")


def _next_occurrence_iso(hhmm: str, *, bare_hour: bool = False,
                         now: "dt.datetime | None" = None) -> str:
    """The next moment he plausibly meant by HH:MM, operator-local.

    `bare_hour` says he gave an hour with no am/pm. Then both readings are
    live — 3 could be 03:00 or 15:00 — and the answer is the earliest
    future one that a person could have meant, which is never the small
    hours. "At 3" at 08:45 is this afternoon; at 16:00 it is tomorrow
    afternoon, not tomorrow before dawn.
    """
    import datetime as dt
    from aletheia import localtime
    tz = localtime.operator_tz()
    now = now.astimezone(tz) if now is not None else dt.datetime.now(tz)
    hour, minute = map(int, hhmm.split(":"))

    def at(day_offset: int, h: int) -> "dt.datetime":
        return (now + dt.timedelta(days=day_offset)).replace(
            hour=h, minute=minute, second=0, microsecond=0)

    hours = [hour]
    if bare_hour and 1 <= hour <= 11:
        hours.append(hour + 12)
    candidates = sorted(at(day, h) for day in (0, 1) for h in hours)
    for candidate in candidates:
        if candidate <= now:
            continue
        if bare_hour and candidate.hour < EARLIEST_BARE_HOUR:
            continue
        return candidate.isoformat()
    # Only reachable if every reading is in the past or the small hours;
    # the literal next occurrence is still better than no reminder.
    return next(c for c in candidates if c > now).isoformat()


def _status_say() -> str:
    from aletheia.core import status_payload  # late import; core imports us too
    s = status_payload()
    parts = []
    if s["halted"]:
        parts.append("I am HALTED — nothing acts until you say resume.")
    alerts = s["pulse"].get("alerts")
    if alerts:
        parts.append(f"{alerts} fleet alert{'s' if alerts != 1 else ''}.")
    live = s["tasks"]["live"]
    parts.append(f"{live} live task{'s' if live != 1 else ''}.")
    pending = s["approvals_pending"]
    if pending:
        parts.append(f"{len(pending)} approval{'s' if len(pending) != 1 else ''} "
                     "waiting on you — approve them on your phone; the routine "
                     "ones I can take by voice.")
    if not s["halted"] and not alerts and not pending:
        parts.append("All quiet.")
    return " ".join(parts)


# Ported from ChatGPT PR #75 (2026-09-01) after review; the rest of that
# branch is superseded by #76's durable delivery. "What needs my
# attention?" is the question most worth answering INSTANTLY: routing it
# through the planner cost ~90 seconds and a model call to read queues
# that are already durable local state. Deterministic is also more honest
# here — it reports what the stores contain, with nothing to invent.
def _attention_say() -> str:
    """Read the durable attention queues locally; no model is needed."""
    from aletheia import current_state
    from aletheia.core import status_payload  # late import; core imports us too

    state = current_state.snapshot()
    needs = state["needs_attention"]
    parts = []
    if state["halted"]:
        parts.append("I am halted — nothing acts until you say resume.")
    alerts = status_payload()["pulse"].get("alerts") or 0
    if alerts:
        parts.append(f"{alerts} fleet alert{'s' if alerts != 1 else ''}.")
    for key, singular in (
        ("pending_approvals", "approval waiting on you"),
        ("waiting_operator", "task waiting on you"),
        ("blocked_tasks", "blocked task"),
        ("overdue_replies", "overdue reply"),
    ):
        count = len(needs[key])
        if count:
            plural = singular if count == 1 else (
                singular.replace("approval", "approvals")
                .replace("task", "tasks")
                .replace("reply", "replies")
            )
            parts.append(f"{count} {plural}.")
    unread = needs["unread_notifications"]
    if unread:
        parts.append(f"{unread} unread notification{'s' if unread != 1 else ''}.")
    return " ".join(parts) or "Nothing needs your attention right now."


# The days a weekly reminder can name, for the deterministic path.
_DAY_WORDS = ("monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
              "mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun|"
              "weekday|weekend")
# "Remind me every monday to take the bins out" names no time, and a
# reminder needs one. Nine in the morning is the hour a person means by
# "on Monday" — and the confirmation says it back, so a wrong guess costs
# him one sentence rather than a missed bin day.
DEFAULT_REMINDER_TIME = "09:00"
# "Snooze that" with no interval. Short, because he is putting something
# down for a moment, and the confirmation says the time back.
DEFAULT_SNOOZE_MINUTES = 15


# The fields of a command that hold HIS OWN WORDS, as opposed to a
# lookup needle or an identifier. Everything here is stored, or read back
# to him later, so it keeps his capitals.
HIS_WORDS = ("text", "description", "item", "body", "question", "goal",
             "need", "note", "topic",
             # People's names, which are the thing he is most likely to
             # notice her re-spelling: "remember person Dana ..." stored a
             # contact whose display name was "dana".
             "name", "person", "who", "to", "alias")


# The words a detail question is MADE of, so "my email" and "my phone
# number" read as him rather than as somebody called "my email".
_FIRST_PERSON = frozenset({"my", "our", "mine"})
_DETAIL_WORDS = frozenset({"email", "phone", "number", "address", "details",
                           "cell", "mobile", "e-mail", "telephone"})


def _is_about_himself(captured: str) -> bool:
    """Is this capture HIM, or a person he knows?

    "What's my email" captured "my" and searched his contacts for someone
    of that name; "what is my email address" captured "my email" the same
    way. Both are questions about him, answered from his profile. "My
    wife's number" captures "my wife", who is a real person and really is
    a contact — so only a possessive followed by nothing but detail words
    is his.
    """
    words = str(captured or "").strip().casefold().split()
    if not words or words[0] not in _FIRST_PERSON:
        return False
    return all(word in _DETAIL_WORDS for word in words[1:])


def _as_he_said(transcript: str, fragment: str) -> str:
    """A matched fragment with his capitals put back.

    The whole deterministic layer matches against a LOWERCASED sentence,
    which is right for matching and wrong for anything it stores: "note
    that Dana called" became the note "that dana called", and a name he
    said is not a name she may re-spell. The fragment came out of the
    lowered text, so it is found there and sliced from the original.
    """
    frag = " ".join(str(fragment or "").split())
    lowered = str(transcript or "").lower()
    if not frag or len(lowered) != len(transcript or ""):
        return fragment
    at = lowered.find(frag)
    return transcript[at:at + len(frag)] if at >= 0 else fragment


def _his_capitals(transcript: str, decided: dict) -> dict:
    """Put his capitals back into every stored field of a command."""
    command = decided.get("command")
    if not isinstance(command, dict):
        return decided
    for field in HIS_WORDS:
        value = command.get(field)
        if isinstance(value, str) and value:
            command[field] = _as_he_said(transcript, value)
    return decided


def _spoken_minutes(text: str) -> int | None:
    """"an hour", "20 minutes", "half an hour", "2 hours" -> minutes."""
    t = " ".join(str(text or "").lower().split()).strip(" .?!")
    if t in ("an hour", "a hour", "one hour", "1 hour"):
        return 60
    if t in ("half an hour", "30 mins", "a half hour"):
        return 30
    if t in ("a minute", "a moment", "a bit", "a while"):
        return 15
    m = re.fullmatch(r"(\d{1,4})\s*(m|min|mins|minute|minutes)", t)
    if m:
        return int(m.group(1))
    m = re.fullmatch(r"(\d{1,3})\s*(h|hr|hrs|hour|hours)", t)
    if m:
        return int(m.group(1)) * 60
    m = re.fullmatch(r"(\d{1,2})\s*(d|day|days)", t)
    if m:
        return int(m.group(1)) * 60 * 24
    return None


def _might_be_several(text: str) -> bool:
    """Could this be a list of things rather than one thing?

    Deliberately generous: a false positive costs a round trip, a false
    negative puts "eggs milk and bread" on the shopping list as a single
    item he then has to find and delete.
    """
    t = " ".join(str(text or "").lower().split())
    return "," in t or " and " in t or " & " in t or " plus " in t


def _to_the_planner(text: str) -> dict:
    """Hand the sentence on rather than ending the turn on a parse error.

    The deterministic layer exists to be FAST, and every dead end it
    produces ("I couldn't parse the time 'noon'") is it being slower than
    useless — the planner would have read the sentence. It may remove
    latency; it may never remove an answer.
    """
    return {"command": {"kind": "intent", "text": text}, "say": None}


def _the_only_open_task() -> str:
    """The description of the single open task, or "" if there are 0 or 2+."""
    try:
        from aletheia import intercom
        rows = intercom._open_tasks()
    except Exception:
        return ""
    if len(rows) != 1:
        return ""
    return str(rows[0].get("description") or rows[0].get("id") or "")


def _known_place(text: str) -> bool:
    """Is this a place she has actually saved? Never raises.

    The gate on reading a bare "how long to X" as a journey. Without it,
    "how long to finish the report" is a destination.
    """
    try:
        from aletheia import places
        places.resolve(text)
        return True
    except Exception:
        return False


# Words that carry no request on their own. Filler, and the handful of
# bare function words a recogniser produces from room noise — "the" is
# the one that actually happened, over and over.
_NOT_CONTENT = frozenset("""
a an the and or but so of to in on at for with from by is are was were be
been am do does did done have has had will would could should may might
must can it its it's this that these those there here he she they them
him her his hers their we us our you your i me my mine
uh uhh um umm er erm hmm mm mhm ah oh eh yeah yep yup nah nope ok okay
right well like just really actually thing things please thanks thank
""".split())


def worth_answering(said: str) -> bool:
    """Did a person actually ask her something?

    False means SAY NOTHING — not "I didn't catch that". A machine that
    apologises to the television is broken, and every apology also cost a
    planner round trip and a notification.

    Anything the deterministic layer compiles is a request whatever its
    length, so "stop" — one word, and the most important word here — can
    never be silenced by this.
    """
    text = " ".join(str(said or "").split())
    if not text:
        return False
    try:
        got = interpret(text) or {}
        if (got.get("command") or {}).get("kind") not in (None, "intent"):
            return True
        if got.get("say") and not got.get("command"):
            return True          # a turn she already knows how to end
    except Exception:
        return True              # never silent because something broke
    try:
        # THE LANE THAT ANSWERS MOST OF WHAT HE SAYS. "Are you halted" is
        # an `intent` to the interpreter and one content word to the
        # counter — "halted" — so without this the most basic question he
        # can ask her was treated as room noise.
        from aletheia import quick
        if quick.answer(text):
            return True
    except Exception:
        return True
    tokens = re.findall(r"[a-z0-9']+", text.lower())
    if not tokens:
        return False
    # THE FIRST WORD IS THE SIGNAL. Every fragment his machine actually
    # picked up starts with filler — "the", "the injuries", "uh", "um
    # the", "ok", "yeah", "right", "er", "it", "that". A person who
    # starts with a real word has said something, however short:
    # "print this" is two words, one of them a stopword, and it is an
    # instruction. Silencing that is the same failure this rule exists
    # to prevent, pointing the other way.
    if tokens[0] not in _NOT_CONTENT:
        return True
    # Otherwise it opened with filler, so it needs two words with meaning
    # in them. The cost of being wrong here is that he repeats himself
    # once; the cost of being wrong the other way was a planner round
    # trip and an apology, every time the television spoke.
    return len([w for w in tokens if w not in _NOT_CONTENT]) >= 2


def interpret(transcript: str) -> dict:
    """One spoken sentence -> a command to gate-check, or words to say.

    The wrapper exists for one reason: every path below matches against a
    LOWERCASED sentence, and anything it STORES has to keep his capitals.
    Doing it here rather than in thirty patterns means the next pattern
    somebody writes gets it for free.
    """
    return _his_capitals(strip_wake_word(transcript), _interpret(transcript))


def _interpret(transcript: str) -> dict:
    text = strip_wake_word(transcript)
    low = _without_preamble(text.lower().strip().rstrip(".?!"))
    if not low:
        return {"command": None, "say": "I'm listening."}

    # THE KILL SWITCH HAS TO CATCH THE SENTENCE HE WOULD ACTUALLY SAY.
    #
    # This was a `fullmatch` against a short list, so "stop everything you're
    # doing" — the natural phrasing, and longer than any entry — fell
    # through to the planner and depended on a language model to compile it
    # into `halt`. Depending on a compiler to reach an emergency stop is the
    # wrong shape twice over: it is slow when it works, and as of today the
    # planner is forbidden from emitting `halt` at all
    # (intercom.PLANNER_FORBIDDEN), so it would not have worked.
    #
    # Phrases, not a bare "stop": searched anywhere in the sentence, and
    # every one of them is unambiguous on its own. "Stop the music" does not
    # contain any of them.
    #
    # "Stop that" and "stop it" are the same emergency, one pronoun longer,
    # and they were reaching the planner — which may not emit `halt` at
    # all, so the sentence that stops her stopped nothing. Only the
    # pronouns: an OBJECT means something else ("stop the music"), and the
    # asymmetry decides the rest. A halt he did not mean costs him the
    # word "resume"; a halt he meant and did not get costs whatever she
    # was doing.
    if (re.fullmatch(r"(halt|stop|kill switch|emergency stop|shut it down|"
                     r"stand down|stop (that|it|now)|that(?:'s| is) enough)", low)
            or re.search(r"\b(stop everything|halt everything|stop all of (it|this)|"
                         r"stop what you.?re doing|stop everything you.?re doing|"
                         r"kill switch|emergency stop|shut (it|everything) down|"
                         r"stand down|drop everything)\b", low)):
        return {"command": {"kind": "halt", "reason": f"by voice: {transcript!r}"},
                "say": None}
    # RESUME STAYS CONSERVATIVE, and deliberately so: the English noun
    # "résumé" is the same six letters as the kind that lifts the kill
    # switch. A `search` here would turn "read my resume" into un-halting
    # her. Only whole sentences that can mean nothing else.
    # The reflexive forms are safe to add and were NOT here: "resume
    # yourself" reached the planner, which is forbidden from emitting
    # `resume` — so it quietly compiled something else instead and she
    # answered "Resume normal operation and surface current state" while
    # resuming nothing. Him telling her to resume is the ordinary path;
    # the rule is that a MODEL may not decide to lift the halt.
    if re.fullmatch(r"(resume|resume everything|start again|back on|carry on|"
                    r"un-?halt|you can (resume|start again|carry on)|"
                    r"(go ahead and )?resume now|"
                    r"resume (yourself|aletheia|thea)( please| now)?|"
                    r"un-?halt (yourself|aletheia|thea)( please| now)?|"
                    r"(lift|cancel|clear) the halt|"
                    r"turn yourself back on)", low):
        return {"command": {"kind": "resume"}, "say": None}
    # CLOSING HER IS NOT HALTING HER, and until 2026-09-07 voice could
    # reach `halt` and had no way at all to reach this one. So "turn
    # yourself off" went to the planner, which is forbidden from emitting
    # `close`, and its only remaining move was to compile something else
    # and report success — on the one command where believing her matters
    # most: he thinks the microphone is off.
    #
    # Whole sentences only, and REFLEXIVE ones wherever the verb is
    # ordinary. "Turn off the kitchen lights" and "close the browser tab"
    # are things he says; neither can reach this.
    if re.fullmatch(r"(close|close yourself|close (aletheia|thea)|"
                    r"turn (yourself )?off|turn off (yourself|aletheia|thea)|"
                    r"shut (yourself|aletheia|thea) down|"
                    r"go to sleep|go offline|power (yourself )?down|"
                    r"close the window|see you later)", low):
        return {"command": {"kind": "close", "reason": f"by voice: {transcript!r}"},
                "say": None}
    # The mirror, for completeness. He can rarely SAY this one: when she is
    # closed the microphone is off with everything else, so opening her
    # again is a thing he does from the phone, the Command Center or the
    # keyboard. It is here so that saying it while she is merely halted
    # gets an honest "I was not closed" instead of a compiled substitute.
    if re.fullmatch(r"(open|open yourself|open (aletheia|thea)|"
                    r"wake up|wake yourself up|come back)", low):
        return {"command": {"kind": "open"}, "say": None}
    # "IS ANY OF THIS ON?" — the question he could previously only answer
    # by reading a process list and Task Scheduler side by side.
    if re.fullmatch(r"(what(?:'s| is)? running|what(?:'s| is)? on"
                    r"(?: right now)?|which parts are running|"
                    r"are (you|u) (all )?running|is anything running|"
                    r"what parts (of you )?are running|are (you|u) on)", low):
        return {"command": {"kind": "running"}, "say": None}
    # SELF-AUTHORITY, NOT EXACTLY MATCHED. Everything above is a whole
    # sentence that can mean nothing else. Anything that is plainly an
    # order about her own kill switch and did NOT match must stop here,
    # because the planner cannot emit these kinds and its only remaining
    # move is to substitute a different action — which it did, silently,
    # and then described the substitute as if it had resumed.
    #
    # Asking him for the one word is the honest answer: it is one
    # syllable, and it is the difference between an emergency stop that
    # works and one that reports success.
    # Only when the rest of the sentence is about HER. "Resume the
    # download when you can" and "stop the music" are ordinary requests
    # that happen to start with the same verb, and swallowing those would
    # trade one silent substitution for another.
    m = re.match(r"^(resume|un-?halt|halt|close|open|shut down|turn off|"
                 r"turn on|go to sleep|wake up)\s+"
                 r"((?:yourself|aletheia|thea|it|everything|all|again|now|"
                 r"please|for me|ok|okay)(?:\s+\w+){0,2})\s*$", low)
    if m:
        word = "resume" if m.group(1).startswith(("resume", "unhalt", "un-halt")) \
            else "halt"
        return {"command": None,
                "say": f"Say just \u201c{word}\u201d and I'll do it — I won't "
                       "guess at anything else for the kill switch."}

    # Apostrophes optional: speech-to-text drops them far more often than it
    # keeps them, and "whats going on" was falling past the instant local
    # answer into the planner — twenty seconds for a question worth 50ms.
    if re.fullmatch(r"(what needs my attention|does anything need my attention|"
                    r"anything need my attention|what do i need to deal with|"
                    r"what needs attention|anything need me)", low):
        return {"command": None, "say": _attention_say()}

    if re.fullmatch(r"(status|what'?s going on|what is going on|what'?s up|"
                    r"how are things|anything happening|report)", low):
        return {"command": None, "say": _status_say()}

    if re.fullmatch(r"(what|who) (are )?(you|u) watching( for)?"
                    r"|what emails? (are )?(you|u) watching for"
                    r"|what are (you|u) waiting (for|on)"
                    r"|(list )?(my )?watches", low):
        return {"command": {"kind": "watches"}, "say": None}
    if re.fullmatch(r"(who|what) (contacts? )?(do i have|have i got)( saved)?"
                    r"|(list )?(my )?contacts"
                    r"|who do i have (saved|on file)", low):
        return {"command": {"kind": "contacts"}, "say": None}
    m = re.fullmatch(r"what'?s? (?:is )?(.+?)'?s? (?:phone )?(?:number|email|"
                     r"address|details)", low)
    # "What's MY email" is a question about HIM, and this pattern captured
    # "my" as a person's name and went looking through his contacts for
    # one — the deterministic-pattern-swallows-too-much failure, giving a
    # different answer than the same question typed, which `quick` answers
    # from his profile. Only the bare possessive is his: "my wife's
    # number" really is a contact, and its capture is "my wife".
    if m and len(m.group(1)) < 40 and not _is_about_himself(m.group(1)):
        return {"command": {"kind": "contacts", "which": m.group(1).strip()},
                "say": None}
    if re.fullmatch(r"(what|which) (jobs?|applications?) have i applied (to|for)"
                    r"|what have i applied (to|for)"
                    r"|(what|which) (jobs?|applications?) did (you|u) apply (to|for)"
                    r"|(list )?(my )?applications", low):
        return {"command": {"kind": "applications"}, "say": None}
    if re.fullmatch(r"(what'?s?( is)? on )?(my |the )?shopping list"
                    r"|what do i need (to buy|from the (shop|store))"
                    r"|read (me )?(my |the )?shopping list", low):
        return {"command": {"kind": "shopping_list"}, "say": None}
    m = re.match(r"(?:take|remove|delete) (.+?) (?:off|from) (?:my |the )?"
                 r"shopping list", low)
    if m:
        return {"command": {"kind": "shopping_off", "item": m.group(1).strip()},
                "say": None}

    # "Snooze that for an hour" — the commonest thing anybody says to a
    # notification, and it had no verb at all.
    m = re.fullmatch(r"snooze(?: (?:that|it|this|them|the (?:alert|notification|"
                     r"reminder)))?\s*(?:for |by )?(.*)", low)
    if m:
        rest = m.group(1).strip()
        # A bare "snooze that" is the commonest form and names no
        # interval. Fifteen minutes, and the confirmation says it back —
        # the same argument as the nine o'clock default for a weekly
        # reminder. Anything it cannot read goes to the planner rather
        # than being rounded to a number nobody said.
        minutes = DEFAULT_SNOOZE_MINUTES if not rest else _spoken_minutes(rest)
        if minutes:
            return {"command": {"kind": "notify_snooze", "minutes": minutes},
                    "say": None}
        return _to_the_planner(text)

    # what is set, and stopping one. Before the "remind me" patterns so a
    # question about reminders is never read as a request for a new one.
    if re.fullmatch(r"(what|which) reminders? (do i have|are set|have i got)"
                    r"|what am i being reminded (of|about)"
                    r"|list (my )?reminders|my reminders|reminders", low):
        return {"command": {"kind": "reminders"}, "say": None}
    m = re.match(r"(?:cancel|stop|delete|turn off|remove) (?:the |my |that )?"
                 r"reminder (?:about |for |to )?(.+)", low)
    if not m:
        m = re.match(r"stop reminding me (?:about|to|of) (.+)", low)
    if m:
        return {"command": {"kind": "reminder_off", "which": m.group(1).strip()},
                "say": None}

    # reminders — before email so "remind me to email bob" stays a reminder
    #
    # WEEKLY FIRST: "every monday" contains "every", and the daily pattern
    # below is anchored on "every day", but a weekly phrasing without a
    # time ("remind me every monday to take out the trash") had no
    # deterministic match at all and reached the planner, which compiled a
    # generic `do_task` under the summary "Set weekly Monday reminder" —
    # a promise of recurrence the step could not keep.
    _one_day = r"(?:" + _DAY_WORDS + r")s?"
    m = re.match(r"remind me (?:every|each) "
                 r"(" + _one_day + r"(?:\s*(?:,|and|&)\s*" + _one_day + r")*)"
                 r"(?:\s+at\s+([\w: ]+?))? (?:to|that) (.+)", low)
    if m:
        hhmm = _spoken_time(m.group(2)) if m.group(2) else DEFAULT_REMINDER_TIME
        if not hhmm:
            # The planner reads times this does not, and the confirmation
            # says the hour back either way. A dead end here is the fast
            # lane removing an answer, which it may never do.
            return _to_the_planner(text)
        # "tuesday and thursday", "mon, wed and fri" — a list he says in one
        # breath. The planner's version of this came back as "Weekly
        # reminder Tue/Thu 6pm", which is a calendar entry, not a sentence.
        days = [d for d in re.split(r"\s*(?:,|and|&)\s*", m.group(1)) if d]
        return {"command": {"kind": "remind_weekly", "days": days,
                            "time": hhmm, "text": m.group(3).strip()},
                "say": None}
    m = re.match(r"remind me (?:every day|daily) at ([\w: ]+?) (?:to|that) (.+)", low)
    if m:
        hhmm = _spoken_time(m.group(1))
        if hhmm:
            return {"command": {"kind": "remind_daily", "time": hhmm,
                                "text": m.group(2).strip()}, "say": None}
        return _to_the_planner(text)
    m = re.match(r"remind me (?:at ([\w: ]+?)|in (\d+) (minutes?|hours?)) (?:to|that) (.+)", low)
    if m:
        if m.group(1):
            hhmm = _spoken_time(m.group(1))
            if not hhmm:
                return _to_the_planner(text)
            at = _next_occurrence_iso(hhmm, bare_hour=_is_bare_hour(m.group(1)))
        else:
            import datetime as dt
            amount = int(m.group(2))
            delta = dt.timedelta(minutes=amount) if m.group(3).startswith("minute") \
                else dt.timedelta(hours=amount)
            at = (dt.datetime.now(dt.timezone.utc) + delta).isoformat()
        return {"command": {"kind": "remind_at", "at": at, "text": m.group(4).strip()},
                "say": None}

    # THE OTHER WORD ORDER, which is the commoner one. Every pattern
    # above is "remind me AT <time> TO <thing>"; "remind me to call the
    # dentist at 3" matched none of them and paid a planner round trip
    # for the most ordinary request an assistant gets.
    #
    # After the forward forms so nothing that already worked changes
    # route, and a time is REQUIRED: "remind me to call the dentist"
    # with no when is a task, and the planner decides that better.
    m = re.match(r"remind me (?:to|that) (.+?) "
                 r"(?:at ([\w: ]+)|in (\d+) (minutes?|hours?))$", low)
    if m:
        if m.group(2):
            hhmm = _spoken_time(m.group(2))
            if not hhmm:
                return _to_the_planner(text)
            at = _next_occurrence_iso(hhmm, bare_hour=_is_bare_hour(m.group(2)))
        else:
            import datetime as dt
            amount = int(m.group(3))
            delta = dt.timedelta(minutes=amount) if m.group(4).startswith("minute") \
                else dt.timedelta(hours=amount)
            at = (dt.datetime.now(dt.timezone.utc) + delta).isoformat()
        return {"command": {"kind": "remind_at", "at": at,
                            "text": m.group(1).strip()}, "say": None}

    # A TIMER IS A ONE-SHOT ALERT, which is what `remind_at` already is.
    # `timer.set` was NOT_BUILT because the sentence reached nothing, not
    # because the mechanism was missing: "remind me in 10 minutes to
    # check the oven" has worked for weeks. So a timer said AS a timer
    # compiles to the same durable schedule, with the words a person
    # wants to hear at the end.
    m = re.fullmatch(r"(?:set|start) (?:a |an )?timer (?:for |of )?"
                     r"(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)"
                     r"(?:\s+(?:to|for|so i can)\s+(.+))?", low)
    if m:
        import datetime as dt
        amount, unit = int(m.group(1)), m.group(2)
        if unit.startswith(("second", "sec")):
            delta, spoken_unit = dt.timedelta(seconds=amount), "second"
        elif unit.startswith(("hour", "hr")):
            delta, spoken_unit = dt.timedelta(hours=amount), "hour"
        else:
            delta, spoken_unit = dt.timedelta(minutes=amount), "minute"
        why = (m.group(3) or "").strip()
        # The unit is an ADJECTIVE here and stays singular — "a 10
        # minute timer", not "a 10 minutes timer". Pluralising it
        # is the right rule in the wrong place, and this is read
        # out loud.
        text = why or f"your {amount} {spoken_unit} timer is up"
        at = (dt.datetime.now(dt.timezone.utc) + delta).isoformat()
        return {"command": {"kind": "remind_at", "at": at, "text": text},
                "say": None}

    # An alarm is the same thing at a clock time, and it inherits the
    # bare-hour rule: "at 7" said in the evening means tomorrow morning,
    # which is written down here already because a bare hour once became
    # three in the morning.
    m = re.fullmatch(r"(?:set|wake me(?: up)?(?: with)?) (?:an |a )?alarm "
                     r"(?:for |at )([\w: ]+?)(?:\s+(?:to|for)\s+(.+))?"
                     r"|wake me(?: up)? at ([\w: ]+)", low)
    if m:
        when = (m.group(1) or m.group(3) or "").strip()
        hhmm = _spoken_time(when)
        if not hhmm:
            return _to_the_planner(text)
        at = _next_occurrence_iso(hhmm, bare_hour=_is_bare_hour(when))
        why = (m.group(2) or "").strip()
        return {"command": {"kind": "remind_at", "at": at,
                            "text": why or "your alarm"}, "say": None}

    # "tell me when I get an email from bob"
    m = re.match(r"(?:tell me|let me know|watch for)\s+when\s+(?:i get|there's)?\s*"
                 r"(?:an?\s+)?e?mail (?:arrives )?from\s+(.+)", low) or \
        re.match(r"watch for e?mail from\s+(.+)", low)
    if m:
        return {"command": {"kind": "watch_email_from",
                            "who": m.group(1).strip()}, "say": None}

    # "What are my tasks" is a store read and it was costing 8.5 seconds
    # through the planner, coming back as markdown bullets. She could
    # CREATE a task by voice and had no verb for reading the list.
    if re.fullmatch(r"(?:what (?:are|r) my tasks|what'?s? on my (?:list|plate)|"
                    r"my tasks|list (?:my )?tasks|what do i have to do|"
                    r"what(?:'s| is|s)? left to do|todo list|"
                    # "task list" and a bare "tasks" made a TASK called
                    # "list", because `task <words>` is the create verb.
                    r"tasks?|task list|the task list|"
                    # "Read me my tasks" is the same request with the verb
                    # said out loud, and it was the one that missed.
                    r"(?:read|say|tell) (?:me )?(?:my |the )?tasks?(?: list)?|"
                    r"what(?:'s| is|s)? on my (?:task|todo|to-do) list|"
                    r"what am i supposed to be doing)", low):
        return {"command": {"kind": "tasks"}, "say": None}

    # "Mark the passport one done" — by what he CALLS it. This went to the
    # planner and came back asking for approval to change a local status,
    # while "add a task to renew my passport" ran instantly.
    # "did you do the dishes" is a QUESTION about her, not an instruction
    # to tick something off, so a bare "did" may not start this — only
    # "I did". The past-tense statements ("finished the passport one")
    # stand on their own because nobody asks a question that way.
    m = (re.fullmatch(r"(?:mark|tick|check|cross) (?:off )?(?:the )?(.+?)"
                      r"(?: one| task)? (?:as )?(?:done|complete[d]?|finished)",
                      low)
         or re.fullmatch(r"(?:tick|check|cross) off (?:the )?(.+?)"
                         r"(?: one| task)?", low)
         or re.fullmatch(r"(?:i(?:'ve)? )?(?:finished|completed) (?:the )?(.+?)"
                         r"(?: one| task)?", low)
         or re.fullmatch(r"i (?:did|have done) (?:the )?(.+?)(?: one| task)?", low))
    if m:
        which = (m.group(1) or "").strip()
        if which and which not in ("it", "that", "them", "everything"):
            return {"command": {"kind": "task_done", "which": which}, "say": None}
        # "Mark that done" with exactly ONE thing open is not ambiguous —
        # it is the ordinary way to say it, and it was costing a round
        # trip and an approval. With two open it stays ambiguous and goes
        # to the planner, which asks him which.
        only = _the_only_open_task()
        if which in ("it", "that", "them") and only:
            return {"command": {"kind": "task_done", "which": only}, "say": None}

    # "what files do you have" reached the planner, which sometimes
    # compiled `file_list` and sometimes let `converse` answer — and
    # `converse` does not know she can list a directory, so it replied
    # "no FILE HE NAMED was passed with this question".
    # "What files do I have" — his files, in her workspace — asked the
    # one way the pattern did not have: about himself rather than her.
    if re.fullmatch(r"(?:what|which) files (?:do you have|do i have|"
                    r"are there|have you got)|list (?:my |your )?files|"
                    r"what(?:'s| is|s)? in (?:my |your )?workspace|"
                    r"show me (?:my |your )?files", low):
        return {"command": {"kind": "file_list"}, "say": None}

    # notifications
    if re.fullmatch(r"(?:check (?:my )?notifications?|any notifications?|"
                    r"what's new|anything new|notifications?)", low):
        return {"command": {"kind": "notify_check"}, "say": None}
    if re.fullmatch(r"(?:clear|dismiss|acknowledge) (?:my |the )?notifications?", low):
        return {"command": {"kind": "notify_clear"}, "say": None}

    # free time. "Am I free tomorrow afternoon" is how a person asks this
    # and it matched none of these, so it fell through to the planner: six
    # and a half seconds, and the word "afternoon" thrown away on the way.
    m = re.fullmatch(r"(?:when am i free|am i free|are we free|"
                     r"what'?s my availability|any free time|do i have time)"
                     r"(?:\s+(?:on\s+|this\s+)?(.+?))?\s*\??", low)
    if m:
        asked = _ambiguous_next_weekday(m.group(1) or "")
        if asked:
            return {"command": None, "say": asked}
        day, part = _spoken_when(m.group(1) or "")
        if day:
            command = {"kind": "free_time", "day": day}
            if part:
                command["part"] = part
            return {"command": command, "say": None}
        # FALL THROUGH, don't answer with a parse error. "Am I free at 3 on
        # friday" and "when am I free next week" are ordinary sentences,
        # and this branch was ending the turn with "I couldn't parse 'next
        # week'" — the fast lane removing an ANSWER rather than latency,
        # which is the one thing it may never do. The planner resolves the
        # date and compiles the same command; it just costs a round trip.

    # private contact: "remember person bob smith bob at gmail dot com"
    m = re.match(r"remember (?:person|contact)\s+(.+?)\s+((?:\S+\s+at\s+\S.*|\S+@\S+))$", low)
    if m:
        return {"command": {"kind": "contact_add", "name": m.group(1).strip(),
                            "email": m.group(2).strip()}, "say": None}

    # "what do you still need from me?"
    if re.fullmatch(r"(?:what do you (?:still )?need(?: from me)?|"
                    r"what'?s left(?: to set up)?|am i done|"
                    r"what'?s still missing|setup status)", low):
        return {"command": {"kind": "setup_status"}, "say": None}

    # "what can you do without asking me?" — a read, so it answers.
    if re.fullmatch(r"(?:what can you do without asking(?: me)?|"
                    r"what are you allowed to do|"
                    r"do you need my permission for (?:everything|anything))", low):
        return {"command": {"kind": "authority_status"}, "say": None}

    # Granting authority is NOT taken by voice. The room microphone is
    # unauthenticated — a television, a guest, or a passing sentence could
    # widen what she may do without asking. §70: ability is not permission,
    # and permission is not something to pick up off the air.
    if (re.search(r"(?:grant|give you|revoke|take away|remove)[a-z ]*authority", low)
            or re.fullmatch(r"stop asking (?:me )?(?:about )?"
                            r"(?:the small stuff|everything|so much)", low)):
        return {"command": None,
                "say": ("I won't take that one by voice — anything in the room "
                        "could say it. Run: python -m aletheia.standing on")}

    # ---- verbs she already had, now sayable ----------------------------
    # These front capabilities that were AVAILABLE, tested and registered
    # and simply unreachable from the room. Placed before the browse verbs
    # so "what am I paying for" is not parsed as a website.
    m = re.match(r"(?:set up|arrange|schedule|book) (?:a )?(?:meeting|time|call) "
                 r"with ([a-z' -]+?)(?: (?:next week|this week|about .+))?$", low)
    if m:
        return {"command": {"kind": "meet", "person": m.group(1).strip()},
                "say": None}

    m = re.match(r"(?:what do you know about|what have you got on|"
                 r"remind me about|tell me about) (.+)", low)
    if m:
        return {"command": {"kind": "recall", "about": m.group(1).strip()},
                "say": None}

    if re.fullmatch(r"(?:the |my )?(?:morning )?brief(?:ing)?|"
                    # The phrasings a person actually uses. "Give me the
                    # brief" and "brief me" both went to the planner.
                    r"(?:give me|read me|run) (?:the |my )?brief(?:ing)?|"
                    r"brief me|catch me up|what did i miss", low):
        return {"command": {"kind": "brief"}, "say": None}

    m = re.match(r"handle (?:it|this|that)[,: ]*(.*)$", low)
    if m and m.group(1).strip():
        return {"command": {"kind": "handle", "text": m.group(1).strip()},
                "say": None}

    # "How long ANYTHING" used to be a travel question. "How long until my
    # meeting" came back "I don't know where until my meeting is" — the
    # deterministic layer answering a different question, which is the one
    # failure he cannot see. An explicit travel phrasing is taken as one
    # whether or not she knows the place (so she can ask for the address);
    # the bare "how long to X" is only travel when X really is a place.
    m = (re.match(r"how long (?:does it |will it |would it |should it )?"
                  r"(?:take )?(?:to )?(?:get|drive|walk|ride|cycle|bike) to (.+)",
                  low)
         or re.match(r"how long is the (?:drive|trip|walk|ride|journey|way) "
                     r"to (.+)", low))
    if m:
        return {"command": {"kind": "travel_time", "place": m.group(1).strip()},
                "say": None}
    m = re.match(r"how (?:long|far) (?:is it )?to (.+)", low)
    if m and _known_place(m.group(1).strip()):
        return {"command": {"kind": "travel_time", "place": m.group(1).strip()},
                "say": None}

    # "Why did you add milk to the list" put "why did you add milk" ON the
    # list. `add` was optional, so any sentence ENDING in "to the list"
    # was a write — and a question is never an instruction (the same rule
    # the spending door holds).
    m = re.match(r"(?:add|put|get|stick|throw) (.+?) (?:on|to) (?:the |my )?"
                 r"(?:shopping |grocery )?list$", low)
    if m and _might_be_several(m.group(1)):
        # "Add eggs milk and bread to the shopping list" put ONE entry on
        # it called "eggs milk and bread". Splitting here would have to
        # guess, and "macaroni and cheese" is one thing — so anything
        # that might be a list goes to the planner, which can emit a step
        # per item. A round trip beats a wrong entry.
        return _to_the_planner(text)
    if m:
        return {"command": {"kind": "shopping_add", "item": m.group(1).strip()},
                "say": None}

    if re.fullmatch(r"(?:what am i paying for|my subscriptions?|"
                    r"what subscriptions do i have)", low):
        return {"command": {"kind": "subscriptions"}, "say": None}

    if re.fullmatch(r"(?:how much money do i have|what'?s my balance|"
                    r"my net worth|how am i doing financially)", low):
        return {"command": {"kind": "money"}, "say": None}

    if re.fullmatch(r"(?:when is the car due|car service|"
                    r"does the car need anything|check the car|"
                    # Mileage is the number on the record she already
                    # reads, and asking for it went to the planner.
                    r"(?:what(?:'s| is|s)? )?(?:my |the )?car'?s? "
                    r"(?:mileage|milage)|"
                    r"how many miles (?:are )?on (?:my|the) car|"
                    r"what(?:'s| is|s)? the mileage(?: on (?:my|the) car)?)", low):
        return {"command": {"kind": "car"}, "say": None}

    if re.fullmatch(r"(?:my projects?|what projects are (?:open|active)|"
                    r"what am i working on|"
                    # "Repos" is the word he uses, in a repository he
                    # wrote. `projects` takes no arguments, so there was
                    # nothing standing between this sentence and it
                    # except the sentence.
                    r"(?:check |how are )?(?:my |the )?repos(?:itories)?|"
                    r"how are my projects|what's happening with my projects|"
                    r"project status)", low):
        return {"command": {"kind": "projects"}, "say": None}

    # "Cancel my gym membership." HIGH-RISK and operator_always, so
    # reaching the verb means she PREPARES it and asks him — which is
    # exactly what should happen. The alternative was the planner
    # compiling something adjacent, and CLAUDE.md already records what
    # that looks like: "1 step ready — Cancel a reminder."
    # Things SHE owns. Naming one of these means he is not talking about a
    # service he pays for, so the subscription verb must not claim the
    # sentence. Searched across the WHOLE phrase, not anchored at its
    # start: the anchored version let "cancel the first reminder" and
    # "cancel my 3pm reminder" through to subscription_cancel, because
    # they begin with "first" and "3pm".
    #
    # Deliberately broad, in the safe direction. Missing here costs a
    # planner round trip; matching wrongly sends her looking for a real
    # service to cancel.
    _HERS_NOT_A_SERVICE = re.compile(
        r"\b(?:that|it|the pending one|approval|approvals|reminder|reminders"
        r"|alarm|alarms|timer|timers|task|tasks|note|notes|meeting|meetings"
        r"|appointment|appointments|event|events|schedule|agenda"
        # No leading "the": `cancel (?:my |the )?` has already eaten it,
        # so "cancel the last one" arrives here as just "last one".
        r"|(?:first|second|third|fourth|last)(?: one)?)\b", re.IGNORECASE)

    m = re.fullmatch(r"cancel (?:my |the )?(.+?)"
                     r"(?: membership| subscription| plan)?", low)
    if (m and 2 <= len(m.group(1)) <= 60
            and not _HERS_NOT_A_SERVICE.search(m.group(1))):
        return {"command": {"kind": "subscription_cancel",
                            "subscription": m.group(1).strip()}, "say": None}

    # Screen questions run BEFORE the browse verbs for the same reason the
    # email ones do: "read this" is about what is in front of him, not a
    # website he forgot to name.
    if re.search(r"\b(?:on|in) (?:my|the) screen\b", low) \
            or re.fullmatch(r"what am i looking at\??", low) \
            or re.fullmatch(r"what does (?:this|that)(?: error)?"
                            r"(?: say| mean)?\??", low) \
            or re.fullmatch(r"read (?:this|that|the screen)\??", low):
        return {"command": {"kind": "screen_ask", "question": text.strip()},
                "say": None}

    # email patterns run BEFORE the browse verbs: "check my email" must
    # never be parsed as "check <website>"
    if re.fullmatch(r"(?:check (?:my )?e?mail|any (?:new )?e?mail|"
                    r"do i have (?:any )?e?mail|what's in my inbox)", low):
        return {"command": {"kind": "email_check"}, "say": None}

    # SHE CAN BE TOLD TO STOP LISTENING, and cannot be told to start.
    # Turning it on is a button (intercom `mic_on`, and PLANNER_FORBIDDEN
    # besides), because a microphone that opens when it is spoken to is
    # not off. Turning it off works from anywhere, always.
    if re.fullmatch(r"(?:stop listening|quit listening|stop the microphone"
                    r"|(?:turn|shut) (?:the )?(?:microphone|mic) off"
                    r"|(?:turn|shut) off (?:the )?(?:microphone|mic)"
                    r"|close (?:your |the )?(?:ears|microphone|mic)"
                    r"|(?:you can )?stop listening now)", low):
        return {"command": {"kind": "mic_off"}, "say": None}

    # LOOKING AT THE ACTUAL PICTURE of his screen: the same shape as the
    # microphone, for the same reason. A screenshot cannot be redacted the
    # way window text can, so it is off until he says otherwise and dies
    # on restart. Matched here rather than compiled, because `eyes_on` is
    # PLANNER_FORBIDDEN and a forbidden verb that reaches the planner gets
    # substituted for something else.
    #
    # Only PERMISSION-GRANTING phrasings switch it on. "Look at my screen
    # and tell me what this is" is a QUESTION and must stay one; if that
    # fell through to here, asking would quietly start sending pictures.
    if re.fullmatch(r"(?:(?:you|u) can |(?:you|u) may |i'?ll let (?:you|u) "
                    r"|let (?:you|u) |i'?m letting (?:you|u) )"
                    r"(?:look at|see|read|photograph) (?:my|the) screen"
                    r"(?: (?:for )?(?:a bit|a while|today|now))?"
                    r"|(?:turn|switch) on (?:screen |screenshot )?"
                    r"(?:looking|vision|eyes)"
                    r"|(?:turn|switch) (?:your )?eyes on"
                    r"|allow (?:screenshots|screen looking|screen shots)"
                    r"|open (?:your )?eyes", low):
        return {"command": {"kind": "eyes_on"}, "say": None}

    # Off works from anywhere, always, like the microphone's.
    if re.fullmatch(r"(?:stop|quit) (?:looking at|reading|photographing) "
                    r"(?:my|the) screen"
                    r"|(?:don'?t|do not) look at (?:my|the) screen(?: any ?more)?"
                    r"|no more screenshots"
                    r"|(?:turn|switch) off (?:screen |screenshot )?"
                    r"(?:looking|vision|eyes)"
                    r"|(?:turn|switch) (?:your )?eyes off"
                    r"|close (?:your )?eyes", low):
        return {"command": {"kind": "eyes_off"}, "say": None}

    if re.fullmatch(r"(?:can|are) (?:you|u) (?:able to )?"
                    r"(?:see|look at|looking at) (?:my|the) screen"
                    r"|(?:can|are) (?:you|u) (?:see|seeing) (?:my|the) screen"
                    r"|are (?:your )?eyes on"
                    r"|(?:screen )?(?:looking|vision|eyes) status", low):
        return {"command": {"kind": "eyes"}, "say": None}

    # AND ASKING FOR IT OUT LOUD IS ANSWERED, NOT COMPILED. `mic_on` is
    # PLANNER_FORBIDDEN, and CLAUDE.md is explicit about what happens to
    # a forbidden verb that reaches the planner anyway: it is SUBSTITUTED.
    # "Resume yourself" ran `brief` and reported success while resuming
    # nothing. So this asks for the one thing that does work rather than
    # letting a compiler near it.
    if re.fullmatch(r"(?:start listening|listen to me|open (?:your |the )?"
                    r"(?:ears|microphone|mic)|(?:turn|switch) on (?:the |your )?"
                    r"(?:microphone|mic)|(?:turn|switch) (?:the |your )?"
                    r"(?:microphone|mic) on|keep listening)", low):
        return {"command": None,
                "say": ("The microphone is a button, not something I turn on "
                        "for you. Press MIC in the Command Center and I'll "
                        "start listening.")}

    if re.fullmatch(r"(?:is (?:the |your )?(?:microphone|mic) on"
                    r"|are (?:you|u) listening"
                    r"|(?:microphone|mic) status)", low):
        return {"command": {"kind": "mic"}, "say": None}

    # MUSIC. Transport only, and the difference is said out loud rather
    # than blurred: media keys control what is already queued, and
    # choosing what plays needs his Spotify account.
    m = re.fullmatch(r"(?:play|start|resume) (?:some |the |my )?"
                     r"(?:music|tunes|spotify|something)"
                     r"|(?:play|resume)(?: it)?"
                     r"|(?:pause|stop) (?:the )?(?:music|song|spotify|track)"
                     r"|pause(?: it)?"
                     r"|(?:skip|next)(?: (?:this|the|that))?(?: (?:song|track|one))?"
                     r"|(?:go back|previous)(?: (?:a |one )?(?:song|track))?"
                     r"|(?:play|start) it again", low)
    if m:
        if re.match(r"(?:pause|stop)", low):
            action = "pause"
        elif re.match(r"(?:skip|next)", low):
            action = "next"
        elif re.match(r"(?:go back|previous)", low):
            action = "previous"
        else:
            action = "play"
        return {"command": {"kind": "music", "action": action}, "say": None}

    # NAMING SOMETHING TO PLAY is the half that needs his account, and
    # she says so instead of resuming whatever was paused on Thursday and
    # calling it what he asked for.
    # The signal is not the word "some", it is what follows it: "play
    # some MUSIC" is transport and "put on some JAZZ" is a choice.
    if re.match(r"(?:play|put on)\s+"
                r"(?!(?:some |the |my )?(?:music|tunes|spotify|something)\b"
                r"|it\b|devils?\b|devil's\b)"
                r"[a-z0-9]", low):
        from aletheia import music as _music
        return {"command": None, "say": _music.cannot_choose()}

    # HIS CHATGPT SUBSCRIPTION AS A SECOND WORKER. Granting it is a
    # deliberate act and stopping it is instant, the same asymmetry as
    # every other switch here.
    if re.fullmatch(r"(?:you can )?use (?:my )?chat ?gpt(?: for this| too| as well)?"
                    r"|(?:ask|check with) chat ?gpt (?:too|as well|for a second opinion)"
                    r"|turn on chat ?gpt|enable chat ?gpt", low):
        return {"command": {"kind": "chatgpt_on"}, "say": None}
    if re.fullmatch(r"(?:stop|quit|don'?t) using (?:my )?chat ?gpt"
                    r"|turn off chat ?gpt|disable chat ?gpt"
                    r"|(?:stop|no more) chat ?gpt", low):
        return {"command": {"kind": "chatgpt_off"}, "say": None}
    if re.fullmatch(r"(?:are|r) (?:you|u) using (?:my )?chat ?gpt"
                    r"|chat ?gpt status|(?:can|could) (?:you|u) use "
                    r"(?:my )?chat ?gpt", low):
        return {"command": {"kind": "chatgpt"}, "say": None}

    # DOCUMENTS, SAID THE WAY HE SAYS THEM. `doc_make` was built and had
    # no sentence, so "make me a spreadsheet of my expenses" went to the
    # planner — a capability with no way to ask for it is one he never
    # uses. The FORMAT is the noun he says: spreadsheet/excel -> .xlsx,
    # deck/presentation/powerpoint -> .pptx, anything else -> .docx.
    m = re.match(r"(?:make|write|create|draft|put together|build)\s+"
                 r"(?:me\s+)?(?:a|an|that|this|it)?\s*"
                 r"(spreadsheet|excel(?: file| sheet)?|sheet|"
                 r"deck|presentation|powerpoint|slides|"
                 r"word doc(?:ument)?|doc(?:ument)?|report|memo|write[- ]?up)"
                 r"\b(?:\s+(?:of|about|for|on|covering)\s+(?P<topic>.+))?$",
                 low)
    if m:
        noun = m.group(1)
        if re.match(r"spreadsheet|excel|sheet", noun):
            suffix, kind_word = ".xlsx", "spreadsheet"
        elif re.match(r"deck|presentation|powerpoint|slides", noun):
            suffix, kind_word = ".pptx", "deck"
        else:
            suffix, kind_word = ".docx", "document"
        topic = (m.group("topic") or "").strip()
        # HIS words, said back by HER: "about my resume" out of her mouth
        # means her resume. And a file called my-resume.docx names whose
        # it is rather than what it is.
        spoken_topic = speech.as_she_says_it(topic)
        stem = speech.file_stem(topic)
        # She needs to know WHAT goes in it, and only he knows that. The
        # honest move is to ask for the contents rather than invent them —
        # a spreadsheet of made-up expenses is worse than no spreadsheet.
        return {"command": None,
                "say": (f"I can make that {kind_word}"
                        + (f" about {spoken_topic}" if spoken_topic else "")
                        + f". Tell me what goes in it and I'll save it as "
                        + (f"{stem}{suffix}" if stem else f"a {suffix} file")
                        + ".")}

    # THE AGENT RUNTIME, said the way a person would say it. He should
    # never have to type `spawn --agent=research --provider=claude`.
    if re.fullmatch(r"(?:what (?:are|r) (?:your|the|my) (?:workers?|agents?) "
                    r"(?:doing|up to|working on)(?: right now)?"
                    r"|who(?:'s| is) working(?: on what)?"
                    r"|(?:list|show me) (?:your|the|my) (?:workers?|agents?)"
                    r"|(?:your|the|my) (?:workers?|agents?))", low):
        return {"command": {"kind": "agents"}, "say": None}

    # Stopping is never gated, for the same reason `halt` is not.
    if re.fullmatch(r"(?:pause|stop) (?:all )?(?:autonomous work|"
                    r"(?:the |your |my )?(?:workers?|agents?))"
                    r"|stop everyone|(?:pause|stop) all (?:the )?(?:workers?|agents?)",
                    low):
        return {"command": {"kind": "agents_pause"}, "say": None}

    m = re.fullmatch(r"(?:kill|stop|cancel|retire) (?:the |my )?(.+?)"
                     r"(?: agent| worker)", low)
    if m:
        return {"command": {"kind": "agent_stop", "which": m.group(1).strip()},
                "say": None}

    # "Make somebody responsible for Barkly."
    m = re.fullmatch(r"(?:make|create|assign) (?:somebody|someone|a worker|"
                     r"an agent|a permanent agent) (?:responsible )?"
                     r"(?:for|to) (.+)", low)
    if m:
        subject = m.group(1).strip()
        return {"command": {"kind": "agent_new",
                            "name": f"{subject} agent",
                            "project": subject.split()[0][:80],
                            "mission": f"own {subject} — know its state, "
                                       f"keep its objectives, and bring me work",
                            "agent_type": "project"}, "say": None}

    # "Text Brant that I'm on my way." Thirteen asks in the demand ledger
    # and no verb behind any of them: the planner named `intercom.relay`
    # as the nearest gap and compiled a sandboxed program, which has no
    # network and cannot text anyone.
    #
    # BEFORE the email pattern, because "text" and "message" are their own
    # verbs and must not fall into it. The body is required: "text Brant"
    # with nothing to say is a question, not a message, and it falls
    # through to the planner to ask what he wants said.
    m = re.match(r"(?:send (?:a )?(?:text|message)(?: to)?|text|message)\s+"
                 r"(.+?)\s+(?:that|saying|and say|telling (?:him|her|them)|:)"
                 r"\s+(.+)", low)
    if m:
        return {"command": {"kind": "message_send", "to": m.group(1).strip(),
                            "body": m.group(2).strip()}, "say": None}

    m = re.match(r"e?mail\s+(.+?)\s+(?:that|saying|and say|:)\s+(.+)", low)
    if m:
        return {"command": {"kind": "email_draft", "to": m.group(1).strip(),
                            "body": m.group(2).strip()}, "say": None}

    # BEFORE the browse pattern: "look into X" and "look at example.com" both
    # start with "look", and the browse branch would swallow the first, then
    # complain it heard no web address.
    m = re.match(r"(?:look into|research|find out(?: about)?|dig into|"
                 r"look up|what do you know about|tell me about)\s+(.+)", low)
    if m:
        question = m.group(1).strip(" ?.")
        if len(question) > 2:
            return {"command": {"kind": "research", "question": question},
                    "say": None}   # the receipt speaks, not a canned line

    # A URL, or nothing — this branch used to answer "I need a web address
    # to read" to anything else, including "read my resume", which is a
    # FILE she can genuinely read (document.read_any is AVAILABLE) and one
    # of the sentences he is most likely to say. Dead-ending a real
    # capability behind a wrong assumption is worse than being slow: the
    # planner can compose a file read, and "read my resume and tell me
    # what I'm bad at" needs it to.
    m = re.match(r"(?:read|open|check|look at|go to|browse)\s+(.+)", low)
    if m:
        url = _spoken_url(m.group(1))
        if url:
            return {"command": {"kind": "browse_read", "url": url}, "say": None}


    m = re.match(r"screenshot\s+(.+)", low)
    if m and _spoken_url(m.group(1)):
        return {"command": {"kind": "browse_shot", "url": _spoken_url(m.group(1))},
                "say": None}

    # His OWN screen. The browse_shot branch above runs first and only
    # fires when the words resolve to a URL, so "screenshot example.com"
    # never reaches this. Everything here is imperative: "did you take a
    # screenshot" is a question, and a question is never an instruction.
    _SCREEN_WORDS = r"(?:screens?|desktop|monitors?|display)"
    m = re.match(
        r"(?:please\s+)?(?:take|grab|get|capture|make|snap)\s+"
        r"(?:me\s+)?(?:a|an|another)?\s*"
        r"(?:screen\s?shot|screen\s?grab"
        r"|(?:picture|photo|shot|capture)\s+of\s+(?:my|the|this)\s+" + _SCREEN_WORDS + r")"
        r"(?:\s+of\s+(?:my|the|this)\s+" + _SCREEN_WORDS + r")?\s*$", low)
    if not m:
        # the bare noun, and "screenshot my screen"
        m = re.match(r"screen\s?shot(?:\s+(?:of\s+)?(?:my|the|this)\s+"
                     + _SCREEN_WORDS + r")?\s*$", low)
    if not m:
        # "capture my screen" / "photograph the desktop" - the verb takes
        # the screen directly, with no "of" to hang the earlier branch on.
        m = re.match(r"(?:please\s+)?(?:capture|photograph|snap)\s+"
                     r"(?:my|the|this)\s+" + _SCREEN_WORDS + r"\s*$", low)
    if m:
        # "all my screens" means the whole virtual desktop; anything else
        # means the one he is looking at.
        monitor = "all" if re.search(r"\ball\b", low) else "active"
        return {"command": {"kind": "screenshot", "monitor": monitor},
                "say": None}

    # "all my screens" / "both monitors" said as the whole sentence
    m = re.match(r"(?:please\s+)?(?:take|grab|get|capture)\s+"
                 r"(?:a\s+)?(?:screen\s?shot|picture)\s+of\s+"
                 r"(?:all|both)\s+(?:my\s+|the\s+)?" + _SCREEN_WORDS + r"\s*$", low)
    if m:
        return {"command": {"kind": "screenshot", "monitor": "all"}, "say": None}

    m = re.match(r"(?:approve|approved|yes to)\s*"
                 r"(?:that|it|the pending one|the (?P<ord>first|second|third|last)"
                 r"(?: one)?|(?P<what>.+?))?$", low)
    if m:
        pending = [a for a in policy.all_approvals() if a["state"] == "PENDING"]
        if not pending:
            return {"command": None, "say": "Nothing is waiting for approval."}
        if len(pending) == 1:
            return _approve_by_voice(pending[0])
        chosen = _pick_approval(pending, m.group("ord"), m.group("what"))
        if chosen is not None:
            return _approve_by_voice(chosen)
        # More than one is now the ORDINARY case — an intent, a mail draft
        # and a meeting can all be waiting at once. Refusing to guess is
        # right; sending him to a browser is not. Read them out so he can
        # say which, in the same breath.
        return {"command": None, "say": _offer_choice(pending)}
    # THE WORDS HE ACTUALLY USES TO SAY NO. This was "deny/denied/no to"
    # only, so "cancel that" and "never mind" fell to the planner — which
    # is forbidden from emitting `deny` and therefore compiled something
    # else and offered THAT for approval: "1 step ready — Cancel the
    # pending approval waiting on his decision. Say approve to run it."
    # Asking for an approval in order to cancel an approval.
    #
    # Each is anchored to the whole sentence, so "cancel my gym
    # membership" is untouched and still reaches the capability that
    # really cancels things.
    asked_to_cancel = re.match(
        r"(?:deny|denied|no to|cancel|scrap|drop)"
        r"(?:\s+(?:that|it|the pending one))?$", low)
    # DROPPING THE SUBJECT, which is not the same sentence. Both deny a
    # pending thing when there is one; they differ only when there is
    # nothing to cancel, and there "Nothing is waiting for approval" is a
    # report on a queue he did not ask about.
    dropped_it = re.match(
        r"(?:never ?mind|forget (?:it|that)|call it off|"
        r"don'?t do (?:it|that))$", low)
    m = asked_to_cancel or dropped_it
    if m:
        pending = [a for a in policy.all_approvals() if a["state"] == "PENDING"]
        if len(pending) == 1:
            return {"command": {"kind": "deny", "id": pending[0]["id"],
                                "because": "denied by voice"}, "say": None}
        if not pending:
            # BOTH things are true and he needs both. A bare "Okay."
            # leaves him believing he just cancelled something, and a bare
            # "Nothing is waiting for approval" answers a question he did
            # not ask. So: acknowledge the dismissal, and say the state.
            return {"command": None,
                    "say": ("Okay - nothing was waiting." if dropped_it
                            else "Nothing is waiting for approval.")}
        # Read them out, the way `approve` does. "Use the Command Center"
        # is an instruction to go somewhere else, said to someone who is
        # standing in a room talking.
        return {"command": None, "say": _offer_choice(pending, verb="deny")}

    # "Thanks" is not a question and has no store behind it, so it does
    # not belong in `quick` — but it went to the PLANNER, which is 25-80
    # seconds on this machine to be told you're welcome. It is the same
    # shape as "never mind" above: a turn that ends politely and asks for
    # nothing. Whole sentence only, so "thanks for the reminder, remind me
    # again at six" is still a reminder.
    if re.fullmatch(r"(?:thanks|thank you|thanks a lot|thanks so much|"
                    r"thank you very much|ty|cheers|appreciate it|"
                    r"thanks thea|thank you thea)", low):
        return {"command": None, "say": "Any time."}

    m = re.match(r"(?:add a task|new task|task)\s*(?:to|:)?\s+(.+)", low)
    if m:
        desc, deadline = _split_deadline(m.group(1).strip())
        slug = re.sub(r"[^a-z0-9]+", "-", desc.lower()).strip("-")[:40] or "voice-task"
        if any(t["id"] == slug for t in tasks.all_tasks()):
            slug = f"{slug}-2"
        command = {"kind": "task_new", "id": slug, "description": desc}
        if deadline:
            command["deadline"] = deadline
        return {"command": command, "say": None}

    # LONGEST ALTERNATIVE FIRST. Python's alternation takes the first that
    # matches, so "note" won and the note read "that Dana called".
    m = re.match(r"(?:note that|note|write down that|write down|log)\s+(.+)", low)
    if m:
        return {"command": {"kind": "note", "text": m.group(1).strip()}, "say": None}

    # Unrecognized by the patterns above — which is not the same as
    # unrecognizable. Until 2026-08-27 this branch journaled the sentence
    # and said "I don't have a command for that yet", and the operator's own
    # journal is full of the result: every real ask he made that did not
    # match a regex died here. It now goes to the reasoning provider as an
    # `intent`, which compiles it into steps expressed in these same kinds
    # and gates every one of them (§104 is satisfied by the gates, not by
    # refusing to think). If no provider is available, `intent` degrades to
    # exactly the honest answer this branch used to give.
    return {"command": {"kind": "intent", "text": text}, "say": None}


#: One definition, in `speech`, because `intercom` resolves tasks with the
#: same table and two copies drift. Kept under this name so every existing
#: reference here still reads the way it did.
ORDINALS = speech.ORDINALS


def approval_label(approval: dict) -> str:
    """What this approval is, in words he would recognise."""
    from aletheia import speech
    action = str(approval.get("requested_action", ""))
    capability = str(approval.get("capability", ""))
    if capability == "email.send" or action.startswith("email.send"):
        # The recipient is the thing he needs, and it is in the reason
        # rather than the summary.
        reason = str(approval.get("reason", ""))
        who = re.search(r"\bto ([A-Za-z][^.]*?)\s*(?:$|\.)", reason)
        return f"the email{' to ' + who.group(1) if who else ''}"
    if capability == "errand.run":
        return speech.tidy(speech.strip_ids(action)) or "the errand"
    if capability == "agent.delegate" or action.startswith("delegate"):
        return "the work order"

    # WHAT WILL HAPPEN beats both the reason and a category. The
    # consequence is the plan's own summary of what it will do, which is
    # the thing he is deciding about; the reason on an intent approval is
    # `operator said: "spoken to the wall: thea remember that my landlord
    # is called Mr Okafor"` — a quote inside a quote inside a transport
    # label, truncated mid-word when it is read out.
    #
    # This check used to sit BELOW `if capability == "intent.execute":
    # return "the plan"`, so every world-touching plan was labelled "the
    # plan" while the routine ones got a real description. He heard "2
    # things waiting: the plan and Remember that landlord is Mr Okafor" —
    # the consequential one was the nameless one.
    said = speech.tidy(speech.strip_ids(str(approval.get("consequence", ""))))
    if said and said.lower() not in ("see the plan", "unknown"):
        return said[:80]
    if capability == "calendar.write" or action.startswith("calendar.write"):
        return "the calendar booking"
    if capability.startswith("intent.execute"):
        return "the plan"
    reason = speech.tidy(speech.strip_ids(_unwrap(str(approval.get("reason", "")))))
    if reason:
        return reason[:80]
    return speech.tidy(speech.strip_ids(action))[:60] or "the pending one"


# The room microphone is an INPUT device, not an authentication device
# (found by a security review, 2026-09-03). This module already refused to
# widen standing authority by voice — a television, a guest or a passing
# sentence could say it — and then, forty lines later, accepted "approve"
# for whatever happened to be pending. If the pending item was an email
# send or a live errand, the microphone WAS the authorization device.
#
# Voice keeps everything that is safe to say out loud: asking, planning,
# drafting, reading, and above all HALT. What it may no longer do is
# authorize an action the registry calls high-risk or operator_always —
# spending, sending, binding agreements, disclosures, destructive changes
# (§56 L4). Those want a decision from him at a keyboard or a trusted
# device, which is the same standard `standing` already applies.
VOICE_MAY_NOT_APPROVE = "high"


def approvable_by_voice(approval: dict) -> tuple[bool, str]:
    """(may voice decide this, why not). Unknown capability fails CLOSED:
    an approval whose risk cannot be read is not one to take off the air."""
    capability = (approval or {}).get("capability")
    if not capability:
        return False, ("it does not name the capability it authorizes, so I "
                       "cannot tell how risky it is")
    try:
        entry = capabilities.get(capability)
    except Exception:
        return False, f"I cannot read the risk of {capability} right now"
    if entry.get("approval_policy") == "operator_always":
        return False, f"{capability} always needs you, not the room"
    if entry.get("risk_class") == VOICE_MAY_NOT_APPROVE:
        return False, f"{capability} is high-risk"
    return True, ""


def _approve_by_voice(approval: dict):
    ok, why = approvable_by_voice(approval)
    if ok:
        return {"command": {"kind": "approve", "id": approval["id"]}, "say": None}
    return {"command": None,
            "say": (f"I won't approve that one by voice — {why}. Anything in "
                    f"the room could say it. Decide it at the keyboard: "
                    f"python -m aletheia.policy decide {approval['id']} APPROVED")}


def _pick_approval(pending: list[dict], ordinal: str | None,
                   phrase: str | None) -> dict | None:
    """Resolve 'the first' / 'the email one' to exactly one approval, or None.

    Ambiguity returns None so the caller asks again. Never a best guess:
    approving the wrong thing is the one mistake an approval exists to stop.
    """
    if ordinal:
        try:
            return pending[ORDINALS[ordinal]]
        except (KeyError, IndexError):
            return None
    words = (phrase or "").strip()
    if not words:
        return None
    words = re.sub(r"^(the|that)\s+", "", words)
    words = re.sub(r"\s+one$", "", words).strip()
    if not words:
        return None
    matches = [a for a in pending if words in approval_label(a).lower()]
    return matches[0] if len(matches) == 1 else None


# How a quote reaches an approval's `reason`: the surface labels it, then
# `intents` wraps it again. Both are true and neither is speech.
_WRAPPERS = re.compile(
    r'^\s*operator said:\s*"?|^\s*(?:spoken to the wall|typed into the '
    r'command center|relayed by chatgpt):\s*|^\s*thea[,: ]\s*|"\s*$',
    re.I)


def _unwrap(reason: str) -> str:
    """Peel the transport labels off his actual words."""
    said = str(reason or "").strip()
    for _ in range(4):
        shorter = _WRAPPERS.sub("", said).strip()
        if shorter == said:
            break
        said = shorter
    return said


def _offer_choice(pending: list[dict], verb: str = "approve") -> str:
    """Read out what is waiting, and ask which one — in HIS verb.

    Answering "never mind" with "say approve the first" is telling him to
    do the opposite of what he just asked for.
    """
    from aletheia import speech
    labels = [approval_label(a) for a in pending[:4]]
    more = "" if len(pending) <= 4 else f", and {len(pending) - 4} more"
    return (f"{speech.count_phrase(len(pending), 'thing')} waiting: "
            + speech.and_list(labels) + more
            + f". Which one — say {verb} the first, or name it.")


def spoken_reply(kind: str, outcome: str, detail: str) -> str:
    """Turn a run_command result into one speakable sentence.

    The receipts these come from are written for a log, not a room. See
    aletheia/speech.py for why a hex id read aloud is the worst version of
    §145 — he cannot hold it in his head, and the sentence after it asks
    him to say it back.
    """
    if outcome == "halted":
        return "I'm halted — only resume works."
    from aletheia import speech as _speech
    if outcome in ("refused", "invalid"):
        return f"I can't do that: {_speech.plainly(detail)}"
    if outcome == "error":
        # "That failed: KeyError: "no place matches 'the airport'"" — the
        # message underneath was fine and arrived with a class name bolted
        # to the front. Same stripper as `intents.spoken` uses, so the two
        # paths cannot drift.
        return f"That failed: {_speech.plainly(detail)}"
    if kind == "halt":
        return "Halted. Nothing acts until you say resume."
    if kind == "resume":
        return "Resumed."
    if kind == "browse_read":
        # detail is "read <url> — <title> :: <excerpt>" — speak title + excerpt
        return detail.split("read ", 1)[-1].replace(" :: ", ". ", 1)
    from aletheia import speech
    return speech.spoken_receipt(kind, detail)
