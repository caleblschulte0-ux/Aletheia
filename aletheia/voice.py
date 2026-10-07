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

import datetime as dt
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
    # "ACTUALLY cancel that" went to the planner while "cancel that" was
    # instant: the correction words a person leads with carry no request.
    r"i mean|like|actually|oh|oops|sorry)\b[,\s]*)*",
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
    # AN ADDRESS FOLLOWED BY AN OBJECTIVE IS NOT AN ADDRESS. Everything below
    # joins the whole tail into one string, because that is how "example dot
    # com" is said out loud - and that made "go to https://books.toscrape.com
    # and tell me the title of the first book" into
    # `https://books.toscrape.comandtellmethetitleofthefirstbook`, which she
    # tried to load and reported back as "the address did not resolve"
    # (measured live, acceptance D, 2026-09-18). A goal attached to a page is
    # a web task; letting the planner have it is the whole point of returning
    # None here. The joining still happens when the FIRST word is not already
    # an address, so a spoken host ("my site dot com") is unchanged.
    first, _, rest = t.partition(" ")
    if rest.strip() and _one_address(first):
        return None
    return _one_address(t.replace(" ", ""))


def _one_address(t: str) -> str | None:
    """One token that is already an address, or None. No joining, no guessing."""
    if not t or "." not in t:
        return None
    if t.startswith(("http://", "https://")):
        return t
    host = t.split("/", 1)[0].split(":", 1)[0].split("?", 1)[0]
    if "." not in host or host.rsplit(".", 1)[-1] not in TLDS:
        return None
    return "https://" + t


_AMOUNT_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                 "eight": 8, "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30,
                 "forty": 40, "forty five": 45, "sixty": 60, "an": 1, "a": 1, "half an": 0.5}


def _spoken_amount(raw: str) -> float | None:
    """"ten", "10", "an", "half an" - the number a timer or a reminder was
    given, or None when it is not one."""
    raw = " ".join(str(raw or "").lower().split())
    if raw.isdigit():
        return float(raw)
    return _AMOUNT_WORDS.get(raw)


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
    from aletheia import localtime
    today = localtime.today()
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
        pass
    return _spoken_date(t, today)


# A DATE SAID THE WAY PEOPLE SAY ONE. "Remind me on the 15th to pay rent"
# and "on october 20 to renew my tags" matched no reminder pattern, fell to
# the planner, and the first one was refused as SPENDING because it
# contains "pay" (2026-10-07). The month names and their short forms, and
# a day with or without its ordinal ending.
MONTHS = ("january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december")
_MONTH = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
          r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_NTH = r"(?:[12]?\d|3[01])(?:st|nd|rd|th)?"
#: "the 15th", "october 20", "oct 20th", "the 20th of october".
SPOKEN_DATE = (r"(?:the " + _NTH + r"(?: of " + _MONTH + r")?|" + _MONTH + r" (?:the )?" + _NTH
               + r"|" + _NTH + r" of " + _MONTH + r")")


def _spoken_date(text: str, today=None) -> str | None:
    """'the 15th' / 'october 20' / '20th of october' -> the NEXT such date.

    A day with no month is this month's, or next month's once it has
    passed; a month and day is this year's, or next year's once it has
    passed. A date that does not exist (the 31st of a 30-day month) is
    None, never quietly moved to a neighbouring day.
    """
    import datetime as dt
    today = today or dt.date.today()
    t = re.sub(r"^(?:on )", "", str(text or "").strip().lower())
    m = re.fullmatch(r"(?:the )?(\d{1,2})(?:st|nd|rd|th)?(?: of (" + _MONTH + r"))?", t)
    if not m:
        m2 = re.fullmatch(r"(" + _MONTH + r") (?:the )?(\d{1,2})(?:st|nd|rd|th)?", t)
        if not m2:
            return None
        month_word, day = m2.group(1), int(m2.group(2))
    else:
        day, month_word = int(m.group(1)), m.group(2)
    if month_word:
        month = next(i for i, name in enumerate(MONTHS, 1) if name.startswith(month_word[:3]))
        for year in (today.year, today.year + 1):
            try:
                d = dt.date(year, month, day)
            except ValueError:
                return None
            if d >= today:
                return d.isoformat()
        return None
    year, month = today.year, today.month
    for _ in range(2):
        try:
            d = dt.date(year, month, day)
        except ValueError:
            d = None
        if d and d >= today:
            return d.isoformat()
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
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
        # "Call the plumber tomorrow", "pay the gas bill on friday": a day
        # said last is as much a deadline as "by friday" (2026-10-07).
        bare = re.search(r"^(\S+\s.*?)\s+(?:on |this )?(today|tonight|tomorrow|monday|tuesday|wednesday"
                         r"|thursday|friday|saturday|sunday)$", text, re.IGNORECASE)
        if bare:
            day = _spoken_day("today" if bare.group(2).lower() == "tonight" else bare.group(2))
            if day:
                return bare.group(1).strip(), day
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
    from aletheia import localtime
    today = localtime.today()
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
    """"What's going on?", answered the way a person answers it.

    It read the dashboard out loud: **"1 fleet alert. 0 live tasks."**
    Three things wrong in six words. Nobody says zero of anything — an
    absent thing is not news, it is the absence of news. "Fleet alert" is
    a word off a screen he is not looking at. And neither half answers
    what he asked, which is what is HAPPENING, not how many rows are in
    two tables.

    So: what she is doing, then what is waiting on him, then the honest
    "nothing" when that is really the answer. A count survives only where
    it is the fact ("two tasks running"), never as a tally of nothing.
    """
    from aletheia import quick, speech
    from aletheia.core import status_payload  # late import; core imports us too
    s = status_payload()
    if s["halted"]:
        return "I'm halted — nothing acts until you say resume."
    parts = [quick.doing_words()]
    pending = s["approvals_pending"]
    if pending and "waiting on you" not in parts[0]:
        parts.append(f"{speech.count_phrase(len(pending), 'thing')} needs your "
                     "yes — approve it on your phone or at the keyboard; the "
                     "routine ones I can take by voice.")
    live = s["tasks"]["live"]
    if live:
        parts.append(f"{speech.count_phrase(live, 'task')} still running.")
    alerts = s["pulse"].get("alerts")
    if alerts:
        parts.append(f"{speech.count_phrase(alerts, 'thing')} in your "
                     f"repositories {'needs' if int(alerts) == 1 else 'need'} looking at.")
    return " ".join(parts)


# Ported from ChatGPT PR #75 (2026-09-01) after review; the rest of that
# branch is superseded by #76's durable delivery. "What needs my
# attention?" is the question most worth answering INSTANTLY: routing it
# through the planner cost ~90 seconds and a model call to read queues
# that are already durable local state. Deterministic is also more honest
# here — it reports what the stores contain, with nothing to invent.
def _attention_say() -> str:
    """"What needs my attention" — the SAME answer as "what's waiting on me".

    These were two questions with two implementations reading two
    different sets of stores, and they disagreed: this one counted rows
    ("1 approval waiting on you. 2 blocked tasks. 3 unread
    notifications.") while the other named the thing. Two answers to one
    question is how he learns to ask both and trust neither.

    `quick._waiting` reads the one needs-you list, so there is one
    implementation of "is anything sitting on me" and a row can only be
    missing from both places or neither.
    """
    from aletheia import quick
    return quick._waiting()


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
                           "cell", "mobile", "e-mail", "telephone",
                           # "what's my ip address" searched his contacts for
                           # somebody called "my ip" (2026-09-22)
                           "ip", "mac"})


#: "Call it a day", "call it off", "call the shots" are idioms, not people,
#: and "call me" is him talking about himself. A name to ring is one or two
#: plain words that are not an idiom's tail.
_NOT_SOMEBODY = frozenset({"me", "it", "this", "that", "them", "him", "her", "us",
                           "you", "back", "again", "later", "off", "out", "in",
                           "round", "over", "up", "the", "a", "an"})
_NOT_A_CALL = ("it a day", "it quits", "it off", "it even", "the shots",
               "the police on", "a meeting", "a vote", "a halt", "time on", "dibs")


def _is_a_person_to_ring(captured: str) -> bool:
    """Is the thing after "call" somebody he could actually ring?"""
    text = " ".join(str(captured or "").split()).casefold()
    text = re.sub(r"^(?:the|my|a|an) ", "", text)
    if not text or any(text.startswith(tail) for tail in _NOT_A_CALL):
        return False
    words = text.split()
    if len(words) > 3 or words[0] in _NOT_SOMEBODY:
        return False
    # "Call the whole thing off" ends on a particle, and a particle is
    # what makes the verb mean something other than the telephone.
    if len(words) > 1 and words[-1] in _NOT_SOMEBODY:
        return False
    # "call the plumber" is a person; "call the meeting" and "call the list"
    # are her own nouns, and every one of those has a verb of its own here.
    return not any(word in {"task", "tasks", "reminder", "reminders", "note", "notes",
                            "list", "meeting", "vote", "shots", "day", "quits", "time"}
                   for word in words)


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


#: Words that mean a place on his disk. "what's in my downloads" is a
#: file question; "what's in my calendar" is not, and the difference is a
#: named list rather than a guess at everything he might say. A pattern
#: that swallows too much answers a DIFFERENT question, which is the
#: failure he cannot detect.
_HIS_PLACES = {
    "downloads": "Downloads", "download": "Downloads",
    "documents": "Documents", "document": "Documents", "docs": "Documents",
    "desktop": "Desktop", "pictures": "Pictures", "photos": "Pictures",
    "picture": "Pictures", "images": "Pictures",
}


def _a_place_she_knows(said: str) -> str:
    """The folder he named, if he named a folder rather than a store."""
    return _HIS_PLACES.get(" ".join(str(said or "").casefold().split()), "")


#: Things "find my ..." can mean that are NOT a file, every one of which
#: already has a better answer somewhere else. "Find my keys" is not a
#: file search, and "do I have any reminders" is a store she reads.
_NOT_A_FILE = frozenset({
    "keys", "phone", "wallet", "car", "glasses", "charger", "money",
    "email", "emails", "inbox", "mail", "messages", "texts",
    "calendar", "schedule", "appointment", "appointments", "meeting",
    "meetings", "reminder", "reminders", "task", "tasks", "todo", "to do",
    "contact", "contacts", "number", "phone number", "address",
    "subscription", "subscriptions", "balance", "account", "accounts",
    "notification", "notifications", "shopping list", "list", "time",
})


def _where_he_lives() -> str:
    """His city, from what he has said and his resume; never a guess."""
    try:
        from aletheia import memory, profile
        address = memory.recall("identity", "address")
        if address:
            return f"Your address on file is {address}."
        known = profile.known()
        city = str(known.get("city") or memory.recall("identity", "home_city") or "").strip()
        state = str(known.get("state") or "").strip()
        if city:
            return f"You live in {city}" + (f", {state}" if state and state.casefold() not in city.casefold() else "") \
                + ", as far as I know. Tell me your address if you want me to have it."
    except Exception:  # noqa: BLE001
        pass
    return "I don't have your address or city on file. Tell me and I'll remember it."


def _spell_his_name(which: str) -> str:
    try:
        from aletheia import profile
        known = profile.known()
    except Exception:  # noqa: BLE001
        known = {}
    first = str(known.get("first_name") or "").strip()
    last = str(known.get("last_name") or "").strip()
    parts = ([first] if which == "first" else [last] if which in ("last", "sur") else [first, last])
    parts = [p for p in parts if p]
    if not parts:
        return "I don't have your name on file. Tell me and I'll remember it."
    return "; ".join(f"{p}: " + "-".join(ch.upper() for ch in p if ch.isalpha()) for p in parts) + "."


def _not_a_file(said: str) -> bool:
    """True when "find my X" is not about a file at all."""
    low = " ".join(str(said or "").casefold().split())
    if not low:
        return True
    # "Where do I live": a question with a verb in it is not a filename.
    if re.match(r"(?:do|does|did|am|is|are|can|could|should|will|was|were) (?:i|we|you|u)\b", low):
        return True
    if low in _NOT_A_FILE:
        return True
    # "Find ME a plumber near me": a person or a service, never a file.
    if re.match(r"(?:me|us) (?:a|an|some)\b", low) or re.search(r"\b(?:near me|nearby|around here|in town)\b", low) \
            or re.match(r"(?:the )?(?:nearest|closest)\b", low):
        return True
    # "Find me customer success jobs in Denver" is a job search, whatever
    # else the sentence says (2026-09-22: it read Desktop and Downloads).
    if re.search(r"\b(?:jobs?|openings|positions|roles|vacancies|careers|hiring)\b", low):
        return True
    # "Where are you with Barkly", "where are we on the promo video": a
    # question about how far some work has got, never a lost file.
    if re.match(r"(?:you|u|we|things|it) (?:at )?(?:with|on)\b|(?:you|u|we) at\b", low):
        return True
    # "any unread emails", "my next meeting" — the store word anywhere in
    # a short phrase is enough, because none of those are filenames.
    words = low.split()
    return len(words) <= 4 and any(w in _NOT_A_FILE for w in words)


#: What "add X to the shopping list" looks like, so a follow-up can ask
#: whether that is what just happened. One definition, used by the
#: pattern itself and by the continuation below it.
_SHOPPING_ADD = re.compile(
    r"(?:add|put|get|stick|throw) (.+?) (?:on|to) (?:the |my )?"
    r"(?:shopping |grocery )?list$")


#: The continuation itself, so a RUN of them can be recognised. "Add milk
#: to the shopping list / add bread too / and eggs" is one act said three
#: ways, and checking only the immediately previous turn broke the chain
#: after the first: "and eggs" follows a continuation, not a full
#: sentence, and went back to costing four seconds and an approval.
#
# It has to carry a MARKER — a leading "and"/"also", or a trailing
# "too"/"as well". Written without one it matched "add a task to call the
# plumber" as a continuation, so the walk stepped straight over a change
# of subject and back to the groceries behind it. The live run happened
# to survive that because an unrelated turn sat in between; the unit test
# did not, which is the whole argument for having both.
_ALSO = re.compile(r"(?:and |also )add (.+)"
                   r"|add (.+?)(?: too| as well| also)"
                   r"|(?:and|also) (.+)")


def _also_item(said: str) -> str:
    """The thing named by a continuation, or "".

    ONE definition, matched the same way in both places it is used —
    deciding whether the PREVIOUS turn was part of a run, and reading the
    item out of THIS one. Writing the second without the marker requirement
    put "a task to call the plumber" on the shopping list, because a bare
    "add X" inside a run swallowed a change of subject whole.
    """
    m = _ALSO.fullmatch(str(said or "").strip())
    if not m:
        return ""
    return (m.group(1) or m.group(2) or m.group(3) or "").strip()

#: How far back a run may reach. Small on purpose: this resolves "too",
#: which means the thing just said, not the thing said before lunch.
_SHOPPING_RUN = 4


def _on_the_shopping_list(item: str) -> bool:
    """Is that actually on his shopping list right now?

    Asked instead of guessed. "Got the milk" and "I got the job" are the
    same sentence, and only the store can tell them apart — so a removal
    that reads a store beats a pattern that reads a verb.

    Never raises: an unreadable list means the sentence goes to the
    planner, which is what it did before.
    """
    needle = " ".join(str(item or "").casefold().split())
    if not needle:
        return False
    try:
        from aletheia import intercom
        rows = intercom._shopping_items()
    except Exception:
        return False
    for row in rows or []:
        need = " ".join(str(row.get("need") or row.get("id") or "")
                        .casefold().split())
        if need and (need == needle or needle in need or need in needle):
            return True
    return False


def _just_added_to_the_list() -> bool:
    """Is he in the middle of putting things on the shopping list?

    Walks BACK through the thread: a full "add X to the shopping list"
    means yes, another continuation means keep looking, and anything else
    at all means no — which is what stops "add a task to call the plumber"
    followed by "add cheese too" from quietly becoming groceries.

    Read from the conversation thread, which every spoken turn goes
    through, including the fast ones — the whole reason it was moved out
    of `converse`. Matched against HIS sentence rather than HER answer:
    her wording is exactly the sort of thing that gets improved, and a
    pattern anchored to it drifts silently the moment it does.

    Never raises. No thread means the follow-up goes to the planner,
    which is what it did before.
    """
    try:
        from aletheia import converse
        turns = converse.recent(limit=_SHOPPING_RUN)
    except Exception:
        return False
    for turn in reversed(turns or []):
        said = _without_preamble(
            str(turn.get("he_asked") or "").casefold()).strip()
        if _SHOPPING_ADD.match(said):
            return True
        if _also_item(said):
            continue
        return False
    return False


#: A when said as part of a day, and the clock time a person means by it.
#: "Tonight" is nine, as `night` already is; lunch is noon; "before bed"
#: half past nine; the end of the day five.
_LOOSE_TIMES = {
    "this morning": "09:00", "this afternoon": "14:00", "this evening": "19:00", "tonight": "21:00",
    "later tonight": "21:00", "at lunch": "12:00", "at lunchtime": "12:00", "at lunch time": "12:00",
    "before bed": "21:30", "at bedtime": "21:30", "at bed time": "21:30", "before i go to bed": "21:30",
    "at the end of the day": "17:00", "end of day": "17:00", "at end of day": "17:00", "after work": "17:30",
    "in the morning": "09:00", "first thing in the morning": "08:00", "first thing tomorrow": "08:00",
}
_LOOSE_WHEN = (r"(?P<when>" + "|".join(sorted((re.escape(k) for k in _LOOSE_TIMES), key=len, reverse=True))
               + r"|in (?:a|one|\d+|two|three|four|five|six|seven|a couple of|a few) (?:days?|weeks?)"
               + r"|next week|in a fortnight)")


def _a_loose_when(low: str, text: str, now=None) -> dict | None:
    """"Remind me tonight to take out the trash", "remind me to follow up
    in 3 days", "remind me next week to call Bob" - all went to the planner
    (2026-10-07). Either word order. A time that has already passed today
    moves to tomorrow, and the receipt names the day, so a wrong guess is
    caught in one syllable."""
    import datetime as dt
    from aletheia import localtime
    m = (re.fullmatch(r"remind me " + _LOOSE_WHEN + r",? (?:to|that|about) (?P<text>.+)", low)
         or re.fullmatch(r"remind me (?:to|that|about) (?P<text>.+?),? " + _LOOSE_WHEN, low))
    if not m:
        return None
    when, what = m.group("when"), m.group("text").strip()
    if re.search(r"\b(?:every|each)\b", what):
        return None
    now = now or dt.datetime.now(localtime.operator_tz())
    if when in _LOOSE_TIMES:
        hour, minute = map(int, _LOOSE_TIMES[when].split(":"))
        at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if "tonight" in when and at <= now and now.hour < 23:
            # Said at ten at night, "tonight" still means tonight: an hour on.
            at = (now + dt.timedelta(hours=1)).replace(second=0, microsecond=0)
        elif at <= now or (when.endswith("morning") and when != "this morning" and now.hour >= 5) \
                or when == "first thing tomorrow":
            at += dt.timedelta(days=1)
    else:
        hour, minute = map(int, DEFAULT_REMINDER_TIME.split(":"))
        if when == "next week":
            days = 7 - now.weekday()                    # next Monday
        elif when == "in a fortnight":
            days = 14
        else:
            n = re.search(r"in (a couple of|a few|\S+) (day|week)", when)
            count = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                     "a couple of": 2, "a few": 3}.get(n.group(1), None)
            if count is None:
                count = int(n.group(1)) if n.group(1).isdigit() else None
            if not count:
                return None
            days = count * (7 if n.group(2) == "week" else 1)
        at = (now + dt.timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return {"command": {"kind": "remind_at", "at": at.isoformat(), "text": _as_he_said(text, what)}, "say": None}
#: People named by who they are to him, not by name.
_RELATIONS = {"mom", "mum", "mother", "dad", "father", "wife", "husband", "sister", "brother", "grandma",
              "grandpa", "son", "daughter", "boss", "girlfriend", "boyfriend", "partner", "roommate"}
_ORDINAL_DAYS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
                 "eighth": 8, "ninth": 9, "tenth": 10, "fifteenth": 15, "twentieth": 20, "last": 31}
_SPAN = (r"(?P<span>(?:every|each) (?:month|other day|other week|other (?P<oday>monday|tuesday|wednesday|thursday|friday|"
         r"saturday|sunday)|(?P<n>\d+|two|three|four|five|six) (?P<unit>days|weeks)|couple of weeks)|monthly|fortnightly)")
_MDAY = r"(?:on )?the (?P<mday>\d{1,2}(?:st|nd|rd|th)?|first|second|third|fourth|fifth|tenth|fifteenth|twentieth|last)(?: day)?(?: of)?"


def _every_minutes(low: str) -> int | None:
    """"every hour" -> 60, "every 2 hours" -> 120, "every half hour" -> 30,
    "every 45 minutes" -> 45. None for "every few hours": a guess."""
    m = re.search(r"every (?:(?P<n>\d+|two|three|four|couple of|other) )?(?P<unit>hours?|minutes?|mins?)\b"
                  r"|every (?P<half>half an? hour|half hour)", low)
    if not m:
        return None
    if m.group("half"):
        return 30
    said = m.group("n")
    n = (1 if said is None else 2 if said in ("two", "couple of", "other") else 3 if said == "three"
         else 4 if said == "four" else int(said))
    return n * 60 if m.group("unit").startswith("hour") else n


def _a_repeat(low: str, text: str) -> dict | None:
    """A reminder that repeats monthly, every N days or every N weeks."""
    at = r"(?: at (?P<time>[\w: ]+?))?"
    m = (re.fullmatch(r"remind me (?:" + _MDAY + r" )?" + _SPAN + r"(?: " + _MDAY.replace("mday", "mday2") + r")?"
                      + at + r",? (?:to|that|about) (?P<text>.+)", low)
         or re.fullmatch(r"remind me (?:to|that|about) (?P<text>.+?),? (?:" + _MDAY + r" )?" + _SPAN
                         + r"(?: " + _MDAY.replace("mday", "mday2") + r")?" + at, low))
    if not m:
        return None
    hhmm = _spoken_time(m.group("time")) if m.group("time") else DEFAULT_REMINDER_TIME
    if not hhmm:
        return None
    hour, minute = map(int, hhmm.split(":"))
    if m.group("time") and _is_bare_hour(m.group("time")) and hour <= EARLIEST_BARE_HOUR:
        hour += 12
    hhmm = f"{hour:02d}:{minute:02d}"
    what = _as_he_said(text, m.group("text").strip())
    span = m.group("span")
    if "month" in span:
        said = m.group("mday") or m.group("mday2")
        if said:
            day = _ORDINAL_DAYS.get(said) or int(re.match(r"\d+", said).group(0))
        else:
            import datetime as dt
            from aletheia import localtime
            day = dt.datetime.now(localtime.operator_tz()).day      # today's date, each month
        return {"command": {"kind": "remind_monthly", "day": day, "time": hhmm, "text": what}, "say": None}
    words = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
    if span == "fortnightly" or "couple of weeks" in span:
        n, unit = 2, "weeks"
    elif "other day" in span:
        n, unit = 2, "days"
    elif "other" in span:
        n, unit = 2, "weeks"
    else:
        n = int(m.group("n")) if m.group("n").isdigit() else words[m.group("n")]
        unit = m.group("unit")
    if unit == "days":
        return {"command": {"kind": "remind_daily", "time": hhmm, "text": what, "every": n}, "say": None}
    import datetime as dt
    from aletheia import localtime
    day = m.group("oday") or WEEKDAYS[dt.datetime.now(localtime.operator_tz()).weekday()]
    return {"command": {"kind": "remind_weekly", "days": [day], "time": hhmm, "text": what, "every": n},
            "say": None}


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


def _timer_left(now=None) -> str:
    """What is left on each running timer, from the reminder store."""
    from aletheia import intercom, speech
    now = now or dt.datetime.now(dt.timezone.utc)
    left = []
    for spec in intercom._reminder_schedules():
        text = str((spec.get("command") or {}).get("text") or "")
        m = re.fullmatch(r"your (.+?) timer is up", text)
        if spec.get("kind") != "once" or not m:
            continue
        try:
            at = dt.datetime.fromisoformat(str(spec.get("at") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=dt.timezone.utc)
        seconds = (at - now).total_seconds()
        if seconds <= 0:
            continue
        minutes = int(seconds // 60)
        amount = (speech.count_phrase(int(seconds), "second") if seconds < 60
                  else speech.count_phrase(minutes, "minute") if minutes < 60
                  else speech.count_phrase(minutes // 60, "hour") + (f" and {speech.count_phrase(minutes % 60, 'minute')}" if minutes % 60 else ""))
        left.append((seconds, f"{amount} left on your {m.group(1)} timer"))
    if not left:
        return "No timer is running."
    left.sort()
    said = speech.and_list([words for _, words in left])
    return said[:1].upper() + said[1:] + "."


def _a_plain_list(text: str) -> bool:
    """A list nobody has to guess at: the shopping store splits it into
    more than one row ("eggs, bread and butter", "milk and eggs"), and no
    piece of it is a stray filler word."""
    from aletheia import intercom
    parts = intercom.shopping_items_of(text)
    if len(parts) == 1:
        # One thing whose name has "and" in it: "mac and cheese".
        return any(re.search(r"\b" + re.escape(d) + r"\b", parts[0], re.IGNORECASE)
                   for d in intercom.SHOPPING_ONE_THING)
    return all(p and p not in ("some", "also", "too", "more") for p in parts)


#: An item on "my list" that starts like this is a thing to DO, not to buy.
_TASK_VERB = re.compile(
    r"^(?:call|phone|ring|email|text|message|write to|pay|book|fix|send|check|finish|schedule|cancel|renew|"
    r"return|pick up|drop off|clean|wash|mow|file|submit|apply|follow up|chase|ask|tell|remind|order|"
    r"print|sign|read|review|update|install|set up|back up|look into|look up|talk to|meet|visit|water)\b")


def _new_task(raw: str) -> dict:
    """A task from his words: the description, a deadline if he named one,
    and an id that does not collide with a task he already has."""
    from aletheia import tasks
    desc, deadline = _split_deadline(raw.strip())
    slug = re.sub(r"[^a-z0-9]+", "-", desc.lower()).strip("-")[:40] or "voice-task"
    if any(t["id"] == slug for t in tasks.all_tasks()):
        slug = f"{slug}-2"
    command = {"kind": "task_new", "id": slug, "description": desc}
    if deadline:
        command["deadline"] = deadline
    return {"command": command, "say": None}


def _calendar_hold(transcript: str, title: str, day: str, part: str | None, time_words: str | None) -> dict | None:
    """A calendar_hold command from a day, an optional part and time. A bare
    hour on a calendar reads as a person means it: "dinner at 7" is the
    evening, "the call at 10" the morning, noon is noon."""
    import datetime as dt
    from aletheia import localtime
    day_iso = _spoken_day(day)
    if not day_iso:
        return None
    if time_words:
        hhmm = _spoken_time(time_words)
        if not hhmm:
            return None
        hour, minute = map(int, hhmm.split(":"))
        if _is_bare_hour(time_words) and 1 <= hour <= 7:
            hour += 12
        if part in ("evening", "night") and hour < 12:
            hour += 12
    else:
        hour, minute = {"morning": (9, 0), "afternoon": (14, 0), "evening": (19, 0), "night": (21, 0)}.get(
            part or "", (9, 0))
    start = dt.datetime.combine(dt.date.fromisoformat(day_iso), dt.time(hour, minute),
                                tzinfo=localtime.operator_tz())
    return {"command": {"kind": "calendar_hold", "title": _as_he_said(transcript, title.strip()),
                        "start": start.isoformat(), "minutes": 60}, "say": None}


#: A turn that only makes sense against the one before it. Skipped when
#: looking for "his last ask", so "make that 4" then "cancel it" finds the
#: reminder and not the move (and never re-reads itself).
_IS_FOLLOW_UP = re.compile(
    r"^(?:(?:make|change|move) (?:that|it)\b|(?:cancel|scrap|drop|undo) (?:that|it)$|undo$|take that back$|"
    r"(?:and|what about|how about|also)\b|(?:read|list|show) (?:me )?(?:them|those)\b)")


def _previous_ask() -> str:
    """His last full sentence from the conversation thread, wake word gone
    and follow-ups skipped."""
    try:
        from aletheia import converse
        turns = converse.recent(limit=4)
    except Exception:
        return ""
    for turn in reversed(turns or []):
        said = " ".join(str(turn.get("he_asked") or "").split())
        said = re.sub(r"^(?:thea|aletheia)[,]?\s+", "", said, flags=re.IGNORECASE)
        if said and not _IS_FOLLOW_UP.match(_without_preamble(said.casefold().rstrip(".?!"))):
            return said
    return ""


def _interview_hours(a: str, b: str) -> tuple[str, str] | None:
    """Two spoken times -> ("13:00", "14:30"), read as interview hours: a
    bare 1 to 7 is the afternoon, 8 to 11 the morning, 12 noon. None when
    either does not read or the end is not after the start."""
    out = []
    for words in (a, b):
        hhmm = _spoken_time(words)
        if not hhmm:
            return None
        hour, minute = map(int, hhmm.split(":"))
        if _is_bare_hour(words) and 1 <= hour <= 7:
            hour += 12
        out.append(f"{hour:02d}:{minute:02d}")
    return (out[0], out[1]) if out[0] < out[1] else None


def _last_ask_kind() -> str:
    """The command kind his last full sentence compiles to, or ""."""
    prev = _previous_ask()
    if not prev:
        return ""
    try:
        return str(((interpret(f"thea {prev}") or {}).get("command") or {}).get("kind") or "")
    except Exception:
        return ""


def _last_ask_is_undoable() -> bool:
    """Was his last ask a task, a list item, a reminder, a hold or a file -
    the things "cancel it" can take straight back?"""
    try:
        from aletheia import intercom
        return _last_ask_kind() in intercom.UNDOES_HIS_ASK
    except Exception:
        return False


def _moved_reminder(transcript: str, time_words: str) -> dict | None:
    """"Make that 4": the reminder he just set, at the new time, replacing
    the old one. None unless his last ask was a one-off reminder and the
    time reads."""
    prev = _previous_ask()
    if not prev:
        return None
    try:
        previous = (interpret(f"thea {prev}") or {}).get("command") or {}
    except Exception:
        return None
    if previous.get("kind") != "remind_at" or not previous.get("text"):
        return None
    hhmm = _spoken_time(time_words)
    if not hhmm:
        return None
    bare = _is_bare_hour(time_words)
    if bare:
        # "Remind me at 5" then "make that 6" set it for SIX IN THE MORNING
        # (2026-10-07): the bare-hour rule read 6 on its own. A correction
        # keeps the half of the day the reminder was already in.
        try:
            import datetime as dt
            was = dt.datetime.fromisoformat(str(previous.get("at") or "").replace("Z", "+00:00"))
            hour, minute = map(int, hhmm.split(":"))
            if was.hour >= 12 and hour < 12:
                hhmm, bare = f"{hour + 12:02d}:{minute:02d}", False
        except (ValueError, TypeError):
            pass
    at = _next_occurrence_iso(hhmm, bare_hour=bare)
    return {"command": {"kind": "remind_at", "at": at, "text": previous["text"],
                        "replaces": previous["text"]}, "say": None}


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


def _names_one_open_task(words: str) -> bool:
    """Do his words pick out exactly one open task? The gate on reading
    "delete X" or "move X to friday" as being about a task at all: "delete
    my last note" and "move my 3pm" are about other stores. Never raises."""
    try:
        from aletheia import intercom
        found, _why = intercom._one_task(words)
        return found is not None
    except Exception:
        return False
def _named_list_said(low: str, text: str) -> dict | None:
    """One of his named lists, or None. Never raises."""
    from aletheia import lists
    name_ = r"(?P<name>[a-z][a-z' -]{1,30}?)"
    if re.fullmatch(r"what (?:lists|other lists) do i have|what are my lists|(?:list|read me|show me) my lists", low):
        return {"command": {"kind": "list_read"}, "say": None}
    if re.fullmatch(r"(?:make|start|create|begin|new) (?:me )?(?:a )?(?:new )?list", low):
        return {"command": None, "say": "What should I call it? Say \"make a list called packing\"."}
    m = (re.fullmatch(r"(?:make|start|create|begin) (?:me )?(?:a )?(?:new )?list (?:called|named|for) " + name_, low)
         or re.fullmatch(r"(?:make|start|create|begin) (?:me )?(?:a |my )?(?:new )?" + name_ + r" list", low))
    if m and lists.is_named_list(m.group("name")):
        return {"command": {"kind": "list_new", "list": _as_he_said(text, m.group("name"))}, "say": None}
    m = re.fullmatch(r"(?:add|put|stick|throw) (?P<item>.+?) (?:to|on|onto|in) (?:my |the )" + name_ + r" list", low)
    if m and lists.is_named_list(m.group("name")):
        return {"command": {"kind": "list_add", "list": _as_he_said(text, m.group("name")),
                            "item": _as_he_said(text, m.group("item"))}, "say": None}
    m = (re.fullmatch(r"(?:take|remove|delete|cross|scratch|tick) (?:off )?(?P<item>.+?) (?:off|from) (?:of )?(?:my |the )"
                      + name_ + r" list", low)
         or re.fullmatch(r"(?:clear|empty|wipe) (?:out )?(?:my |the )" + name_ + r" list(?P<item>)", low))
    if m and lists.is_named_list(m.group("name")):
        return {"command": {"kind": "list_off", "list": _as_he_said(text, m.group("name")),
                            "item": m.group("item") or "everything"}, "say": None}
    m = re.fullmatch(r"(?:what(?:'s| is|s)? on |what(?:'s| is|s)? in |read (?:me )?|show (?:me )?|how many things are on )?"
                     r"(?:my |the )" + name_ + r" list", low)
    if m and lists.is_named_list(m.group("name")) and m.group("name") not in ("whole", "full", "entire"):
        return {"command": {"kind": "list_read", "list": _as_he_said(text, m.group("name"))}, "say": None}
    return None


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


#: A nod: "ok", "cool", "got it". Typed, it gets "Okay." back instead of a
#: planner error; heard by the room, it is the commonest television noise
#: there is, so `worth_answering` keeps it SILENT.
_A_NOD = re.compile(r"(?:ok|okay|k|cool|nice|great|got it|gotcha|alright|all right|sounds good|"
                    r"perfect|awesome|good|fine|sure|hmm+|mm+|right|understood|noted|will do|"
                    # "Wait" and "hold on" went to the planner (2026-10-07).
                    r"wait|hold on|hang on|one sec(?:ond)?|just a (?:sec|second|minute|moment)|"
                    r"give me a (?:sec|second|minute|moment))(?: thanks| thea| please)?")
_NO_PASSWORDS = ("I don't keep passwords - anything that looks like one is blanked out of "
                 "everything I write down, so I couldn't read it back to you. "
                 "Your password manager is the place for it.")


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
            # A nod is answered when typed and silent in the room.
            return not _A_NOD.fullmatch(text.lower().strip(" .!,"))
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


_BARE_VERBS = (
    (r"(?:set|make|add|create|new) (?:a |me a )?(?:new )?reminder(?: for me)?|remind me(?: of something| about something| later)?",
     'What should I remind you about, and when? Say "remind me at 3 to call the dentist".'),
    (r"(?:take|make|add|write|create|new) (?:a |me a )?(?:new )?note(?: for me)?|(?:take|write) (?:this|something) down|note this",
     'What should the note say? Say "note that the plumber comes Tuesday".'),
    (r"(?:add|make|create|new) (?:a |me a )?(?:new )?task(?: for me)?",
     'What\'s the task? Say "add a task to renew my passport".'),
    (r"(?:set|start) (?:a |me a )?(?:new )?timer",
     'For how long? Say "set a timer for ten minutes".'),
    (r"(?:set|make) (?:an |me an )?alarm",
     'For what time? Say "wake me up at 6".'),
    (r"(?:did (?:anyone|anybody|someone|somebody) call(?: me)?|any missed calls|who called(?: me)?|missed calls"
     r"|(?:read|check) (?:me )?my (?:texts|text messages)|any (?:new )?(?:texts|text messages))",
     "I can't see your phone's calls or texts - they stay on your phone. "
     "I can read your email, and texts that reach your Google Voice number."),
)


def _bare_verb(low: str) -> str | None:
    """The one question a verb with nothing after it needs, or None."""
    said = low.strip().rstrip("?.! ")
    said = re.sub(r"^(?:can you |could you |please |i (?:want|need) (?:you )?to )", "", said)
    said = re.sub(r" please$", "", said)
    for pattern, answer in _BARE_VERBS:
        if re.fullmatch(pattern, said):
            return answer
    return None


def interpret(transcript: str) -> dict:
    """One spoken sentence -> a command to gate-check, or words to say.

    The wrapper exists for one reason: every path below matches against a
    LOWERCASED sentence, and anything it STORES has to keep his capitals.
    Doing it here rather than in thirty patterns means the next pattern
    somebody writes gets it for free.
    """
    return _his_capitals(strip_wake_word(transcript), _interpret(transcript))


def _a_study_is_open() -> bool:
    """A study's own words ("accept the first one", "what did you find") mean a study only
    when one is open; otherwise they belong to whatever else he might mean."""
    try:
        from aletheia import studies
        return any(s.get("state") == studies.OPEN for s in studies.all_studies())
    except Exception:  # noqa: BLE001
        return False


def _a_study_waits_for_a_verdict() -> bool:
    try:
        from aletheia import studies
        return any(h.get("state") == studies.VERDICT for s in studies.all_studies() if s.get("state") == studies.OPEN
                   for h in s.get("hypotheses") or [])
    except Exception:  # noqa: BLE001
        return False


def _job_hunt_is_the_context() -> bool:
    """Was the job hunt the last thing she did or talked about? True when a
    batch ran, or an application was staged, in the last few hours, or the
    last turn of the conversation was about it. Never raises."""
    import datetime as dt
    try:
        from aletheia import current_state
        hunt = current_state.job_hunt()
        if hunt.get("running"):
            return True
        lock = hunt.get("campaign") or {}
        started = lock.get("started_at")
        if started:
            when = dt.datetime.fromisoformat(str(started).replace("Z", "+00:00"))
            if dt.datetime.now(dt.timezone.utc) - when < dt.timedelta(hours=6):
                return True
        today = hunt.get("today") or {}
        if any(today.get(k) for k in ("discovered", "sent", "blocked", "ready")):
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        from aletheia import converse
        text = " ".join(f"{t.get('he_asked', '')} {t.get('she_answered', '')}"
                        for t in converse.recent(2) if isinstance(t, dict)).casefold()
        return bool(re.search(r"\b(apply|applying|applications?|job hunt|job search|jobs)\b", text))
    except Exception:  # noqa: BLE001
        return False


def _interpret(transcript: str) -> dict:
    text = strip_wake_word(transcript)
    low = _without_preamble(text.lower().strip().rstrip(".?!"))
    # "hey thea, apply to jobs for me": the filler hid her name from the
    # strip above, and her name then hid the sentence from every pattern.
    low = re.sub(r"^(?:%s)\b[\s,.!?:;]*" % "|".join(WAKE_WORDS), "", low) or low
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
    # THE ANSWER TO HER QUESTION. "Add a task" -> "What's the task?" -> "call
    # the plumber": his last sentence was a bare ask, so this one is what it
    # was missing. After the two switches, which nothing may stand in front
    # of; before everything else, or "call the plumber" is a phone call.
    filled = _fills_a_bare_ask(text, low)
    if filled:
        return filled
    # RESTARTING HER is the third switch. "Restart yourself" reached the
    # planner, which is forbidden from emitting it, so it compiled
    # something else. Whole sentences only, and never "restart the music".
    if re.fullmatch(r"(?:restart|reboot|relaunch|reload) (?:yourself|aletheia|thea|the core|yourself please)"
                    r"|restart (?:her|it)( please)?|(?:please )?restart", low):
        return {"command": {"kind": "restart", "reason": f"by voice: {transcript!r}"},
                "say": None}
    # "UPDATE YOURSELF" is one beat of her sync loop, now, and what happened.
    if re.fullmatch(r"(?:update|upgrade) (?:yourself|your code|thea|aletheia)(?: now)?"
                    r"|(?:check for|pull|get|grab|fetch) (?:the )?(?:latest|newest|new) (?:code|version|update|updates)"
                    r"|(?:try (?:the|to) update|update now|check for updates|pull the update)(?: now)?", low):
        return {"command": {"kind": "update_now", "reason": f"by voice: {transcript!r}"}, "say": None}

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
                    # NOT "see you later" (2026-10-07): it shut her down
                    # until he opened her again, while "goodbye" and "see
                    # you" said she would keep at it. A farewell is not an
                    # off switch; `quick`'s farewell answers it.
                    r"close the window)", low):
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
    # "TURN OFF ALL MY ALARMS" is about her alarms, not her switch
    # (2026-10-07: it got the kill-switch speech). Every one of that sort.
    m = re.fullmatch(r"(?:turn off|cancel|delete|clear|stop|remove|disable|kill) (?:all|every one of) (?:of )?(?:my |the )?"
                     r"(?P<sort>alarms|timers|reminders)", low)
    if m:
        return {"command": {"kind": "reminder_off", "which": "all " + m.group("sort")}, "say": None}
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

    # THE OUTWARD MAIL HOLD is lifted at his keyboard, never from a sentence
    # anything in the room could say (his 2026-09-24 ruling put it on; a
    # voice rule that lifts it would be a bypass). Said plainly, with where.
    if re.fullmatch(r"(?:lift|remove|take off|turn off|end|drop|release) (?:the )?(?:outward |outgoing )?"
                    r"(?:mail|email) hold(?: now| please)?"
                    r"|(?:let|allow) (?:the )?(?:emails?|mail) (?:go )?out(?: again| now)?"
                    r"|(?:start|resume) sending (?:emails?|mail)(?: again)?"
                    r"|(?:stop|quit) holding (?:my |the )?(?:emails?|mail|drafts)", low):
        try:
            from aletheia import mail as _mail
            where = str(_mail.outward_hold().get("command") or "")
        except Exception:
            where = ""
        return {"command": None,
                "say": ("Lifting the mail hold is yours, at the keyboard - not something I do from a sentence. "
                        "Until then I draft and keep, and nothing goes out."
                        + (f" The switch is '{where}'." if where else ""))}

    # THE MACHINE'S OWN POWER is not hers: "shut down the computer" went to
    # nobody at the bottom rung (2026-09-24). Said plainly, never compiled.
    if re.fullmatch(r"(?:shut ?down|turn off|power off|restart|reboot|log off|sign out of|lock)"
                    r" (?:the |my |this )?(?:computer|pc|machine|laptop|desktop|windows)(?: now| please)?", low):
        act_word = "lock" if low.startswith("lock") else "restart" if low.startswith(("restart", "reboot")) \
            else "sign out of" if low.startswith(("log off", "sign out")) else "shut down"
        return {"command": None,
                "say": f"I don't {act_word} this PC - that's yours at the keyboard. "
                       "I keep running, and everything I hold is saved as I go."}

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
                    # "Who's in my contacts" (2026-10-07: to a model).
                    r"|(who'?s|who is|what'?s) in my (contacts|address book|phone book)"
                    r"|(show|read)( me)? (my )?contacts", low):
        return {"command": {"kind": "contacts"}, "say": None}
    if re.fullmatch(r"who do i have (saved|on file)", low):
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
    # "APPLY TO JOBS FOR ME" is a sentence he will say, and it went to the
    # planner for 25-80 seconds to become the one verb there is for it. No
    # role is needed: she works out what fits from his resume (campaign).
    m = re.fullmatch(
        r"(?:(?:can you|could you|please|go|hey) )?(?:find and )?apply (?:me )?(?:to|for) "
        r"(?:(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|a few|some|a bunch of) )?"
        r"(?:(.+?) )?(?:jobs?|positions?|roles?|openings?)"
        r"(?: for me)?(?: (?:with|using) (?:my|this|the) (?:resume|cv))?(?: for me)?", low)
    if m:
        words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                 "seven": 7, "eight": 8, "nine": 9, "ten": 10, "a few": 3,
                 "some": 5, "a bunch of": 8}
        said_count = m.group(1) or ""
        count = int(said_count) if said_count.isdigit() else words.get(said_count, 5)
        kind_of = [w for w in (m.group(2) or "").split()
                   if w not in ("a", "the", "some", "new", "more", "good", "any", "few",
                                "remote", "me", "of", "bunch")]
        command = {"kind": "apply_campaign", "count": max(1, min(count, 10))}
        if kind_of:
            command["role"] = _as_he_said(transcript, " ".join(kind_of))
        if "remote" in (m.group(2) or "").split():
            command["where"] = "remote"
        return {"command": command, "say": None}
    # THE SENTENCE HAD TO CONTAIN "APPLY ... JOBS" OR IT WENT TO THE PLANNER.
    # "Start applying", "keep going with the job search", "get back to
    # applying", "find me more jobs and apply" - his ordinary ways of
    # saying the one thing she is most often asked to do - each cost a
    # frontier round trip, and on 2026-09-19 with the frontier out cost
    # him the whole ask. The phrasing of a sentence must not gate a
    # capability she has (the seamless brief, section 1). No count: the
    # campaign's own default. "Keep going" on its own is only this when
    # the job hunt is what she was last doing (`_job_hunt_is_the_context`);
    # otherwise it asks, because a wrong guess opens real employer pages.
    if re.fullmatch(
            r"(?:(?:can you|could you|please|go|hey|just|ok|okay|now|go ahead and|let'?s) )*"
            r"(?:(?:start|keep|continue|resume|restart|get back to|go back to|carry on|carry on with|"
            r"get on with|get going with|get going on|go on with|crack on with|stay on|"
            r"go and start|start on|begin|get|set|kick off|fire up|spin up) )?"
            r"(?:(?:applying|apply)(?: (?:to|for) (?:(?:some |more |a few |new |remote |local |"
            r"the |other )*(?:jobs|work|positions|places|companies|openings)))?"
            r"|(?:the |my |our )?(?:job (?:hunt|search|hunting|applications?)|applications?|"
            r"job stuff|hunt|hunting)(?: going| running| up| moving| rolling| back up| up again)?"
            r"|(?:sending|send)(?: out)? (?:some |more |the |a few )?applications"
            # Finding is only this when applying is said too: "look for
            # jobs" on its own is a search, and a search does not fill forms.
            r"|(?:finding|find|look for|looking for|search for|searching for)(?: me)? "
            r"(?:some |more |a few |new |some more |remote )*(?:jobs|openings|positions|work)"
            r" (?:and|then) (?:apply|apply to them|apply for them|send applications|start applying)"
            r"|(?:go|get) (?:apply|applying)(?: (?:to|for) (?:some |more |a few |remote )*jobs)?"
            r"|(?:get|go) back to (?:the )?(?:jobs|job hunt|applications|applying)"
            r"|going with the (?:job (?:hunt|search)|applications))"
            r"(?: for me| please| now| again| today| tonight| this (?:morning|afternoon|evening)"
            r"| while i'?m (?:gone|out|away|asleep)| some more| a bit more)*", low) \
            and re.search(r"\b(apply|applying|job|jobs|hunt|application|applications|openings|"
                          r"positions|work)\b", low):
        command = {"kind": "apply_campaign", "count": 5}
        if "remote" in low.split():
            command["where"] = "remote"
        return {"command": command, "say": None}
    # "STOP APPLYING FOR NOW". There was no such switch: the sentence went
    # to the planner and, with every frontier off, waited two minutes on
    # her own model (2026-09-22). Not the kill switch - everything else of
    # hers keeps going - and a batch already running finishes.
    if re.fullmatch(
            r"(?:(?:can you|could you|please|go|hey|just|ok|okay|now|let'?s) )*"
            r"(?:stop|pause|hold off on|hold off|halt|quit|no more|take a break from|give it a rest with|"
            r"put a hold on|freeze|suspend)"
            r"(?: (?:the |my |our |with the )?(?:applying|applications?|job (?:hunt|search|hunting|applications?)|"
            r"jobs?|hunt|sending (?:out )?applications|applying (?:to|for) (?:jobs|work|places|companies)))"
            r"(?: for now| for today| for tonight| for a (?:bit|while|few days)| until (?:i say|tomorrow|monday)| please)*", low) \
            and re.search(r"\b(?:apply|applying|applications?|jobs?|hunt)\b", low):
        reason = ""
        m = re.search(r"\b(for (?:now|today|tonight|a (?:bit|while|few days))|until [a-z ]+)$", low)
        if m:
            reason = m.group(1)
        return {"command": {"kind": "apply_pause", **({"reason": reason} if reason else {})}, "say": None}
    # "YOU'RE WRONG" with nothing else waited two minutes on her own model
    # to guess at a correction (2026-09-22). She asks for the correction
    # instead: a correction she guesses at is a second mistake.
    if re.fullmatch(r"(?:you'?re|that'?s|thats|youre) (?:wrong|not right|incorrect|mistaken|off)|wrong|"
                    r"no,? that'?s (?:not it|wrong|not right)|not that|nope,? wrong", low):
        return {"command": None,
                "say": "Tell me what's wrong and I'll put it right - I won't guess at a correction."}
    # "THE OTHER ONE" with nothing before it. A follow-up word with an
    # empty thread went to the planner and waited two minutes on her own
    # model; the honest answer is instant and asks for the whole thing.
    if re.fullmatch(r"(?:the )?(?:other|first|second|third|last|next) one|that one|this one|"
                    r"the other|not that one|the same one", low):
        try:
            from aletheia import converse
            if not converse.recent(limit=1):
                return {"command": None,
                        "say": "Nothing came before this for me to pick from - say the whole thing."}
        except Exception:  # noqa: BLE001
            pass
    # "KEEP GOING" / "CONTINUE" with nothing named: the job hunt when that
    # is what she was last doing; otherwise ask, out loud, rather than
    # guess at something that opens real employer pages.
    if re.fullmatch(r"(?:(?:can you|could you|please|go|hey|just|ok|okay|now) )*"
                    r"(?:keep going|keep at it|carry on|continue|keep it up|keep on|go on|"
                    r"keep working|keep going with (?:that|it)|carry on with (?:that|it)|"
                    r"continue (?:that|with that|with it)|more of (?:that|the same)|"
                    r"do (?:that|it) again|again|another (?:batch|round))"
                    r"(?: please| for me| now)*", low):
        if _job_hunt_is_the_context():
            return {"command": {"kind": "apply_campaign", "count": 5}, "say": None}
        try:
            from aletheia import friction
            friction.record("question", "what 'keep going' meant", asked=transcript, source="voice")
        except Exception:  # noqa: BLE001
            pass
        return {"command": None,
                "say": "Keep going with what? Say the thing - the job hunt, a project, or "
                       "a task - and I'll pick it back up."}
    # WHAT AN EMPLOYER DID about one he sent. Narrow on purpose: "I heard
    # back from Dana" is not about a job, and a pattern that swallows too
    # much answers a different question than the one he asked.
    for pattern, fixed in (
            (r"(?:mark )?(?:my |the )?application (?:at|with|to) (?P<who>.+?) as "
             r"(?P<said>replied|interview|offer|rejected|closed)", None),
            (r"(?P<who>.+?) (?:rejected|turned down) (?:my|the) application", "rejected"),
            (r"(?P<who>.+?) (?:replied|got back to me) about (?:my|the) (?:job )?application",
             "replied"),
            (r"i (?:have|got) an interview (?:with|at) (?P<who>.+)", "interview"),
            (r"i got an offer from (?P<who>.+)", "offer"),
            (r"(?:my |the )?application (?:at|with|to) (?P<who>.+?) is closed", "closed")):
        hit = re.fullmatch(pattern, low)
        if hit:
            return {"command": {"kind": "apply_outcome",
                                "which": _as_he_said(transcript, hit.group("who")),
                                "outcome": fixed or hit.group("said")},
                    "say": None}
    if re.fullmatch(r"(what|which) (jobs?|applications?) have i applied (to|for)"
                    r"|what have i applied (to|for)"
                    r"|(what|which) (jobs?|applications?) did (you|u) apply (to|for)"
                    r"|(list )?(my )?applications", low):
        return {"command": {"kind": "applications"}, "say": None}
    # HIS OWN NAMED LISTS (2026-10-07: "make a list called packing", "add
    # socks to my packing list" and "what's on my packing list" went to the
    # planner). A list with a name of its own - never shopping, tasks or
    # reminders, which each have their own store and verbs.
    named = _named_list_said(low, text)
    if named:
        return named
    if re.fullmatch(r"(what'?s?( is)? on )?(my |the )?(shopping|grocery) list"
                    r"|how many (things|items) (are )?on (my |the )?(shopping |grocery )?list"
                    r"|what do i need (to buy|from the (shop|store|grocery store))"
                    r"|read (me )?(my |the )?(shopping|grocery) list"
                    # "What's on the grocery list" (2026-10-07: to a model).
                    r"|(show me|what'?s in|check) (my |the )?(shopping|grocery) list", low):
        return {"command": {"kind": "shopping_list"}, "say": None}
    # "Start a grocery list": she keeps one, and it is already there.
    if re.fullmatch(r"(?:start|make|create|begin|open) (?:a |my |the |new )*(?:shopping|grocery) list", low):
        return {"command": None,
                "say": "Your shopping list is ready - tell me what to put on it, like \"add milk and eggs to the list\"."}
    # "SHOPPING LIST" WAS REQUIRED IN FULL, while the ADD side beside it
    # has always accepted a bare "the list" — so "add milk to the list"
    # was instant and "take milk off the list" cost four and a half
    # seconds at the planner and then asked permission to undo it. The
    # same asymmetry the reminder cancel had: the writer is fast and the
    # un-doer is not, which teaches him to be careful about asking.
    #
    # "Got the milk" is here because that is what a person says in a shop,
    # and it means the same thing.
    m = re.match(r"(?:take|remove|delete|cross|scratch|tick) (?:off )?(.+?) "
                 r"(?:off|from) (?:my |the )?(?:shopping |grocery )?list", low)
    if not m:
        # "GOT THE MILK" is what a person says in a shop, and it means the
        # same thing. It is also how "I got the job" and "got it" are
        # said, so this asks the STORE rather than guessing: it is a
        # removal only if that thing is actually on his list right now. A
        # pattern that swallows too much answers a different question,
        # which is the failure he cannot detect.
        said = re.fullmatch(r"(?:i(?:'ve| have)? )?(?:got|bought|picked up) "
                            r"(?:the |some |a |an )?(.+?)", low)
        if said and _on_the_shopping_list(said.group(1)):
            m = said
        # A bare "remove milk" (2026-10-07: to the planner) - the same
        # rule: only when milk is on the list.
        bare = re.fullmatch(r"(?:remove|cross off|scratch|take off|delete) (?:the |some )?(.+?)", low)
        if not m and bare and _on_the_shopping_list(bare.group(1)):
            m = bare
    if not m:
        # "TAKE EGGS OFF" with no list named (2026-10-07: to the planner) -
        # only when that thing is on the list, the same store check.
        said = re.fullmatch(r"(?:take|cross|scratch|tick) (?:the |my )?(.+?) off", low)
        if said and _on_the_shopping_list(said.group(1)):
            m = said
    if m:
        # "Take the plumber one off my list": "my list" is his task list
        # too, so a thing that is a task and not a grocery is the task.
        item = m.group(1).strip()
        if not re.search(r"shopping|grocery", m.group(0)) and not _on_the_shopping_list(item) \
                and _names_one_open_task(item):
            return {"command": {"kind": "task_change", "which": item, "drop": True}, "say": None}
        return {"command": {"kind": "shopping_off", "item": item},
                "say": None}

    # A BARE "ADD MILK" (2026-10-07: to the planner) - the list is the only
    # place a bare thing goes. A verb is a task; anything naming another
    # store, or with a preposition in it, is left to the patterns for those.
    # "Add bread too" is the thread's ("the second item is free too").
    m = re.fullmatch(r"add (?:some |more )?(?P<item>[a-z][a-z' -]{1,30})", low)
    if m and not re.search(r"\b(?:to|on|with|at|for|from|in|into|by|task|tasks|meeting|reminder|note|contact|event|"
                           r"appointment|calendar|alarm|timer|that|it|this|them|everything|all|too|also|well)\b", m.group("item")):
        if _TASK_VERB.match(m.group("item")):
            return _new_task(_as_he_said(text, m.group("item")))
        if not _might_be_several(m.group("item")):
            return {"command": {"kind": "shopping_add", "item": _as_he_said(text, m.group("item").strip())},
                    "say": None}

    # "WE'RE OUT OF COFFEE", "we need paper towels", "I need to buy
    # batteries": a thing to buy, said as a need (2026-10-07: the planner,
    # and the last one refused as SPENDING). It goes on the list; buying
    # it stays his. Anything that starts with a verb is not a thing.
    m = (re.fullmatch(r"(?:we(?:'re| are)|i(?:'m| am)) (?:all )?out of (?:the |some )?(?P<item>[a-z][a-z '-]{1,40})", low)
         or re.fullmatch(r"(?:we|i) need (?:to (?:buy|get|pick up) )?(?:more |some |a new |new |a |an )?(?P<item>[a-z][a-z '-]{1,40})", low)
         or re.fullmatch(r"(?:we(?:'re| are)|i(?:'m| am)) (?:running )?(?:low on|almost out of) (?:the )?(?P<item>[a-z][a-z '-]{1,40})", low))
    if m and not _TASK_VERB.match(m.group("item")) \
            and not re.match(r"(?:to|break|help|you|time|rest|sleep|nap|money|cash|job|minute|second|hand|hug|"
                             r"vacation|holiday|day off|shower|ride|lift|doctor|dentist|lawyer|therapist|advice|"
                             r"idea|ideas|plan|answer|answers|space|quiet|coffee break|drink|win|friend|friends|"
                             r"date|haircut|change|reminder|timer|alarm|it|that|this|them|him|her)\b", m.group("item")):
        return {"command": {"kind": "shopping_add", "item": _as_he_said(text, m.group("item").strip())},
                "say": None}

    # "Snooze that for an hour" — the commonest thing anybody says to a
    # notification, and it had no verb at all.
    m = re.fullmatch(r"snooze(?: (?:that|it|this|them|(?:your |all |the )?(?:notifications|notices|alerts)|the (?:alert|notification|"
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

    # "Remind me again in 10 minutes" after a reminder fires is a snooze
    # said the way a person says it (2026-10-07: to the planner).
    m = re.fullmatch(r"remind me (?:again|later|of (?:that|it) (?:again|later))(?: in (.+))?", low)
    if m:
        minutes = DEFAULT_SNOOZE_MINUTES if not m.group(1) else _spoken_minutes(m.group(1))
        if minutes:
            return {"command": {"kind": "notify_snooze", "minutes": minutes}, "say": None}
        return _to_the_planner(text)

    # FORGETTING, which she could do all along and could not be asked to.
    # `memory.forget` is a real function with no kind, no registry entry
    # and no phrasing, so "forget my landlord" reached the planner, which
    # invented the identifier `memory.forget`, filed a build task for a
    # thing that already existed, and read the id out loud.
    #
    # "Forget it" and "forget that" are deliberately NOT here: those mean
    # "never mind" and already deny a pending approval, which is a
    # different act and the safer one to keep.
    m = re.fullmatch(r"forget (?:about )?(?!it$|that$|everything$)"
                     r"((?:what you know about |everything about )?.+?)"
                     r"\s*\??", low)
    if m:
        return {"command": {"kind": "forget",
                            "about": _as_he_said(transcript, m.group(1))},
                "say": None}

    # "HOW LONG LEFT ON MY TIMER" told him she couldn't think (2026-10-07,
    # no model). A timer is a reminder with a time on it; the answer is a
    # subtraction.
    if re.fullmatch(r"(?:how (?:long|much time|many minutes)(?: is)? (?:left|remaining)|time left|"
                    r"how long (?:until|till|before)|when (?:does|will))"
                    r"(?: on| for| in)? (?:my|the|that) timers?(?: (?:go off|be done|ring|done))?"
                    r"|how(?:'s| is) (?:my|the) timer(?: doing| going)?", low):
        return {"command": None, "say": _timer_left()}

    # what is set, and stopping one. Before the "remind me" patterns so a
    # question about reminders is never read as a request for a new one.
    # "Do I have any reminders set" waited two minutes on her own model
    # for a store this branch reads (2026-09-22): the question in the
    # shape of a yes/no is the same question.
    if re.fullmatch(r"(what|which) (?:reminders?|timers?|alarms?) (do i have|are set|have i got|are running)"
                    r"|what am i being reminded (of|about)"
                    # A timer is a reminder with a countdown (bottom rung 2026-09-24).
                    r"|(?:any|do i have any|list (?:my )?|my )?(?:timers?|alarms?)(?: running| set| going)?"
                    r"|(do i have|have i got|are there|is there) (any |a )?reminders?( set| pending| coming up)?"
                    r"|any reminders( set| pending| coming up)?"
                    r"|list (my )?reminders|my reminders|reminders"
                    # "What are my reminders" - the commonest way to ask - went to the
                    # planner and, with no model, came back prefaced with an apology.
                    r"|(?:what are|show me|tell me|read me|read) (?:all )?(?:my|the) (?:reminders|timers|alarms)"
                    # "When is my next reminder" (2026-09-24, offline: "I can't think just now")
                    r"|(when|what time)(?: is|'s) (my|the) next (?:reminder|alarm|timer)"
                    r"|what(?:'s| is) my next reminder"
                    # "When's my next reminder", "what are my reminders" (2026-10-07: to a model)
                    r"|(?:what are|show(?: me)?|read(?: me)?|tell me) (?:all )?(?:my |the )?(?:reminders|alarms|timers)"
                    r"|what reminders (?:have i (?:got|set)|did i set)", low):
        return {"command": {"kind": "reminders"}, "say": None}
    # "Stop the timer" (2026-10-07: to the planner). A timer is a reminder
    # whose words end "timer is up"; two running are asked about by name.
    if re.fullmatch(r"(?:cancel|stop|delete|turn off|remove|kill|end|clear) (?:the |my |that |this )?timers?", low):
        return {"command": {"kind": "reminder_off", "which": "timer is up"}, "say": None}
    m = re.match(r"(?:cancel|stop|delete|turn off|remove) (?:the |my |that )?"
                 r"reminder (?:about |for |to )?(.+)", low)
    if not m:
        m = re.match(r"stop reminding me (?:about|to|of) (.+)", low)
    if not m:
        # THE OTHER WORD ORDER, which is the one he used: "cancel the
        # DENTIST REMINDER", not "cancel the reminder about the dentist".
        # Setting one is instant and free; cancelling it cost four seconds
        # at the planner and then asked permission to undo something she
        # had just done for nothing. Anchored to the whole sentence and
        # ending in the word itself, so "cancel my gym membership" is
        # untouched and still reaches the thing that really cancels.
        m = re.fullmatch(r"(?:cancel|stop|delete|turn off|remove) "
                         r"(?:the |my |that )?(.+?) reminders?\s*", low)
    if not m:
        # "CANCEL MY ALARM": an alarm is a reminder that says "wake up", and
        # setting one was instant while cancelling it reached the planner.
        if re.fullmatch(r"(?:cancel|stop|delete|turn off|remove|clear|switch off|kill) "
                        r"(?:the |my |that |all )?(?:my )?alarms?(?: for (?:tomorrow|the morning|[\w: ]+))?", low):
            return {"command": {"kind": "reminder_off", "which": "wake up"}, "say": None}
    if m:
        # "CANCEL THAT REMINDER", straight after setting it, searched his
        # reminders for the word "that" and answered "None of your reminders
        # is about that. The one you have is email Sam" - naming the very one
        # he meant. A pronoun is a reference to what he just did.
        if re.fullmatch(r"(?:that|it|this|the|new|latest)", m.group(1).strip()) \
                and _last_ask_kind() == "remind_at":
            return {"command": {"kind": "undo"}, "say": None}
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
    # THE OTHER WORD ORDER, RECURRING. "Remind me to take out the trash every
    # tuesday night" was set ONCE, for next Tuesday, as "take out the trash
    # every" (2026-10-07) - wrong data in a fluent sentence, the failure he
    # cannot hear. The "every" belongs to the schedule.
    m = re.fullmatch(r"remind me (?:to|that) (?P<text>.+?),? (?:every|each|on) "
                     r"(?P<days>" + _one_day + r"(?:\s*(?:,|and|&)\s*" + _one_day + r")*)"
                     r"(?: (?P<part>morning|afternoon|evening|night))?(?: at (?P<time>[\w: ]+?))?", low)
    if m and (low.split(" every ")[-1] != low or m.group("days").endswith("s")):
        part_time = {"morning": "09:00", "afternoon": "14:00", "evening": "19:00", "night": "21:00"}.get(
            m.group("part") or "")
        hhmm = _spoken_time(m.group("time")) if m.group("time") else part_time or DEFAULT_REMINDER_TIME
        if not hhmm:
            return _to_the_planner(text)
        if m.group("time") and _is_bare_hour(m.group("time")) and int(hhmm[:2]) <= EARLIEST_BARE_HOUR:
            hhmm = f"{int(hhmm[:2]) + 12:02d}{hhmm[2:]}"      # "every monday at 6" is the evening
        days = [d for d in re.split(r"\s*(?:,|and|&)\s*", m.group("days")) if d]
        return {"command": {"kind": "remind_weekly", "days": days, "time": hhmm,
                            "text": _as_he_said(text, m.group("text").strip())}, "say": None}
    m = re.fullmatch(r"remind me (?:to|that) (?P<text>.+?),? (?:every (?:day|morning|evening|night)|daily|each day)"
                     r"(?: at (?P<time>[\w: ]+?))?", low)
    if m:
        part = re.search(r"every (morning|evening|night)", low)
        hhmm = (_spoken_time(m.group("time")) if m.group("time")
                else {"morning": "09:00", "evening": "19:00", "night": "21:00"}.get(part.group(1) if part else "",
                                                                                    DEFAULT_REMINDER_TIME))
        if hhmm:
            return {"command": {"kind": "remind_daily", "time": hhmm,
                                "text": _as_he_said(text, m.group("text").strip())}, "say": None}
        return _to_the_planner(text)
    m = re.match(r"remind me (?:every day|daily) at ([\w: ]+?) (?:to|that) (.+)", low)
    if m:
        hhmm = _spoken_time(m.group(1))
        if hhmm:
            return {"command": {"kind": "remind_daily", "time": hhmm,
                                "text": m.group(2).strip()}, "say": None}
        return _to_the_planner(text)
    # MONTHLY, EVERY OTHER DAY, EVERY TWO WEEKS (2026-10-07: "remind me on
    # the first of every month to pay rent" was refused as SPENDING, the
    # rest went to the planner). Either word order; nine o'clock when he
    # names no time, as for the weekly ones, and the receipt says it back.
    repeat = _a_repeat(low, text)
    if repeat:
        return repeat
    # "REMIND ME ABOUT THIS LATER" names neither the thing nor the time,
    # and was read as a memory search for "this later". Asked for whole.
    # (A bare "remind me later" is a snooze of what just fired.)
    if re.fullmatch(r"remind me (?:about|of) (?:this|that|it)(?: (?:later|in a bit|another time|some other time|soon))?", low):
        return {"command": None,
                "say": "Remind you of what, and when? Say it whole - like \"remind me at 4 to call Sam\" "
                       "or \"remind me in an hour to check the oven\"."}
    # "REMIND ME TOMORROW" names a when and no what (2026-10-07: to the
    # planner). Asked for whole, with the day he said in the example.
    m = re.fullmatch(r"remind me (?P<when>tomorrow(?: morning| afternoon| evening| night)?|tonight|later today"
                     r"|this (?:morning|afternoon|evening)|next week|on (?:monday|tuesday|wednesday|thursday|friday"
                     r"|saturday|sunday)|(?:at|around) \d{1,2}(?::\d\d)?(?: ?[ap]m)?)", low)
    if m:
        when = m.group("when")
        return {"command": None,
                "say": f"Remind you of what? Say it whole - like \"remind me {when} to call Sam\"."}
    # "SET AN ALARM FOR 6AM EVERY DAY", "wake me up at 7 every weekday"
    # (2026-10-07: to the planner). The repeating kinds, a wake-up's words.
    m = re.fullmatch(r"(?:wake me(?: up)?|get me up|set (?:an |my )?alarm(?: for)?) (?:at )?(?P<time>[\w: ]+?) "
                     r"(?P<when>every (?:day|morning|weekday|weekend)|each (?:day|morning)|daily|on weekdays|weekdays)", low)
    if m and _spoken_time(m.group("time")):
        hour, minute = map(int, _spoken_time(m.group("time")).split(":"))
        if _is_bare_hour(m.group("time")) and hour == 12:
            hour = 0
        hhmm = f"{hour:02d}:{minute:02d}"
        if "weekday" in m.group("when"):
            return {"command": {"kind": "remind_weekly", "days": ["weekdays"], "time": hhmm, "text": "wake up"},
                    "say": None}
        if "weekend" in m.group("when"):
            return {"command": {"kind": "remind_weekly", "days": ["weekend"], "time": hhmm, "text": "wake up"},
                    "say": None}
        return {"command": {"kind": "remind_daily", "time": hhmm, "text": "wake up"}, "say": None}

    # THE VERB WITH NOTHING AFTER IT. "Set a reminder", "take a note" and
    # "add a task" went to the planner, which with nothing thinking kept
    # them for later - an ask with no content, filed. The answer is the
    # one question that gets the content, with the sentence that works.
    bare = _bare_verb(low)
    if bare:
        return {"command": None, "say": bare}
    # "WAKE ME UP AT 6" and "SET A TIMER FOR TEN MINUTES" are reminders in
    # other clothes; both went to the planner. A timer is a reminder from
    # now; an alarm is a reminder at a clock time.
    m = re.fullmatch(r"(?:wake me(?: up)?|get me up|set an alarm(?: for)?) (?:at )?([\w: ]+?)"
                     r"(?: (tomorrow|today))?", low)
    if m and _spoken_time(m.group(1)):
        # A WAKE-UP IS A MORNING. "Wake me up at 6" is six in the morning,
        # whatever the clock says now, and "tomorrow" means tomorrow even
        # when six this morning has passed - _next_occurrence_iso's
        # afternoon reading would have set it for 18:00.
        import datetime as dt
        from aletheia import localtime
        hour, minute = map(int, _spoken_time(m.group(1)).split(":"))
        if _is_bare_hour(m.group(1)) and 1 <= hour <= 11:
            pass                                    # already a morning hour
        tz = localtime.operator_tz()
        now = dt.datetime.now(tz)
        when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if m.group(2) == "tomorrow" or when <= now:
            when += dt.timedelta(days=1)
        return {"command": {"kind": "remind_at", "at": when.isoformat(), "text": "wake up"}, "say": None}
    m = re.fullmatch(r"(?:set|start) (?:a |me a )?timer(?: for)? (half an|\w+) (minutes?|mins?|hours?|seconds?)"
                     r"|timer(?: for)? (half an|\w+) (minutes?|mins?|hours?|seconds?)"
                     r"|remind me in (half an|\w+) (minutes?|mins?|hours?)", low)
    if m:
        import datetime as dt
        raw = m.group(1) or m.group(3) or m.group(5)
        unit = m.group(2) or m.group(4) or m.group(6)
        amount = _spoken_amount(raw)
        if amount:
            seconds = amount * (3600 if unit.startswith("hour") else 1 if unit.startswith("sec") else 60)
            at = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=seconds)).isoformat()
            one = "hour" if unit.startswith("hour") else "second" if unit.startswith("sec") else "minute"
            # "Remind me in an hour" was "your an-hour timer is up" (2026-10-07).
            # His own number word stays ("your ten-minute timer"); only an
            # article becomes a number.
            if amount < 1 and one == "hour":
                amount, one = amount * 60, "minute"
            number = (raw if not raw.isdigit() and raw not in ("a", "an", "half an")
                      else int(amount) if float(amount).is_integer() else amount)
            said = f"{number}-{one}"
            return {"command": {"kind": "remind_at", "at": at, "text": f"your {said} timer is up"},
                    "say": None}
    # "remind me in TWENTY minutes to check the oven": the amount is a
    # word as often as a digit out loud, and only the digit form was read
    # - the word form fell through to a planner that, with no model, kept
    # it for later. Same words table as the timer above.
    # THE TIME BEFORE THE DAY, AT THE END. "Remind me to call mom at 5:30 pm
    # tomorrow" was set for 9 am with "at 5:30 pm" left in the words
    # (2026-10-07): the day pattern below reads "at <time>" only AFTER the
    # day. Same handling as there, the other order.
    m = re.fullmatch(r"remind me (?:to|that) (?P<text>.+?) at (?P<time>[\w: ]+?) (?:on |this )?"
                     r"(?P<day>monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|today)", low)
    if m:
        import datetime as dt
        from aletheia import localtime
        day_iso, hhmm = _spoken_day(m.group("day")), _spoken_time(m.group("time"))
        if day_iso and hhmm:
            hour, minute = map(int, hhmm.split(":"))
            if _is_bare_hour(m.group("time")) and hour <= EARLIEST_BARE_HOUR:
                hour += 12
            tz = localtime.operator_tz()
            when = dt.datetime.combine(dt.date.fromisoformat(day_iso), dt.time(hour, minute), tzinfo=tz)
            return {"command": {"kind": "remind_at", "at": when.isoformat(),
                                "text": _as_he_said(text, m.group("text").strip())}, "say": None}

    # A DAY IN THE SENTENCE. "Remind me to call mom on Sunday at 6" was set
    # for TODAY at 6 with "on sunday" swallowed into the text (2026-09-22):
    # the day is read from either end of the sentence. "Next friday" is
    # still asked about, as before.
    # A date ("on the 15th", "on october 20") is a day too, and "next
    # tuesday" is caught so it can be ASKED about rather than guessed.
    _days = (r"(?:(?:next )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|tomorrow|today|"
             + SPOKEN_DATE + r")")
    # "Remind me TOMORROW MORNING to email Dana": a part of the day is a time
    # too (2026-09-24, offline: to the planner). Morning nine, afternoon two,
    # evening seven, night nine.
    _part = r"(?: (?P<part>morning|afternoon|evening|night))?"
    m = (re.fullmatch(r"remind me (?:to|that) (?P<text>.+?),? (?:on |this )?(?P<day>" + _days + r")" + _part
                      + r"(?: at (?P<time>[\w: ]+?))?", low)
         or re.fullmatch(r"remind me (?:on |this )?(?P<day>" + _days + r")" + _part + r"(?: at (?P<time>[\w: ]+?))? "
                         r"(?:to|that) (?P<text>.+)", low)
         or re.fullmatch(r"remind me at (?P<time>[\w: ]+?) (?:on |this )?(?P<day>" + _days + r")" + _part + r" "
                         r"(?:to|that) (?P<text>.+)", low))
    if m and re.search(r"\b(?:every|each)\b", m.group("text")):
        # A repeat this cannot read is never set as a one-off.
        return _to_the_planner(text)
    if m:
        import datetime as dt
        from aletheia import localtime
        asked = _ambiguous_next_weekday(m.group("day"))
        if asked:
            # Asked, with the sentence that settles it in his own words, so
            # the answer is one breath and not a guess about what to say.
            soon = re.search(r"the (\d+\w\w)", asked).group(1)
            what = _as_he_said(text, m.group("text").strip())
            return {"command": None,
                    "say": f"{asked} Say 'remind me on the {soon} to {what}' and it's set."}
        day_iso = _spoken_day(m.group("day"))
        part_time = {"morning": "09:00", "afternoon": "14:00", "evening": "19:00", "night": "21:00"}.get(
            m.group("part") or "")
        hhmm = (_spoken_time(m.group("time")) if m.group("time")
                else part_time or DEFAULT_REMINDER_TIME)
        if not day_iso or not hhmm:
            return _to_the_planner(text)
        hour, minute = map(int, hhmm.split(":"))
        if m.group("time") and _is_bare_hour(m.group("time")) and hour <= EARLIEST_BARE_HOUR:
            hour += 12                                  # "at 6" on a Sunday is the evening; "at 9" the morning
        tz = localtime.operator_tz()
        when = dt.datetime.combine(dt.date.fromisoformat(day_iso), dt.time(hour, minute), tzinfo=tz)
        if when <= dt.datetime.now(tz) and m.group("day") in ("today", ""):
            when += dt.timedelta(days=1)
        return {"command": {"kind": "remind_at", "at": when.isoformat(),
                            "text": _as_he_said(text, m.group("text").strip())}, "say": None}
    # TWO UNITS IN ONE BREATH. "Remind me in 2 hours and 30 minutes to
    # stretch" and "in an hour and a half" went to the planner (2026-10-07):
    # every pattern here read one number and one unit.
    _span = (r"(?P<h>\w+|an) hours? (?:and )?(?:(?P<m>\w+) (?:minutes?|mins?)|(?P<half>a half))"
             r"|(?P<h2>\w+|an) and a half hours?")
    m = (re.fullmatch(r"remind me in (?:" + _span + r") (?:to|that) (?P<text>.+)", low)
         or re.fullmatch(r"remind me (?:to|that) (?P<text>.+?) in (?:" + _span + r")", low))
    if m:
        import datetime as dt
        hours = _spoken_amount("1" if (m.group("h") or m.group("h2")) == "an" else m.group("h") or m.group("h2"))
        minutes = 30 if (m.group("half") or m.group("h2")) else _spoken_amount(m.group("m"))
        if hours is None or minutes is None:
            return _to_the_planner(text)
        at = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=hours, minutes=minutes)).isoformat()
        return {"command": {"kind": "remind_at", "at": at,
                            "text": _as_he_said(text, m.group("text").strip())}, "say": None}
    # "REMIND ME 15 MINUTES BEFORE MY MEETING" (2026-10-07: to the planner).
    # The next event on his calendar - or the next one whose title has the
    # words he said - less the lead time he gave.
    m = re.fullmatch(r"remind me (?P<n>\w+(?: an)?) (?P<unit>minutes?|mins?|hours?) before (?:my |the )?(?:next )?"
                     r"(?P<what>.+?)", low)
    if m:
        import datetime as dt
        from aletheia import calendar as cal
        amount = _spoken_amount(m.group("n"))
        if amount:
            lead = dt.timedelta(hours=amount) if m.group("unit").startswith("hour") else dt.timedelta(minutes=amount)
            what = m.group("what").strip()
            generic = what in ("meeting", "appointment", "event", "call", "thing", "one")
            now = dt.datetime.now(dt.timezone.utc)
            try:
                upcoming = [e for e in cal.all_events()
                            if e.get("status") != "CANCELLED" and cal.parse_time(e["start"]) > now + lead]
            except Exception:
                upcoming = []
            if not generic:
                words = [w for w in re.findall(r"[a-z0-9]+", what) if len(w) > 2]
                upcoming = [e for e in upcoming if all(w in str(e.get("title") or "").lower() for w in words)]
            if not upcoming:
                return {"command": None,
                        "say": ("Nothing on your calendar coming up" if generic
                                else f"I don't see {what} on your calendar coming up") + " to remind you before."}
            event = upcoming[0]
            at = (cal.parse_time(event["start"]) - lead).astimezone(dt.timezone.utc).isoformat()
            said = f"{int(amount) if float(amount).is_integer() else amount} {m.group('unit').rstrip('s')}"
            plural = "s" if amount != 1 else ""
            return {"command": {"kind": "remind_at", "at": at,
                                "text": f"{event.get('title') or 'your next event'} in {said}{plural}"},
                    "say": None}

    m = re.match(r"remind me (?:at ([\w: ]+?)|in (\w+(?: an)?) (minutes?|mins?|hours?)) (?:to|that) (.+)", low)
    if m:
        if m.group(1):
            hhmm = _spoken_time(m.group(1))
            if not hhmm:
                # "At lunch", "at the end of the day": a time with no clock.
                return _a_loose_when(low, text) or _to_the_planner(text)
            at = _next_occurrence_iso(hhmm, bare_hour=_is_bare_hour(m.group(1)))
        else:
            import datetime as dt
            amount = _spoken_amount(m.group(2))
            if not amount:
                return _to_the_planner(text)
            delta = dt.timedelta(hours=amount) if m.group(3).startswith("hour") \
                else dt.timedelta(minutes=amount)
            at = (dt.datetime.now(dt.timezone.utc) + delta).isoformat()
        return {"command": {"kind": "remind_at", "at": at, "text": _as_he_said(text, m.group(4).strip())},
                "say": None}

    loose = _a_loose_when(low, text)
    if loose:
        return loose

    # THE OTHER WORD ORDER, which is the commoner one. Every pattern
    # above is "remind me AT <time> TO <thing>"; "remind me to call the
    # dentist at 3" matched none of them and paid a planner round trip
    # for the most ordinary request an assistant gets.
    #
    # After the forward forms so nothing that already worked changes
    # route, and a time is REQUIRED: "remind me to call the dentist"
    # with no when is a task, and the planner decides that better.
    # A PLACE IS NOT A TIME. "Remind me to call mom when I get home"
    # waited two minutes on her own model (2026-09-22); she has no way to
    # know where he is, and says so instead of guessing at a time.
    m = re.match(r"remind me (?:to|that) (.+?) when i(?:'m| am| get| arrive| go| come)? "
                 r"(?:get |am |arrive |go |come )?(?:back )?(?:home|back|there|at work|to work|at the office|to the office|in)$", low)
    if m:
        return {"command": None,
                "say": "I can't tell where you are yet, so I can't do it when you get home. "
                       f"Give me a time - 'remind me at 6 to {m.group(1).strip()}' - and I'll do that."}
    m = re.match(r"remind me (?:to|that) (.+?) "
                 r"(?:at ([\w: ]+)|in (\d+) (minutes?|hours?))$", low)
    if m and re.search(r"\b(?:every|each)\b", m.group(1)):
        return _to_the_planner(text)    # a repeat is never set as a one-off
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
                    r"what(?:'s| is|s)? on my (?:task|todo|to-do|to do) list|(?:my )?to(?:-| )?do list|"
                    r"(?:read|show) (?:me )?my (?:todo|to-do|to do) list|"
                    r"what am i supposed to be doing)", low):
        return {"command": {"kind": "tasks"}, "say": None}

    # MOVING, RENAMING AND DROPPING A TASK (2026-10-07: "move call the
    # plumber to friday", "delete call the plumber", "rename call the
    # plumber to call joe" all went to the planner). Only when his words
    # name one open task: the same verbs are about notes, reminders and
    # meetings everywhere else.
    _task_tail = r"(?: task| one)?(?: (?:from|on|off) my (?:list|tasks|task list|to-?do list))?"
    m = re.fullmatch(r"(?:move|push|reschedule|bump|change|shift) (?:the )?(?:task )?(?P<w>.+?)" + _task_tail
                     + r" (?:to|till|until|for|back to) (?P<day>today|tomorrow|tonight|(?:this |next )?(?:monday|tuesday"
                       r"|wednesday|thursday|friday|saturday|sunday))", low) \
        or re.fullmatch(r"(?:make|set) (?:the )?(?:task )?(?P<w>.+?)" + _task_tail + r" (?:due|for) "
                        r"(?P<day>today|tomorrow|tonight|(?:this )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))", low)
    if m and _names_one_open_task(m.group("w")):
        said = m.group("day")
        if said.startswith("next "):
            asked = _ambiguous_next_weekday(said)
            if asked:
                return {"command": None, "say": asked}
        day = _spoken_day("today" if said == "tonight" else said)
        if day:
            return {"command": {"kind": "task_change", "which": m.group("w"), "deadline": day}, "say": None}
    m = re.fullmatch(r"(?:rename|retitle|reword) (?:the )?(?:task )?(?P<w>.+?)" + _task_tail + r" (?:to|as) (?P<new>.+)", low) \
        or re.fullmatch(r"change (?:the )?(?:task )?(?P<w>.+?)" + _task_tail + r" to say (?P<new>.+)", low)
    if m and _names_one_open_task(m.group("w")):
        return {"command": {"kind": "task_change", "which": m.group("w"),
                            "description": _as_he_said(text, m.group("new").strip())}, "say": None}
    m = re.fullmatch(r"(?:delete|remove|drop|cancel|scrap|forget about|get rid of|take) (?:the )?(?:task )?(?P<w>.+?)"
                     + _task_tail + r"(?: off(?: my (?:list|tasks|task list|to-?do list))?)?", low)
    # Not "cancel the first one": counting is about whatever she just read
    # out, and that is usually approvals.
    # "Cancel the passport task" has its own branch further down.
    if m and m.group("w") not in ("it", "that", "this", "everything", "all") \
            and not re.search(r" (?:task|one|item)(?: from (?:my|the) (?:task )?list)?$", low) \
            and not re.search(r"\b(?:first|second|third|last|latest|newest|oldest|next|other)\b", m.group("w")) \
            and _names_one_open_task(m.group("w")):
        return {"command": {"kind": "task_change", "which": m.group("w"), "drop": True}, "say": None}

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
    #
    # And that last line was wrong, found by talking to her: "list my
    # files" is not a question about her workspace at all. It answered
    # "(empty)" — true about a directory he has never opened, in reply to
    # a question about his own disk. The possessive was the whole signal
    # and it was being thrown away, exactly the way "can you read my
    # files" was being answered about the web browser. HERS below, HIS
    # after it.
    if re.fullmatch(r"(?:what|which) files (?:do you have|are there|"
                    r"have you got)|list your files|"
                    r"what(?:'s| is|s)? in (?:my |your )?workspace|"
                    r"show me your files", low):
        return {"command": {"kind": "file_list"}, "say": None}

    # "Read rename_files.py" — the sentence her OWN answer tells him to
    # say after she writes a script. It reached the planner, which is six
    # seconds and a guess, for something she can do in one call. A
    # filename is unmistakable: it has a suffix and no spaces, so this
    # cannot swallow "read me my tasks" or "read example.com".
    m = re.fullmatch(r"(?:read|open|show me)(?: me)? (?:the |my )?"
                     r"([\w.-]+\.[a-z0-9]{1,5})\s*\??", low)
    if m and not _spoken_url(m.group(1)):
        return {"command": {"kind": "file_read",
                            "path": _as_he_said(transcript, m.group(1)),
                            "anywhere": True}, "say": None}

    m = re.fullmatch(
        r"(?:what(?:'s| is|s)?|show me what(?:'s| is)?) (?:in|inside) "
        r"(?:my |the )?([a-z][a-z ]{2,20}?)(?: folder| directory)?\s*\??", low)
    if m and _a_place_she_knows(m.group(1)):
        return {"command": {"kind": "file_find",
                            "place": _a_place_she_knows(m.group(1))}, "say": None}

    # "Find me customer success jobs in Denver" is a JOB search. It was
    # compiled as a file search ("I looked in Desktop, Documents,
    # Downloads...") - the fluent wrong verb, which is the failure he
    # cannot detect (2026-09-22). Jobs are a search of the boards she
    # knows; a file is a file.
    m = re.fullmatch(
        r"(?:(?:can you|could you|please|go|hey) )?"
        r"(?:find|look for|search for|look up|show me|get me|any|are there any|what)(?: me)? "
        r"(?:some |any |new |more |a few |good |open |remote |local )*"
        r"(?P<role>[a-z][a-z /&+.'-]{1,60}?) (?:jobs|openings|positions|roles|job openings)"
        r"(?: (?:in|near|around|out of) (?:the )?(?P<where>[a-z][a-z .'-]{1,40}?))?"
        r"(?: for me| please| right now| today)?\s*\??", low)
    if m:
        command = {"kind": "jobs", "role": _as_he_said(transcript, m.group("role"))}
        if m.group("where"):
            command["where"] = _as_he_said(transcript, m.group("where"))
        return {"command": command, "say": None}

    # "Read me the landlord note": not a filename (no suffix), so the
    # read-a-file shape above did not take it and the planner did. A named
    # note, draft or document is found by name, and the not-found answer
    # is instant and honest instead of two minutes on her own model.
    m = re.fullmatch(
        r"(?:read|read me|open|show me|pull up|find)(?: me)? (?:the |my |that )?"
        # A bare possessive is not a name: "read me my notes" was a file
        # search for "my" (15 files matching my, 2026-09-24) while the
        # notes reader sat one rung down.
        r"(?P<what>[a-z][a-z0-9 '-]{1,40}?) "
        r"(?:note|draft|file|document|letter|memo|doc)s?\s*\??", low)
    if m and not _not_a_file(m.group("what")) and any(
            w not in ("me", "my", "your", "the", "all", "any", "those", "these", "our", "a")
            for w in m.group("what").split()):
        return {"command": {"kind": "file_find",
                            "query": _as_he_said(transcript, m.group("what"))},
                "say": None}

    # "DO I HAVE ANYTHING TOMORROW" is his calendar, never a file. `quick`
    # answers it when a feed answers, and with no feed it fell through to
    # here: "I could not find anything matching anything tomorrow. I looked
    # in Documents." The calendar's own answer says what it knows.
    m = re.fullmatch(r"(?:do i|have i|do we) (?:have|got) (?:anything|any plans|something|much|"
                     r"any meetings|any appointments|plans)(?: on| planned| scheduled| going on| booked)?"
                     r"(?:\s+(?:on\s+|this\s+)?(.+?))?\s*\??", low)
    if m:
        asked = _ambiguous_next_weekday(m.group(1) or "")
        if asked:
            return {"command": None, "say": asked}
        day, part = _spoken_when(m.group(1) or "today")
        if day:
            command = {"kind": "free_time", "day": day}
            if part:
                command["part"] = part
            return {"command": command, "say": None}
        stretch = re.sub(r"^(?:the |this )", "", str(m.group(1) or ""))
        if stretch in ("weekend", "week", "next week", "next few days", "next two weeks"):
            when = {"weekend": "this weekend", "week": "this week"}.get(stretch, stretch)
            return {"command": {"kind": "calendar_find_free", "when": when}, "say": None}
        return _to_the_planner(text)

    m = re.fullmatch(
        r"(?:find|look for|search for|do i have|have i got) "
        r"(?:a |an |any |my |the )?(?:files? |documents? )?"
        r"(?:called |named |about )?(.+?)\s*\??", low)
    if m and not _not_a_file(m.group(1)):
        return {"command": {"kind": "file_find",
                            "query": _as_he_said(transcript, m.group(1))},
                "say": None}

    if re.fullmatch(r"(?:list|show me) (?:my |all my )?files|"
                    r"what files do i have|my (?:recent )?files", low):
        return {"command": {"kind": "file_find"}, "say": None}

    # "Where is my lease" reached the planner and came back "I don't have
    # a lease saved anywhere I can check — no file storage or document
    # search has come back with anything." She has both. A model asked
    # about a store nothing in its context mentions DENIES THE STORE
    # EXISTS, and that is worse than an error: an error sends him back to
    # her, this sends him off to keep his files somewhere else.
    # WHERE HE LIVES and WHAT HIS NAME IS are his facts, on file. "Where do I
    # live" went to the file finder ("I could not find anything matching
    # do I live") and "spell my last name" waited two minutes on her own
    # model (2026-09-22).
    if re.fullmatch(r"where do i live|what(?:'s| is) my (?:address|home address|city|home ?town)|"
                    r"what city (?:am i in|do i live in)|where(?:'s| is) (?:my )?home", low):
        return {"command": None, "say": _where_he_lives()}
    m = re.fullmatch(r"(?:spell|how do (?:you|u) spell) my (?P<which>first|last|full|sur)?\s*name(?: for me)?", low)
    if m:
        return {"command": None, "say": _spell_his_name(m.group("which") or "full")}

    m = re.fullmatch(r"where(?:'s| is| are)? (?:my |the )?(.+?)\s*\??", low)
    if m and not _not_a_file(m.group(1)):
        return {"command": {"kind": "file_find",
                            "query": _as_he_said(transcript, m.group(1))},
                "say": None}

    # "How big is my downloads folder" spent 28 seconds compiling a
    # two-step plan — open File Explorer, read the properties dialog —
    # and asked for approval to run it. Every one of those numbers was
    # already in her hand.
    m = re.fullmatch(
        r"how (?:big|large) is (?:my |the )?([a-z ]+?)(?: folder| directory)?"
        r"\s*\??|how much (?:space|room) (?:is )?in (?:my |the )?"
        r"([a-z ]+?)(?: folder| directory)?\s*\??", low)
    if m:
        where = _a_place_she_knows(m.group(1) or m.group(2) or "")
        if where:
            return {"command": {"kind": "file_size", "place": where},
                    "say": None}

    # notifications
    if re.fullmatch(r"(?:check (?:my )?notifications?|any notifications?|"
                    r"what's new|anything new|notifications?)", low):
        return {"command": {"kind": "notify_check"}, "say": None}
    # "CLEAR MY SHOPPING LIST" (2026-10-07: to the planner). Every row is
    # cancelled, never deleted, through the verb that already does it.
    if re.fullmatch(r"(?:clear|empty|wipe|reset|delete everything on|clear out|empty out) (?:my |the )?"
                    r"(?:shopping|grocery) list", low):
        return {"command": {"kind": "shopping_off", "item": "everything"}, "say": None}
    if re.fullmatch(r"(?:clear|dismiss|acknowledge) (?:my |the )?notifications?", low):
        return {"command": {"kind": "notify_clear"}, "say": None}

    # A STANDING PERMISSION TO SEND IN HIS NAME is not taken off the air, for the
    # same reason standing authority is not: a television could say it. It is
    # typed (aletheia.conversation_authority.grant_from_words).
    if (re.search(r"(?:you can|you may|go ahead and|feel free to|you have my permission to)\b.*"
                  r"follow[- ]?up.*without (?:asking|checking)", low)):
        return {"command": None,
                "say": ("I won't take permission to send emails in your name by voice - anything in the room "
                        "could say it. Type it: python -m aletheia.conversations grant \"" + text.strip() + "\"")}

    # "Did they reply", "did the landlord get back to me", "any word from the
    # recruiter": read from the conversation she keeps, not guessed.
    m = re.fullmatch(r"(?:did|has|have) (.+?) (?:replied|reply|respond|responded|(?:gotten|got|get) back(?: to (?:me|us))?|"
                     r"written back|write back|answered|answer)(?: yet)?(?: to (?:me|us|my email))?"
                     r"(?: about .+)?", low)
    if not m:
        m = re.fullmatch(r"any (?:reply|replies|response|word|answer) (?:from|back from) (.+?)(?: yet)?", low)
    if m and not re.search(r"\bapplication\b", low):
        named = m.group(1).strip()
        which = "" if named in ("they", "them", "anyone", "anybody") else named
        # "Did anyone write back" with no conversation open is about his
        # applications, not a thread she keeps: it answered "there's no
        # conversation open right now" while an employer's reply sat on
        # the record (2026-09-22). "They" still means the last thread;
        # "anyone" with nothing open falls through to the fast lane's
        # employer-replies reader.
        if named in ("anyone", "anybody"):
            try:
                from aletheia import conversations
                if not conversations.all_threads():
                    m = None
            except Exception:  # noqa: BLE001
                pass
    if m and not re.search(r"\bapplication\b", low):
        return {"command": {"kind": "thread_status", **({"which": which} if which else {})}, "say": None}

    # "When am I free next week for a tour": a stretch of days and a purpose,
    # around his calendar. The single-day form below stays free_time.
    m = re.fullmatch(r"(?:when am i free|when are we free|when could i (?:fit in|do|schedule)(?: a| an)?|"
                     r"what times? (?:am i|are we) free|when do i have time)\s+"
                     r"(this week|next week|this weekend|the next few days|next few days|next two weeks)"
                     r"(?:\s+for (?:a |an |the )?(.+?))?", low)
    if m:
        command = {"kind": "calendar_find_free", "when": m.group(1).replace("the ", "")}
        if m.group(2):
            command["purpose"] = m.group(2).strip()
        return {"command": command, "say": None}

    # "AM I FREE FRIDAY AT 10" - a moment, not a day (2026-10-07: to the
    # planner). Either order, and a bare "at 10" is today, or tomorrow once
    # it has passed. A bare hour gets the same no-small-hours rule as a
    # reminder.
    m = (re.fullmatch(r"(?:am i|are we) (?:free|busy|available) (?:on |this )?(?P<day>[a-z]+) at (?P<time>[\w: ]+?)\s*\??", low)
         or re.fullmatch(r"(?:am i|are we) (?:free|busy|available) at (?P<time>[\w: ]+?)(?: (?:on |this )?(?P<day>[a-z]+))?\s*\??", low))
    if m:
        hhmm = _spoken_time(m.group("time"))
        day_word = m.group("day") or ""
        if hhmm and not _ambiguous_next_weekday(day_word):
            if day_word:
                day_iso = _spoken_day(day_word)
            else:
                at = _next_occurrence_iso(hhmm, bare_hour=_is_bare_hour(m.group("time")))
                day_iso, hhmm = at[:10], at[11:16]
            if day_iso:
                hour, minute = map(int, hhmm.split(":"))
                if day_word and _is_bare_hour(m.group("time")) and hour <= EARLIEST_BARE_HOUR:
                    hour += 12
                return {"command": {"kind": "free_time", "day": day_iso, "at": f"{hour:02d}:{minute:02d}"},
                        "say": None}

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

    # "MOM'S NUMBER IS 605 555 0123": "text mom" says "Tell me the number
    # once and I'll remember it", and telling her went to the planner
    # (2026-10-07). Same for an email address.
    m = re.fullmatch(r"(?:my )?([a-z][a-z' -]{0,30}?)'s (?:phone |cell |mobile |cell phone )?(?:number|phone) is "
                     r"(\+?[\d][\d ().-]{5,20}\d)", low)
    if m and m.group(1) not in ("my", "your", "his", "her"):
        return {"command": {"kind": "contact_add", "name": _as_he_said(transcript, m.group(1)).strip(),
                            "phone": m.group(2).strip()}, "say": None}
    m = re.fullmatch(r"(?:my )?([a-z][a-z' -]{0,30}?)'s (?:email|e-mail|email address) is "
                     r"(\S+@\S+\.\S+|\S+ at \S+ dot \S+)", low)
    if m and m.group(1) not in ("my", "your", "his", "her"):
        return {"command": {"kind": "contact_add", "name": _as_he_said(transcript, m.group(1)).strip(),
                            "email": m.group(2).strip().rstrip(".")}, "say": None}
    # "MY BIRTHDAY IS MARCH 3RD 1995" (2026-10-07: to the planner). One
    # fact about him, kept in her memory, read by "how old am I".
    m = re.fullmatch(r"(?:my birthday is|my birthday's|i was born on|i was born|my date of birth is|my dob is) "
                     r"(?:on )?((?:[a-z]+\.? \d{1,2}(?:st|nd|rd|th)?|\d{1,2}(?:st|nd|rd|th)? (?:of )?[a-z]+)(?:,? \d{4})?"
                     r"|\d{4}-\d{1,2}-\d{1,2})", low)
    if m:
        return {"command": {"kind": "remember", "domain": "identity", "key": "birthday",
                            "value": m.group(1).strip()}, "say": None}
    # "MY ADDRESS IS 123 MAIN ST, HARTFORD, SD": "where do I live" says "tell
    # me and I'll remember it", and telling her went to the planner
    # (2026-10-07). `_where_he_lives` reads exactly this line.
    m = re.fullmatch(r"(?:my (?:home )?address is|my address's|i live at) (\d+[\w .,#'-]{4,120})", low)
    if m:
        return {"command": {"kind": "remember", "domain": "identity", "key": "address",
                            "value": _as_he_said(text, m.group(1)).strip().rstrip(".")}, "say": None}

    # "MY EMAIL IS ..." / "MY PHONE NUMBER IS ...": "what's my email" says
    # "tell me and I'll remember it" (2026-10-07: telling her went nowhere).
    m = re.fullmatch(r"my (?:email|e-mail|email address) is (\S+@\S+\.\S+)", low)
    if m:
        return {"command": {"kind": "remember", "domain": "identity", "key": "email",
                            "value": m.group(1).rstrip(".")}, "say": None}
    m = re.fullmatch(r"my (?:phone|cell|mobile|cell phone|phone number|cell number|mobile number|number) is "
                     r"(\+?\d[\d ().-]{5,20}\d)", low)
    if m:
        return {"command": {"kind": "remember", "domain": "identity", "key": "phone",
                            "value": m.group(1).strip()}, "say": None}

    # private contact: "remember person bob smith bob at gmail dot com"
    m = re.match(r"remember (?:person|contact)\s+(.+?)\s+((?:\S+\s+at\s+\S.*|\S+@\S+))$", low)
    if m:
        return {"command": {"kind": "contact_add", "name": m.group(1).strip(),
                            "email": m.group(2).strip()}, "say": None}

    # "SAM'S NUMBER IS 555 123 4567", "save mom's number as ...", "Dana's
    # email is ..." (2026-10-07: all to the planner). His own number is the
    # profile's, never a contact called "my".
    _who = r"(?P<name>[a-z][a-z.-]*(?: [a-z][a-z.-]*){0,2}?)"
    _num = r"(?P<phone>\+?\(?\d[\d ().-]{6,18}\d)"
    _mail = r"(?P<email>\S+@\S+\.\S+|\S+ at \S+ dot \S+)"
    m = (re.fullmatch(r"(?:save|store|remember|put|add) " + _who + r"(?:'s)? (?:phone )?(?:number|phone|cell|mobile)"
                      r"(?: number)?(?: as| is| to|:)? " + _num, low)
         or re.fullmatch(_who + r"'s (?:phone )?(?:number|phone|cell|mobile)(?: number)? is " + _num, low)
         or re.fullmatch(r"add " + _who + r" to (?:my )?contacts(?: with| at| as)?(?: (?:the )?(?:phone )?(?:number|phone))? " + _num, low))
    if m and m.group("name").split()[0] not in ("my", "your", "the", "a", "his", "her", "their", "our"):
        return {"command": {"kind": "contact_add", "name": _as_he_said(text, m.group("name")).title()
                            if m.group("name").islower() and text.islower() else _as_he_said(text, m.group("name")),
                            "phone": m.group("phone")}, "say": None}
    m = (re.fullmatch(r"(?:save|store|remember|put|add) " + _who + r"(?:'s)? email(?: address)?(?: as| is| to|:)? " + _mail, low)
         or re.fullmatch(_who + r"'s email(?: address)? is " + _mail, low)
         or re.fullmatch(r"add " + _who + r" to (?:my )?contacts(?: with| at| as)?(?: (?:the )?email(?: address)?)? " + _mail, low))
    if m and m.group("name").split()[0] not in ("my", "your", "the", "a", "his", "her", "their", "our"):
        return {"command": {"kind": "contact_add", "name": _as_he_said(text, m.group("name")).title()
                            if m.group("name").islower() and text.islower() else _as_he_said(text, m.group("name")),
                            "email": m.group("email")}, "say": None}
    m = re.fullmatch(r"add " + _who + r" to (?:my )?contacts", low)
    if m and m.group("name").split()[0] not in ("my", "your", "the", "a"):
        name = _as_he_said(text, m.group("name"))
        name = name.title() if name.islower() else name
        return {"command": None,
                "say": f"What's {name}'s number or email? Say \"{name}'s number is ...\" and I'll keep it."}

    # "what do you still need from me?" - SETUP. Not the bare "what do you
    # need from me": that is the brief's fourth question, about what is
    # waiting on him (approvals, applications stopped on his answers), and
    # `quick` answers it in a file read. Said out loud it was sent here
    # instead, to a twenty-second live setup audit, while typing the same
    # sentence got the answer he meant - two doors, two answers.
    if re.fullmatch(r"(?:what do you still need(?: from me)?|"
                    r"what'?s left(?: to set up)?|am i done|"
                    r"what'?s still missing|setup status)", low):
        return {"command": {"kind": "setup_status"}, "say": None}
    # "IS MY EMAIL SET UP?" is about ONE thing. It reached the whole
    # checklist and he heard four of sixteen done and every step left.
    m = re.fullmatch(r"(?:is|are) (?:my |the |your )?(?P<what>[a-z][a-z ]{1,30}?) "
                     r"(?:set ?up|configured|connected|hooked up|working|ready)(?: yet)?"
                     r"|(?:have|did) (?:you|i|we) (?:set ?up|configured|connected) "
                     r"(?:my |the |your )?(?P<what2>[a-z][a-z ]{1,30}?)(?: yet)?", low)
    # "Is my internet working" is a question about the connection, which
    # `quick` answers by trying it - not the setup step "thinking with no
    # internet" (2026-10-07).
    if m and (m.group("what") or m.group("what2")) not in ("you", "u", "it", "everything", "all",
                                                            "internet", "wifi", "wi-fi", "network",
                                                            "connection", "internet connection"):
        return {"command": {"kind": "setup_status",
                            "about": _as_he_said(transcript, m.group("what") or m.group("what2"))},
                "say": None}

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

    # "REMIND ME ABOUT THE LICENSE TASK TOMORROW" is a reminder with a when,
    # not a lookup: it answered "I don't have anything remembered about 'the
    # license task tomorrow'" (2026-10-07).
    m = re.fullmatch(r"remind me (?:about|of) (.+?),? ((?:tomorrow|today|tonight|this (?:morning|afternoon|evening))"
                     r"(?: (?:morning|afternoon|evening|night))?(?: at [\w: ]+)?|on [a-z]+(?: at [\w: ]+)?|"
                     r"at [\w: ]+|in (?:\d+|an?|half an) (?:minutes?|mins?|hours?))", low)
    if m:
        when = m.group(2).replace("tonight", "today night").replace("this ", "today ")
        again = _interpret(f"remind me to {m.group(1)} {when}")
        if (again.get("command") or {}).get("kind") in ("remind_at",):
            again["command"]["text"] = _as_he_said(text, m.group(1).strip())
            return again
    m = re.match(r"(?:what do you know about|what have you got on|"
                 r"remind me about|tell me about) (.+)", low)
    # "What do you know about me" is not a lookup under the key "me" (it
    # answered "I don't have anything remembered about 'me'"); the fast
    # lane says the whole of what she holds about him.
    if m and m.group(1).strip() not in ("me", "myself", "me then", "yourself", "you"):
        return {"command": {"kind": "recall", "about": m.group(1).strip()},
                "say": None}

    # "Read me the DevRev email": the unread message that names them.
    m = (re.fullmatch(r"(?:read me|read|open|show me) (?:the |that |my )?(?P<which>[a-z0-9][a-z0-9 .&'-]{1,40}?) "
                      r"(?:email|e-mail|mail|message from them)", low)
         # "Read me the email FROM Stripe" (bottom rung 2026-09-24: to nobody).
         or re.fullmatch(r"(?:read me|read|open|show me) (?:the |that |my )?(?:email|e-mail|mail|message) from "
                         r"(?P<which>[a-z0-9][a-z0-9 .&'-]{1,40}?)", low))
    # "Read my email" is not an email from somebody called "my" (2026-10-07):
    # a word that names no sender is the inbox, and `email_check` reads it.
    if m and m.group("which") in ("my", "me", "the", "your", "all", "all my", "all the", "any", "some", "an", "new"):
        return {"command": {"kind": "email_check"}, "say": None}
    if m and m.group("which") not in ("latest", "last", "newest", "first", "new", "unread"):
        return {"command": {"kind": "email_read", "which": _as_he_said(transcript, m.group("which"))},
                "say": None}

    if re.fullmatch(r"(?:the |my )?(?:morning )?brief(?:ing)?|"
                    # The phrasings a person actually uses. "Give me the
                    # brief" and "brief me" both went to the planner.
                    r"(?:give me|read me|run) (?:the |my |a )?(?:morning |daily )?brief(?:ing)?|"
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
    # "Add call the bank to my to do list" fell to the planner (2026-10-07).
    m = re.fullmatch(r"(?:add|put|stick) (.+?) (?:on|to) (?:the |my )?(?:to ?do|to-do|task) list", low)
    if m:
        return _new_task(_as_he_said(transcript, m.group(1)).strip())
    m = re.match(r"(?:add|put|get|stick|throw) (.+?) (?:on|to) (?:the |my )?"
                 r"(?:shopping |grocery )?list$", low)
    if m and not re.search(r"(?:shopping|grocery) list$", low) and _TASK_VERB.match(m.group(1)):
        # "Add call the dentist to my list" went on the SHOPPING list
        # (2026-09-24). A thing to do is a task; a thing to buy is a purchase.
        return _new_task(m.group(1).strip())
    if m and _might_be_several(m.group(1)) and _a_plain_list(m.group(1)):
        # "Add eggs, bread and butter to my shopping list" asked for an
        # APPROVAL with no model (2026-10-07) - for the thing one item does
        # for free. A comma list, or single words joined by "and", is a list
        # the store itself splits the same way; only the doubtful shapes
        # ("eggs milk and bread") still go to the planner.
        return {"command": {"kind": "shopping_add",
                            "item": _as_he_said(transcript, m.group(1).strip())},
                "say": None}
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

    # THE SECOND ITEM COST HIM FOUR AND A HALF SECONDS AND AN APPROVAL.
    #
    #   > add milk to the shopping list   [0.1s] Added to the shopping list: milk.
    #   > add bread too                   [4.6s] 1 step ready - Add bread to
    #                                     the shopping list. Say approve to run it.
    #
    # The same act, one turn apart, with two completely different
    # experiences — and the slower one asks permission to do the thing the
    # faster one just did for free. Nobody says the whole sentence twice.
    #
    # Matched on what HE SAID last, never on her reply: her wording is
    # exactly the sort of thing that gets improved, and a pattern anchored
    # to it drifts the moment somebody rewrites the sentence.
    item = _also_item(low)
    if item and (not _might_be_several(item) or _a_plain_list(item)) and _just_added_to_the_list():
        return {"command": {"kind": "shopping_add",
                            "item": _as_he_said(transcript, item)},
                "say": None}

    if re.fullmatch(r"(?:what am i paying for|my subscriptions?|"
                    r"what subscriptions do i have)", low):
        return {"command": {"kind": "subscriptions"}, "say": None}

    # "What's my BANK balance" and "what do I have IN THE BANK" reached no
    # pattern, so `converse` answered them with no finance context and
    # invented one - "I have read-only access to your balances and
    # transactions", about a store with nothing in it. A question she can
    # answer from a store must never be left to a model without it.
    if re.fullmatch(r"(?:how much money do i have|what'?s my balance|"
                    r"my net worth|how am i doing financially"
                    r"|what'?s my bank balance|what'?s in (?:my|the) bank"
                    r"|what do i have in (?:my|the) bank"
                    r"|how much (?:do i have|money is there)"
                    r"(?: in (?:my|the) bank| in the bank)?"
                    r"|what are my (?:accounts|balances)"
                    r"|my (?:accounts|balances))", low):
        return {"command": {"kind": "money"}, "say": None}

    # AND THE SAME INVENTED SENTENCE CAME BACK FOR SPENDING. The comment
    # above records "I have read-only access to your balances and
    # transactions" being fixed for BALANCE phrasings; asked "what did I
    # spend this month" she said it again, word for word, about a store
    # holding zero accounts — and then offered to go and use that access.
    # An OFFER is a claim about ability, and inventing a SOURCE sounds
    # like helpfulness, which makes it harder to catch than inventing an
    # answer. Same store, same door.
    if re.fullmatch(r"(?:what (?:did|have) i spen[dt](?: .*)?"
                    r"|how much (?:did|have) i spen[dt](?: .*)?"
                    r"|what(?:'s| is| are)? my (?:spending|expenses|"
                    r"transactions)(?: .*)?"
                    r"|show me my (?:spending|transactions|expenses)(?: .*)?"
                    r"|where (?:did|is) my money (?:go|going)(?: .*)?)"
                    r"\s*\??", low):
        return {"command": {"kind": "money", "about": "spending"}, "say": None}

    if re.fullmatch(r"(?:when is the car due|car service|"
                    r"does the car need anything|check the car|"
                    # Mileage is the number on the record she already
                    # reads, and asking for it went to the planner.
                    r"(?:what(?:'s| is|s)? )?(?:my |the )?car'?s? "
                    r"(?:mileage|milage)|"
                    r"how many miles (?:are )?on (?:my|the) car|"
                    r"what(?:'s| is|s)? the mileage(?: on (?:my|the) car)?)", low):
        return {"command": {"kind": "car"}, "say": None}

    # HIS LONG MISSIONS, BY SAYING SO (aletheia.programs). An objective that
    # runs for weeks is a sentence; so is adding to it, confirming its draft,
    # and asking what it waits on. The draft is a model's; the yes is his, and
    # it is only ever this layer that reads "confirm my mission" as that yes -
    # the words that start it are matched here, never compiled.
    m = re.fullmatch(r"(?:(?:i want to |let's |lets |please )?(?:start|begin|create|make|open) )"
                     r"(?:a |my |the )?(?:new )?(?:(?:long|big|long-term|long term) )?mission"
                     r"(?: called| about| for| to)?[:,]? (.{3,})", low)
    if m and not re.fullmatch(r"(?:draft|now|again|please)", m.group(1).strip()):
        return {"command": {"kind": "mission_new", "objective": _as_he_said(transcript, m.group(1))},
                "say": None}
    if re.fullmatch(r"(?:yes[,]? )?(?:confirm|activate|launch|go ahead with|start) (?:the |my )?"
                    r"(?:(?:long|big|new) )?mission(?: draft| now)?(?:[,]? please)?", low):
        return {"command": {"kind": "mission_confirm"}, "say": None}
    m = re.fullmatch(r"(?:add (?:this )?to|for|on|about|update) (?:my|the) (?:(?:long|big) )?mission[:,]? (.{2,})"
                     r"|(?:my|the) (?:(?:long|big) )?mission[:,] (.{2,})", low)
    if m:
        return {"command": {"kind": "mission_add", "text": _as_he_said(transcript, m.group(1) or m.group(2))},
                "say": None}
    if re.fullmatch(r"what (?:are|r) we (?:still )?waiting (?:on|for)(?: now)?"
                    r"|what(?:'s| is|s) (?:my |the )?(?:(?:long|big) )?mission (?:still )?waiting (?:on|for)"
                    r"|what (?:are|is) (?:my |the )?(?:(?:long|big) )?missions? (?:still )?waiting (?:on|for)", low):
        return {"command": {"kind": "missions", "about": "waiting"}, "say": None}
    if re.fullmatch(r"how(?:'s| is|s) (?:my |the )?(?:(?:long|big) )?mission(?: going| coming along| doing)?"
                    r"|how are my (?:(?:long|big) )?missions(?: going)?"
                    r"|(?:my |the )?(?:(?:long|big) )?missions?(?: status)?|mission status|where(?:'s| is) my mission at", low):
        return {"command": {"kind": "missions"}, "say": None}

    # "STUDY THESE AND IMPROVE MY PROJECT." (aletheia.studies) - research that turns
    # into changes he decides on, then measurement. An ORDER to study AND improve
    # something of his: a question about a study ("how's the study going") starts
    # with a question word and is matched below, never here.
    if (not re.match(r"(?:how|what|why|when|where|which|who|is|are|did|does|do|can you tell)\b", low)
            and re.search(r"\b(?:stud(?:y|ied)|research|analy[sz]e|dig into|look (?:in)?to|learn from)\b", low)
            and re.search(r"\b(?:improve|do(?:ing)? (?:way |much |a lot )?better|make (?:it|ours|mine|my \w+|our \w+) better|"
                          r"better than (?:ours|mine|my|our))\b", low)
            and re.search(r"\b(?:my|our|ours|mine)\b", low)):
        return {"command": {"kind": "study_new", "words": _as_he_said(text, low)}, "say": None}
    m = re.fullmatch(r"(accept|reject|reshape|decline|turn down) (?:the |proposal |change |idea |hypothesis |number )?"
                     r"(first|second|third|fourth|fifth|top|last|\d)(?: one| idea| proposal| change| hypothesis)?"
                     r"(?:[:,]? (?:so that |to |and |but )?(.{3,}))?", low)
    if m and _a_study_is_open():
        choice = {"decline": "reject", "turn down": "reject"}.get(m.group(1), m.group(1))
        cmd = {"kind": "study_decide", "choice": choice, "which": m.group(2)}
        if m.group(3):
            cmd["words"] = _as_he_said(text, m.group(3))
        return {"command": cmd, "say": None}
    m = re.fullmatch(r"(keep|revert|undo|roll back|iterate on) (?:the |that |this )?(?:study |measured )?change"
                     r"(?: (?:from|in) the study)?|(iterate on|keep|revert) (?:it|that)(?: then)?", low)
    if m and _a_study_waits_for_a_verdict():
        verb = m.group(1) or m.group(2)
        choice = {"undo": "revert", "roll back": "revert", "iterate on": "iterate"}.get(verb, verb)
        return {"command": {"kind": "study_decide", "choice": choice}, "say": None}
    if re.fullmatch(r"(?:yes[,]? |ok(?:ay)?[,]? |sure[,]? )?(?:go ahead and )?(?:study|read) (?:them|those)(?: (?:too|then|now))?"
                    r"|confirm (?:the |those )?comparables", low) and _a_study_is_open():
        return {"command": {"kind": "study_confirm"}, "say": None}
    if re.fullmatch(r"how(?:'s| is|s) (?:the |my |our |your )?(?:study|research study)(?: (?:going|coming along|doing))?"
                    r"|(?:the |my )?study(?: status| update)"
                    r"|where (?:are we|is it) (?:with|on) the study", low):
        return {"command": {"kind": "studies"}, "say": None}
    if re.fullmatch(r"what did (?:you|the study|your study) (?:find|learn|measure)(?: out)?(?: (?:in|from|about) (?:the study|them|it))?"
                    r"|what(?:'s| is|s| are) (?:the )?(?:study'?s? )?findings", low) and _a_study_is_open():
        return {"command": {"kind": "studies", "about": "found"}, "say": None}
    if re.fullmatch(r"what should (?:we|i|you) change(?: (?:about|in|on) (?:it|my \w+|our \w+|the project))?"
                    r"|what (?:changes|proposals) (?:do you have|are there|did you come up with)"
                    r"|what do you (?:propose|suggest) (?:we |i )?change", low) and _a_study_is_open():
        return {"command": {"kind": "studies", "about": "change"}, "say": None}

    # "WORK ON MY PROJECTS." (aletheia.project_work) - the continuity brief's final
    # target, said the ways he says it. An ORDER to work, never a question about
    # the projects ("how are my projects" stays below). "Stop working on X" is a
    # drop, so only "keep/start/go" forms and the bare order are matched here.
    if re.fullmatch(r"(?:(?:can|could|would|will) (?:you|u) |i (?:want|need) (?:you )?to |let'?s |go |now |just )?"
                    r"(?:(?:go |get |start |keep |continue |carry on |get back to )(?:on )?)?"
                    r"(?:work(?:ing)?|crack(?:ing)?|mak(?:e|ing) progress|push(?:ing)?|grind(?:ing)?) on "
                    r"(?:all )?(?:my|our|the|his) (?:projects?|stuff|things|work|repos|code)"
                    r"(?: (?:for (?:a (?:while|bit)|me|now|(?:the next )?(?:an? )?(?:hour|half(?: an)? hour|\d+ minutes?))|"
                    r"now|today|tonight|"
                    r"while i'?m (?:gone|away|out)|please))*"
                    r"|(?:(?:can|could) (?:you|u) )?(?:get|do) some work done(?: on (?:my|our|the) (?:projects?|stuff))?"
                    r"(?: (?:for me|now|please))*"
                    r"|what (?:can|could) (?:you|u) get done(?: (?:right now|now|today|for me|without claude))*"
                    r"|(?:go |get )?(?:be )?productive(?: on (?:my|the) projects?)?"
                    r"|keep (?:going|working) on (?:my|the|our) (?:projects?|stuff|work)", low):
        minutes = None
        found = re.search(r"for (?:the next )?(an hour|half an hour|hour|half hour|(\d+) minutes?)", low)
        if found:
            minutes = int(found.group(2)) if found.group(2) else (30 if "half" in found.group(1) else 60)
        return {"command": {"kind": "work_projects", **({"minutes": minutes} if minutes else {})}, "say": None}
    if re.fullmatch(r"what (?:did|have) (?:you|u) (?:get|got|gotten|finish|finished|do|done) (?:done )?"
                    r"(?:on|with|for) (?:my|the|our) (?:projects?|stuff|work)(?: (?:today|so far|just now))?"
                    r"|how(?:'s| is|s| did) (?:the |your |my )?work(?:ing)? session (?:go(?:ing)?|doing)"
                    r"|how(?:'s| is|s) the work (?:on my projects )?going"
                    r"|what came of (?:the |your )?work(?:ing)? session"
                    r"|(?:give me )?(?:the |a )?work (?:session )?report", low):
        return {"command": {"kind": "work_report"}, "say": None}

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

    # HIS PROJECTS, BY SAYING SO (aletheia.charters). His words, 2026-09-10:
    # "Is it fluid tho I don't need a hard coded barkly area". So a new
    # project is a sentence, and so are a step and a drop. A step or a drop
    # must name a charter that EXISTS: "add eggs to the list" and "drop it"
    # are other sentences, and asking the store is how they are told apart —
    # the same reason "got the milk" asks the shopping list.
    m = re.fullmatch(r"(?:(?:start|make|create) )?(?:a )?new project"
                     r"(?: called| about| for| to)?[:,]? (.{3,})"
                     r"|(?:i (?:want|wanna|would like) to )?start (?:a )?(?:new )?project"
                     r"(?: called| about| for| to)?[:,]? (.{3,})", low)
    if m:
        idea = m.group(1) or m.group(2)
        return {"command": {"kind": "project_new", "idea": _as_he_said(transcript, idea)},
                "say": None}
    from aletheia import plans as _plans
    m = re.fullmatch(r"add (?:a step )?(.+?) (?:to|for) (?:the |my )?(.+?)"
                     r"(?: project| charter)?", low)
    if m:
        found, _why = _plans.find_charter(m.group(2))
        if found is not None:
            return {"command": {"kind": "project_step", "project": found["slug"],
                                "text": _as_he_said(transcript, m.group(1))}, "say": None}
    m = re.fullmatch(r"(?:drop|shelve|abandon|stop working on) (?:the |my )?(.+?)"
                     r"(?: project| charter)?", low)
    if m:
        found, _why = _plans.find_charter(m.group(1))
        if found is not None:
            return {"command": {"kind": "project_drop", "project": found["slug"]}, "say": None}

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
        # Plans with a person are not services either. "Cancel lunch with
        # sam" (2026-10-07) was prepared as a cancellation of a
        # subscription called "lunch with sam".
        r"|with|lunch|dinner|breakfast|brunch|coffee|drinks|call|date|party"
        r"|plans|trip|flight|booking|reservation|order|visit|interview"
        # No leading "the": `cancel (?:my |the )?` has already eaten it,
        # so "cancel the last one" arrives here as just "last one".
        r"|(?:first|second|third|fourth|last)(?: one)?"
        # A TIME OR A DAY IS NOT A SERVICE. "Cancel my 3pm" compiled
        # subscription_cancel for a service called "3pm" (2026-10-07).
        r"|\d{1,2}(?::\d\d)?\s*(?:am|pm|o'?clock)|\d{1,2}:\d\d|noon|midnight"
        r"|today|tonight|tomorrow|this (?:morning|afternoon|evening)|monday|tuesday|wednesday"
        r"|thursday|friday|saturday|sunday|weekend|lunch|dinner|breakfast|call|plans)\b", re.IGNORECASE)

    if re.fullmatch(r"cancel (?:my |the )?(?:\d{1,2}(?::\d\d)?\s*(?:am|pm|o'?clock)?|noon)"
                    r"(?: (?:today|tomorrow|meeting|appointment|call))?", low):
        return {"command": None,
                "say": "I can't cancel things on your calendar yet - I can only add holds to it. "
                       "If that's a reminder of mine, tell me what it's for and I'll turn it off."}
    # "MOVE MY DENTIST APPOINTMENT TO FRIDAY" (2026-10-07: to the planner,
    # which has no door to his calendar's events). Said plainly, unless the
    # words pick out one of his tasks, which can be moved.
    m = re.fullmatch(r"(?:move|reschedule|push|shift|bump) (?:my |the )?(?P<what>.*?(?:appointment|meeting|call|lunch|dinner"
                     r"|breakfast|interview|\d{1,2}(?::\d\d)?\s*(?:am|pm|o'?clock))(?: with [a-z' ]+?)?)(?: back)? (?:to|till|until|for) .+", low)
    if m and not _names_one_open_task(m.group("what")):
        return {"command": None,
                "say": "I can't move things on your calendar yet - I can only add holds to it. "
                       "Move it in your calendar, and if you want a hold at the new time, tell me when."}
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
    # "Who emailed me today" and "what's the last email I got" were answered
    # "I haven't checked your inbox yet - want me to?" (2026-09-23). A
    # question about the inbox IS the ask to look; she looks.
    if re.fullmatch(r"(?:check (?:my )?e?mail|any (?:new )?e?mails?|"
                    r"do i have (?:any )?(?:new )?e?mails?|what's in my inbox|"
                    r"who (?:e?mailed|has e?mailed|wrote to) me(?: today| this morning| overnight)?|"
                    r"(?:did|has) (?:anyone|anybody|somebody) (?:e?mail|e?mailed|written to) me(?: today)?|"
                    r"what(?:'s| is|s)? (?:the |my )?(?:last|latest|newest|most recent) e?mail(?: i got| i received)?|"
                    r"anything (?:new )?in (?:my|the) inbox|"
                    # "How many unread emails do I have", "read my latest
                    # email", "check my inbox" (2026-10-07: to a model).
                    r"how many (?:unread |new )?e?mails?(?: do i have| have i got| are there)?(?: unread| today)?|"
                    r"(?:read|read me|show me|open) (?:my |the )?(?:last|latest|newest|most recent|new) e?mails?|"
                    r"(?:read|show) (?:me )?(?:my )?(?:e?mails?|inbox)|"
                    r"check (?:my |the )?inbox|(?:any|do i have any) unread e?mails?)", low):
        return {"command": {"kind": "email_check"}, "say": None}

    # AN HOURLY REMINDER is a door she does not have (daily and weekly she
    # does). "Remind me to drink water every hour" planned for a hundred
    # seconds on her own model (2026-09-23); the honest answer is a sentence.
    m = (re.fullmatch(r"remind me (?:to |that )?(?P<what>.+?) every (?:(?:\d+|few|couple of|half an?|other) )?"
                      r"(?:hour|hours|minutes?|mins?|half hour)(?: or so)?", low)
         or re.fullmatch(r"remind me every (?:(?:\d+|few|couple of|half an?|other) )?(?:hour|hours|minutes?|mins?|half hour)"
                         r"(?: or so)? (?:to |that )(?P<what>.+)", low))
    if m and _every_minutes(low):
        return {"command": {"kind": "remind_every", "minutes": _every_minutes(low),
                            "text": _as_he_said(transcript, m.group("what").strip())}, "say": None}
    if m:
        what = _as_he_said(transcript, m.group("what"))
        return {"command": None,
                "say": f"How often - every hour, every two hours? Say it with a number, like "
                       f"'remind me every 2 hours to {what}', and I'll set it."}

    # "DELETE THE LAST TASK" planned for a minute on her own model for want
    # of a verb: the newest open task, cancelled, said back by name.
    m = re.fullmatch(r"(?:delete|remove|drop|cancel|scrap|get rid of) (?:the |my )?(?:last|latest|newest|most recent) task", low)
    if m:
        from aletheia import contracts   # `tasks` is already this module's
        rows = [t for t in tasks.all_tasks() if str(t.get("status")) not in contracts.TASK_TERMINAL]
        rows.sort(key=lambda t: str(t.get("created_at") or ""), reverse=True)
        if not rows:
            return {"command": None, "say": "There's no open task to remove."}
        newest = rows[0]
        return {"command": {"kind": "task_status", "id": str(newest["id"]), "state": "CANCELLED",
                            "note": "he asked to remove the last task"},
                "say": None}

    # "DELETE THAT NOTE" went to the planner (2026-10-07) one turn after he
    # made it. The newest note, forgotten by its own words, through the
    # verb that already tombstones notes - said back so he hears which.
    if re.fullmatch(r"(?:delete|remove|forget|scratch|get rid of|erase) (?:that|the last|my last|the latest|my latest"
                    r"|the newest|my newest|the most recent|my most recent) note", low):
        from aletheia import quick as _quick
        rows = _quick._notes(1)
        if not rows:
            return {"command": None, "say": "There's no note to delete."}
        return {"command": {"kind": "forget", "about": str(rows[0].get("text") or "")}, "say": None}

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

    # "Are you listening TO ME RIGHT NOW" is how the question is really
    # asked, and `are you listening` had to match the whole sentence, so
    # it reached the planner: nine and a half seconds, and an answer about
    # being a chat model — "whatever you say gets converted to text and
    # handed to me at the moment you send it" — which is plausible, is not
    # about Aletheia, and is not an answer about HIS microphone. He ruled
    # on this one himself; it is a question he is entitled to answer to
    # instantly, whatever else is happening.
    if re.fullmatch(r"(?:is (?:the |your )?(?:microphone|mic) (?:on|off|live|open)"
                    r"|are (?:you|u) listening(?: to me)?(?: right now| now)?"
                    r"|can (?:you|u) hear me(?: right now| now)?"
                    r"|(?:is )?(?:the |your )?(?:microphone|mic)(?: status| live)?"
                    r"|are (?:you|u) recording(?: me)?)\s*\??", low):
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
    # VOLUME is the same kind of key. "Turn the volume down" waited two
    # minutes on her own model for want of it (2026-09-22).
    m = re.fullmatch(r"(?:turn (?:the |it )?(?:volume |sound )?(?P<dir>up|down)(?: a (?:bit|little|notch))?|"
                     # "Turn up the volume" fell to the planner (2026-10-07).
                     r"turn (?P<dir3>up|down) (?:the )?(?:volume|sound|music)(?: a (?:bit|little|notch))?|"
                     r"(?:volume|sound) (?P<dir2>up|down)(?: a (?:bit|little|notch))?|"
                     r"(?P<louder>louder|turn it up|make it louder)|(?P<quieter>quieter|softer|make it quieter)|"
                     r"(?P<mute>mute(?: it| the sound| the music| the volume)?|shut it up|silence it)|"
                     r"(?P<unmute>unmute(?: it)?|sound back on))(?: please)?", low)
    if m:
        direction = m.group("dir") or m.group("dir2") or m.group("dir3")
        action = ("volume_up" if direction == "up" or m.group("louder")
                  else "volume_down" if direction == "down" or m.group("quieter")
                  else "mute")
        return {"command": {"kind": "music", "action": action}, "say": None}

    # DO NOT DISTURB is the one switch of hers this can honestly mean: her
    # own notices go quiet for a while (`notify_snooze`). Windows' Focus
    # Assist is not a door she has, and "turn on do not disturb" waited 78 s
    # on her own model to ask what he meant (2026-09-23).
    m = re.fullmatch(r"(?:turn on|enable|switch on|put me on|set|go|activate) (?:do not disturb|dnd|quiet mode|focus mode|"
                     r"silent mode)(?: mode)?(?: for (?P<n>\d+) (?P<unit>minutes?|mins?|hours?|hrs?))?"
                     r"|(?:don'?t|do not) (?:disturb|bother|interrupt) me(?: for (?P<n2>\d+) (?P<unit2>minutes?|mins?|hours?|hrs?))?"
                     r"|(?:quiet|hush|shush|mute your notifications)(?: for (?P<n3>\d+) (?P<unit3>minutes?|mins?|hours?|hrs?))?"
                     r"|(?:snooze|pause) (?:your |the |all )?(?:notifications|notices|alerts)(?: for (?P<n4>\d+) (?P<unit4>minutes?|mins?|hours?|hrs?))?",
                     low)
    if m:
        n = next((m.group(k) for k in ("n", "n2", "n3", "n4") if m.group(k)), "")
        unit = next((m.group(k) for k in ("unit", "unit2", "unit3", "unit4") if m.group(k)), "")
        minutes = int(n) * (60 if unit.startswith(("h",)) else 1) if n else 60
        return {"command": {"kind": "notify_snooze", "minutes": max(1, min(minutes, 60 * 24 * 7))},
                "say": None}

    # A LOST OBJECT is not a file. "Find my keys" planned for a minute and
    # came back "she does not know a folder called on my computer" (2026-09-23).
    m = re.fullmatch(r"(?:find|where(?:'s| are| is| did i (?:put|leave))|locate|look for) (?:my |the )?"
                     r"(?P<thing>keys|phone|wallet|glasses|remote|car|bag|purse|shoes|charger|headphones|earbuds|passport|watch)"
                     r"(?: please)?", low)
    if m:
        thing = m.group("thing")
        return {"command": None,
                "say": (f"I can't see where your {thing} are - I have no eyes in the room. "
                        if thing in ("keys", "glasses", "shoes", "headphones", "earbuds")
                        else f"I can't see where your {thing} is - I have no eyes in the room. ")
                       + "I can find files and places, and I can ring your phone if it's linked."}

    # A PHONE CALL is a door she does not have. "Call the dentist" waited
    # two minutes on her own model (2026-09-22) for a verb nothing here
    # owns; the honest answer names the three doors she does have.
    m = re.fullmatch(r"(?:call|phone|ring|ring up|dial|give (?:a )?call to) "
                     r"(?:my |the )?(?P<who>[a-z][a-z .'-]{1,40}?)"
                     r"(?: for me| now| please| back)?", low)
    if m and _is_a_person_to_ring(m.group("who")):
        who = _as_he_said(transcript, m.group("who"))
        return {"command": None,
                "say": f"I can't place phone calls from here. I can text or email {who}, "
                       "or remind you to call them - which would you like?"}

    # A VOLUME LEVEL is not a key. "Set the volume to 50" planned for a
    # minute on her own model and was refused with a list of action ids
    # (2026-09-23); up, down and mute are the keys she has.
    if re.fullmatch(r"(?:set|put|turn|change) (?:the )?(?:volume|sound) (?:to|at) (?:\d+|half|max|maximum|full|low|high)"
                    r"(?: ?%| percent)?", low):
        return {"command": None,
                "say": "I can't set the volume to a level - only up, down and mute, a notch at a time. "
                       "Say 'volume up' or 'volume down' and I'll press it."}

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
    # "What song is this" is the same honest half, asked the other way:
    # a media key does not tell her what is playing.
    if re.fullmatch(r"what(?:'s| is) (?:this|that|playing|this song|that song|the song)"
                    r"(?: song| called| playing)?(?: right now| now)?"
                    r"|(?:what|which) song is (?:this|that|playing|on)(?: right now| now)?"
                    r"|who (?:sings|is) this(?: song)?", low):
        return {"command": None,
                "say": "I can't see what's playing - the media keys only play, pause "
                       "and skip. The player's window has the name."}

    # HIS CHATGPT SUBSCRIPTION AS A SECOND WORKER. Granting it is a
    # deliberate act and stopping it is instant, the same asymmetry as
    # every other switch here.
    if re.fullmatch(r"(?:you can )?use (?:my )?chat ?gpt(?: for this| too| as well)?"
                    r"|(?:ask|check with) chat ?gpt (?:too|as well|for a second opinion)"
                    r"|turn on chat ?gpt|enable chat ?gpt"
                    # "You can open ChatGPT again" - the words he uses to lift his own stop
                    r"|(?:you can |it'?s (?:ok|okay|fine) to )?open(?:ing)? chat ?gpt(?: windows)? (?:again|is fine|is ok|is okay)"
                    r"|chat ?gpt (?:windows )?(?:are|is) (?:fine|ok|okay)(?: again)?", low):
        return {"command": {"kind": "chatgpt_on"}, "say": None}
    if re.fullmatch(r"(?:stop|quit|don'?t) using (?:my )?chat ?gpt"
                    r"|turn off chat ?gpt|disable chat ?gpt"
                    r"|(?:stop|no more) chat ?gpt"
                    # His words, 2026-09-12, twice: "stop opening up ChatGPT windows". They
                    # reached the planner with every model off (2026-09-24 battery).
                    r"|(?:stop|quit|don'?t keep|don'?t|no more|i said stop) opening(?: up)? (?:the |my )?chat ?gpt(?: windows?| tabs?)?"
                    r"|no (?:more )?chat ?gpt windows", low):
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
    # "TEXT MOM HAPPY BIRTHDAY" - no "that" between them, so the name ran
    # into the message: "I don't have a phone number for mom happy"
    # (2026-10-07). The longest leading words that name a contact he has,
    # or a one-word relation, are the person; the rest is the message.
    m = re.fullmatch(r"(?:send (?:a )?(?:text|message) to|text|message) (?P<rest>.+)", low)
    if m:
        words = m.group("rest").split()
        try:
            from aletheia import contacts as _contacts
            people = _contacts.all_contacts()
        except Exception:
            people = []
        for n in range(min(3, len(words) - 1), 0, -1):
            who = " ".join(words[:n])
            try:
                _contacts.resolve(who, people)
                known = True
            except Exception:
                known = n == 1 and who in _RELATIONS
            if known:
                return {"command": {"kind": "message_send", "to": who,
                                    "body": _as_he_said(text, " ".join(words[n:]))}, "say": None}
    # "SEND A MESSAGE TO DANA" names who and not what (2026-10-07: to the
    # planner). Asked for whole, the way the bare verbs are.
    # One word after a bare "text": "text bob happy birthday" is a stranger
    # and a message, and is not guessed at here.
    m = (re.fullmatch(r"send (?:a )?(?:text|message|text message) to (?P<who>[a-z][a-z']{1,20}(?: [a-z][a-z']{1,20})?)", low)
         or re.fullmatch(r"(?:send|message|text) (?P<who>[a-z][a-z']{1,20})(?: a (?:text|message))?", low))
    if m and m.group("who").split()[0] not in ("a", "the", "my", "him", "her", "them", "it", "that", "this", "me", "help",
                                                "money", "everything", "all", "email", "emails", "mail", "flowers",
                                                "invites", "invite", "reminders", "now", "back", "again", "off"):
        who = _as_he_said(text, m.group("who"))
        who = who.title() if who.islower() else who
        return {"command": None,
                "say": f"What should it say? Say \"text {who} that you're running late\" and I'll draft it for you to send."}

    # "Send an email to dana@example.com saying thanks for the call" went to
    # the planner - and with every frontier off, to her own model for two
    # minutes - because only "email X saying Y" was a shape (2026-09-22).
    m = re.match(r"(?:send (?:an? |the )?e?mail(?: to)?|e?mail|write (?:an? )?e?mail to|draft (?:an? |the )?e?mail(?: to)?"
                 # "Draft a reply to Stripe saying thanks" / "reply to Stripe saying
                 # thanks" / "write back to Stripe saying ..." - a reply is a
                 # draft to them, held like every other (bottom rung 2026-09-24).
                 r"|draft (?:a |the )?reply to|reply to|write back to|answer)\s+"
                 r"(.+?)\s+(?:that says|that|saying|and say|telling (?:him|her|them)|:)\s+(.+)", low)
    if m:
        return {"command": {"kind": "email_draft", "to": m.group(1).strip(),
                            "body": m.group(2).strip()}, "say": None}
    # "Send DANA an email saying I'm running late" - the name before the
    # noun, which is how he says it (2026-09-24, offline: to the planner).
    m = re.match(r"(?:send|draft|write)\s+(.+?)\s+(?:an? |the )?e?mail\s+(?:that says|that|saying|and say|"
                 r"telling (?:him|her|them)|:)\s+(.+)", low)
    if m and not re.search(r"\b(?:remind|reminder)\b", low):
        return {"command": {"kind": "email_draft", "to": m.group(1).strip(),
                            "body": m.group(2).strip()}, "say": None}

    # "Email the landlord about the listing": a CONVERSATION she carries - the
    # draft, the reply, the follow-up - rather than one message and forget.
    m = re.match(r"(?:e?mail|write to|reach out to|contact)\s+(.+?)\s+(?:about|regarding|asking about|to ask about)"
                 r"\s+(.+)", low)
    if m and not re.search(r"\b(?:remind|reminder)\b", low):
        return {"command": {"kind": "thread_draft", "to": m.group(1).strip(),
                            "about": m.group(2).strip()}, "say": None}

    # "Follow up with the landlord."
    m = re.fullmatch(r"(?:follow up|nudge|chase up|check in)(?: with| on)? (.+?)(?: for me)?", low)
    if m and not re.search(r"\b(?:remind|task|application)\b", low):
        return {"command": {"kind": "thread_followup", "thread": m.group(1).strip()}, "say": None}

    # BEFORE the browse pattern: "look into X" and "look at example.com" both
    # start with "look", and the browse branch would swallow the first, then
    # complain it heard no web address.
    m = re.match(r"(?:look into|research|find out(?: about)?|dig into|"
                 r"look up|what do you know about|tell me about|"
                 # "Search the web for the best tacos in Denver" went to the
                 # planner (2026-10-07); it is the same read-only research.
                 r"(?:search|look|check) (?:the web|online|the internet|google) (?:for|about)|google|"
                 r"search (?:for|up))\s+(.+)", low)
    if m and not low.endswith(" on youtube"):
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
            only = pending[0]
            if _asked_recently(only):
                return _approve_by_voice(only)
            # ONE pending is unambiguous about WHICH, not evidence that he
            # knows what it is. Read it back with its age and let him say
            # yes to the thing itself.
            #
            # AND RECORD THAT HE HAS BEEN TOLD, or this is a loop: the
            # guard asked whether the approval was REQUESTED recently, so
            # "approve that" came back with the same sentence, and so did
            # every other phrasing. She was telling him to say something
            # that did nothing. The age he hears stays the age of the
            # REQUEST — five days old is the fact that matters — and only
            # the "does he know what this is" test moves.
            #
            # AND AN OFFER IS A CLAIM ABOUT ABILITY. "Say approve that if
            # you still want it" was wrong a second way: his real pending
            # one is `intent.execute`, which is operator_always and may
            # NEVER be approved by voice — so the sentence sent him down a
            # path that ends in a refusal for a different reason. Ask the
            # gate first and say the true thing, including the thing she
            # CAN do: denying needs no gate, because denying is the safe
            # direction and refusing to deny would leave it sitting.
            allowed, why_not = approvable_by_voice(only)
            head = (f"The only thing waiting is from {_how_long_ago(only)}: "
                    f"{approval_label(only)}.")
            if not allowed:
                return {"command": None,
                        "say": (f"{head} I can't approve that one by voice - "
                                f"{why_not}, and anything in the room could "
                                f"say it. Approve it at the keyboard, or say "
                                f"deny that and I'll clear it.")}
            surfaced(only)
            return {"command": None,
                    "say": f"{head} Say approve that if you still want it."}
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
        r"(?:\s+(?:that|it|the pending one|(?P<which>the (?:last|latest|newest|most recent|first|oldest)(?: one)?)))?$", low)
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
        # "Deny the last one" names which of several: the newest asked, or
        # the oldest. It waited two minutes on her own model (2026-09-22).
        which = (asked_to_cancel.groupdict().get("which") or "") if asked_to_cancel else ""
        if which and len(pending) > 1:
            ordered = sorted(pending, key=lambda a: str(a.get("requested_at") or ""))
            chosen = ordered[0] if re.search(r"first|oldest", which) else ordered[-1]
            return {"command": {"kind": "deny", "id": chosen["id"],
                                "because": "denied by voice"}, "say": None}
        if len(pending) == 1:
            return {"command": {"kind": "deny", "id": pending[0]["id"],
                                "because": "denied by voice"}, "say": None}
        if not pending:
            # "Cancel it" right after "remind me at 3" means the reminder,
            # not the approval queue (bottom rung 2026-09-24: "Nothing is
            # waiting for approval" after setting one). His last ask, if it
            # can be taken back, is what he means.
            if asked_to_cancel and re.fullmatch(r"(?:cancel|scrap|drop)\s+(?:that|it)", low) \
                    and _last_ask_is_undoable():
                return {"command": {"kind": "undo"}, "say": None}
            # "Remember that my car is in spot 14" then "forget that" said
            # "Okay - nothing was waiting" and KEPT the note (2026-10-07).
            # With nothing pending, "that" is the note he just made.
            noted = re.match(r"(?:remember that|note that|make a note(?: that| of)?|take a note(?: that)?|"
                             r"jot down(?: that)?|write down(?: that)?)\s+(.+)",
                             _previous_ask().casefold().rstrip(".!"))
            if dropped_it and re.fullmatch(r"forget (?:it|that)", low) and noted:
                return {"command": {"kind": "forget", "about": noted.group(1)}, "say": None}
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

    # SMALL THINGS A PERSON SAYS TO A ROOM. "Flip a coin" and "spell
    # necessary" were kept for a model "when the big models are back"
    # (2026-10-07). Neither needs one.
    if re.fullmatch(r"(?:flip|toss) a coin|heads or tails", low):
        import secrets
        return {"command": None, "say": secrets.choice(("Heads.", "Tails."))}
    m = re.fullmatch(r"roll (?:a|one|an?) (?:die|dice|d(\d{1,3}))|roll (?:the )?dice|"
                     r"roll (two|2) dice|pick a (?:random )?number between (\d+) and (\d+)", low)
    if m:
        import secrets
        if m.group(3):
            lo, hi = sorted((int(m.group(3)), int(m.group(4))))
            return {"command": None, "say": f"{lo + secrets.randbelow(hi - lo + 1)}."}
        if m.group(2):
            a, b = 1 + secrets.randbelow(6), 1 + secrets.randbelow(6)
            return {"command": None, "say": f"{a} and {b} - {a + b}."}
        sides = int(m.group(1) or 6)
        if sides >= 2:
            return {"command": None, "say": f"{1 + secrets.randbelow(sides)}."}
    m = re.fullmatch(r"(?:how do (?:you|u|i) spell|spell|spell out|what(?:'s| is) the spelling of) "
                     r"(?!my |your |his |her |their )([a-z][a-z'-]{1,30})(?: for me)?\s*\??", low)
    if m:
        word = m.group(1)
        return {"command": None, "say": f"{word.capitalize()}: " + ", ".join(c.upper() for c in word if c.isalpha()) + "."}
    # A BARE "SET A REMINDER" / "ADD A TASK" / "TAKE A NOTE" went to the
    # planner, which with no model kept the sentence "for later" (2026-10-07).
    # She asks for the rest, and his next sentence fills it (above).
    bare = _BARE_ASK.fullmatch(low)
    if bare:
        return {"command": None, "say": _BARE_QUESTION[_bare_kind(bare)]}

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
    # "OK", "cool", "got it" with nothing waiting went to the planner and came
    # back "I could not plan that" (2026-10-07): a nod answered with an error.
    # With an approval pending, the yes/no rules above decide what it means.
    if _A_NOD.fullmatch(low) \
            and not any(a.get("state") == "PENDING" for a in policy.all_approvals()):
        return {"command": None, "say": "Okay."}
    # Said TO her about her. A line, not a model call; a complaint is the one
    # worth a question back, because it is a defect report.
    if re.fullmatch(r"(?:you(?:'re| are) (?:awesome|great|the best|amazing|a lifesaver|smart|good)|good job|"
                    r"nice work|well done|good girl|love you|i love you)(?: thea)?", low):
        return {"command": None, "say": "Thanks - that's nice to hear."}
    if re.fullmatch(r"(?:you suck|you(?:'re| are) (?:useless|stupid|dumb|terrible|bad|annoying|wrong again)|"
                    r"that(?:'s| is| was) (?:wrong|useless|terrible|not what i (?:asked|meant|wanted)))(?: thea)?", low):
        return {"command": None, "say": "Sorry. Tell me what I got wrong and I'll fix it."}

    m = re.match(r"(?:add a task|new task|task)\s*(?:to|:)?\s+(.+)", low)
    if m:
        return _new_task(m.group(1).strip())
    # "Add pay rent to my tasks for Friday" was refused as SPENDING by a
    # planner door (2026-10-07). A task with a day is a task with a deadline.
    m = re.fullmatch(r"(?:add|put) (?P<what>.+?) (?:to|on) (?:my |the )?(?:tasks?|task list|todos?|to-?dos?)"
                     r"(?: (?:for|by|on|due) (?P<day>.+))?", low)
    if m:
        what = _as_he_said(text, m.group("what").strip())
        return _new_task(f"{what} by {m.group('day')}" if m.group("day") else what)

    # "SET MY INTERVIEW WINDOW TO 2 TO 4": his hours, in his own words only.
    # A bare hour reads as an interview hour: 1 to 7 is the afternoon, 8 to
    # 11 the morning, 12 noon.
    m = (re.fullmatch(r"(?:set|make|change|move) (?:my )?interview (?:window|hours|times) (?:to |as |from )?"
                      r"(?P<a>[\w:]+(?: ?[ap]m)?) (?:to|until|till|-|and) (?P<b>[\w:]+(?: ?[ap]m)?)"
                      r"(?: (?P<tz>central|eastern|mountain|pacific))?", low)
         or re.fullmatch(r"(?:i can (?:do |take |have )?interviews?|interviews? (?:are|is) (?:ok|fine|good)|"
                         r"i(?:'m| am) (?:free|available) for interviews?) (?:from |between )?"
                         r"(?P<a>[\w:]+(?: ?[ap]m)?) (?:to|until|till|-|and) (?P<b>[\w:]+(?: ?[ap]m)?)"
                         r"(?: (?P<tz>central|eastern|mountain|pacific))?", low))
    if m:
        window = _interview_hours(m.group("a"), m.group("b"))
        if window:
            command = {"kind": "interview_window_set", "start": window[0], "end": window[1]}
            zone = {"central": "America/Chicago", "eastern": "America/New_York", "mountain": "America/Denver",
                    "pacific": "America/Los_Angeles"}.get(m.group("tz") or "")
            if zone:
                command["timezone"] = zone
            return {"command": command, "say": None}
    if re.fullmatch(r"what(?:'s| is) my interview (?:window|hours|times)(?: set to)?|are (?:you|u) booking interviews"
                    r"|what(?:'s| is) the interview (?:switch|booking) set to", low):
        return {"command": {"kind": "interview_status"}, "say": None}

    # "POST <picture> TO INSTAGRAM SAYING ...": one post, his approval
    # (instagram_post is world-tier). "What have you posted to Instagram" is
    # her own ledger. The picture is an https address OR a file on his PC -
    # his content is files here, so a rule that only took a URL took nothing
    # he owns. A bare word is NOT a file: the token has to look like one (a
    # picture or video extension), or nothing here matches and the sentence
    # goes on to the planner rather than being guessed into a post.
    m = re.fullmatch(r"(?:post|publish|put) (?P<media>https?://\S+|\"[^\"]+\"|\S+\.(?:jpe?g|png|webp|bmp|gif|tiff?|mp4|mov|m4v))"
                     r" (?:to|on) instagram"
                     r"(?: (?:saying|with the caption|captioned|with the words|with) (?P<cap>.+))?", low)
    if m:
        said = m.group("media")
        # Take it back out of the ORIGINAL text: a path and a URL are both
        # case-sensitive and `low` has destroyed that.
        exact = re.search(re.escape(said), text, flags=re.IGNORECASE)
        command = {"kind": "instagram_post",
                   "media": (exact.group(0) if exact else said).strip().strip('"'),
                   "caption": _as_he_said(text, m.group("cap").strip()) if m.group("cap") else ""}
        return {"command": command, "say": None}
    if re.fullmatch(r"what (?:have (?:you|u)|did (?:you|u)) post(?:ed)? (?:to|on) instagram(?: today| lately| so far)?"
                    r"|(?:did|has) (?:the |my )?(?:instagram )?post go (?:out|up)(?: on instagram)?"
                    r"|what(?:'s| is) (?:been )?posted (?:to|on) instagram", low):
        return {"command": {"kind": "instagram_posts"}, "say": None}

    # "OPEN YOUTUBE" / "open the Thea page": a page on his screen is his tap
    # (open_page), and a site he names by one word is in a small table -
    # nothing else is guessed into an address (bottom rung 2026-09-24:
    # the rules compiled "Open youtube in the browser" for approval).
    m = re.fullmatch(r"(?:open|open up|go to|bring up|pull up|launch) (?P<site>[a-z][a-z ]{1,24}?)"
                     r"(?: for me| please| in the browser| in a tab)?", low)
    if m:
        try:
            from aletheia import open_it as _open
            known = m.group("site").strip().casefold()
            if known in _open.KNOWN_SITES or known.removeprefix("the ").strip() in _open.KNOWN_SITES:
                return {"command": {"kind": "open_page", "which": known}, "say": None}
        except Exception:
            pass

    # "SEARCH YOUTUBE FOR CAT VIDEOS" - YouTube's own results page, opened
    # in his browser (2026-10-07: to the planner).
    m = (re.fullmatch(r"(?:search|look up|find) (?P<q>.{2,80}?) on youtube", low)
         or re.fullmatch(r"(?:search youtube for|youtube search(?: for)?|look on youtube for) (?P<q>.{2,80})", low))
    if m:
        return {"command": {"kind": "open_page", "which": "youtube search " + _as_he_said(text, m.group("q").strip())},
                "say": None}

    # "CANCEL THE PASSPORT TASK": a task he named, cancelled - the same
    # lookup "mark the passport one done" uses (bottom rung: no verb).
    m = re.fullmatch(r"(?:cancel|drop|scrap|remove|delete|kill) (?:the |my )?(?P<what>.+?)(?: task| one| item)"
                     r"(?: from (?:my|the) (?:task )?list)?", low)
    if m and m.group("what") not in ("that", "it", "this"):
        try:
            from aletheia import intercom as _ic
            found, why = _ic._one_task(_as_he_said(text, m.group("what")))
        except Exception:
            found, why = None, ""
        if found is not None:
            return {"command": {"kind": "task_status", "id": str(found["id"]), "state": "CANCELLED",
                                "note": "cancelled by voice"}, "say": None}
        if why:
            return {"command": None, "say": str(why)}

    # "MOVE THE DENTIST TO 4": the reminder he named, at the new time.
    m = re.fullmatch(r"(?:move|push|change|shift) (?:the |my )?(?P<what>.+?)(?: reminder)? to (?:at )?(?P<time>[\w: ]+?)"
                     r"(?: instead| please)?", low)
    if m and m.group("what") not in ("that", "it", "this"):
        hhmm = _spoken_time(m.group("time"))
        try:
            from aletheia import intercom as _ic
            found, _why = _ic._one_reminder(_as_he_said(text, m.group("what")))
        except Exception:
            found = None
        if hhmm and found is not None:
            said_text = str((found.get("command") or {}).get("text") or m.group("what"))
            return {"command": {"kind": "remind_at", "at": _next_occurrence_iso(hhmm, bare_hour=_is_bare_hour(m.group("time"))),
                                "text": said_text, "replaces": said_text}, "say": None}

    # "MAKE ME A WORD DOCUMENT CALLED NOTES WITH THE TEXT HELLO": a document
    # with words he already has (doc_make; the planner is for authoring).
    m = re.fullmatch(r"(?:make|create|write|save)(?: me)? (?:a |an )?(?:new )?(?:word |text )?(?:document|doc) "
                     r"(?:called|named) (?P<name>[\w][\w .-]{0,60}?) (?:with the text|with the words|with|containing|that says|saying) "
                     r"(?P<body>.+)", low)
    if m:
        name = m.group("name").strip()
        path = name if name.lower().endswith((".docx", ".txt", ".md")) else f"{name}.docx"
        return {"command": {"kind": "doc_make", "path": path,
                            "content": [_as_he_said(text, m.group("body").strip())]}, "say": None}

    # "MAKE THAT 4" after "remind me at 3 to call the dentist": the same
    # reminder, moved. The previous ask is read back from the thread and
    # re-interpreted; only a reminder is moved this way (bottom rung
    # 2026-09-24: it went to nobody).
    m = re.fullmatch(r"(?:make (?:that|it)|change (?:that|it) to|move (?:that|it) to|actually,? make (?:that|it)|"
                     r"no,? make (?:that|it))\s+(?:at )?(?P<time>[\w: ]+?)(?: instead| please)?", low)
    if m:
        moved = _moved_reminder(text, m.group("time"))
        if moved:
            return moved

    # "UNDO THAT" is his word over her own ledger (bottom rung, 2026-09-24:
    # it went to nobody). A study verdict's "undo the change" is matched
    # further down and is a different verb.
    m = re.fullmatch(r"(?:undo|take back|reverse) (?:that|it|this|the last (?:thing|one)(?: you did)?)"
                     r"|undo|take that back"
                     r"|undo (?!(?:the |that |this )?(?:study |measured )?change\b)"
                     r"(?:the |that |what you did with (?:the |my )?)(?P<which>[a-z0-9 '-]{2,40}?)"
                     r"(?: you (?:added|made|wrote|did|noted))?", low)
    if m:
        command = {"kind": "undo"}
        if m.group("which"):
            command["which"] = _as_he_said(text, m.group("which").strip())
        return {"command": command, "say": None}

    # ANNOUNCEMENTS ARE HER SWITCH (bottom rung, 2026-09-24: "turn
    # announcements off" fell through to nobody).
    m = re.fullmatch(r"(?:turn |switch )?(?:the )?announcements? (?P<on>on|off)"
                     r"|(?P<start>start announcing(?: things)?|announce things again|announcements back on)"
                     r"|(?P<stop>stop announcing(?: things)?|stop talking (?:to me )?unless i ask|no more announcements)", low)
    if m:
        on = (m.group("on") == "on") if m.group("on") else bool(m.group("start"))
        return {"command": {"kind": "announce_set", "on": on}, "say": None}

    # A HOLD ON HIS CALENDAR, in her own model: "put dinner with Sam on my
    # calendar Friday at 7", "hold Friday at 10 for the tour". Nothing is
    # sent and no live calendar is written; it is the reversible half.
    _cal_days = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|today)"
    held_by = [re.fullmatch(r"(?:put|add|pencil in|pencil|schedule|book) (?P<title>.+?) (?:on|in|to|into|onto) my calendar"
                      r"(?: for| on| this)? ?(?P<day>" + _cal_days + r")?(?: (?P<part>morning|afternoon|evening|night))?"
                      r"(?: at (?P<time>[\w: ]+?))?", low),
               # "Add lunch with Dana Friday at noon to my calendar": the day and
               # the time said BEFORE the calendar (2026-10-07, fell to the planner).
               re.fullmatch(r"(?:put|add|pencil in|pencil|schedule|book) (?P<title>.+?)(?: on| this| for)? (?P<day>" + _cal_days
                         + r")(?: (?P<part>morning|afternoon|evening|night))?(?: at (?P<time>[\w: ]+?))?"
                         r" (?:on|in|to|into|onto) my calendar", low),
         re.fullmatch(r"(?:put|add|pencil in|pencil|schedule|book) (?P<title>.+?) at (?P<time>[\w: ]+?)"
                         r"(?: (?P<day>" + _cal_days + r"))?(?: (?P<part>morning|afternoon|evening|night))?"
                         r" (?:on|in|to|into|onto) my calendar", low),
         re.fullmatch(r"hold (?:on |this )?(?P<day>" + _cal_days + r")(?: (?P<part>morning|afternoon|evening|night))?"
                         r"(?: at (?P<time>[\w: ]+?))? for (?P<title>.+)", low)]
    # The shape that reads the most of it as a day and a time, and the least
    # as title: "add lunch Friday at noon to my calendar" also fits the first
    # pattern with the day inside the title, and "dentist at 3 tomorrow" fits
    # one with "at 3" inside it.
    held_by = [h for h in held_by if h and (h.group("day") or h.group("time"))]
    m = max(held_by, key=lambda h: (bool(h.group("day")) + bool(h.group("time")), -len(h.group("title"))),
            default=None)
    # "ADD DENTIST APPOINTMENT FRIDAY AT 2" (2026-10-07: to the planner)
    # names no calendar, and an appointment, meeting or dinner on a day
    # is nothing else. Not "book": that is somebody else's diary.
    m = m or re.fullmatch(r"(?:add|schedule|put|pencil in|set up) (?:a |an |my )?"
                          r"(?P<title>[a-z' ]*?(?:appointment|meeting|lunch|dinner|breakfast|call|interview|party"
                          r"|date|class|practice|haircut|checkup|check-up)(?: with [a-z' ]+?)?)"
                          r"(?: on| this| for)? (?P<day>" + _cal_days + r")(?: (?P<part>morning|afternoon|evening|night))?"
                          r"(?: at (?P<time>[\w: ]+?))?", low)
    # "BLOCK OFF FRIDAY AFTERNOON" (2026-10-07: to the planner): a hold
    # called Busy for that part of that day, the same reversible hold.
    if not m:
        b = re.fullmatch(r"(?:block|block off|block out|keep|hold) (?:my )?(?P<day>" + _cal_days + r")"
                         r"(?: (?P<part>morning|afternoon|evening|night))?(?: free| clear| open)?", low)
        if b:
            held = _calendar_hold(text, "Busy", b.group("day"), b.group("part"), None)
            if held:
                held["command"]["minutes"] = 60 if not b.group("part") else (180 if b.group("part") != "night" else 120)
                return held
    if m:
        held = _calendar_hold(text, m.group("title"), m.group("day") or "today", m.group("part"), m.group("time"))
        if held:
            return held

    # A FILE WITH TEXT HE ALREADY HAS: "write a file called notes.md with
    # hello". Reversible, in her workspace; the planner is for authoring.
    m = re.fullmatch(r"(?:write|create|make|save) (?:me )?(?:a |an )?(?:new )?(?:text )?file (?:called|named) "
                     r"(?P<name>[\w][\w.-]{0,60}) (?:with|containing|that says|saying|with the text|that reads) "
                     r"(?P<body>.+)", low)
    if m:
        name = m.group("name") if "." in m.group("name") else m.group("name") + ".txt"
        return {"command": {"kind": "file_write", "path": name,
                            "text": _as_he_said(text, m.group("body").strip())}, "say": None}

    # WHERE HE PARKED. "I parked on level 3" went to the planner and
    # "where did I park" to a model (2026-10-07). It is a note, in his
    # words, and `quick` reads the newest one back.
    m = re.fullmatch(r"(?:i(?:'ve| have)? parked|i'm parked|my car is(?: parked)?|the car is(?: parked)?)"
                     r" (?:on|at|in|by|near|outside|behind|across from|next to) .+", low)
    if m:
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # A FACT ABOUT HIM, SAID AS ONE. "My favorite color is blue", "my wifi
    # password is ...", "Jess's birthday is March 3" went to the planner
    # (2026-10-07). Kept as a note in his words, which is what `quick`
    # reads back. Only keys that name a fact - a favourite, a size, a code,
    # a number, someone's name or birthday - so "my head is killing me"
    # and "my computer is slow" are never filed as facts. His own name,
    # address, email, phone and birthday have their own patterns.
    m = re.fullmatch(r"(?:my |our )?(?P<key>(?:favou?rite|fave) [a-z ]{2,25}|[a-z][a-z' ]{0,30}?(?:'s|s') (?:name|birthday|anniversary)"
                     r"|blood type|shoe size|shirt size|ring size|pants size|dress size|wifi(?: password| name)?|wi-fi(?: password)?"
                     r"|gate code|door code|garage code|locker (?:number|combination)|license plate|plate number"
                     r"|anniversary|account number|member(?:ship)? number|policy number) (?:is|are) (?P<value>.{1,80})", low)
    if m and not re.search(r"\b(?:what|who|when|where|why|how|not|wrong)\b", m.group("key") + " " + m.group("value")[:12]) \
            and not low.startswith(("what", "who", "when", "where", "how", "why")):
        if re.search(r"pass(?:word|code|phrase)", m.group("key")):
            # `sensitivity` blanks a password out of every record she
            # keeps, so a note would read back "[redacted]". Said, not faked.
            return {"command": None, "say": _NO_PASSWORDS}
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "Delete my last note" (2026-10-07: to the planner). The newest note,
    # by its own words, through the same `forget` the rest of her memory
    # uses - the journal keeps it and a tombstone hides it.
    if re.fullmatch(r"(?:delete|remove|forget|scratch|erase|undo) (?:my |the |that )?(?:last|latest|most recent|newest) note", low):
        from aletheia import quick
        newest = next(iter(quick._notes(limit=1)), None)
        if not newest:
            return {"command": None, "say": "You don't have any notes."}
        return {"command": {"kind": "forget", "about": str(newest.get("text") or "").strip()}, "say": None}

    # LONGEST ALTERNATIVE FIRST. Python's alternation takes the first that
    # matches, so "note" won and the note read "that Dana called".
    # "Make a note that the roof leaks" waited two minutes on her own model
    # with every frontier off (2026-09-22); it is the same note.
    # "MY NAME IS CALEB": she answered "what's my name" with "Tell me and
    # I'll remember it", and telling her went to the planner - which, with
    # no model, kept the sentence "for later". A name is one line in her
    # memory of him; two to four words is a full name, one is what he goes by.
    # "MY ZIP CODE IS 80202": the weather asks for his postcode, and telling
    # her went to the planner. Five digits are a fact, not a plan.
    m = re.fullmatch(r"(?:my (?:zip|zip code|zipcode|postcode|postal code) is|my (?:zip|postcode)'s|"
                     r"i live in|i'm in|i am in) (\d{5}(?:-\d{4})?)", low)
    if m:
        return {"command": {"kind": "remember", "domain": "identity", "key": "postal_code",
                            "value": m.group(1)}, "say": None}
    m = re.fullmatch(r"(?:my name is|my name's|you can call me|please call me|call me) "
                     r"([a-z][a-z'\-]*(?: [a-z][a-z'\-]*){0,3})", low)
    if m and not re.match(r"(?:not|what|who|wrong|spelled|spelt|on|in|the|a|an|at|missing|still|also|now|being"
                          r"|already|me|it|that|this)\b", m.group(1)) \
            and not re.fullmatch(r"(?:back|later|tomorrow|tonight|now|soon|when .+|if .+|at .+|in .+)", m.group(1)) \
            and not (low.startswith("call me") and len(m.group(1).split()) > 1):
        name = _as_he_said(text, m.group(1)).strip()
        name = " ".join(w[:1].upper() + w[1:] if w.islower() else w for w in name.split())
        key = "full_name" if len(name.split()) >= 2 else "operator_name"
        return {"command": {"kind": "remember", "domain": "identity", "key": key, "value": name}, "say": None}
    # "DELETE ALL MY NOTES" is not done on one sentence (2026-10-07: to the
    # planner): one note at a time, each forgotten by its words.
    if re.fullmatch(r"(?:delete|forget|erase|clear|remove|wipe) (?:all|every one of|everything in) (?:of )?(?:my |the |your )?notes"
                    r"|(?:clear|wipe|empty) (?:my |the |your )?notes", low):
        return {"command": None,
                "say": "I won't wipe every note on one sentence. Say \"forget\" and what the note says, "
                       "or \"delete my last note\", and I'll take them off one at a time."}
    m = re.match(r"(?:make a note(?: that| of|:)?|take a note(?: that|:)?|jot down(?: that)?|"
                 # "Write a note that the car needs oil" (2026-10-07: to the planner).
                 r"(?:write|leave|add) (?:me )?a note(?: that| saying| of|:)?|"
                 # "Note: buy a card for Dana" missed this (a colon, not a
                 # space), reached the planner and was refused as SPENDING
                 # (2026-10-07). Writing a line down commits nothing.
                 r"note that|note|write down that|write down|log)(?:\s*:\s*|\s+)(.+)", low)
    if m:
        return {"command": {"kind": "note", "text": m.group(1).strip()}, "say": None}
    # "Remember that my landlord is Mr Okafor" is the same note. With every
    # frontier off (2026-09-23) it was compiled by a rule into a plan that
    # waited for his approve - to write one line in her own store. "Remember
    # to call mom" is a reminder and stays with the reminder shapes above.
    # WHAT THE HUNT STEERS BY, in his words (2026-09-23 night sweep: each of
    # these went to a planner nobody could run). A sentence about what he
    # wants, will not do, wants to be paid, or when he could start is one
    # line in his profile, and the reply says what she steers by now.
    if re.fullmatch(r"what (?:do|are) (?:you|u) (?:steer(?:ing)? by|going by|going on|looking for now|looking for these days)"
                    r"|what are my (?:job )?preferences|what have i told (?:you|u) to (?:look for|avoid|leave out)"
                    r"|what am i (?:looking for|after)(?: now)?", low):
        return {"command": {"kind": "preferences"}, "say": None}
    # "Add Sales Engineer to the roles" / "also look for sales engineer jobs":
    # a role he names is hunted for beside the ones his resume is for.
    m = re.fullmatch(r"(?:add|put|include) (.+?) (?:to|in|on) (?:the |my )?(?:roles|role list|list of roles|job roles|hunt|job hunt|search)"
                     r"|(?:also|and also|and) (?:look for|apply (?:to|for)|hunt for|go after|search for|consider|try) (.+?) (?:roles|jobs|positions|openings)", low)
    if m and (m.group(1) or m.group(2)):
        return {"command": {"kind": "preference_set", "field": "roles_added",
                            "value": (m.group(1) or m.group(2)).strip()}, "say": None}
    m = re.match(r"(?:only (?:apply (?:to|for)|look for|look at|go for|go after|take|consider|send me) |i only want )(.+)", low)
    if m and not m.group(1).startswith(("if ", "when ")):
        return {"command": {"kind": "preference_set", "field": "work_wanted",
                            "value": "only " + m.group(1).strip()}, "say": None}
    m = re.match(r"(?:don'?t|do not|never|no longer|stop) (?:apply (?:to|for)|applying (?:to|for)|look at|go for|send me|consider) (.+)"
                 r"|no more (.+?)(?: jobs| roles| positions| work)?$", low)
    if m and (m.group(1) or m.group(2)) and not re.fullmatch(r"(?:jobs|anything|work|things|for (?:today|now)|today|now)", (m.group(1) or m.group(2)).strip()):
        return {"command": {"kind": "preference_set", "field": "work_not_wanted",
                            "value": (m.group(1) or m.group(2)).strip()}, "say": None}
    m = re.match(r"(?:raise|set|change|make|put|bump|lower|drop) my (?:minimum|min|floor|lowest|base)? ?(?:salary|pay|comp|compensation)(?: floor| minimum)? to (.+)"
                 r"|my (?:minimum|min|lowest) (?:salary|pay) is (?:now )?(.+)", low)
    if m:
        return {"command": {"kind": "preference_set", "field": "desired_pay",
                            "value": (m.group(1) or m.group(2)).strip()}, "say": None}
    m = re.match(r"(?:i can start|i could start|i(?:'m| am) (?:free|available) to start|i(?:'m| am) available from|my notice period is|my start date is|i(?:'m| am) available) (.+)", low)
    if m:
        return {"command": {"kind": "preference_set", "field": "notice_period", "value": m.group(1).strip()}, "say": None}
    m = re.match(r"remember(?: that|:)?\s+(?!to\b|me\b)(.+)", low)
    if m and not re.match(r"(?:the |my )?(?:last|previous|earlier)\b", m.group(1)):
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


_BARE_ASK = re.compile(
    r"(?:can you |could you |please |i want to |i need to |let'?s )?"
    r"(?:(?P<remind>set (?:a |me a )?reminder|remind me|create a reminder|new reminder|add a reminder)"
    r"|(?P<task>add a task|new task|create a task|add something to my (?:to ?do|task) list|add a to ?do)"
    r"|(?P<note>take a note|make a note|new note|create a note|write something down|jot something down)"
    r"|(?P<shop>add (?:something )?to (?:my |the )?shopping list|new shopping list|start a shopping list))"
    r"(?: for me| please)?")

_BARE_QUESTION = {
    "remind": "Sure - what should I remind you about, and when?",
    "task": "What's the task?",
    "note": "Go ahead - what should the note say?",
    "shop": "What should I put on the shopping list?",
}

#: A sentence that is plainly not the thing she asked for: a question, or him
#: changing his mind.
_NOT_AN_ANSWER = re.compile(
    r"(?:what|when|where|who|why|how|is|are|do|does|did|can|could|will|would|should|am)\b"
    r"|(?:never ?mind|forget it|cancel|no|nothing|stop)\b")


def _bare_kind(m) -> str:
    return next(k for k in ("remind", "task", "note", "shop") if m.group(k))


def _fills_a_bare_ask(text: str, low: str) -> dict | None:
    """His sentence, as the thing his last bare ask was missing - or None."""
    if not low or text.rstrip().endswith("?") or _NOT_AN_ANSWER.match(low) or _BARE_ASK.fullmatch(low):
        return None
    if re.match(r"(?:remind me|add|note|remember|put|set)\b", low):
        return None                 # a whole ask of its own; the patterns below read it
    before = _BARE_ASK.fullmatch(_previous_ask().casefold().rstrip(".?!"))
    if not before:
        # "Set a reminder" -> "stretch" -> "When should I remind you?" -> "at 6":
        # the what came a turn ago, and this is the when.
        try:
            from aletheia import converse
            last = (converse.recent(limit=1) or [{}])[-1]
        except Exception:
            return None
        if str(last.get("she_answered") or "").startswith(_ASK_WHEN):
            what = str(last.get("he_asked") or "").strip().rstrip(".")
            again = _interpret(f"remind me to {what} {text.strip().rstrip('.')}")
            if ((again or {}).get("command") or {}).get("kind") in ("remind_at", "remind_daily", "remind_weekly"):
                return again
        return None
    kind = _bare_kind(before)
    said = text.strip().rstrip(".")
    said = re.sub(r"^(?:(?:%s)\b[\s,]*)" % "|".join(WAKE_WORDS), "", said, flags=re.IGNORECASE) or said
    if kind == "task":
        return _new_task(said)
    if kind == "note":
        return {"command": {"kind": "note", "text": said}, "say": None}
    if kind == "shop":
        return {"command": {"kind": "shopping_add", "item": said}, "say": None}
    again = _interpret("remind me " + (said if re.match(r"(?:to|that|at|in|on|tomorrow|today|every) ", low)
                                       else "to " + said))
    if ((again or {}).get("command") or {}).get("kind") in ("remind_at", "remind_daily", "remind_weekly"):
        return again
    return {"command": None, "say": _ASK_WHEN + " Say a time, like 'at 5' or 'tomorrow morning'."}


_ASK_WHEN = "When should I remind you?"


#: One definition, in `speech`, because `intercom` resolves tasks with the
#: same table and two copies drift. Kept under this name so every existing
#: reference here still reads the way it did.
ORDINALS = speech.ORDINALS

#: How recently an approval must have been asked for a bare "approve" to
#: be taken as an answer to it. "Yes" replies to something he has just
#: heard; past this it is worth naming what he is agreeing to. Found the
#: hard way: a four-day-old misparse ("Fully shut down Aletheia") was the
#: only thing pending, so any "approve" would have run it.
ANSWERING_WINDOW_MINUTES = 10


def surfaced(approval: dict) -> dict:
    """Record that she has just read this one back to him.

    THE GUARD ATE ITS OWN EXIT. `_asked_recently` asked "was this
    REQUESTED recently", which is the same question as "has he just been
    told about it" for a fresh approval and a different one for an old
    one. So the four-day-old "Fully shut down Aletheia" answered a bare
    "approve" with "the only thing waiting is from 5 days ago... say
    approve that if you still want it" — and "approve that" gave the
    identical sentence. So did "approve it", "yes to that", "approve the
    first one". Every route in, and no route through: a stale approval had
    become unapprovable by voice at all, and she was telling him to say a
    sentence that did nothing.

    The question the guard actually wants is whether he KNOWS WHAT HE IS
    APPROVING, so this stamps the moment he was told. The loop terminates
    in one turn and nothing runs on a bare word he did not aim.

    Never raises — failing to write the stamp costs him one repeat, and
    breaking the approval path costs him the approval — but it does not
    fail SILENTLY. The first version caught everything and returned, and
    the contract was rejecting `surfaced_at` as an unknown field, so the
    loop was still a loop and the code looked correct. A swallowed write
    is how a fix ships as a no-op.
    """
    import datetime as dt

    from aletheia import journal, policy

    try:
        stored = policy.load(approval["id"])
        stored["surfaced_at"] = dt.datetime.now(dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        policy.save(stored)
        return stored
    except Exception as exc:
        try:
            journal.append(
                "event", "aletheia-voice",
                f"could not record that an approval was read back "
                f"({type(exc).__name__}: {exc})"[:200], actor="aletheia-voice")
        except Exception:
            pass
        return approval


def _asked_recently(approval: dict,
                    now: "dt.datetime | None" = None) -> bool:
    """Was this put to him recently enough that "approve" means it?

    Either because it was just requested, or because she just read it back
    — see `surfaced`. Unreadable or missing timestamps count as NOT
    recent: the safe mistake is asking him which one, never running the
    wrong thing.
    """
    import datetime as dt

    stamp = (approval.get("surfaced_at") or approval.get("requested_at")
             or approval.get("created_at"))
    if not stamp:
        return False
    try:
        asked = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if asked.tzinfo is None:
        asked = asked.replace(tzinfo=dt.timezone.utc)
    now = now or dt.datetime.now(dt.timezone.utc)
    return (now - asked) <= dt.timedelta(minutes=ANSWERING_WINDOW_MINUTES)


def _how_long_ago(approval: dict) -> str:
    """"four days ago", for reading back to him."""
    import datetime as dt

    stamp = approval.get("requested_at") or approval.get("created_at")
    try:
        asked = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return "a while back"
    if asked.tzinfo is None:
        asked = asked.replace(tzinfo=dt.timezone.utc)
    gap = dt.datetime.now(dt.timezone.utc) - asked
    if gap.days >= 1:
        return f"{speech.count_phrase(gap.days, 'day')} ago"
    hours = int(gap.total_seconds() // 3600)
    if hours >= 1:
        return f"{speech.count_phrase(hours, 'hour')} ago"
    return "a few minutes ago"


#: An application approval's id is `<run id>-submit`, and the run id is
#: `apply-<tag of the url>`. The record beside it knows the employer.
_APPLICATION_APPROVAL = "-submit"


def _application_label(approval: dict) -> str:
    """"Analyst at Notion", never "Submit an application at <a link>".

    Never raises and never guesses: an unreadable record, or one that
    knows neither the employer nor the role, falls back to whatever the
    rest of `approval_label` would have said.
    """
    approval_id = str((approval or {}).get("id") or "")
    if not approval_id.endswith(_APPLICATION_APPROVAL):
        return ""
    try:
        from aletheia import apply_run
        record = apply_run.load_run(approval_id[:-len(_APPLICATION_APPROVAL)])
        if not (record.get("company") or record.get("job_title")):
            return ""
        return speech.for_the_room(apply_run.describe(record))[:80]
    except Exception:
        return ""


#: A browser mission's approval id is `<mission id>--g<n>-commit-<digest>`
#: (`browser_loop._gate`). The mission beside it knows what it is about.
_MISSION_APPROVAL = re.compile(r"^(?P<mission>.+?)--g\d+-commit-[0-9a-f]+$")


def _mission_label(approval: dict) -> str:
    """"'Create Account' for Account Manager II at PNC", never "apply for
    this job".

    Sixteen of his thirty-eight pending approvals came from the browser
    loop on 2026-09-19, and every one of them said "apply for this job"
    and named no employer and no role — while the mission's own record
    knew both. `_application_label` does this for the form filler's
    approvals from the apply record; this does it for the loop's from the
    mission, which is the other half of the same list.

    Never raises and never guesses: a mission it cannot read, or a skill
    that cannot name its subject, says nothing and the rest of
    `approval_label` speaks as before.
    """
    hit = _MISSION_APPROVAL.match(str((approval or {}).get("id") or ""))
    if not hit or str(approval.get("capability") or "") != "web.commit":
        return ""
    try:
        # Importing the job skill is also what registers it, so a mission
        # that ran with it is findable by the name on its record.
        from aletheia import browser_loop, browser_mission, job_skill  # noqa: F401
        record = browser_mission.load(hit.group("mission"))
        about = browser_loop.skill_named(record.get("skill")).subject(record)
        if not about:
            return ""
        button = " ".join(str((record.get("gate") or {}).get("button") or "").split())
        # `shorten`, never `said[:80]`: a headline cut mid-word ("...Large Cor")
        # is the thing CLAUDE.md already names as the wrong way to do this.
        return speech.shorten(
            speech.for_the_room(f"press {button!r} for {about}" if button else about), 80)
    except Exception:
        return ""


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

    # AN APPLICATION IS NAMED BY THE EMPLOYER AND THE ROLE, always.
    # Half of them said "Apply: <page title> — <url>" and the other half
    # "Submit an application at <url>", depending on which path staged
    # them — so the same list showed him two shapes, and one of them was
    # a link where a company should be. The employer and the job title
    # are on the application RECORD, whose id prefixes the approval's,
    # and `apply_run.describe` is already the one sentence that names an
    # application the way he would.
    said = _application_label(approval) or _mission_label(approval)
    if said:
        return said

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
        # NOT `said[:80]`. On his screen that read "It presses a button that
        # says 'Create Account'. That is not something she can un" — cut
        # mid-word, as the headline of a decision he cannot undo.
        # `speech.shorten` exists for exactly this and cuts at a space.
        return speech.shorten(said, 80)
    if capability == "calendar.write" or action.startswith("calendar.write"):
        return "the calendar booking"
    if capability.startswith("intent.execute"):
        return "the plan"
    reason = speech.tidy(speech.strip_ids(_unwrap(str(approval.get("reason", "")))))
    if reason:
        return speech.shorten(reason, 80)
    return speech.shorten(speech.tidy(speech.strip_ids(action)), 60) or "the pending one"


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
    # NEITHER THE ID NOR THE DESCRIPTION. These sentences are read out in
    # a room, and this one said `intent.execute always needs you, not the
    # room` — an identifier, out loud, in the exchange where he most needs
    # to understand what he is being refused. Expanding it through the
    # registry is worse, not better: the descriptions are clauses written
    # for a reader, so it became "run an approved plan later, bound to a
    # sha256 of exactly the plan that was approved always needs you". He
    # does not need the name of the capability here. He is already being
    # told the CONSEQUENCE in the same breath ("Fully shut down
    # Aletheia"); what is missing is only why she will not take his word
    # for it from across the room. The id stays in the journal.
    if entry.get("approval_policy") == "operator_always":
        return False, "that kind of thing always needs you in person"
    if entry.get("risk_class") == VOICE_MAY_NOT_APPROVE:
        return False, "that one is high-risk"
    return True, ""


def _approve_by_voice(approval: dict):
    ok, why = approvable_by_voice(approval)
    if ok:
        return {"command": {"kind": "approve", "id": approval["id"]}, "say": None}
    # NAME THE THING SHE IS REFUSING. This said "I won't approve that ONE
    # by voice — email.send is high-risk", and a test asserted the id was
    # in the sentence — using an identifier read out loud as the proxy for
    # something real: that he can tell WHICH thing was refused. Taking the
    # id out without putting the answer back left "I won't approve that
    # one by voice - that kind of thing always needs you in person", which
    # names nothing at all. `approval_label` is what the wall and the
    # Command Center already show for the same approval.
    return {"command": None,
            "say": (f"I won't approve that by voice: {approval_label(approval)}. "
                    f"{why[0].upper()}{why[1:]}, and anything in the room could "
                    f"say it. Approve it at the keyboard: "
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


#: A URL inside a sentence he is deciding about. He does not need the path,
#: the query or the tracking token in it — he needs to know which site.
_URL_IN_A_SENTENCE = re.compile(r"https?://([^\s/]+)\S*")
#: What a sentence is left dangling on when the URL it ended with is removed.
_DANGLING = {"at", "to", "on", "for", "from", "in", "with", "via"}


def approval_about(approval: dict) -> str:
    """WHICH one — the line that tells two approvals apart. "" when the
    reason says nothing the label has not already said.

    Live on his machine, 2026-09-19: thirty-eight pending approvals, every
    one of them reading *"It sends your application to this employer under
    your name. There is no undo."* That consequence is true, it is the
    right headline, and it is identical for all thirty-eight — so the
    screen asked him to make thirty-eight irreversible decisions with
    nothing on it to tell them apart. The job and the employer were in
    `reason` the whole time, under a transport wrapper and behind a
    tracking URL, which is exactly why `approval_label` does not use it.

    So this is the sub-line and never the headline: his words with the
    wrapper peeled off and ids stripped, a URL reduced to its host and
    kept only when dropping it would leave the sentence hanging on a
    preposition. Nothing is invented, nothing is decided, and a reason
    that only repeats the label returns "" rather than saying it twice.
    """
    from aletheia import speech
    said = speech.tidy(speech.strip_ids(_unwrap(str(approval.get("reason", "")))))
    if not said:
        return ""
    bare = " ".join(_URL_IN_A_SENTENCE.sub(" ", said).split()).rstrip(",;:-— ")
    words = bare.split()
    if words and words[-1].lower().strip(",;:-—") not in _DANGLING:
        said = bare
    else:
        said = " ".join(
            _URL_IN_A_SENTENCE.sub(lambda m: " " + m.group(1), said).split())
    label = approval_label(approval).lower()
    meaningful = [w for w in re.findall(r"[a-z0-9]+", said.lower()) if len(w) > 3]
    if meaningful and all(w in label for w in meaningful):
        return ""                      # it would say the same thing twice
    return said[:120]


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
        said = _speech.plainly(detail)
        # A REASON THAT IS ALREADY A SENTENCE DOES NOT NEED A PREAMBLE.
        # The good refusals say the whole thing — "You have no reminder
        # about the plumber. The one you have is take out the bins" —
        # and "I can't do that: You have no reminder..." reads as two
        # people talking. The prefix earns its place in front of a
        # fragment ("no place matches 'the airport'"), which is what most
        # of these still are.
        if said[:1].isupper() and said.rstrip().endswith((".", "!", "?")):
            return said
        return f"I can't do that: {said}"
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
    if kind == "restart":
        return "Restarting. I'll be back in about a minute."
    if kind == "update_now":
        return detail[0].upper() + detail[1:] + "." if detail else "I tried the update."
    if kind == "browse_read":
        # detail is "read <url> — <title> :: <excerpt>" — speak title + excerpt
        return detail.split("read ", 1)[-1].replace(" :: ", ". ", 1)
    from aletheia import speech
    return speech.spoken_receipt(kind, detail)
