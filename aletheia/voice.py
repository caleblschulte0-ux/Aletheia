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
        # A whole word only: "theater tickets" was "ter tickets" (2026-10-07).
        if t.lower().startswith(w) and not t[len(w):len(w) + 1].isalnum():
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
    r"i mean|i meant|like|actually|oh|oops|sorry)\b[,\s]*"
    # "No, add eggs" and "wait, cancel that" (2026-10-07: to the planner).
    # Only with the comma: a bare "no" or "yes" is an answer, not filler.
    r"|(?:no|nope|yeah|yep|yes|yup|wait|hold on|hang on|oh wait)\s*,\s*)*",
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
    # "6am" glued to its number is still am: "put gym on my calendar tomorrow
    # at 6am" was held at six in the EVENING (2026-10-07).
    return not re.search(r"(?:^|[\d\s])(?:am|pm)\b", t)


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
    if t in ("today", "", "tonight"):
        return today.isoformat()
    if t == "tomorrow":
        return (today + dt.timedelta(days=1)).isoformat()
    # "The day after tomorrow" (2026-10-07: to the planner).
    if re.fullmatch(r"(?:the )?day after tomorrow", t):
        return (today + dt.timedelta(days=2)).isoformat()
    if t in WEEKDAYS:
        ahead = (WEEKDAYS.index(t) - today.weekday()) % 7
        return (today + dt.timedelta(days=ahead)).isoformat()
    # "In three days", "in 2 weeks", "the end of the month" have one
    # meaning each (2026-10-07: "renew my passport in 2 weeks" kept no day).
    n = re.fullmatch(r"in (a|an|one|two|three|four|five|six|seven|eight|nine|ten|\d{1,3}) (day|days|week|weeks)", t)
    if n:
        count = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                 "eight": 8, "nine": 9, "ten": 10}.get(n.group(1)) or int(n.group(1))
        return (today + dt.timedelta(days=count * (7 if n.group(2).startswith("week") else 1))).isoformat()
    if re.fullmatch(r"(?:the )?end of (?:the |this )?month", t):
        first_next = (today.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        return (first_next - dt.timedelta(days=1)).isoformat()
    try:
        return dt.date.fromisoformat(t).isoformat()
    except ValueError:
        pass
    said = _spoken_date(t, today)
    if said:
        return said
    # "On Halloween", "on Christmas Eve" (2026-10-07: to the planner) - the
    # holidays the countdown already knows.
    try:
        from aletheia import quick
        named = quick._named_date(re.sub(r"^on ", "", t), today)
    except Exception:  # noqa: BLE001
        named = None
    return named.isoformat() if named else None


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
        # "Call mom this weekend", "pay rent on the 1st" (2026-10-07: the
        # day stayed in the description and no deadline was kept).
        bare = re.search(r"^(\S+\s.*?)\s+(?:on |this )?((?:the )?day after tomorrow|today|tonight|tomorrow|monday|tuesday|wednesday"
                         r"|thursday|friday|saturday|sunday|(?:over )?(?:this |the )?weekend"
                         r"|the \d{1,2}(?:st|nd|rd|th)|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{1,2}(?:st|nd|rd|th)?"
                         r"|in (?:a|an|one|two|three|four|five|six|seven|eight|nine|ten|\d{1,3}) (?:days?|weeks?)"
                         # "Renew my license next month" (2026-10-07: "next
                         # month" stayed in the task and nothing was due).
                         r"|next week|next month|(?:by )?(?:the )?end of (?:the |this )?(?:week|month))$",
                         text, re.IGNORECASE)
        if bare and re.fullmatch(r"next week|next month|(?:by )?(?:the )?end of (?:the |this )?(?:week|month)",
                                 bare.group(2).lower()):
            import calendar as _cal
            import datetime as dt
            from aletheia import localtime
            today = dt.datetime.now(localtime.operator_tz()).date()
            said = bare.group(2).lower()
            if said == "next week":
                due = today + dt.timedelta(days=7 - today.weekday())             # next Monday
            elif said == "next month":
                due = (today.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
            elif said.endswith("week"):
                due = today + dt.timedelta(days=4 - today.weekday() if today.weekday() <= 4 else 6 - today.weekday())
            else:
                due = today.replace(day=_cal.monthrange(today.year, today.month)[1])
            return bare.group(1).strip(), due.isoformat()
        if bare:
            said = bare.group(2).lower()
            if said.endswith("weekend"):
                said = "sunday"  # the weekend is over when Sunday is
            day = _spoken_day("today" if said == "tonight" else said)
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
    # "Call tomorrow" offered to "text or email Tomorrow" (2026-10-07): a
    # day is when, never who.
    if words[0] in ("today", "tonight", "tomorrow", "later", "now", "soon", "back", "monday", "tuesday",
                    "wednesday", "thursday", "friday", "saturday", "sunday", "this", "next", "in", "at"):
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
    # "Search for cheap flights to Denver" and "look up the best hotels" are
    # the web, never a file (2026-10-07: both compiled a file search).
    if re.search(r"\b(?:flights?|hotels?|tickets?|deals?|recipes?|restaurants?|reviews?|cheap|cheapest|best|"
                 r"prices?|reservations?|airbnbs?|rentals?|apartments?|how to)\b", low):
        return True
    # "Find my note about Dana" is a note of hers, not a file (2026-10-07:
    # a file search for "note about dana").
    if re.match(r"notes? (?:about|on|for|mentioning)\b", low):
        return True
    # "Find a time for lunch" is the calendar.
    if re.match(r"(?:a |some )?time (?:for|to)\b", low):
        return True
    # "Do I have any alarms" searched his files for "alarms" (2026-10-07).
    # Her own stores are never a file.
    if re.fullmatch(r"(?:any |my |the )?(?:alarms?|reminders?|timers?|meetings?|appointments?|events?|plans|tasks?|to-?dos?|"
                    r"bills?|subscriptions?|deadlines?)(?: set| today| tomorrow| this week| coming up| due)?", low):
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


def _in_a_shopping_turns(turns: int = 3) -> bool:
    """Was the shopping list what his last few exchanges were about?"""
    try:
        from aletheia import converse
        rows = converse.recent(limit=turns) or []
    except Exception:  # noqa: BLE001
        return False
    return any(re.search(r"\b(?:shopping|grocery) list\b",
                         f"{t.get('he_asked') or ''} {t.get('she_answered') or ''}", re.IGNORECASE) for t in rows)


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


def _other_lists() -> bool:
    """Does he keep any named list besides shopping? Unknown counts as yes,
    so an unreadable store never empties the wrong list."""
    try:
        from aletheia import lists
        return bool(lists.all_lists())
    except Exception:  # noqa: BLE001
        return True


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
        # A bare "add bananas" is a shopping add too (2026-10-07: "and
        # apples" after it went to the planner) - but only when it really
        # went on the list, since a bare "add" can also be a task.
        if re.fullmatch(r"add (?:some |more )?[a-z][a-z' -]{1,30}", said) and \
                str(turn.get("she_answered") or "").startswith("Added to the shopping list"):
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
    # 2026-10-07: "remind me after lunch to stretch" went to the planner.
    "after lunch": "13:00", "after dinner": "19:30", "at dinner": "18:30", "at dinnertime": "18:30",
    "after school": "15:30", "before work": "08:00", "at noon": "12:00", "midday": "12:00",
}
_LOOSE_WHEN = (r"(?P<when>" + "|".join(sorted((re.escape(k) for k in _LOOSE_TIMES), key=len, reverse=True))
               + r"|in (?:a|one|\d+|two|three|four|five|six|seven|a couple of|a few) (?:days?|weeks?)"
               + r"|next week|in a fortnight|next month"
               # "Remind me in a month to cancel Netflix" (2026-10-07: to the planner).
               + r"|in (?:a|one|\d+|two|three|four|five|six) months?)")


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
        elif "month" in when:
            # Next month is its 1st; "in N months" is the same date N on,
            # held to the month's last day (31 January + 1 is 28 February).
            import calendar as _cal
            n = re.search(r"in (\S+) month", when)
            count = 1 if not n else {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                                     "six": 6}.get(n.group(1)) or (int(n.group(1)) if n.group(1).isdigit() else 0)
            if not count or count > 24:
                return None
            month0 = now.month - 1 + count
            year, month = now.year + month0 // 12, month0 % 12 + 1
            day = 1 if when == "next month" else min(now.day, _cal.monthrange(year, month)[1])
            at = now.replace(year=year, month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
            return {"command": {"kind": "remind_at", "at": at.isoformat(), "text": _as_he_said(text, what)},
                    "say": None}
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


def _timer_left(now=None, named: str = "") -> str:
    """What is left on each running timer, from the reminder store; with
    `named`, only the timer whose name has that word ("the pasta")."""
    from aletheia import intercom, speech
    now = now or dt.datetime.now(dt.timezone.utc)
    named = re.sub(r"^(?:the|my) ", "", " ".join(str(named or "").casefold().split()))
    left, others = [], []
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
        minutes = int((seconds + 30) // 60)  # 9:59 left is "10 minutes", not "9"
        amount = (speech.count_phrase(int(seconds), "second") if seconds < 60
                  else speech.count_phrase(minutes, "minute") if minutes < 60
                  else speech.count_phrase(minutes // 60, "hour") + (f" and {speech.count_phrase(minutes % 60, 'minute')}" if minutes % 60 else ""))
        # "10 minutes left on your 10 minute eggs timer": a named timer is
        # the eggs timer, and its length is already in the amount.
        called = re.fullmatch(r"\d+(?:[- ]and a half)?[- ](?:minute|hour|second)s?[- ](.+)", m.group(1))
        # "15 minutes left on your 10-minute timer" after "add 5 minutes"
        # (2026-10-07): a length it has outgrown is not its name any more.
        length = re.fullmatch(r"(\d+)[- ](minute|hour)s?", m.group(1))
        if length and seconds > int(length.group(1)) * (3600 if length.group(2) == "hour" else 60) + 30:
            line = (seconds, f"{amount} left on your timer")
        else:
            line = (seconds, f"{amount} left on the {called.group(1)} timer" if called
                    else f"{amount} left on your {m.group(1)} timer")
        if named and not re.search(r"\b" + re.escape(named) + r"\b", m.group(1)):
            others.append(line)
            continue
        left.append(line)
    if named and not left:
        # "How long on the pasta" answered about the EGGS (2026-10-07).
        said = f"You don't have a {named} timer."
        if others:
            others.sort()
            rest = speech.and_list([words for _, words in others])
            said += f" There's {rest}."
        return said
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
    r"print|sign|read|review|update|install|set up|back up|look into|look up|talk to|meet|visit|water|sort|organize|organise|vacuum|take out|bring|replace|feed|prepare|study|research|cook|buy|clear out|tidy)\b")


def _birthday_reminder(m) -> dict:
    """A reminder some days before a birthday his note names, at 9 am."""
    import datetime as dt
    from aletheia import localtime, quick
    who = m.group("who").strip()
    words = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
    if m.group("n"):
        n = words.get(m.group("n")) or int(m.group("n"))
        before = n * (7 if m.group("unit").startswith("week") else 1)
    else:
        before = 1 if m.group("eve") else 0
    for shown, month, day in quick._birthday_notes():
        if re.sub(r"^your ", "", shown.casefold()) != who:
            continue
        tz = localtime.operator_tz()
        now = dt.datetime.now(tz)
        when, _days = quick._next_birthday(month, day)
        for _ in range(2):
            at = dt.datetime.combine(when - dt.timedelta(days=before), dt.time(9, 0), tzinfo=tz)
            if at > now:
                break
            when, _days = quick._next_birthday(month, day) if when.year > now.year else (when.replace(year=when.year + 1), None)
        if at <= now:
            return {"command": None, "say": "That's already gone by this year. Say a different number of days."}
        lead = f"{shown}'s birthday"
        text = (f"{lead} is today" if before == 0 else f"{lead} is tomorrow" if before == 1
                else f"{lead} is in a week, on {when.strftime('%A')}" if before == 7
                else f"{lead} is in {before} days, on {when.strftime('%A')}")
        return {"command": {"kind": "remind_at", "at": at.isoformat(), "text": text}, "say": None}
    relation = who in quick._relation_words() or " " in who
    said, his = (f"your {who}", f"My {who}") if relation else (who.title(), who.title())
    return {"command": None,
            "say": f"I don't know when {said}'s birthday is. Say \"{his}'s birthday is\" and the date, "
                   "and then I can."}


#: Past-tense verbs a done thing is said with. Kept to plain chores and
#: errands: anything with a door of its own (paid a bill to a merchant,
#: finished a task, took his pills) is matched before this is reached.
_DONE_VERBS = ("changed|gave|fed|walked|watered|cleaned|washed|mowed|vacuumed|replaced|renewed|fixed|serviced"
               "|rotated|flushed|emptied|refilled|filled|charged|backed up|updated|trimmed|cut|groomed|bathed"
               "|dropped off|picked up|returned|mailed|posted|vaccinated|dewormed|descaled|defrosted")


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
    if str(day).strip().casefold() == "tonight":
        part = part or "night"          # "a party tonight at 8" is eight in the evening
    # "Schedule lunch with Sam next Tuesday" held "lunch with sam next"
    # (2026-10-07): the word before the day belongs to the day.
    title = re.sub(r"\s+(?:next|this|on|for|coming)$", "", str(title or "").strip(), flags=re.IGNORECASE) or title
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
        # "Schedule lunch with Sam on Friday" was held at 9 am (2026-10-07).
        # A meal named with no time is at that meal's hour; the receipt
        # says the time, so a wrong guess is caught in one syllable.
        meal = re.search(r"\b(breakfast|brunch|lunch|dinner|supper|drinks|happy hour)\b", str(title).lower())
        if meal and not part:
            hour, minute = {"breakfast": (8, 0), "brunch": (11, 0), "lunch": (12, 0), "dinner": (18, 30),
                            "supper": (18, 30), "drinks": (18, 0), "happy hour": (17, 0)}[meal.group(1)]
    start = dt.datetime.combine(dt.date.fromisoformat(day_iso), dt.time(hour, minute),
                                tzinfo=localtime.operator_tz())
    return {"command": {"kind": "calendar_hold", "title": _as_he_said(transcript, title.strip()),
                        "start": start.isoformat(), "minutes": 60}, "say": None}


#: A turn that only makes sense against the one before it. Skipped when
#: looking for "his last ask", so "make that 4" then "cancel it" finds the
#: reminder and not the move (and never re-reads itself).
_IS_FOLLOW_UP = re.compile(
    r"^(?:(?:make|change|move|push|bump|shift) (?:that|it)\b|(?:cancel|scrap|drop|undo) (?:that|it)$|undo$|take that back$|"
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


def _where_he_put(thing: str) -> str | None:
    """His newest note saying where the thing is, read back to him; None
    when there is none. Never raises."""
    stem = re.sub(r"(?:es|s)$", "", str(thing or "").strip().casefold()) or thing
    if len(stem) < 3:
        return None
    try:
        from aletheia import quick, speech
        for row in quick._notes():
            said = str(row.get("text") or "").strip()
            low = said.casefold()
            if re.search(rf"\b{re.escape(stem)}", low) and re.search(
                    r"\b(?:put|left|keep|hid|placed|parked|are|is)\b.*\b(?:in|on|at|under|by|behind|next to|inside|near)\b", low):
                hers = speech.as_she_says_it(said).rstrip(".")
                # "You left your keys on the counter.", not "You told me:
                # you left..." - the same as where he parked.
                if re.match(r"you (?!told\b)", hers):
                    return hers[0].upper() + hers[1:] + "."
                return f"You told me: {hers}."
    except Exception:
        return None
    return None


def _known_person_first(rest: str) -> tuple[str, str] | None:
    """(who, the rest) when the leading words name a contact he has, or a
    one-word relation; else None. Never a stranger guessed at."""
    words = str(rest or "").split()
    try:
        from aletheia import contacts as _contacts
        people = _contacts.all_contacts()
    except Exception:
        _contacts, people = None, []
    for n in range(min(3, len(words) - 1), 0, -1):
        who = " ".join(words[:n])
        try:
            _contacts.resolve(who, people)
            known = True
        except Exception:
            known = n == 1 and who in _RELATIONS
        if known:
            return who, " ".join(words[n:])
    return None


def _previous_turn() -> tuple[str, str]:
    """(what he said, what she answered) for the last exchange. Never raises."""
    try:
        from aletheia import converse
        turns = converse.recent(limit=1)
    except Exception:
        return "", ""
    if not turns:
        return "", ""
    return (" ".join(str(turns[-1].get("he_asked") or "").split()),
            " ".join(str(turns[-1].get("she_answered") or "").split()))


def _the_task_just_added() -> str:
    """The task his last exchange added, in its own words, or "". "Make it
    due Friday" a turn after "add a task to call the dentist" means that
    task, and nothing else in the conversation does (2026-10-07: both went
    to the planner, which with nothing thinking kept them for later)."""
    try:
        from aletheia import converse
        turns = converse.recent(limit=3)
    except Exception:  # noqa: BLE001
        return ""
    for turn in reversed(turns or []):
        answered = " ".join(str(turn.get("she_answered") or "").split())
        # The receipt says ", due Friday" (and ", due 20 October") since
        # 2026-10-07; the task is the words before it.
        found = re.match(r"Added a task: (.+?)(?:,? due [^.]+)?\.(?:\s|$)", answered) \
            or re.match(r"Moved: (.+?) due ", answered) \
            or re.match(r"(.+?) is due .+ now\.(?:\s|$)", answered) \
            or re.match(r"Renamed .+? to (.+?)\.(?:\s|$)", answered)
        if found:
            return found.group(1).strip()
    return ""


def _only_asked(said: str, command: dict) -> bool:
    """Was that turn only a question - answered from her stores, a reader,
    or a wh-question nobody could plan? Such a turn is stepped over when
    "it" is looked for."""
    try:
        from aletheia import intercom, quick
        kind = str((command or {}).get("kind") or "")
        if kind and kind in intercom.READ_ONLY_KINDS:
            return True
        if quick.match(said):
            return True
        return kind in ("intent", "") and bool(re.match(
            r"(?:what|when|where|who|why|how|which|is|are|do|does|did|can|could|will|would)\b", said.casefold()))
    except Exception:
        return False


def _last_ask_is_undoable() -> bool:
    """Was his last ask a task, a list item, a reminder, a hold or a file -
    the things "cancel it" can take straight back? A question between
    ("who is it with") is stepped over."""
    try:
        from aletheia import converse, intercom
        turns = converse.recent(limit=4) or []
    except Exception:
        return False
    if not turns:
        try:
            from aletheia import intercom
            return _last_ask_kind() in intercom.UNDOES_HIS_ASK
        except Exception:
            return False
    for turn in reversed(turns):
        said = re.sub(r"^(?:thea|aletheia)[,]?\s+", "", " ".join(str(turn.get("he_asked") or "").split()), flags=re.I)
        if not said:
            continue
        try:
            command = (interpret(f"thea {said}") or {}).get("command") or {}
        except Exception:
            return False
        if _only_asked(said, command):
            continue
        return str(command.get("kind") or "") in intercom.UNDOES_HIS_ASK
    return False


def _recent_reminder_ask(turns: int = 4) -> dict:
    return _recent_ask_of("remind_at", "text", turns)


def _hold_as_it_is_now(held: dict) -> dict:
    """The hold he asked for, at the time it is NOW. "Dentist Friday at 2",
    "make it 3", "remind me an hour before" reminded him at 1 (2026-10-07):
    the move is a follow-up, so the ask found was the first one."""
    if not held or not held.get("title"):
        return held
    try:
        from aletheia import calendar, calendar_reasoning
        event = calendar.load(calendar_reasoning.hold_id(held["title"], str(held["start"]), held.get("thread") or ""))
        if event.get("status") != "CANCELLED":
            return held
        title = " ".join(str(held["title"]).split()).casefold()
        live = [e for e in calendar.all_events()
                if e.get("status") != "CANCELLED" and " ".join(str(e.get("title") or "").split()).casefold() == title]
    except Exception:  # noqa: BLE001
        return held
    if len(live) != 1:
        return held
    return {**held, "start": live[0]["start"]}


def _recent_ask_of(kind: str, needs: str, turns: int = 4) -> dict:
    """The one-off reminder among his last few asks, newest first, or {}.

    "Remind me at 6", "what are my reminders for today", "actually make
    that 7" (2026-10-07): a QUESTION in between is not what "that" points
    at, so it is stepped over; any other writer stops the search, because
    then "that" is the newer thing."""
    try:
        from aletheia import converse, intercom
        recent = converse.recent(limit=turns) or []
    except Exception:
        return {}
    if not recent:
        recent = [{"he_asked": _previous_ask()}]
    for at in range(len(recent) - 1, -1, -1):
        turn = recent[at]
        said = " ".join(str(turn.get("he_asked") or "").split())
        said = re.sub(r"^(?:thea|aletheia)[,]?\s+", "", said, flags=re.IGNORECASE)
        if not said or _IS_FOLLOW_UP.match(_without_preamble(said.casefold().rstrip(".?!"))):
            continue
        try:
            from aletheia import quick
            # "At 2pm" answering her "When should I remind you to call the
            # bank?" is that whole reminder; read alone it is nothing, and
            # "move it to 3" two turns later found no reminder (2026-10-07).
            before = " ".join(str(recent[at - 1].get("she_answered") or "").split()) if at else ""
            rebuilt = _answering_her(said.casefold().rstrip(".?!"), answered=before) if before else None
            if rebuilt and (rebuilt.get("command") or {}).get("kind") == kind:
                cmd = rebuilt["command"]
                if cmd.get(needs):
                    return cmd
            if quick.match(said):
                continue                          # a question she answered from her stores
            cmd = (interpret(f"thea {said}") or {}).get("command") or {}
        except Exception:
            return {}
        if cmd.get("kind") == kind and cmd.get(needs):
            return cmd
        # A QUESTION nobody could answer in between ("what time?") changed
        # nothing, so it is stepped over like any other question.
        if cmd.get("kind") == "intent" and re.match(
                r"(?:what|when|where|who|why|how|which|is|are|do|does|did|can|could|will|would)\b", said.casefold()):
            continue
        if cmd.get("kind") not in intercom.READ_ONLY_KINDS:
            return {}
    return {}


def _relative_length_asked(previous: dict) -> str | None:
    """"minute" or "hour" when the reminder he just set was asked for as a
    length ("remind me in 20 minutes to ..."), else None."""
    try:
        from aletheia import converse
        recent = converse.recent(limit=4) or []
    except Exception:
        return None
    what = str(previous.get("text") or "").casefold()
    for turn in reversed(recent):
        said = " ".join(str(turn.get("he_asked") or "").casefold().split())
        found = re.search(r"\bremind me in (?:\d{1,3}|an?|one) (minute|hour)s?\b", said)
        if found and what and what in said:
            return found.group(1)
    return None


def _shifted_reminder(amount: str, unit: str, direction: str) -> dict | None:
    """The reminder he just set, moved by an amount from its stored time."""
    import datetime as dt
    from aletheia import intercom
    previous = _recent_reminder_ask()
    if not previous:
        return None
    found, _why = intercom._one_reminder(str(previous.get("text") or ""))
    if not found or found.get("kind") != "once":
        return None
    try:
        was = dt.datetime.fromisoformat(str(found.get("at") or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    words = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10, "fifteen": 15,
             "twenty": 20, "thirty": 30, "forty-five": 45}
    n = 0.5 if amount.startswith("half") else (int(amount) if amount.isdigit() else words.get(amount))
    if not n:
        return None
    minutes = n * (60 if unit.startswith("hour") else 1)
    sign = -1 if direction in ("forward", "earlier", "up", "sooner") else 1
    at = was + dt.timedelta(minutes=sign * minutes)
    if at <= dt.datetime.now(dt.timezone.utc):
        return {"command": None, "say": "That would put it in the past. Say the new time instead."}
    return {"command": {"kind": "remind_at", "at": at.isoformat(), "text": previous["text"],
                        "replaces": previous["text"]}, "say": None}


def _moved_reminder(transcript: str, time_words: str) -> dict | None:
    """"Make that 4": the reminder he just set, at the new time, replacing
    the old one. None unless his last ask was a one-off reminder and the
    time reads."""
    previous = _recent_reminder_ask()
    if not previous:
        return None
    # "Make it Saturday at 10", then "make it 4", went back to FRIDAY
    # (2026-10-07): the day came from the first sentence, not from where the
    # reminder now is. The stored one wins.
    try:
        from aletheia import intercom
        found, _why = intercom._one_reminder(str(previous.get("text") or ""))
        if found and found.get("kind") == "once" and found.get("at"):
            previous = {**previous, "at": found["at"]}
    except Exception:  # noqa: BLE001 - the sentence's own time still stands
        pass
    # "Set a timer for 10 minutes", "make it 15" moved the timer to THREE
    # IN THE AFTERNOON (2026-10-07). After a timer, a bare number is its
    # new length, counted from now.
    timer = re.fullmatch(r"your (\d+)-(minute|hour|second) timer is up", str(previous.get("text") or ""))
    length = re.fullmatch(r"(\d{1,3})(?: (minutes?|mins?|hours?|hrs?|seconds?|secs?))?", " ".join(str(time_words).split()))
    if timer and length:
        import datetime as dt
        n = int(length.group(1))
        unit = (length.group(2) or timer.group(2))[:1]
        unit = {"m": "minute", "h": "hour", "s": "second"}[unit]
        if n < 1:
            return None
        at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(**{unit + "s": n})
        return {"command": {"kind": "remind_at", "at": at.isoformat(), "text": f"your {n}-{unit} timer is up",
                            "replaces": previous["text"]}, "say": None}
    # "Remind me in 20 minutes to check the oven", "make it 25" went to the
    # planner (2026-10-07): a reminder set as a length is moved as one.
    relative = _relative_length_asked(previous)
    if relative and length:
        import datetime as dt
        n = int(length.group(1))
        unit = {"m": "minute", "h": "hour", "s": "second"}[(length.group(2) or relative)[:1]]
        if n < 1:
            return None
        at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(**{unit + "s": n})
        return {"command": {"kind": "remind_at", "at": at.isoformat(), "text": previous["text"],
                            "replaces": previous["text"]}, "say": None}
    # "Actually make it Thursday" (2026-10-07: to the planner): the same
    # reminder on that day, at its own time unless he names another.
    said = " ".join(str(time_words).split()).lower()
    on_day = re.fullmatch(r"(?:on )?(?P<day>[a-z0-9 ]+?)(?: at (?P<t>[\w: ]+))?", said)
    day_iso = None
    if on_day and on_day.group("day") not in ("", "today") and not _spoken_time(on_day.group("day")):
        day_iso = _spoken_day(on_day.group("day"))
    if day_iso:
        try:
            import datetime as dt
            from aletheia import localtime
            tz = localtime.operator_tz()
            was = dt.datetime.fromisoformat(str(previous.get("at") or "").replace("Z", "+00:00")).astimezone(tz)
            hour, minute = was.hour, was.minute
            if on_day.group("t"):
                hhmm = _spoken_time(on_day.group("t"))
                if not hhmm:
                    return None
                hour, minute = map(int, hhmm.split(":"))
                if _is_bare_hour(on_day.group("t")) and 1 <= hour <= 7:
                    hour += 12
            at = dt.datetime.combine(dt.date.fromisoformat(day_iso), dt.time(hour, minute), tzinfo=tz)
        except (ValueError, TypeError):
            return None
        if at <= dt.datetime.now(tz):
            return None
        return {"command": {"kind": "remind_at", "at": at.isoformat(), "text": previous["text"],
                            "replaces": previous["text"]}, "say": None}
    # "Make it the afternoon" (2026-10-07: to a model): the same day, at
    # the hour that part of the day starts with her other reminders.
    part = {"morning": "9:00 am", "the morning": "9:00 am", "afternoon": "2:00 pm", "the afternoon": "2:00 pm",
            "evening": "6:00 pm", "the evening": "6:00 pm", "tonight": "9:00 pm", "night": "9:00 pm",
            "the night": "9:00 pm", "lunchtime": "12:00 pm", "lunch": "12:00 pm"}.get(" ".join(str(time_words).split()))
    if part:
        time_words = part
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
    # "Remind me tomorrow to call the bank" then "make it 10am" moved it to
    # TODAY at ten (2026-10-07). A new time keeps the reminder's own day,
    # unless that would put it in the past.
    try:
        import datetime as dt
        from aletheia import localtime
        tz = localtime.operator_tz()
        was = dt.datetime.fromisoformat(str(previous.get("at") or "").replace("Z", "+00:00")).astimezone(tz)
        hour, minute = map(int, hhmm.split(":"))
        if bare and 1 <= hour <= 7:
            # "Make it 4" on a 10 am reminder is four in the afternoon,
            # the way a bare hour is read everywhere else.
            hour += 12
        same_day = was.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if same_day > dt.datetime.now(tz):
            at = same_day.isoformat()
    except (ValueError, TypeError):
        pass
    return {"command": {"kind": "remind_at", "at": at, "text": previous["text"],
                        "replaces": previous["text"]}, "say": None}


def _one_of_her_holds(words: str):
    """(hold, why-not): the one tentative hold SHE pencilled in that his
    words name - by its time ("my 2pm") or its title ("meeting with sam").
    Only her own holds: an event on his live calendar is never one."""
    import datetime as dt
    try:
        from aletheia import calendar, localtime
        tz = localtime.operator_tz()
        now = dt.datetime.now(dt.timezone.utc)
        mine = []
        for event in calendar.all_events():
            if event.get("status") != "TENTATIVE" or not str(event.get("source") or "").startswith("hold:"):
                continue
            start = calendar.parse_time(event["start"])
            if start > now:
                mine.append((start.astimezone(tz), event))
    except Exception:
        return None, ""
    said = " ".join(str(words or "").casefold().split())
    said = re.sub(r"^(?:my|the|our) ", "", said)
    said = re.sub(r" (?:today|tomorrow)$", "", said)
    clock = re.fullmatch(r"(\d{1,2})(?::(\d\d))?\s*(am|pm|o'?clock)?(?: (?:meeting|appointment|call|one|thing))?", said)
    if clock:
        hour, minute = int(clock.group(1)), int(clock.group(2) or 0)
        hits = [(s, e) for s, e in mine if s.minute == minute and s.hour % 12 == hour % 12
                and (clock.group(3) not in ("am", "pm") or (s.hour >= 12) == (clock.group(3) == "pm"))]
    else:
        title = re.sub(r"^(?:appointment|meeting|call)(?: with)? ", "", said)
        title = re.sub(r" (?:appointment|meeting|call|thing|hold)$", "", title)
        keys = [w for w in re.findall(r"[a-z0-9']+", title) if w not in ("with", "the", "a", "my")]
        hits = [(s, e) for s, e in mine if keys and all(k in str(e.get("title") or "").casefold() for k in keys)]
    if len(hits) == 1:
        return hits[0][1], ""
    if len(hits) > 1:
        return None, "more than one"
    return None, ""


def _moved_hold(time_words: str) -> dict | None:
    """"Make it 8" after "put dinner with Sam on my calendar Friday at 7"
    (2026-10-07: to the planner): the hold he just made, same day, the new
    time, the same length. None unless his last ask was a hold."""
    import datetime as dt
    previous = _recent_ask_of("calendar_hold", "start")
    hhmm = _spoken_time(time_words) if previous else None
    if not hhmm:
        return None
    try:
        was = dt.datetime.fromisoformat(str(previous["start"]).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    hour, minute = map(int, hhmm.split(":"))
    # A bare hour keeps the half of the day the hold was in: dinner at 7
    # "made 8" is eight in the evening.
    if _is_bare_hour(time_words) and was.hour >= 12 and hour < 12:
        hour += 12
    new = was.replace(hour=hour, minute=minute)
    command = {"kind": "calendar_hold", "title": previous["title"], "start": new.isoformat(),
               "replaces": previous["start"]}
    if previous.get("minutes"):
        command["minutes"] = previous["minutes"]
    elif previous.get("end"):
        try:
            ends = dt.datetime.fromisoformat(str(previous["end"]).replace("Z", "+00:00"))
            command["minutes"] = max(5, int((ends - was).total_seconds() // 60))
        except (TypeError, ValueError):
            pass
    if previous.get("location"):
        command["location"] = previous["location"]
    return {"command": command, "say": None}


def _reminder_moved_to(which: str, time_words: str) -> dict | None:
    """The one-off reminder named by its time ("3pm") or its words ("pill"),
    moved to `time_words` on the day it was already on. None when the new
    time does not read; a sentence when nothing, or more than one, matches."""
    import datetime as dt
    from aletheia import localtime
    hhmm = _spoken_time(time_words)
    if not hhmm:
        return None
    tz = localtime.operator_tz()
    which = which.strip()
    named_at = _spoken_time(which)
    found = []
    for at, words in _running_once(""):
        local = at.astimezone(tz)
        if named_at:
            hour, minute = map(int, named_at.split(":"))
            # "My 3 reminder" with no am/pm is either 3 o'clock.
            if local.minute == minute and (local.hour == hour or (_is_bare_hour(which) and local.hour % 12 == hour % 12)):
                found.append((local, words))
        elif all(w in words.casefold() for w in re.findall(r"[a-z0-9]+", which.casefold())):
            found.append((local, words))
    if not found:
        return {"command": None, "say": f"I don't see a reminder {'at ' if named_at else 'for '}{which}. "
                                        "Say \"what reminders do I have\" and I'll read them."}
    if len(found) > 1:
        from aletheia import speech
        return {"command": None, "say": "Which one - " + speech.or_list([w for _, w in found[:4]]) + "?"}
    was, words = found[0]
    hour, minute = map(int, hhmm.split(":"))
    if _is_bare_hour(time_words) and was.hour >= 12 and hour < 12:
        hour += 12                       # "move my 3pm reminder to 4" means 4 pm
    at = was.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return {"command": {"kind": "remind_at", "at": at.isoformat(), "text": words, "replaces": words}, "say": None}


def _running_once(marker: str) -> list:
    """[(when, text)] for the one-off reminders still to fire whose words
    carry `marker` ("timer is up", "wake up"), soonest first. Never raises."""
    import datetime as dt
    try:
        from aletheia import scheduler
        specs = scheduler.all_schedules()
    except Exception:
        return []
    now = dt.datetime.now(dt.timezone.utc)
    out = []
    for spec in specs:
        words = str((spec.get("command") or {}).get("text") or "")
        if spec.get("kind") != "once" or not spec.get("enabled") or marker not in words.casefold():
            continue
        try:
            at = scheduler.next_occurrence(spec, now)
        except Exception:
            continue
        if at is not None:
            out.append((at, words))
    return sorted(out)


def _more_on_the_timer(minutes: int, named: str = "") -> dict:
    """"Add 5 minutes" to the one timer running (2026-10-07: to the planner),
    or to the one he names when there are several."""
    import datetime as dt
    running = _running_once("timer is up")
    if named:
        word = re.sub(r"^(?:the|my) ", "", named.strip())
        running = [(at, w) for at, w in running if re.search(r"\b" + re.escape(word) + r"\b", w.casefold())]
        if not running:
            return {"command": None, "say": f"You don't have a {word} timer running."}
    if not running:
        return {"command": None, "say": "No timer running. Say \"set a timer for 5 minutes\" to start one."}
    if len(running) > 1:
        return {"command": None, "say": f"You have {len(running)} timers running - cancel the one you don't "
                                        "want and set it again for the new time."}
    at, words = running[0]
    later = (at + dt.timedelta(minutes=minutes)).astimezone(dt.timezone.utc)
    return {"command": {"kind": "remind_at", "at": later.isoformat(), "text": words, "replaces": words},
            "say": None}


def _moved_alarm(time_words: str, was_words: str = "") -> dict:
    """"Change my alarm to 6:30": the one alarm, same day, the new time.
    "Change my 6:30 alarm to 7" names which one when there are several."""
    import datetime as dt
    from aletheia import localtime
    running = _running_once("wake up")
    hhmm = _spoken_time(time_words)
    if not hhmm:
        return _to_the_planner(f"change my alarm to {time_words}")
    if not running:
        return {"command": None, "say": f"You don't have an alarm set. Say \"set an alarm for {time_words}\" and I'll set one."}
    was_hhmm = _spoken_time(was_words) if was_words else None
    if was_hhmm:
        h, mi = map(int, was_hhmm.split(":"))
        wanted = {f"{h:02d}:{mi:02d}"} | ({f"{h + 12:02d}:{mi:02d}"} if _is_bare_hour(was_words) and h < 12 else set())
        named = [r for r in running if r[0].astimezone(localtime.operator_tz()).strftime("%H:%M") in wanted]
        if not named:
            return {"command": None, "say": f"You don't have an alarm at {was_words}."}
        running = named
    if len(running) > 1:
        return {"command": None, "say": f"You have {len(running)} alarms - say which, like "
                                        "\"change my 6:30 alarm to 7\"."}
    at, words = running[0]
    was = at.astimezone(localtime.operator_tz())
    hour, minute = map(int, hhmm.split(":"))
    if _is_bare_hour(time_words) and was.hour >= 12 and hour < 12:
        hour += 12
    new = was.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if new <= dt.datetime.now(new.tzinfo):
        new += dt.timedelta(days=1)
    return {"command": {"kind": "remind_at", "at": new.isoformat(), "text": words,
                        "replaces": f"{words} {was_hhmm}" if was_hhmm else words},
            "say": None}


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
    # "Make a packing list for my trip" made a list called "my trip"
    # (2026-10-07): the sort of list he named is its name; "for my trip" is
    # what it is for.
    m = re.fullmatch(r"(?:make|start|create|begin) (?:me )?(?:a )?(?:new )?(?P<sort>packing|gift|wish|reading|movie|bucket|chore)"
                     r" list for .{2,40}", low)
    if m and lists.is_named_list(m.group("sort")):
        return {"command": {"kind": "list_new", "list": m.group("sort")}, "say": None}
    m = (re.fullmatch(r"(?:make|start|create|begin) (?:me )?(?:a )?(?:new )?(?:grocery |shopping |packing |to-?do |to do |todo |check ?)?"
                      r"list (?:called|named|for) " + name_, low)
         # "Start a list of movies to watch" (2026-10-07: to the planner).
         or re.fullmatch(r"(?:make|start|create|begin|keep) (?:me )?(?:a )?(?:new )?list of " + name_, low)
         or re.fullmatch(r"(?:make|start|create|begin) (?:me )?(?:a |my )?(?:new )?" + name_ + r" list", low))
    if m:
        named = re.sub(r"^(?:the|my|our|a) ", "", m.group("name"))
        if lists.is_named_list(named):
            return {"command": {"kind": "list_new", "list": _as_he_said(text, named)}, "say": None}
    m = re.fullmatch(r"(?:add|put|stick|throw) (?P<item>.+?) (?:to|on|onto|in) (?:my |the )" + name_ + r" list", low)
    # "Add paper towels to costco" (2026-10-07: to the planner) names a list
    # he HAS without saying "list"; only an existing one counts.
    if not m:
        m = re.fullmatch(r"(?:add|put|stick|throw) (?P<item>.+?) (?:to|on|onto) (?:my |the )?" + name_, low)
        if m and not lists.exists(m.group("name")):
            m = None
    if m and lists.is_named_list(m.group("name")):
        return {"command": {"kind": "list_add", "list": _as_he_said(text, m.group("name")),
                            "item": _as_he_said(text, m.group("item"))}, "say": None}
    m = (re.fullmatch(r"(?:take|remove|delete|cross|scratch|tick) (?:off )?(?P<item>.+?) (?:off|from) (?:of )?(?:my |the )"
                      + name_ + r" list", low)
         # "Delete the packing list" (2026-10-07: to the planner) empties it;
         # the receipt says cleared, which is what happened.
         or re.fullmatch(r"(?:clear|empty|wipe|delete|get rid of|scrap|throw out) (?:out )?(?:my |the )" + name_ + r" list(?P<item>)", low))
    if m and lists.is_named_list(m.group("name")):
        # "Delete my weekend list" emptied it and left an empty list behind
        # (2026-10-07); delete, scrap and get rid of mean the list itself.
        whole = not m.group("item") and re.match(r"(?:delete|get rid of|scrap|throw out)\b", low)
        return {"command": {"kind": "list_off", "list": _as_he_said(text, m.group("name")),
                            "item": m.group("item") or ("the list" if whole else "everything")}, "say": None}
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
    # "Set a reminder for 5" (2026-10-07: to the planner) has the when and
    # not the what; her question carries the time to his answer.
    (r"(?:set|make|add|create) (?:a |me a )?reminder (?:for|at) (?P<t>\d{1,2}(?::\d{2})?(?: ?[ap]\.?m\.?)?|noon)",
     'What should I remind you about at {t}? Just say it, like "take the bins out".'),
    (r"(?:set|make|add|create|new) (?:a |me a )?(?:new )?reminder(?: for me)?|remind me(?: of something| about something| later)?",
     'What should I remind you about, and when? Say "remind me at 3 to call the dentist".'),
    (r"(?:take|make|add|write|create|new) (?:a |me a )?(?:new )?note(?: for me)?|(?:take|write) (?:this|something) down|note this",
     'What should the note say? Say "note that the plumber comes Tuesday".'),
    (r"(?:add|make|create|new) (?:a |me a )?(?:new )?task(?: for me)?",
     'What\'s the task? Say "add a task to renew my passport".'),
    (r"(?:set|start) (?:a |me a )?(?:new )?(?:nap |power nap |cooking |kitchen )?timer",
     'For how long? Say "set a timer for ten minutes".'),
    (r"(?:send|write|draft|compose) (?:an |a )?(?:new )?e-?mail(?: for me)?",
     'Who to, and what should it say? Say "email Dana saying I\'ll be late".'),
    # "Wake me up", "set an alarm for tomorrow" (2026-10-07: to the planner).
    (r"(?:set|make) (?:an |me an )?alarm(?: for (?:tomorrow|the morning|tomorrow morning))?"
     r"|wake me(?: up)?(?: tomorrow| in the morning| tomorrow morning)?",
     'For what time? Say "wake me up at 6".'),
    (r"(?:did (?:anyone|anybody|someone|somebody) call(?: me)?|any missed calls|who called(?: me)?|missed calls"
     r"|(?:read|check) (?:me )?my (?:texts|text messages)|any (?:new )?(?:texts|text messages)"
     # 2026-10-07, each to the planner (and voicemail to a FILE search).
     r"|(?:read|check) (?:me )?my (?:messages|voicemails?)|any (?:new )?(?:messages|voicemails?)"
     r"|do i have (?:any )?(?:new )?(?:voicemails?|messages|texts)"
     r"|what did [a-z]+(?: [a-z]+)? (?:text|message) me(?: about)?)",
     "I can't see your phone's calls or the texts on it - those stay on your phone. "
     "I can read your email, and texts that reach your Google Voice number: say \"read my texts\"."),
)


def _bare_verb(low: str) -> str | None:
    """The one question a verb with nothing after it needs, or None."""
    said = low.strip().rstrip("?.! ")
    said = re.sub(r"^(?:can you |could you |please |i (?:want|need) (?:you )?to )", "", said)
    said = re.sub(r" please$", "", said)
    for pattern, answer in _BARE_VERBS:
        found = re.fullmatch(pattern, said)
        if found:
            return answer.format(**found.groupdict()) if found.groupdict() else answer
    return None


def interpret(transcript: str) -> dict:
    """One spoken sentence -> a command to gate-check, or words to say.

    The wrapper exists for one reason: every path below matches against a
    LOWERCASED sentence, and anything it STORES has to keep his capitals.
    Doing it here rather than in thirty patterns means the next pattern
    somebody writes gets it for free.
    """
    transcript = _a_follow_on(_a_polite_ask(_with_the_person_named(_a_clock_said(transcript))))
    return _his_capitals(strip_wake_word(transcript),
                         _no_password_in_a_note(_no_reminder_about_a_pronoun(_interpret(transcript))))


# What "can you ..." is asking her to DO, when the rest is a concrete ask.
# A question about ability ("can you text people", "can you buy things")
# compiles to nothing here and is still answered as one.
_POLITE_DOING = frozenset({
    "remind_at", "remind_daily", "remind_every", "remind_weekly", "remind_monthly", "remind_weekdays",
    "shopping_add", "shopping_off", "shopping_list", "task_new", "task_done", "task_change", "tasks",
    "reminders", "reminder_off", "note", "email_check", "stopwatch", "stopwatch_read", "music",
    "travel_time", "free_time", "notify_snooze", "list_add", "list_read", "list_off", "brief", "contacts",
})


_CLOCK_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                  "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}


def _a_clock_said(transcript: str) -> str:
    """"At quarter to 5" is "at 4:45".

    "Remind me at quarter to 5 to pick up Jo" went to the planner
    (2026-10-07): the "to" of the clock and the "to" of the errand are the
    same word, and the pattern reading one took the other. Said as digits
    once, here, every pattern below reads it.
    """
    def said(m):
        hour = m.group("h")
        hour = int(hour) if hour.isdigit() else _CLOCK_NUMBERS.get(hour.casefold())
        if not hour or not 1 <= hour <= 12:
            return m.group(0)
        minutes = {"quarter": 15, "half": 30}[m.group("q").casefold()]
        if minutes == 30 and m.group("way").casefold() == "to":
            return m.group(0)                     # "half to five" is not a time anybody agrees on
        if m.group("way").casefold() == "to":
            hour, minutes = (hour - 1) or 12, 60 - minutes
        return f"{m.group('at')}{hour}:{minutes:02d}"
    out = re.sub(r"(?i)(?P<at>\b(?:at|by|for|until|till|from) )(?:a )?(?P<q>quarter|half) (?P<way>to|past) "
                 r"(?P<h>\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b",
                 said, str(transcript or ""))
    # "Remind me every Sunday night to plan the week" (2026-10-07: to the
    # planner): a part of a named day is the hour every other path uses.
    # "...every Sunday night at 8": the part says which 8.
    out = re.sub(r"(?i)\b(every|each|on) (monday|tuesday|wednesday|thursday|friday|saturday|sunday)s? "
                 r"(morning|afternoon|evening|night) at (\d{1,2}(?::\d{2})?)(?!\s*(?:am|pm|a\.m|p\.m))\b",
                 lambda m: f"{m.group(1)} {m.group(2)} at {m.group(4)}"
                           + ("am" if m.group(3).casefold() == "morning" else "pm"), out)
    if re.search(r"(?i)\bremind me\b", out) and not re.search(r"(?i)\bat \d", out):
        out = re.sub(r"(?i)\b(every|each|on) (monday|tuesday|wednesday|thursday|friday|saturday|sunday)s? "
                     r"(morning|afternoon|evening|night)\b",
                     lambda m: f"{m.group(1)} {m.group(2)} at "
                               + {"morning": "9am", "afternoon": "2pm", "evening": "6pm", "night": "9pm"}[m.group(3).casefold()],
                     out)
    return out


def _a_follow_on(transcript: str) -> str:
    """"And add a task to pay rent" is "add a task to pay rent".

    Said straight after another ask (2026-10-07) it went to the planner,
    whose money door refused it as spending. Only when what follows the
    "and" is an ask she already handles; anything else is left as he said it.
    """
    said = strip_wake_word(transcript)
    m = re.match(r"(?i)\s*(?:oh,? |ok,? |okay,? )?(?:and also|and then|and|also|plus|then)[, ]+(?P<rest>.{3,})", said)
    if not m:
        return transcript
    rest = m.group("rest")

    def handled(sentence):
        out = _interpret(sentence) or {}
        return bool(out.get("say")) or (out.get("command") or {}).get("kind") not in (None, "intent")
    try:
        # "And water" after a list is the list's own follow-on: whatever
        # already reads the whole sentence keeps it.
        if handled(transcript) or not handled(_a_polite_ask(rest)):
            return transcript
    except Exception:  # noqa: BLE001 - as he said it
        return transcript
    return _a_polite_ask(rest)


def _a_polite_ask(transcript: str) -> str:
    """"Can you remind me at 5 to call mom" is "remind me at 5 to call mom".

    It was answered "Yes, but it is experimental: place and hold a phone
    conversation" (2026-10-07) - a polite instruction read as a question
    about ability, matched to the wrong ability, and nothing done. Only
    when the rest is an ask she already knows how to do; anything else is
    handed back untouched and answered as the question it may be.
    """
    said = str(transcript or "")
    bare = strip_wake_word(said)
    # "Would you mind adding...", "I need you to remind me...", and a bare
    # ask that ends "please" (2026-10-07: all three to the planner, and "I
    # need you to remind me to pay rent" refused as SPENDING).
    m = re.fullmatch(r"(?:hey |ok |okay )?(?P<lead>would (?:you|u) mind |(?:can|could|would|will) (?:you|u) (?:please |kindly |just )?"
                     r"|(?:i need|i want|i'd like|i would like) (?:you|u) to (?:please )?)?"
                     r"(?P<rest>.{3,160}?)(?P<tail>,? please|, thanks|, thank you)?(?: for me)?\s*[?.!]?",
                     " ".join(bare.split()), re.IGNORECASE)
    if not m or not (m.group("lead") or m.group("tail")):
        return said
    rest = m.group("rest")
    if m.group("lead") and "mind" in m.group("lead"):
        # "Adding a task" is "add a task".
        verb, _, after = rest.partition(" ")
        base = {"adding": "add", "setting": "set", "reminding": "remind", "putting": "put", "making": "make",
                "taking": "take", "removing": "remove", "checking": "check", "reading": "read",
                "playing": "play", "starting": "start", "noting": "note", "writing": "write"}.get(verb.casefold())
        if not base:
            return said
        rest = f"{base} {after}".strip()
    try:
        cmd = (_interpret(rest) or {}).get("command") or {}
    except Exception:
        return said
    # "Would you remind me to call mom" has no time yet, and her question
    # back ("When should I remind you to call mom?") is the right answer.
    # "Can you wake me up" was answered about the room microphone (2026-10-07).
    asks_back = cmd.get("kind") is None and re.match(r"(?:remind me|wake me|set (?:a|an|me a) (?:alarm|timer))\b",
                                                     rest, re.IGNORECASE)
    if cmd.get("kind") not in _POLITE_DOING and not asks_back:
        return said
    return said[:len(said) - len(bare)] + rest


def sensitivity_where() -> str:
    from aletheia import sensitivity
    return sensitivity.WHERE_IT_IS


def _no_password_in_a_note(said: dict) -> dict:
    """"Note that the wifi password is hunter2" answered "Noted." and kept
    "[redacted]" (2026-10-07) - `sensitivity` blanks a password out of
    everything she writes. Said instead of faked, the way "my wifi password
    is" already was."""
    cmd = (said or {}).get("command") or {}
    from aletheia import sensitivity
    if cmd.get("kind") == "note" and re.search(r"\bpass(?:word|code|phrase)\b.{0,30}\b(?:is|are|=|:)\s*\S",
                                               str(cmd.get("text") or ""), re.IGNORECASE) \
            and sensitivity.carries_secret(str(cmd.get("text") or "")):
        return {"command": None, "say": _NO_PASSWORDS}
    return said


_NOT_A_NAME = {"my", "your", "his", "her", "its", "it", "that", "this", "what", "who", "today", "tomorrow",
               "everyone", "nobody", "somebody", "someone", "the", "a", "an"}


def _the_person_just_named() -> str:
    """The one person his last few sentences named, or "". "My sister's name
    is Jess", "save Jess's number": Jess. Never a guess between two."""
    try:
        from aletheia import converse
        turns = converse.recent(limit=3) or []
    except Exception:  # noqa: BLE001
        return ""
    for turn in reversed(turns):
        said = " ".join(str(turn.get("he_asked") or "").split()).casefold()
        said = re.sub(r"^(?:thea|aletheia)[,]?\s+", "", said)
        found = re.search(r"\bname is ([a-z][a-z'-]{1,20})\b", said) \
            or re.search(r"\b([a-z][a-z-]{1,20})'s (?:name|number|phone|email|birthday|address|anniversary)\b", said) \
            or re.search(r"^(?:text|message|email|call|ring) ([a-z][a-z-]{1,20})\b", said)
        if found and found.group(1) not in _NOT_A_NAME:
            return found.group(1)
    return ""


def _with_the_person_named(transcript: str) -> str:
    """"Her birthday is March 3", "what's her number", "text her happy
    birthday" a turn after he named somebody (2026-10-07: the first went to
    the planner, the second found "no contact for 'her'", the third texted
    somebody called "her happy"). Only these shapes, and only when one
    person was just named; otherwise the sentence is left exactly as said."""
    low = " ".join(str(transcript or "").split())
    shapes = (r"^((?:thea,? )?)(?:her|his) (number|phone(?: number)?|email(?: address)?|birthday|address|anniversary)( is .+)$",
              r"^((?:thea,? )?what(?:'s| is|s) )(?:her|his) (number|phone(?: number)?|email(?: address)?|birthday|address)(\??)$",
              r"^((?:thea,? )?(?:text|message|email) )(?:her|him) (.+)$",
              # "Call Dana" -> "I can text or email Dana" -> "text her"
              # (2026-10-07: to the planner).
              r"^((?:thea,? )?(?:text|message|email|call|ring) )(?:her|him|them)()$")
    for i, shape in enumerate(shapes):
        m = re.match(shape, low, flags=re.IGNORECASE)
        if not m:
            continue
        who = _the_person_just_named()
        if not who:
            return transcript
        who = who[:1].upper() + who[1:]
        if i == 2:
            return f"{m.group(1)}{who} {m.group(2)}"
        if i == 3:
            return f"{m.group(1)}{who}"
        return f"{m.group(1)}{who}'s {m.group(2)}{m.group(3)}"
    return transcript


_PRONOUN_ONLY = {"this", "that", "it", "these", "those", "something", "stuff", "that thing", "this thing"}


def _the_named_list_just_used(turns: int = 3) -> tuple[str, bool]:
    """(the named list his last few exchanges were about, whether it was the
    very last one) - ("", False) when it was the shopping list or none."""
    try:
        from aletheia import converse
        rows = converse.recent(limit=turns) or []
    except Exception:  # noqa: BLE001
        return "", False
    for depth, turn in enumerate(reversed(rows)):
        both = f"{turn.get('he_asked') or ''} {turn.get('she_answered') or ''}".casefold()
        # "Make a grocery list called costco" - "Started your costco list":
        # her own answer names the list, whatever kind he called it.
        mine = re.search(r"\byour ([a-z][a-z'-]*(?: [a-z][a-z'-]*){0,2}?) list\b", str(turn.get("she_answered") or "").casefold())
        if re.search(r"\b(?:shopping|grocery) list\b", both) and not (mine and mine.group(1) not in ("shopping", "grocery")):
            return "", False
        name_ = r"([a-z][a-z'-]*(?: [a-z][a-z'-]*){0,2}?)"
        found = re.search(r"\byour " + name_ + r" list\b", str(turn.get("she_answered") or "").casefold()) \
            or re.search(r"\b(?:to|on|from|off|of|read|in) (?:my|the) " + name_ + r" list\b", both) \
            or re.search(r"\blist called " + name_ + r"\b", both)
        if found and found.group(1).strip() not in ("to-do", "to do", "todo", "task", "this", "that", "a"):
            return found.group(1).strip(), depth == 0
    return "", False


def _shopping_just_said() -> bool:
    """Was the shopping list what his last exchange was about? Never raises."""
    try:
        from aletheia import converse
        rows = converse.recent(limit=1) or []
    except Exception:  # noqa: BLE001
        return False
    if not rows:
        return False
    both = f"{rows[-1].get('he_asked') or ''} {rows[-1].get('she_answered') or ''}".casefold()
    return bool(re.search(r"\b(?:shopping|grocery) list\b", both))


def _onto_the_named_list(low: str) -> dict | None:
    if re.search(r"\blist\b", low) and not re.fullmatch(r"(?:delete|clear|empty|scrap) (?:the|this|that) list", low):
        return None                               # he named a list himself
    name, last = _the_named_list_just_used()
    if not name:
        return None
    m = re.fullmatch(r"(?:and |also )?add (?:the |some )?(?P<w>[a-z][a-z0-9' ,-]{1,60}?)(?: back| too| as well| again)?", low) \
        or re.fullmatch(r"(?:and|also) (?P<w>[a-z][a-z0-9' ,-]{1,60}?)(?: too| as well)?", low)
    # "Add a meeting to friday" is not a thing for the costco list: an item
    # with somewhere or somewhen after it belongs to another verb.
    # A verb is a task ("and call the bank"); a lone word is a thing, even
    # one that can be a verb ("and water").
    if m and last and not (_TASK_VERB.match(m.group("w")) and " " in m.group("w").strip()) \
            and not re.search(r"\b(?:to|on|at|onto|into|by|tomorrow|today|tonight|monday|tuesday|wednesday|thursday"
                              r"|friday|saturday|sunday|meeting|appointment|reminder|task)\b", m.group("w")):
        return _interpret(f"add {m.group('w')} to my {name} list")
    m = re.fullmatch(r"(?:take|cross|scratch|tick) (?:the |my )?(?P<w>[a-z][a-z0-9' -]{1,40}?) off"
                     r"|(?:remove|cross off|take off|delete) (?:the |my )?(?P<w2>[a-z][a-z0-9' -]{1,40}?)", low)
    if m and (m.group("w") or m.group("w2")) not in ("it", "that", "this", "list", "everything", "all"):
        return _interpret(f"take {m.group('w') or m.group('w2')} off my {name} list")
    if re.fullmatch(r"what'?s on (?:it|there)(?: now)?|read (?:it|that)(?: back| out)?|what'?s left(?: on it)?"
                    r"|how many (?:things|items)(?: are)? on (?:it|there)(?: now)?", low):
        return {"command": {"kind": "list_read", "list": name}, "say": None}
    # Emptying it needs it to be the very last thing said.
    if last and re.fullmatch(r"(?:delete|clear|empty|scrap|wipe) (?:it|the list|this list|that list)(?: out)?", low):
        return {"command": {"kind": "list_off", "list": name, "item": "everything"}, "say": None}
    return None


_HER_QUESTIONS = (
    (r"When should I remind you to (.+?)\? ", "remind me {low} to {0}", "remind_"),
    (r"When should I remind you about (.+?)\? ", "remind me {low} to {0}", "remind_"),
    (r"For how long\? Say \"set a timer", "set a timer for {low}", "remind_at"),
    (r"For what time\? Say \"wake me up", "wake me up at {low}", "remind_"),
    # "Add a reminder" - "What should I remind you about, and when?" - "for
    # tomorrow at 9 to email Sam" (2026-10-07: she asked "when?" again).
    (r"What should I remind you about, and when\? ", "remind me {free}", "remind_"),
    # "Set a reminder for 5" - "What should I remind you about at 5?" - "to
    # take the bins out" (2026-10-07: both went to the planner).
    (r"What should I remind you about at (.+?)\? ", "remind me at {0} {what}", "remind_"),
    # "Text Mom" - "What should it say?" - "that I'll be late" (2026-10-07:
    # the answer went to the planner).
    (r"What should it say\? Say \"text (.+?) that ", "text {0} that {body}", "message_send"),
    (r"What should it say\? Say \"email (.+?) saying ", "email {0} saying {body}", "email_draft"),
)


def _answering_her(low: str, answered: str | None = None) -> dict | None:
    """His short answer to the question she just asked, as the whole ask.
    `answered` is what she said before it, when that is not the last turn."""
    if len(low.split()) > 40:
        return None
    if answered is None:
        _said, answered = _previous_turn()
    for question, template, kind in _HER_QUESTIONS:
        m = re.match(question, answered or "")
        if not m:
            continue
        if low.startswith(template.split("{")[0].strip()):
            continue                    # already the whole ask, not an answer to put back together
        loose = "{free}" in template or "{what}" in template
        if "{body}" not in template and len(low.split()) > (16 if loose else 6):
            continue
        if ("{body}" in template or loose) and not re.match(r"(?:that|saying|say|tell)\b", low):
            # "What time is it" after "What should it say?" is his own
            # question, not the text (2026-10-07: it was drafted as one).
            # Only a sentence that is not an ask of hers becomes the words.
            try:
                from aletheia import quick
                if quick.match(low) or re.match(r"(?:what|when|where|who|why|how|which|is|are|do|does|did|can|could|"
                                                r"will|would|should|stop|cancel|never ?mind|no|nope)\b", low):
                    continue
                # "Call mom" after "What should it say?" became a text that
                # said "call mom" (2026-10-07): an ask of hers is an ask.
                if re.match(r"(?:call|phone|ring|text|email|e-mail|message|remind me|set|add|make|delete|remove|turn|play"
                            r"|open|show me|read me|find|search|wake me|start|schedule|book|pencil|block|note|remember"
                            r"|forget|undo|halt|resume|approve|deny|what's|whats)\b", low):
                    continue
            except Exception:  # noqa: BLE001
                continue
        body = re.sub(r"^(?:that|saying|say|tell (?:her|him|them)(?: that)?)\s+", "", low)
        what = low if re.match(r"(?:to|about|that)\b", low) else f"to {low}"
        rebuilt = template.format(*[g for g in m.groups()], body=body, what=what,
                                  free=re.sub(r"^(?:for|on) (?!\d)", "", low),
                                  low=re.sub(r"^(?:at|for|in) (?=\d)", "", low) if "{low} to" not in template else low)
        got = _interpret(rebuilt)
        if str(((got or {}).get("command") or {}).get("kind", "")).startswith(kind):
            return got
    return None


def _no_reminder_about_a_pronoun(said: dict) -> dict:
    """"Remind me about this tomorrow" set a reminder whose whole text was
    "this" (2026-10-07). At nine tomorrow "this" means nothing, so she asks
    what, rather than keep a reminder he cannot use."""
    cmd = (said or {}).get("command") or {}
    if str(cmd.get("kind", "")).startswith("remind_") and \
            str(cmd.get("text") or "").strip().lower() in _PRONOUN_ONLY:
        # "Remind me about it tomorrow" a turn after adding a task: "it" is that task.
        task = _the_task_just_added()
        if task:
            return {**said, "command": {**cmd, "text": task}}
        return {"command": None, "say": "What should I remind you about? Say it with the thing, like "
                                        "\"remind me tomorrow to call the bank\"."}
    return said


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
    # Only her name ("hey thea") is a call, not a sentence: she answers it.
    low = re.sub(r"^(?:%s)\b[\s,.!?:;]*" % "|".join(WAKE_WORDS), "", low)
    if not low:
        return {"command": None, "say": "I'm listening."}
    # "Remind me on weekdays at 8 to stand up", "remind me Mondays at 9"
    # (2026-10-07: to the planner). A plural day IS "every" that day.
    if low.startswith("remind me ") and not re.search(r"\bevery\b", low):
        plural = re.sub(r"\b(?:on )?(weekday|weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)s\b",
                        r"every \1", low, count=1)
        if plural != low:
            again = _interpret(plural)
            if (again.get("command") or {}).get("kind") in ("remind_weekly", "remind_daily"):
                return again
    # "Every weekday at 8 remind me to stretch" (2026-10-07: to the planner):
    # the when said first. The same sentence with the when after "remind me"
    # is one every reminder branch below already reads.
    # THE ANSWER TO HER OWN QUESTION (2026-10-07): "When should I remind
    # you to email Sam?" - "tomorrow at 2" went to the planner, as did "ten
    # minutes" after "For how long?". The question and the answer are one
    # sentence, put back together; kept only if it becomes that command.
    # "Both" / "all of them" to "You have 2 reminders at 5 pm: ... Which one, or
    # all of them?" (2026-10-07: "cancel both" was a subscription called "both").
    if re.fullmatch(r"(?:cancel |turn off |delete |remove |stop )?(?:both|all of them|them all|both of them|all|them both"
                    r"|all three|all of those|both please|all of them please)", low):
        _said, answered = _previous_turn()
        at = re.search(r"reminders at (.+?): .+Which one, or all of them\?", answered or "")
        if at and _spoken_time(at.group(1)):
            return {"command": {"kind": "reminder_off", "which": f"all at {_spoken_time(at.group(1))}"}, "say": None}
    answered = _answering_her(low)
    if answered:
        return answered
    # HIS NAMED LIST, SPOKEN TO AS "IT" (2026-10-07): after "make a list
    # called packing", "add sunscreen, towels and a hat" went to the
    # planner, "add the hat back" went on the SHOPPING list, and "what's on
    # it" and "delete the list" found nothing. The list he is working on is
    # the one he just named.
    on_list = _onto_the_named_list(low)
    if on_list:
        return on_list
    # "Make a grocery list", "add apples to it" (2026-10-07: to the
    # planner). "It" is the list he was just on: his named one, or the
    # shopping list when that was what the last turn was about.
    m = re.fullmatch(r"(?:add|put|stick|throw) (?P<w>[a-z][a-z0-9' ,-]{1,60}?) (?:to|on|onto|in) "
                     r"(?:it|that|this|that list|this list|the list)", low)
    if m:
        name, _last = _the_named_list_just_used()
        try:
            from aletheia import lists as _lists
            gone = bool(name) and not _lists.exists(name)
        except Exception:  # noqa: BLE001
            gone = False
        if gone:
            # "Delete my packing list", then "add Dune to it" put Dune on
            # the list he had just deleted (2026-10-07).
            item = _as_he_said(transcript, m.group("w"))
            return {"command": None,
                    "say": f"Which list? Your {name} list is deleted. Say \"add {item} to my\" and the list's name."}
        if name:
            return {"command": {"kind": "list_add", "list": name, "item": _as_he_said(transcript, m.group("w"))},
                    "say": None}
        if _shopping_just_said():
            return {"command": {"kind": "shopping_add", "item": _as_he_said(transcript, m.group("w"))}, "say": None}
    # "Set another one for 10 minutes" / "another timer for the rice"
    # (2026-10-07: to the planner) is a new timer like the first.
    another = re.fullmatch(r"(?:set |start |make )?another (?:one|timer)(?: for| of)? (.+)", low)
    if another:
        got = _interpret(f"set a timer for {another.group(1)}")
        if ((got or {}).get("command") or {}).get("kind") == "remind_at":
            return got
    # "And remind me to email Sam too" (2026-10-07: to the planner).
    also = re.fullmatch(r"(?:and|also|oh and|and also) (remind me .+?)(?: too| as well| also)?", low)
    if also:
        return _interpret(also.group(1))
    lead = re.fullmatch(r"((?:every|each|tomorrow|tonight|today|on|at|this|in) [a-z0-9: ]{1,40}?),? "
                        r"remind me (to|about|that) (.+)", low)
    if lead:
        return _interpret(f"remind me {lead.group(1)} {lead.group(2)} {lead.group(3)}")
    # "Remind me to take my pills at 9pm every day" was a DAILY reminder at
    # 9 am whose text was "take my pills at 9pm" (2026-10-07): the time sat
    # between the thing and the repeat, where no branch looks for it. Said
    # in the order every branch reads.
    tail = re.fullmatch(r"remind me (to|about) (.+?) at ((?:\d{1,2}(?::\d{2})? ?(?:am|pm|a\.m\.|p\.m\.)?)|noon|midnight)"
                        r" ((?:every|each) [a-z ]{3,30}|daily|on weekdays|weekdays)", low)
    if tail:
        repeat = {"daily": "every day", "on weekdays": "every weekday", "weekdays": "every weekday"}.get(
            tail.group(4), tail.group(4))
        return _interpret(f"remind me {repeat} at {tail.group(3)} {tail.group(1)} {tail.group(2)}")

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
    # "Pause everything" (2026-10-07: to the planner, which may not halt).
    if (re.fullmatch(r"(halt|stop|kill switch|emergency stop|shut it down|"
                     r"stand down|stop (that|it|now)|that(?:'s| is) enough|"
                     r"pause (everything|yourself|all (of )?(it|this|your work))|stop (all )?(your )?work(ing)?|"
                     r"stop (doing )?everything)", low)
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
    filled = _fills_a_bare_ask(text, low) or _answers_which(low)
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
    # "Pause my reminders" (2026-10-07: to the planner) stops them all, each
    # one disabled and kept; "turn my reminders back on" is the other half.
    m = re.fullmatch(r"(?:pause|mute|silence|snooze|hold) (?:all )?(?:of )?(?:my |the )?(?P<sort>reminders|alarms)"
                     r"(?: for now)?", low)
    if m:
        return {"command": {"kind": "reminder_off", "which": "all " + m.group("sort")}, "say": None}
    m = re.fullmatch(r"(?:unpause|unmute|unsilence|bring back) (?:all )?(?:of )?(?:my |the )?(?P<sort>reminders|alarms|timers)"
                     r"|turn (?:all )?(?:of )?(?:my |the )?(?P<sort2>reminders|alarms|timers) (?:back on|on again)", low)
    if m:
        return {"command": {"kind": "reminder_on", "which": "all " + (m.group("sort") or m.group("sort2"))}, "say": None}
    # "Put that back" after stopping a reminder (2026-10-07: the planner,
    # though every comment beside reminder_off promised one command).
    m = re.fullmatch(r"(?:actually,? |no,? |wait,? )?(?:put|turn|switch) (?:that|it) back(?: on)?|bring (?:that|it) back"
                     r"|(?:actually,? )?turn (?:that|it) on again", low)
    if m:
        previous = _previous_ask()
        before = (_interpret(previous).get("command") or {}) if previous else {}
        if before.get("kind") == "reminder_off":
            return {"command": {"kind": "reminder_on", "which": before["which"]}, "say": None}
    m = re.fullmatch(r"(?:turn|switch|put) (?:the |my )?(?P<w>[a-z][a-z' ]{1,30}?) (?:reminder|alarm) (?:back on|on again|back)", low)
    if m:
        return {"command": {"kind": "reminder_on", "which": m.group("w")}, "say": None}
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
                    r"what needs attention|anything need me|what'?s urgent|is anything urgent|anything urgent)", low):
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
    # "What's my locker number" looked up a contact called "my locker"
    # (2026-10-07): a thing with a number is not a person.
    if m and len(m.group(1)) < 40 and not _is_about_himself(m.group(1)) \
            and not re.match(r"(?:new|up|happening|going on|the latest|latest|good) in\b", m.group(1)) \
            and not re.search(r"\b(?:locker|account|member(?:ship)?|policy|license|licence|plate|wifi|wi-fi|gate|door"
                              r"|garage|room|seat|flight|confirmation|order|tracking|case|ticket|insurance|social security"
                              r"|passport|employee|student|customer|reference|serial|model|pin|bank|routing|card|apartment"
                              r"|unit|house|street|home|work|office|zip|postal|post)$", m.group(1)):
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
                    r"|(list )?(my )?applications|(show|read|tell)( me)? (my|the) (job )?applications", low):
        return {"command": {"kind": "applications"}, "say": None}
    # "WHAT'S ON IT" right after the shopping list was touched (2026-10-07:
    # to a model, with "it" lost). The list the last exchange was about.
    # "How many things are on it", "clear it" (2026-10-07: to the planner) -
    # the same list. A list touched in the last few turns, not only the last.
    clear_it = re.fullmatch(r"(?:clear|empty|wipe) it(?: out)?|(?:clear|empty) (?:it|that) (?:all )?out", low)
    if clear_it or re.fullmatch(r"what'?s on (?:it|there)(?: now)?|read (?:it|that) (?:back|out)|read it|what'?s left(?: on it)?"
                                r"|how many (?:things|items|things are|items are)(?: are)? on (?:it|there)(?: now)?", low):
        said, answered = _previous_turn()
        just_now = re.search(r"\b(?:shopping|grocery) list\b", f"{said} {answered}", re.IGNORECASE)
        # Emptying it needs the list to be the LAST thing said; reading it
        # back may reach a few turns further.
        if clear_it and just_now:
            return {"command": {"kind": "shopping_off", "item": "everything"}, "say": None}
        if not clear_it and (just_now or _in_a_shopping_turns()):
            return {"command": {"kind": "shopping_list"}, "say": None}
        named = re.search(r"\byour ([a-z][a-z' -]{1,30}?) list\b", answered, re.IGNORECASE)
        if named:
            return {"command": {"kind": "list_read", "list": named.group(1)}, "say": None}
        # "What's left" after ticking a task off (2026-10-07: it read the
        # SETUP checklist). The task list the last exchange was about.
        if re.match(r"(?:Done|Added a task|Moved|\d+ things? on your list|1 thing on your list)\b", answered):
            return {"command": {"kind": "tasks"}, "say": None}
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
    if m and m.group(1).strip() in ("that", "it", "this", "them", "those"):
        # "Take that off the list" bought "that" off the list (2026-10-07):
        # a pronoun is the thing he just added, or nothing she can name.
        if _last_ask_is_undoable():
            return {"command": {"kind": "undo"}, "say": None}
        m = None
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
        # "Add eggs and butter" (2026-10-07: to the planner) is a plain list.
        if not _might_be_several(m.group("item")) or _a_plain_list(m.group("item")):
            return {"command": {"kind": "shopping_add", "item": _as_he_said(text, m.group("item").strip())},
                    "say": None}

    # "WE'RE OUT OF COFFEE", "we need paper towels", "I need to buy
    # batteries": a thing to buy, said as a need (2026-10-07: the planner,
    # and the last one refused as SPENDING). It goes on the list; buying
    # it stays his. Anything that starts with a verb is not a thing.
    m = (re.fullmatch(r"(?:we(?:'re| are)|i(?:'m| am)) (?:all )?out of (?:the |some )?(?P<item>[a-z][a-z '-]{1,40})", low)
         or re.fullmatch(r"(?:we|i) need (?:to (?:buy|get|pick up) )?(?:more |some |a new |new |a |an )?(?P<item>[a-z][a-z '-]{1,40})", low)
         or re.fullmatch(r"(?:we(?:'re| are)|i(?:'m| am)) (?:running )?(?:low on|almost out of) (?:the )?(?P<item>[a-z][a-z '-]{1,40})", low))
    # "I need to pick up my prescription tomorrow" was put on the shopping
    # list as "my prescription tomorrow" (2026-10-07): a pick-up, or anything
    # with a day or a time in it, is an errand - the task rule below.
    # "I need to buy batteries tomorrow": the thing still goes on the list,
    # without the day.
    if m and re.match(r"(?:we|i) need to (?:buy|get)\b", low):
        bare_item = re.sub(r"\s+(?:today|tomorrow|tonight|this (?:morning|afternoon|evening|week)|next week|"
                           r"(?:on )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))$", "", m.group("item"))
        if bare_item != m.group("item") and not _TASK_VERB.match(bare_item):
            return {"command": {"kind": "shopping_add", "item": _as_he_said(text, bare_item.strip())}, "say": None}
    if m and (re.match(r"(?:we|i) need to pick up\b", low) or re.search(
            r"\b(?:today|tomorrow|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
            r"this (?:morning|afternoon|evening|week)|next week|at \d|by \d)\b", m.group("item"))):
        m = None
    if m and not _TASK_VERB.match(m.group("item")) \
            and not re.match(r"(?:to|break|help|you|time|rest|sleep|nap|money|cash|job|minute|second|hand|hug|"
                             r"vacation|holiday|day off|shower|ride|lift|doctor|dentist|lawyer|therapist|advice|"
                             r"idea|ideas|plan|answer|answers|space|quiet|coffee break|drink|win|friend|friends|"
                             r"date|haircut|change|reminder|timer|alarm|it|that|this|them|him|her)\b", m.group("item")):
        return {"command": {"kind": "shopping_add", "item": _as_he_said(text, m.group("item").strip())},
                "say": None}

    # "Snooze that for an hour" — the commonest thing anybody says to a
    # notification, and it had no verb at all.
    # "Snooze my alarm for 10 minutes" (2026-10-07: to the planner): an
    # alarm that just went off is a notice like any other.
    m = re.fullmatch(r"snooze(?: (?:(?:my |the |that |this )(?:alarm|reminder|timer|alert|notification)|"
                     r"(?:your |all |the )?(?:notifications|notices|alerts)|that|it|this|them))?\s*(?:for |by )?(.*)", low)
    if m:
        rest = m.group(1).strip()
        # A bare "snooze that" is the commonest form and names no
        # interval. Fifteen minutes, and the confirmation says it back —
        # the same argument as the nine o'clock default for a weekly
        # reminder. Anything it cannot read goes to the planner rather
        # than being rounded to a number nobody said.
        # "Snooze for 5": a bare number after snooze is minutes.
        if re.fullmatch(r"\d{1,3}", rest):
            rest += " minutes"
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
                     r"((?:what you know about |everything about |what i (?:said|told you) about |(?:my |the )?notes? about )?.+?)"
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
                    r"(?: on| for| in)? (?:my|the|that) timers?(?: (?:go off|goes off|be done|is done|ring|rings|done))?"
                    r"|how(?:'s| is) (?:my|the) timer(?: doing| going)?"
                    # "What timers do I have" read back "1 reminder: ..." (2026-10-07).
                    r"|(?:what|which) timers (?:do i have|are (?:running|set|going))|(?:any|my) timers(?: running)?", low):
        return {"command": None, "say": _timer_left()}
    # "How long on the pasta", "how long left on the eggs timer" (2026-10-07:
    # to the planner, and once answered about a different timer).
    m = re.fullmatch(r"how (?:long|much time|many minutes)(?: is)?(?: left| remaining)?(?: on| for| until| till) (?:the |my )?"
                     r"(?P<what>[a-z][a-z ]{1,25}?)(?: timer)?(?: (?:go off|is done|be done|ready))?", low)
    running = _running_once("timer is up") if m else []
    # "How long until christmas" with a timer running answered "You don't
    # have a christmas timer" (2026-10-07). "Until" names a timer only when
    # he says timer, or a running one has that name.
    names_a_timer = m and (re.search(r"\btimer\b", low) or not re.search(r"\b(?:until|till)\b", low)
                           or any(re.search(r"\b" + re.escape(re.sub(r"^(?:the|my) ", "", m.group("what"))) + r"\b",
                                            words.casefold()) for _at, words in running))
    if m and m.group("what") not in ("timer", "timers", "it", "that", "my alarm", "alarm", "reminder", "my reminder",
                                     "next reminder", "next alarm") and running and names_a_timer:
        return {"command": None, "say": _timer_left(named=m.group("what"))}

    # "When's my next alarm" read out every alarm he had (2026-10-07).
    m = re.fullmatch(r"(?:(?:when|what time)(?: is|'s) (?:my|the) next|what(?:'s| is) (?:my|the) next|next) "
                     r"(reminder|alarm|timer)\??", low)
    if m:
        from aletheia import intercom
        return {"command": None, "say": intercom._next_reminder_answer(m.group(1))}
    # "How long until my reminder" (2026-10-07: to a model).
    m = re.fullmatch(r"how (?:long|much time) (?:until|till|til|before) (?:my |the )?(?:next )?(reminder|alarm)"
                     r"(?: goes off| rings)?\??", low)
    if m:
        from aletheia import intercom
        return {"command": None, "say": intercom._until_next_reminder(m.group(1))}
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
                    r"|what reminders (?:have i (?:got|set)|did i set)"
                    # "Did you set any reminders" (2026-10-07: to the planner).
                    r"|(?:did|have) (?:you|u) (?:set|made|make|add|added|got) (?:any|my|the) (?:reminders?|alarms?|timers?)(?: for me)?(?: today| yet)?"
                    r"|(?:what are |show me |read me )?my (?:recurring|repeating|regular) reminders"
                    # "How many reminders do I have" (2026-10-07: to a model)
                    r"|how many (?:reminders|alarms|timers) (?:do i have|have i got|are (?:there|set|running))(?: set| running| on)?", low):
        # "What alarms do I have" was answered "2 reminders: wake up -
        # tomorrow at 6:30 am and wake up - ...": asked about alarms, it
        # says alarms.
        if re.search(r"\balarms?\b", low) and not re.search(r"\b(?:reminders?|timers?)\b", low):
            return {"command": {"kind": "reminders", "which": "wake up"}, "say": None}
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
        alarm = re.fullmatch(r"(?:cancel|stop|delete|turn off|remove|clear|switch off|kill) "
                             r"(?:the |my |that |all )?(?:my )?(?P<before>\d{1,2}(?::\d{2})?(?: ?[ap]\.?m\.?)? )?"
                             r"alarms?(?: (?:for|at) (?:tomorrow|the morning|(?P<after>[\w: ]+)))?", low)
        if alarm:
            # "CANCEL MY 6:30 ALARM" names WHICH alarm; the time travels
            # with the words, and a bare "6" becomes "6:00" so it reads as
            # a time and not a number.
            when = (alarm.group("before") or alarm.group("after") or "").strip()
            if re.fullmatch(r"\d{1,2}", when):
                when += ":00"
            if when and not re.search(r"\d", when):
                when = ""
            return {"command": {"kind": "reminder_off", "which": ("wake up " + when).strip()},
                    "say": None}
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
                            "time": hhmm, "text": _as_he_said(text, m.group(3).strip())},
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
        # "Remind me to drink water every day at 3" was set for 3 am, and
        # "every night at 10" for ten in the morning (2026-10-07).
        if hhmm and m.group("time") and _is_bare_hour(m.group("time")) and int(hhmm[:2]) < 12 \
                and ((part and part.group(1) in ("evening", "night")) or int(hhmm[:2]) <= EARLIEST_BARE_HOUR):
            hhmm = f"{int(hhmm[:2]) + 12:02d}{hhmm[2:]}"
        if hhmm:
            return {"command": {"kind": "remind_daily", "time": hhmm,
                                "text": _as_he_said(text, m.group("text").strip())}, "say": None}
        return _to_the_planner(text)
    # "Remind me every morning to stretch": the part of day BEFORE the
    # thing (2026-10-07: to the planner; only the other order matched).
    m = re.fullmatch(r"remind me (?:every|each) (?P<part>morning|evening|night|day)(?: at (?P<time>[\w: ]+?))? (?:to|that) (?P<text>.+)", low)
    if m:
        hhmm = (_spoken_time(m.group("time")) if m.group("time")
                else {"morning": "09:00", "evening": "19:00", "night": "21:00"}.get(m.group("part"), DEFAULT_REMINDER_TIME))
        if hhmm and m.group("time") and _is_bare_hour(m.group("time")) and int(hhmm[:2]) < 12 \
                and (m.group("part") in ("evening", "night") or int(hhmm[:2]) <= EARLIEST_BARE_HOUR):
            hhmm = f"{int(hhmm[:2]) + 12:02d}{hhmm[2:]}"      # "every night at 10" is ten at night
        if hhmm:
            return {"command": {"kind": "remind_daily", "time": hhmm,
                                "text": _as_he_said(text, m.group("text").strip())}, "say": None}
    m = re.match(r"remind me (?:every day|daily) at ([\w: ]+?) (?:to|that) (.+)", low)
    if m:
        hhmm = _spoken_time(m.group(1))
        if hhmm:
            return {"command": {"kind": "remind_daily", "time": hhmm,
                                "text": _as_he_said(text, m.group(2).strip())}, "say": None}
        return _to_the_planner(text)
    # MONTHLY, EVERY OTHER DAY, EVERY TWO WEEKS (2026-10-07: "remind me on
    # the first of every month to pay rent" was refused as SPENDING, the
    # rest went to the planner). Either word order; nine o'clock when he
    # names no time, as for the weekly ones, and the receipt says it back.
    repeat = _a_repeat(low, text)
    if repeat:
        return repeat
    # "SET A REMINDER FOR 3 TO CALL BOB" and "remind me to check the oven
    # in 20" (2026-10-07: both to the planner) are reminders said another
    # way: the first is "remind me at 3 to", and a bare number after "in"
    # is minutes.
    m = re.fullmatch(r"(?:set|make|create|add) (?:a |me a |an? )?reminder (?:for|at) "
                     r"(?P<t>\d{1,2}(?::\d\d)?(?: ?[ap]\.?m\.?)?|noon|midnight)"
                     r"(?P<day> (?:today|tomorrow|tonight))? (?:to|about|that i need to) (?P<what>.+)", low)
    if m:
        again = _interpret(f"remind me at {m.group('t')}{m.group('day') or ''} to "
                           + _as_he_said(text, m.group("what")))
        if ((again or {}).get("command") or {}).get("kind") == "remind_at":
            return again
    if re.fullmatch(r"remind me to .+ in \d{1,3}", low):
        again = _interpret(text.strip().rstrip(".?! ") + " minutes")
        if ((again or {}).get("command") or {}).get("kind") == "remind_at":
            return again
    # "REMIND ME ABOUT THIS LATER" names neither the thing nor the time,
    # and was read as a memory search for "this later". Asked for whole.
    # (A bare "remind me later" is a snooze of what just fired.)
    if re.fullmatch(r"remind me (?:about|of) (?:this|that|it)(?: (?:later|in a bit|another time|some other time|soon))?"
                    # "Remind me in a bit" (2026-10-07: to the planner).
                    r"|remind me (?:in a (?:bit|while|little bit|little while|few(?: minutes)?)|soon|in a minute)", low):
        return {"command": None,
                "say": "Remind you of what, and when? Say it whole - like \"remind me at 4 to call Sam\" "
                       "or \"remind me in an hour to check the oven\"."}
    # "REMIND ME TOMORROW" names a when and no what (2026-10-07: to the
    # planner). Asked for whole, with the day he said in the example.
    m = re.fullmatch(r"remind me (?P<when>tomorrow(?: morning| afternoon| evening| night)?|tonight|later today"
                     r"|this (?:morning|afternoon|evening)|next week|on (?:monday|tuesday|wednesday|thursday|friday"
                     r"|saturday|sunday)|(?:at|around) (?:\d{1,2}(?::\d\d)?(?: ?[ap]m)?|noon|midnight)(?: (?:today|tomorrow|tonight))?"
                     r"|tomorrow (?:at|around) (?:\d{1,2}(?::\d\d)?(?: ?[ap]m)?|noon))", low)
    if m:
        when = m.group("when")
        return {"command": None,
                "say": f"Remind you of what? Say it whole - like \"remind me {when} to call Sam\"."}
    # "SET AN ALARM FOR 6AM EVERY DAY", "wake me up at 7 every weekday"
    # (2026-10-07: to the planner). The repeating kinds, a wake-up's words.
    m = re.fullmatch(r"(?:wake me(?: up)?|get me up|set (?:an |my )?alarm(?: for)?) (?:at )?(?P<time>[\w: ]+?) "
                     r"(?P<when>every (?:day|morning|weekday|weekend)|each (?:day|morning)|daily|on weekdays|weekdays)", low) \
        or re.fullmatch(r"(?:wake me(?: up)?|get me up|set (?:an |my )?alarm(?: for)?) "
                        r"(?P<when>every (?:day|morning|weekday|weekend)|each (?:day|morning)|on weekdays|weekdays|weekday mornings)"
                        r" (?:at |for )(?P<time>[\w: ]+?)", low)
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

    # "WAKE ME UP IN 20 MINUTES" (2026-10-07: to the planner) - a nap is an
    # alarm from now.
    m = re.fullmatch(r"(?:wake me(?: up)?|get me up|set an alarm) (?:in|for) (?P<span>.+?)(?: from now)?", low)
    if m and _spoken_minutes(m.group("span")) and not re.search(r"\d:\d|\b(?:am|pm)\b", m.group("span")):
        import datetime as dt
        at = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=_spoken_minutes(m.group("span")))).isoformat()
        return {"command": {"kind": "remind_at", "at": at, "text": "wake up"}, "say": None}
    # "REMIND ME THIS WEEKEND TO CLEAN THE GARAGE" (2026-10-07: to the
    # planner): Saturday at nine, the same default hour a day with no time gets.
    m = re.fullmatch(r"remind me (?:this|on the|over the|next) weekend to (?P<what>.+)"
                     r"|remind me to (?P<what2>.+?) (?:this|on the|over the|next) weekend", low)
    if m:
        import datetime as dt
        from aletheia import localtime
        tz = localtime.operator_tz()
        now = dt.datetime.now(tz)
        ahead = (5 - now.weekday()) % 7 + (7 if low.find("next weekend") >= 0 and now.weekday() < 5 else 0)
        when = (now + dt.timedelta(days=ahead)).replace(hour=9, minute=0, second=0, microsecond=0)
        if when <= now:
            when = now.replace(second=0, microsecond=0) + dt.timedelta(hours=1)   # it is the weekend now
        what = m.group("what") or m.group("what2")
        return {"command": {"kind": "remind_at", "at": when.isoformat(), "text": _as_he_said(text, what)}, "say": None}

    # ON A DAY HE TOLD HER ABOUT (2026-10-07: "remind me to buy her flowers
    # on her birthday" went to the planner, with the birthday in a note).
    m = re.fullmatch(r"remind me (?:to |about )?(?P<what>.+?) on (?P<whose>(?:my|our|her|his|their|[a-z]+'s)(?: [a-z]+'s)? "
                     r"(?:birthday|anniversary|wedding anniversary))", low)
    if m:
        import datetime as dt
        from aletheia import localtime, quick
        tz = localtime.operator_tz()
        today = dt.datetime.now(tz).date()
        whose = m.group("whose")
        pron = re.match(r"(?:her|his|their) (.+)", whose)
        if pron:
            # "Call dad on his birthday": the person in the same sentence;
            # otherwise the one the last turns named.
            named = re.search(r"\b(" + "|".join(sorted(_RELATIONS, key=len, reverse=True)) + r")\b", m.group("what"))
            who = named.group(1) if named else _the_person_just_named()
            whose = f"{who.casefold()}'s {pron.group(1)}" if who else whose
        try:
            day = quick._his_date(whose, today)
        except Exception:
            day = None
        if day is None:
            whose = re.sub(r"^my ", "your ", whose)
            if whose.split("'")[0] in _RELATIONS:
                whose = "your " + whose
            return {"command": None, "say": f"I don't know when {whose} is. Tell me the date once and I'll remember it."}
        at = dt.datetime.combine(day, dt.time(9, 0), tzinfo=tz)
        return {"command": {"kind": "remind_at", "at": at.isoformat(), "text": _as_he_said(text, m.group("what"))},
                "say": None}
    # BEFORE THE THING HE JUST PUT ON THE CALENDAR (2026-10-07): "I have a
    # dentist appointment Tuesday at 2", then "remind me the day before" or
    # "remind me an hour before" went to the planner. The hold he just made
    # is "it"; the day before is nine in the morning.
    m = re.fullmatch(r"remind me (?:about it |of it )?(?:(?P<day>the day|the night|the morning) before|"
                     r"(?P<n>\d{1,3}|an|a|one|two|five|ten|fifteen|twenty|thirty|forty-five) (?P<unit>minutes?|mins?|hours?) "
                     r"(?:before|ahead|early|beforehand))(?: it| that)?(?: starts)?", low)
    if m:
        held = _hold_as_it_is_now(_recent_ask_of("calendar_hold", "start"))
        if held:
            import datetime as dt
            from aletheia import localtime
            try:
                start = dt.datetime.fromisoformat(str(held["start"])).astimezone(localtime.operator_tz())
            except (TypeError, ValueError):
                start = None
            if start is not None:
                if m.group("day"):
                    hour = {"the day": 9, "the morning": 8, "the night": 19}[m.group("day")]
                    if m.group("day") == "the morning":
                        when = start.replace(hour=hour, minute=0, second=0, microsecond=0)
                    else:
                        when = (start - dt.timedelta(days=1)).replace(hour=hour, minute=0, second=0, microsecond=0)
                else:
                    n = _spoken_amount(m.group("n")) if m.group("n") not in ("a", "an") else 1
                    when = start - dt.timedelta(**{("hours" if m.group("unit").startswith("h") else "minutes"): n or 1})
                if when > dt.datetime.now(localtime.operator_tz()) and when < start:
                    clock = start.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()
                    return {"command": {"kind": "remind_at", "at": when.isoformat(),
                                        "text": f"{held['title']} {start.strftime('%A')} at {clock}"}, "say": None}
    # BEFORE AN EVENT, SAID THE OTHER WAY ROUND (2026-10-07): "remind me
    # about the meeting 10 minutes before" compiled a memory RECALL of "the
    # meeting 10 minutes before". It is "remind me 10 minutes before my
    # meeting", which has its own branch.
    m = re.fullmatch(r"remind me (?:about |of )?(?:my |the )?(?P<what>[a-z][a-z' ]{1,40}?) "
                     r"(?P<n>\d{1,3}|an|a|one|five|ten|fifteen|twenty|thirty|forty-five) (?P<unit>minutes?|mins?|hours?) "
                     r"(?:before|ahead|early|beforehand)(?: it starts)?", low)
    if m:
        return _interpret(f"remind me {m.group('n')} {m.group('unit')} before my {m.group('what')}")

    # A TASK SAID AS A NEED (2026-10-07): "I need to call the bank
    # tomorrow" and "don't let me forget to pay rent" went to the planner.
    # Only when what follows starts like a thing to do - "I need to know"
    # and "I have to say" are not tasks.
    m = re.fullmatch(r"(?:i (?:need|have|got) to|i've got to|i gotta|i must|i should(?: really)?|"
                     r"(?:don'?t|do not) let me forget to|make sure i|remember i (?:need|have) to)"
                     r" (?P<what>.{3,120})", low)
    if m and (_TASK_VERB.match(m.group("what")) or low.startswith(("don't let me", "dont let me", "do not let me"))):
        if re.search(r"\bat \d{1,2}(?::\d\d)?(?: ?[ap]\.?m\.?)?\b", m.group("what")):
            # A clock time makes it a reminder: "pick up the kids at 3".
            timed = _interpret(f"remind me to {m.group('what')}")
            if ((timed or {}).get("command") or {}).get("kind") == "remind_at":
                return timed
        return _new_task(_as_he_said(text, m.group("what")))

    # THE VERB WITH NOTHING AFTER IT. "Set a reminder", "take a note" and
    # "add a task" went to the planner, which with nothing thinking kept
    # them for later - an ask with no content, filed. The answer is the
    # one question that gets the content, with the sentence that works.
    # "READ MY LAST TEXT": the texts on his Google Voice number have had a
    # reader since September and no sentence reached it, while the answer
    # beside it offered exactly that. Texts on his own phone still stay
    # there, and that answer still says so.
    said = low.strip().rstrip("?.! ")
    texts = re.fullmatch(
        r"(?:(?:can you |could you |please )?(?:read|check|show) (?:me )?(?:my )?"
        r"(?:last|latest|newest|most recent|new|recent)? ?(?:texts?|text messages?|sms)"
        r"(?: from (?P<from1>[a-z][a-z' ]{0,30}))?"
        r"|(?:any|do i have any|have i got any|did i get any) (?:new )?(?:texts?|text messages?)"
        r"(?: from (?P<from2>[a-z][a-z' ]{0,30}))?"
        r"|(?:did|has) (?P<from3>[a-z][a-z' ]{0,30}?) (?:text|texted) me(?: back)?"
        r"|what did (?P<from4>[a-z][a-z' ]{0,30}?) (?:text|say in (?:his|her|their) text)(?: me)?(?: about)?)",
        said)
    # "HOW MANY STEPS DID I TAKE" went to a model, which has no steps to
    # count. Health readings live on his phone or watch, and saying so is
    # the whole answer.
    if re.fullmatch(r"(?:how many|what(?:'s| are| is)? my|did i (?:hit|reach|get)(?: my)?) "
                    r"(?:steps?|step count|steps goal|heart rate|resting heart rate|sleep score|calories burned)"
                    r"(?: (?:did i (?:take|do|walk|get|burn)|have i (?:taken|done|walked|burned)|today|yesterday|this week|goal))*",
                    said):
        return {"command": None,
                "say": "I can't see your health data - steps, heart rate and sleep stay on your phone or watch."}
    if texts:
        who = next((g for g in texts.group("from1", "from2", "from3", "from4") if g), "")
        who = re.sub(r"^(?:my|the) ", "", who.strip())
        return {"command": {"kind": "texts_read", **({"who": _as_he_said(text, who)} if who else {})},
                "say": None}
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
    # A TIMER OF TWO PARTS (2026-10-07): "set a timer for an hour and a
    # half", "1 hour and 20 minutes", "two and a half minutes" all went to
    # the planner - the pattern below reads one number and one unit.
    m = re.fullmatch(r"(?:(?:set|start) (?:a |me a )?timer(?: for)?|timer(?: for)?|remind me in) "
                     r"(?:(?P<h>an|a|one|\d{1,2}|two|three) (?:hours?|hrs?)(?: and)? "
                     r"(?:(?P<half>a half)|(?P<m>\d{1,2}|five|ten|fifteen|twenty|thirty|forty|forty-five|fifty) (?:minutes?|mins?))"
                     r"|(?P<n>a|one|\d{1,2}|two|three|four|five|ten) and a half (?P<u>minutes?|hours?)"
                     r"|(?P<n2>a|one|\d{1,2}|two|three|four|five|ten) (?P<u2>minutes?|hours?) and a half)", low)
    if m:
        import datetime as dt
        words = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10,
                 "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "forty-five": 45, "fifty": 50}
        num = lambda w: int(w) if w.isdigit() else words[w]
        if m.group("h"):
            minutes = num(m.group("h")) * 60 + (30 if m.group("half") else num(m.group("m")))
        else:
            n, u = (m.group("n"), m.group("u")) if m.group("n") else (m.group("n2"), m.group("u2"))
            minutes = (num(n) + 0.5) * (60 if u.startswith("hour") else 1)
        hours, rest = divmod(minutes, 60)
        if hours and rest:
            said = f"{int(hours)} hour {rest:g} minute"
        elif hours:
            said = f"{int(hours)}-hour"
        else:
            said = f"{rest:g}-minute" if float(rest).is_integer() else f"{int(rest)} and a half minute"
        at = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutes)).isoformat()
        return {"command": {"kind": "remind_at", "at": at, "text": f"your {said} timer is up"}, "say": None}
    # "Pause the timer": a timer here is a reminder at a set time, so there
    # is nothing to pause - say so, and what she can do instead.
    if re.fullmatch(r"(?:pause|hold|freeze|resume|unpause|restart) (?:the |my |that )?timers?", low):
        return {"command": None, "say": "I can't pause a timer - it goes off at a set time. I can cancel it, "
                                         "or add minutes: say \"add 5 minutes\"."}
    # "Remind me in 10" and "a timer for 20" (2026-10-07: to the planner):
    # a bare number of a kitchen timer is minutes.
    bare = re.fullmatch(r"(remind me in|(?:set|start) (?:a |me a )?timer for|timer for) (\d{1,3})( (?:to|about|that) .+)?", low)
    if bare and 1 <= int(bare.group(2)) <= 180:
        return _interpret(f"{bare.group(1)} {bare.group(2)} minutes{bare.group(3) or ''}")
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
    # "The day after tomorrow", "tonight at 8", "on Halloween" (2026-10-07:
    # all three to the planner).
    _days = (r"(?:(?:next )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|tomorrow|today|tonight|"
             r"(?:the )?day after tomorrow|halloween|christmas(?: eve| day)?|new year'?s(?: eve| day)?|"
             r"valentine'?s day|thanksgiving|(?:the )?fourth of july|"
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
        if m.group("time") and _is_bare_hour(m.group("time")) and (
                hour <= EARLIEST_BARE_HOUR or (m.group("day") == "tonight" and hour < 12)):
            hour += 12                                  # "at 6" on a Sunday is the evening; "at 9" the morning
        if m.group("day") == "tonight" and not m.group("time") and not m.group("part"):
            hour, minute = 21, 0
        tz = localtime.operator_tz()
        when = dt.datetime.combine(dt.date.fromisoformat(day_iso), dt.time(hour, minute), tzinfo=tz)
        if when <= dt.datetime.now(tz) and m.group("day") == "tonight":
            # Said at ten at night, "tonight" still means tonight: an hour on.
            when = (dt.datetime.now(tz) + dt.timedelta(hours=1)).replace(second=0, microsecond=0)
        elif when <= dt.datetime.now(tz) and m.group("day") in ("today", ""):
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
                       f"Give me a time - 'remind me at 6 to {_as_he_said(text, m.group(1).strip())}' - and I'll do that."}
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
                            "text": _as_he_said(text, m.group(1).strip())}, "say": None}

    # A TIMER IS A ONE-SHOT ALERT, which is what `remind_at` already is.
    # `timer.set` was NOT_BUILT because the sentence reached nothing, not
    # because the mechanism was missing: "remind me in 10 minutes to
    # check the oven" has worked for weeks. So a timer said AS a timer
    # compiles to the same durable schedule, with the words a person
    # wants to hear at the end.
    # "Set a 10 minute timer for the pasta" (2026-10-07: to the planner) is
    # the same timer with the length said first.
    said_first = re.fullmatch(r"(?:set|start) (?:a |an |me a )?(\d+)[- ]?(seconds?|secs?|minutes?|mins?|hours?|hrs?)"
                              r" timer(?:\s+(to|for|so i can)\s+(.+))?", low)
    timer_words = (f"set a timer for {said_first.group(1)} {said_first.group(2)}"
                   + (f" {said_first.group(3)} {said_first.group(4)}" if said_first.group(3) else "")) if said_first else low
    # "Set a pasta timer for 8 minutes", "set a timer for pasta for 8
    # minutes" (2026-10-07: to the planner) - the name said before the length.
    named_first = re.fullmatch(r"(?:set|start) (?:a |an |me a )?(?:timer for (?:the |my )?(?P<a>[a-z][a-z ]{1,24}?) for"
                               r"|(?P<b>[a-z][a-z ]{1,24}?) timer for) (?P<n>\d+) ?(?P<u>seconds?|secs?|minutes?|mins?|hours?|hrs?)",
                               low)
    if named_first and "timer" not in (named_first.group("a") or named_first.group("b")):
        name = named_first.group("a") or named_first.group("b")
        # "A new timer", "another timer": no name, just a timer.
        plain = re.fullmatch(r"(?:new|another|quick|second|kitchen|other)", name)
        timer_words = (f"set a timer for {named_first.group('n')} {named_first.group('u')}"
                       + ("" if plain else f" for {name}"))
    # "Set a timer for 5 minutes called tea" (2026-10-07: to the planner).
    timer_words = re.sub(r"^((?:set|start) (?:a |an )?timer (?:for |of )?\d+\s*\w+) (?:called|named|labell?ed) "
                         r"(?:the |my )?([a-z][a-z ]{1,24})$", r"\1 for \2", timer_words)
    timer_words = re.sub(r"^(?:set|start) (?:a |an )?(\d+)[- ]?(second|sec|minute|min|hour|hr)s? timer (?:called|named|labell?ed) "
                         r"(?:the |my )?([a-z][a-z ]{1,24})$", r"set a timer for \1 \2s for \3", timer_words)
    m = re.fullmatch(r"(?:set|start) (?:a |an )?timer (?:for |of )?"
                     r"(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)"
                     r"(?:\s+(to|for|so i can)\s+(.+))?", timer_words)
    if m:
        import datetime as dt
        amount, unit = int(m.group(1)), m.group(2)
        if unit.startswith(("second", "sec")):
            delta, spoken_unit = dt.timedelta(seconds=amount), "second"
        elif unit.startswith(("hour", "hr")):
            delta, spoken_unit = dt.timedelta(hours=amount), "hour"
        else:
            delta, spoken_unit = dt.timedelta(minutes=amount), "minute"
        why = (m.group(4) or "").strip()
        if why and m.group(3) == "for":
            # "for the eggs" names the timer, it is not the thing to do:
            # "the eggs" alone read out at the end means nothing.
            # Said as "your 10 minute pasta timer is up", the shape every
            # timer reader matches on ("... timer is up").
            what = re.sub(r"^(?:the|my|some) ", "", why)
            why = f"your {amount} {spoken_unit} {what} timer is up"
        # The unit is an ADJECTIVE here and stays singular — "a 10
        # minute timer", not "a 10 minutes timer". Pluralising it
        # is the right rule in the wrong place, and this is read
        # out loud.
        text = why or f"your {amount} {spoken_unit} timer is up"
        at = (dt.datetime.now(dt.timezone.utc) + delta).isoformat()
        return {"command": {"kind": "remind_at", "at": at, "text": text},
                "say": None}

    # "Set a timer for the pasta" (2026-10-07: to the planner). The thing
    # is named and the length is not; ask for the one missing fact, and
    # keep his word in the example so the answer can be said back whole.
    m = re.fullmatch(r"(?:set|start) (?:a |me a )?timer for (?:the |my |some )?(?P<what>[a-z][a-z ]{1,24}?)", low)
    if m and not re.search(r"\b(?:\d|an?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
                           r"fifteen|twenty|thirty|forty|fifty|sixty|half|quarter|minutes?|mins?|hours?|"
                           r"seconds?|secs?|hrs?|me|later|now|tomorrow|tonight)\b", m.group("what")):
        what = m.group("what").strip()
        return {"command": None,
                "say": f'How long for the {what}? Say "set a timer for 10 minutes for the {what}".'}

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
                    r"my tasks|list (?:my )?tasks|what do i (?:have|need|still have) to do(?: today| now| still)?|"
                    r"what(?:'s| is|s)? left to do(?: today)?|what(?:'s| is|s)? left (?:for|on my list) today|todo list|"
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
    # "MAKE IT DUE FRIDAY" right after a task was added (2026-10-07: to the
    # planner): "it" is the task the last turn added, and only that.
    m = re.fullmatch(r"(?:no,? )?(?:make|set) (?:it|that) (?:due )?(?:on |for |by )?(?P<day>today|tomorrow|tonight|(?:this |next )?"
                     r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))"
                     r"|(?:no,? )?(?:change|move|push|switch|bump) (?:it|that)(?: to| till| until| back to)? (?P<day2>today|tomorrow|tonight|"
                     r"(?:this |next )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))"
                     r"|(?:it'?s|it is) due (?P<day3>today|tomorrow|tonight|(?:this |next )?"
                     r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))", low)
    task = _the_task_just_added() if m else ""
    if m and task:
        said = m.group("day") or m.group("day2") or m.group("day3")
        if said.startswith("next "):
            asked = _ambiguous_next_weekday(said)
            if asked:
                return {"command": None, "say": asked}
        day = _spoken_day("today" if said == "tonight" else said)
        if day:
            return {"command": {"kind": "task_change", "which": task, "deadline": day}, "say": None}
    # "Add a task to email Sam", then "actually make that call Sam"
    # (2026-10-07: to the planner) - the task just added, renamed. A time
    # or a day is a move, handled above and by the reminder mover.
    m = re.fullmatch(r"(?:make (?:it|that)|change (?:it|that) to|rename (?:it|that)(?: to)?|call (?:it|that)) "
                     r"(?P<new>[a-z][a-z0-9 ,.'-]{2,80})", low)
    if m and not re.match(r"(?:due|at|for|by|on|in|next|this|today|tomorrow|tonight|noon|midnight|\d"
                          r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", m.group("new")):
        task = _the_task_just_added()
        if task and task.casefold() != m.group("new").casefold():
            return {"command": {"kind": "task_change", "which": task,
                                "description": _as_he_said(text, m.group("new"))}, "say": None}
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

    # A THING ON THE SHOPPING LIST, TICKED OFF (2026-10-07): "check off
    # milk" marked a TASK called milk done, and "got the milk" / "bought
    # eggs" went to the planner. Only when that thing is on the list; a task
    # by that name is still the task.
    m = re.fullmatch(r"(?:tick|check|cross|mark) off (?:the |some )?(?P<w>.+?)", low) \
        or re.fullmatch(r"(?:i )?(?:got|bought|picked up|grabbed) (?:the |some )?(?P<w>[a-z][a-z' ]{1,30}?)"
                        r"(?: already| now)?", low)
    if m and _on_the_shopping_list(m.group("w")) and not _names_one_open_task(m.group("w")):
        return {"command": {"kind": "shopping_off", "item": m.group("w").strip()}, "say": None}
    # "I GOT EVERYTHING" back from the store (2026-10-07: to the planner).
    # The whole list, and only when there is one to clear.
    if re.fullmatch(r"(?:i )?(?:got|bought|picked up|grabbed) (?:everything|it all|all of it|all of them|all that)"
                    r"(?: on (?:the|my) (?:shopping |grocery )?list)?(?: already| now)?", low):
        try:
            from aletheia import intercom
            if intercom._shopping_items():
                return {"command": {"kind": "shopping_off", "item": "everything"}, "say": None}
        except Exception:  # noqa: BLE001 - unreadable goes to the planner as before
            pass
    # "Did I add milk" is "is milk on the list" (2026-10-07: to the planner).
    m = re.fullmatch(r"did i (?:already )?(?:add|put) (?:the |some )?(?P<w>[a-z][a-z' ]{1,30}?)"
                     r"(?: (?:to|on) (?:the|my) (?:shopping |grocery )?list)?", low)
    if m:
        from aletheia import quick
        said = quick._shopping_has(m.group("w"))
        if said:
            return {"command": None, "say": said}
    # "Clear the list" names no list; with nothing but the shopping list
    # to mean, it is that one - the same cancel-every-row verb.
    if re.fullmatch(r"(?:clear|empty|wipe) (?:the|my) list", low) and not _other_lists():
        return {"command": {"kind": "shopping_off", "item": "everything"}, "say": None}

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
         or re.fullmatch(r"i (?:did|have done) (?:the )?(.+?)(?: one| task)?", low)
         # "The second one is done" after she read the list (2026-10-07: to
         # the planner). Counting only - "the dishwasher is done" is a machine.
         or re.fullmatch(r"(?:the )?(first|second|third|fourth|fifth|last|top|1st|2nd|3rd|4th|5th) (?:one|task|thing)"
                         r"(?:'s| is| was)? (?:done|finished|complete[d]?|taken care of)", low))
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

    # "Done with laundry", "finish the dentist task", "the laundry task is done",
    # "I called the dentist" (2026-10-07: to the planner). Only when the
    # words pick out exactly one open task - "I called the dentist" with no
    # such task is news, not a tick.
    m = (re.fullmatch(r"(?:i'?m )?done with (?:the |my )?(?P<w>.+?)(?: one| task)?", low)
         or re.fullmatch(r"(?:finish|complete|close) (?:the |my )?(?P<w>.+?) (?:task|one)", low)
         # "The dishwasher is done" is the machine, not his task to unload it.
         or re.fullmatch(r"(?:the |my )?(?P<w>.+?) task is (?:done|finished|complete|taken care of)", low)
         # "I need to sort the photos" is not a past tense (2026-10-07: it
         # ticked a task off).
         or re.fullmatch(r"i (?:just |already )?(?P<w>(?![a-z]*eed\b|used\b)[a-z]+ed (?:the |my |a )?.+)", low))
    if m and m.group("w") not in ("it", "that", "this", "everything", "all", "work", "today") \
            and _names_one_open_task(m.group("w")):
        return {"command": {"kind": "task_done", "which": m.group("w")}, "say": None}

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

    # A PLACE NEAR HIM is not a file (2026-10-07): "find a gas station" was
    # a search of his disk and "where's the nearest starbucks" went to the
    # planner. The same web search "pizza near me" already runs.
    m = re.fullmatch(r"(?:find|show me|search for|look for|where(?:'s| is| are)) (?:me )?(?:a |an |the )?"
                     r"(?:nearest|closest|nearby) (?P<what>[a-z][a-z' ]{1,30}?)(?: near me| nearby| around here)?", low) \
        or re.fullmatch(r"(?:find|show me|search for|look for) (?:me )?(?:a |an |some )?(?P<what>[a-z][a-z' ]{1,30}?)"
                        r" (?:near me|nearby|around here|close by|near here)", low) \
        or re.fullmatch(r"find (?:me )?(?:a |an )(?P<what>gas station|petrol station|pharmacy|drugstore|grocery store|"
                        r"supermarket|restaurant|coffee shop|cafe|atm|bank|hospital|urgent care|hotel|parking(?: spot| garage)?|"
                        r"car wash|gym|bar|pizza place|taco place|mechanic|post office|hardware store|vet|dentist|doctor)", low)
    if m:
        return {"command": {"kind": "research", "question": f"{m.group('what').strip()} near me"}, "say": None}
    # "FIND ME A RECIPE FOR CHICKEN" (2026-10-07: to the planner) - a web
    # search like any other, named as a recipe.
    m = re.fullmatch(r"(?:find|get|give|show|look up|search for|pull up) (?:me )?(?:a |some |an )?(?:good |easy |quick |simple )?"
                     r"recipes? (?:for|with) (?P<what>[a-z][a-z' ,-]{1,50})", low)
    if m:
        return {"command": {"kind": "research", "question": f"{m.group('what').strip()} recipe"}, "say": None}

    # "What files did I make today", "my recent files", "what did I
    # download this week" (2026-10-07: to a model). His folders, newest
    # first, cut to the window he named.
    m = (re.fullmatch(r"(?:what|which) (?:files|documents|docs) (?:did i|have i) (?:make|made|save|saved|change|changed|edit|edited|"
                      r"work on|worked on|create|created|touch|touched)(?P<since> today| yesterday| this week| recently| lately)?", low)
         or re.fullmatch(r"(?:show me |what are |list )?(?:my )?(?:recent|latest|newest) (?:files|documents|docs)", low)
         or re.fullmatch(r"what (?:did i|have i) (?:download|downloaded)(?P<since> today| yesterday| this week| recently| lately)?", low))
    if m:
        since = (m.groupdict().get("since") or " recently").strip().replace("lately", "recently")
        command = {"kind": "file_find", "query": "", "since": since}
        if "download" in low:
            command["place"] = _a_place_she_knows("downloads") or "Downloads"
        return {"command": command, "say": None}

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
        # "Find me remote jobs" searched for a job called "remote"
        # (2026-10-07). A word about the job's kind is not its title: the
        # roles come from his resume, and remote is where.
        if m.group("role") in ("remote", "local", "new", "good", "open", "more", "some", "any", "nearby"):
            command = {"kind": "jobs"}
            if m.group("role") == "remote":
                command["where"] = "remote"
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
            w not in ("me", "my", "your", "the", "all", "any", "those", "these", "our", "a",
                      # "read me my latest note" is the newest note, not a file
                      # called "latest" (2026-10-07).
                      "last", "latest", "newest", "recent", "most", "new")
            for w in m.group("what").split()) \
            and not re.search(r"\b(?:called|named|about)$", m.group("what")):
        # "Find a file called notes" searched for "a file called" (2026-10-07);
        # the name is after "called", which the finder below reads.
        return {"command": {"kind": "file_find",
                            "query": _as_he_said(transcript, m.group("what"))},
                "say": None}

    # "FIND A TIME FOR LUNCH WITH SAM THIS WEEK" compiled a file search for
    # "time for lunch with sam this week" (2026-10-07). It is when he is free.
    m = re.fullmatch(r"(?:find|pick|suggest|give me|when(?:'s| is) there) (?:me )?(?:a |some )?(?:good )?time(?:s)? (?:for|to) "
                     r"(?P<purpose>.+?)(?: (?P<when>today|tomorrow|this week|next week|this weekend|monday|tuesday|wednesday"
                     r"|thursday|friday|saturday|sunday))?", low)
    if m:
        command = {"kind": "calendar_find_free", "when": m.group("when") or "this week",
                   "purpose": _as_he_said(transcript, m.group("purpose"))}
        return {"command": command, "say": None}
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

    if re.fullmatch(r"(?:do i have|have i got|are there|is there) (?:any |an? )?(?:alarms?|reminders?|timers?)(?: set| running| on)?(?: for (?:today|tomorrow))?", low):
        if re.search(r"\balarms?\b", low):
            return {"command": {"kind": "reminders", "which": "wake up"}, "say": None}
        return {"command": {"kind": "reminders"}, "say": None}
    m = re.fullmatch(
        r"(?:find|look for|search for|do i have|have i got) "
        r"(?:a |an |any |my |the )?(?:files? |documents? )?"
        r"(?:called |named |about )?(.+?)\s*\??", low)
    # "Find me 30 minutes tomorrow" is time on his calendar, not a file.
    if m and re.match(r"(?:me )?(?:an hour|half an hour|\d{1,3} minutes|\d hours?|some time|a slot|time)\b", m.group(1)):
        m = None
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
                    r"what city (?:am i in|do i live in)|where(?:'s| is) (?:my )?home"
                    r"|where am i|what(?:'s| is) my (?:location|current location)|where do you think i (?:am|live)", low):
        return {"command": None, "say": _where_he_lives()}
    m = re.fullmatch(r"(?:spell|how do (?:you|u) spell) my (?P<which>first|last|full|sur)?\s*name(?: for me)?", low)
    if m:
        return {"command": None, "say": _spell_his_name(m.group("which") or "full")}

    if re.fullmatch(r"what(?:'s| is|s) (?:my |the )?(?:most recent|latest|newest|last) e-?mail(?: about| say| saying)?"
                    r"|(?:my |any |the )?(?:unread|new) (?:e-?mails?|mail)|(?:read|check) (?:me )?(?:my )?(?:unread|new) (?:e-?mails?|mail)"
                    r"|how many (?:unread |new )?e-?mails? (?:do i have|have i got)", low):
        return {"command": {"kind": "email_check"}, "say": None}
    # HIS PACKAGES (2026-10-07: "where is my amazon order" searched his
    # FILES for "amazon order"; "track my package" went to the planner).
    # She cannot track a parcel; the shipping email is the one place she
    # can look, so a named shop is read from his inbox.
    m = re.fullmatch(r"where(?:'s| is| are) my (?P<shop>[a-z][a-z0-9 &'.-]{1,25}?) (?:order|package|delivery|parcel|shipment)s?"
                     r"|(?:track|check on) my (?P<shop2>[a-z][a-z0-9 &'.-]{1,25}?) (?:order|package|delivery|parcel)s?", low)
    if m:
        return {"command": {"kind": "email_read", "which": (m.group("shop") or m.group("shop2")).strip()}, "say": None}
    if re.fullmatch(r"(?:track|check on|where(?:'s| is| are)) (?:my |the )?(?:package|packages|order|orders|delivery|deliveries|parcel|shipment)"
                    r"|did (?:i get|my) (?:a |the |my )?(?:package|order|delivery|parcel)(?: come| arrive)?(?: yet| today)?"
                    r"|(?:has|did) my (?:package|order|delivery|parcel) (?:come|arrive|ship|shipped)(?: yet)?", low):
        return {"command": None,
                "say": "I can't track parcels, but shipping emails come to your inbox. Say \"any emails from Amazon\" "
                       "(or whoever it's from) and I'll read them."}
    # Deleting or marking mail is his: she reads it and drafts it, no more.
    if re.fullmatch(r"(?:delete|trash|archive|mark|flag|star|unsubscribe from) (?:that|this|the|my|the last|my last|all)? ?"
                    r"(?:e-?mails?|mail)(?: as (?:read|unread|spam|important))?(?: from .+)?"
                    # "Mark it as read" right after an email (2026-10-07: to the planner).
                    r"|mark (?:it|that|them|those|everything|all) (?:as )?(?:read|unread|spam|important)", low):
        return {"command": None,
                "say": "I only read your email and write drafts - I can't delete, archive or mark messages. "
                       "Do that in your mail app."}

    m = re.fullmatch(r"where(?:'s| is| are)? (?:my |the )?(.+?)\s*\??", low)
    # "Note that the wifi code is on the fridge", then "where's the wifi
    # code" searched his Documents (2026-10-07). A note saying where it is
    # answers before a file search does.
    if m:
        put = _where_he_put(m.group(1))
        if put:
            return {"command": None, "say": put}
        # "The gym is at 20 Oak Ave", then "where is the gym" searched his
        # Documents for a file called gym. A place she keeps answers first.
        from aletheia import quick
        there = quick._place_where(m.group(1))
        if there:
            return {"command": None, "say": there}
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
                    r"what's new|anything new|notifications?|any updates?|(?:are there )?any news for me)", low):
        return {"command": {"kind": "notify_check"}, "say": None}
    # MORE TIME ON THE TIMER, AND THE ALARM MOVED (2026-10-07: both to the planner).
    # Not "give me a minute": that is a nod to the room, and stays one.
    m = re.fullmatch(r"(?:add|put|give it) (?P<n>\d{1,3}|a|one|two|three|five|ten|fifteen|twenty|thirty) (?:more )?"
                     r"(?P<unit>minutes?|mins?|seconds?)(?: more)?(?: (?:to|on) (?:the |my )?timer)?"
                     r"|(?P<n2>\d{1,3}|a|one|two|three|five|ten|fifteen|twenty|thirty) more (?P<unit2>minutes?|mins?)(?: on (?:the |my )?timer)?"
                     r"|give me (?P<n4>\d{1,3}|a|one|two|three|five|ten|fifteen|twenty|thirty) more (?P<unit4>minutes?|mins?)"
                     r"(?: on (?:the |my )?timer)?"
                     r"|(?:extend|add to) (?:the |my )?timer by (?P<n3>\d{1,3}|five|ten|fifteen|twenty|thirty) (?P<unit3>minutes?|mins?)"
                     # "Add 2 minutes to the pasta timer" (2026-10-07: to the planner).
                     r"|(?:add|put) (?P<n5>\d{1,3}|a|one|two|three|five|ten|fifteen|twenty|thirty) (?:more )?(?P<unit5>minutes?|mins?)"
                     r" (?:to|on) (?:the |my )?(?P<named>[a-z][a-z ]{1,25}?) timer", low)
    if not m:
        # "Add 5 minutes to the pizza" - no word "timer", so only when a
        # running timer is called that (2026-10-07: to the planner).
        bare = re.fullmatch(r"(?:add|put|give) (?P<n5>\d{1,3}|a|one|two|three|five|ten|fifteen|twenty|thirty) (?:more )?"
                            r"(?P<unit5>minutes?|mins?) (?:to|on) (?:the |my )?(?P<named>[a-z][a-z ]{1,25}?)", low)
        if bare and any(re.search(r"\b" + re.escape(bare.group("named")) + r"\b", words)
                        for _at, words in _running_once("timer is up")):
            m = bare
    if m:
        words = {"a": 1, "one": 1, "two": 2, "three": 3, "five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30}
        g = m.groupdict()
        n = g.get("n") or g.get("n2") or g.get("n3") or g.get("n4") or g.get("n5")
        unit = g.get("unit") or g.get("unit2") or g.get("unit3") or g.get("unit4") or g.get("unit5") or "minutes"
        count = int(n) if n.isdigit() else words[n]
        if unit.startswith("sec"):
            return {"command": None, "say": "I can add whole minutes to a timer, not seconds."}
        return _more_on_the_timer(count, named=g.get("named") or "")
    m = re.fullmatch(r"(?:change|move|set|make|push|switch|reset) (?:my |the )?"
                     r"(?P<was>\d{1,2}(?::\d{2})?(?: ?[ap]\.?m\.?)? )?alarm"
                     r"(?: (?:for|at) (?P<was2>\d{1,2}(?::\d{2})?(?: ?[ap]\.?m\.?)?))? (?:to|for|until) (?P<time>[\w: ]+?)", low)
    if m:
        return _moved_alarm(m.group("time"), (m.group("was") or m.group("was2") or "").strip())
    # HOW FAST SHE TALKS (2026-10-07: "slower" and "talk slower" went to the
    # planner). Bare "slower"/"faster" are about her voice only when nothing
    # else could be meant; music has its own words.
    if re.fullmatch(r"(?:(?:talk|speak|go|say it|read)(?: a (?:little|bit|lot))? (?:slower|more slowly|slowly)"
                    r"|slow (?:down|it down)(?: (?:when|while) (?:you )?(?:talk|speak)(?:ing)?)?|slower(?: please)?"
                    r"|(?:you(?:'re| are) )?talking too fast|(?:can|could) you (?:talk|speak) (?:slower|more slowly))(?: please)?", low):
        return {"command": {"kind": "speaking_pace", "action": "slower"}, "say": None}
    if re.fullmatch(r"(?:(?:talk|speak|go|read)(?: a (?:little|bit|lot))? (?:faster|quicker|more quickly)"
                    r"|speed up(?: (?:when|while) (?:you )?(?:talk|speak)(?:ing)?)?|faster(?: please)?"
                    r"|(?:you(?:'re| are) )?talking too slow(?:ly)?|(?:can|could) you (?:talk|speak) (?:faster|quicker))(?: please)?", low):
        return {"command": {"kind": "speaking_pace", "action": "faster"}, "say": None}
    if re.fullmatch(r"(?:talk|speak) (?:normally|at (?:a )?normal speed|at your normal speed|normal(?: speed)?)"
                    r"|(?:go back to |reset )(?:your )?normal (?:talking )?speed|normal speed(?: please)?", low):
        return {"command": {"kind": "speaking_pace", "action": "normal"}, "say": None}
    # "Speak up": her voice is already at full volume; the PC's is his.
    if re.fullmatch(r"speak up|talk louder|speak louder|(?:can|could) you (?:speak|talk) (?:up|louder)|i can'?t hear you", low):
        return {"command": {"kind": "music", "action": "volume_up"}, "say": None}

    # HIS STOPWATCH (2026-10-07: "start a stopwatch" went to the planner).
    if re.fullmatch(r"(?:start|begin|set|run) (?:a |the |my )?stopwatch(?: now| for me)?|stopwatch(?: start| go)", low):
        return {"command": {"kind": "stopwatch", "action": "start"}, "say": None}
    if re.fullmatch(r"(?:stop|pause|end|halt) (?:the |my )?stopwatch(?: now)?|stopwatch stop", low):
        return {"command": {"kind": "stopwatch", "action": "stop"}, "say": None}
    if re.fullmatch(r"(?:reset|clear|restart) (?:the |my )?stopwatch", low):
        return {"command": {"kind": "stopwatch", "action": "reset"}, "say": None}
    # "How long has it been" straight after the stopwatch (2026-10-07: to a
    # model, which had no stopwatch to read).
    if re.fullmatch(r"how long has it been(?: running| going)?|how long(?:'s| is) it been|what(?:'s| is) it at"
                    r"|how much time (?:has passed|is on it)|what(?:'s| is) the time on it", low):
        try:
            from aletheia import converse, quick
            rows = converse.recent(limit=2) or []
            if any("stopwatch" in f"{r.get('he_asked') or ''} {r.get('she_answered') or ''}".casefold() for r in rows):
                said = quick.answer("how long has the stopwatch been running")
                if said:
                    return {"command": None, "say": said}
        except Exception:  # noqa: BLE001 - the planner still has it
            pass
    # "CLEAR MY SHOPPING LIST" (2026-10-07: to the planner). Every row is
    # cancelled, never deleted, through the verb that already does it.
    if re.fullmatch(r"(?:clear|empty|wipe|reset|delete|delete everything on|clear out|empty out|get rid of|scrap) (?:my |the )?"
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

    # "HAVE I HEARD FROM DANA", "did I hear back from Gong", "anything from
    # Dana" (2026-10-07: to the planner). His mail from them, the same read
    # as "any emails from Dana"; a conversation she keeps answers below.
    m = re.fullmatch(r"(?:have i heard|did i hear|have we heard|did we hear|anything|any news)(?: back)?(?: yet)? from "
                     r"(?P<who>[a-z][a-z' .&-]{1,30}?)(?: yet)?", low)
    if m and m.group("who") not in ("work", "anyone", "anybody", "them", "they", "you", "him", "her"):
        # An employer on his job record is the fast lane's to answer.
        try:
            from aletheia import quick
            if quick.answer(text):
                return {"command": {"kind": "intent", "text": text}, "say": None}
        except Exception:  # noqa: BLE001
            pass
        try:
            from aletheia import conversations
            kept = conversations.resolve_thread(m.group("who"))
        except Exception:  # noqa: BLE001
            kept = None
        if kept:
            return {"command": {"kind": "thread_status", "which": m.group("who")}, "say": None}
        return {"command": {"kind": "email_read", "which": m.group("who")}, "say": None}
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

    # "IS FRIDAY FREE" (2026-10-07: to the planner) - the day's free time.
    m = re.fullmatch(r"is (?:my )?(?:this )?(?P<day>today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
                     r"(?: (?P<part>morning|afternoon|evening))? (?:free|open|clear|busy)\s*\??", low)
    if m and _spoken_day(m.group("day")):
        command = {"kind": "free_time", "day": _spoken_day(m.group("day"))}
        if m.group("part"):
            command["part"] = m.group("part")
        return {"command": command, "say": None}

    # "Anything this evening", "do I have anything this afternoon"
    # (2026-10-07: to the planner) - that part of today's free time.
    m = re.fullmatch(r"(?:do i have |have i got |is there )?anything (?:on |planned |happening )?"
                     r"(?:this (?P<part>morning|afternoon|evening)|(?P<tonight>tonight))\s*\??", low)
    if m:
        return {"command": {"kind": "free_time", "day": _spoken_day("today"),
                            "part": m.group("part") or "tonight"}, "say": None}

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

    # "WHAT TIME AM I FREE TOMORROW", "find me 30 minutes tomorrow", "do I
    # have time for lunch", "when's my next free hour" (2026-10-07: the
    # planner, and "find me 30 minutes" searched his FILES). The day's free
    # time, for as long as he says.
    m = re.fullmatch(r"(?:what times? (?:am i|are we) free|when(?:'s| is) my next (?:free (?:hour|slot|time|window)|opening)"
                     r"|find (?:me )?(?P<span>an hour|half an hour|\d{1,3} minutes|\d hours?|some time|a slot|time)"
                     r"|when can i (?:fit in|squeeze in|fit) (?:a |an )?[a-z' ]{2,30}?|do i have time for (?:a |an )?[a-z' ]{2,30}?)"
                     r"(?: (?:on |this )?(?P<when>today|tomorrow|tonight|(?:tomorrow |this )?(?:morning|afternoon|evening)"
                     r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?\s*\??", low)
    if m:
        day, part = _spoken_when(m.group("when") or "today")
        if day:
            command = {"kind": "free_time", "day": day}
            if part:
                command["part"] = part
            span = m.group("span") or ""
            minutes = (60 if span == "an hour" else 30 if span == "half an hour"
                       else int(span.split()[0]) * (60 if "hour" in span else 1) if span[:1].isdigit() else None)
            if minutes:
                command["minutes"] = minutes
            return {"command": command, "say": None}

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
        # A name said all in lower case is still a name (2026-10-07:
        # "dana's email is ..." saved "dana" beside "Dana" from her number).
        name = _as_he_said(transcript, m.group(1)).strip()
        return {"command": {"kind": "contact_add", "name": name.title() if name.islower() and name not in _RELATIONS else name,
                            "phone": m.group(2).strip()}, "say": None}
    m = re.fullmatch(r"(?:my )?([a-z][a-z' -]{0,30}?)'s (?:email|e-mail|email address) is "
                     r"(\S+@\S+\.\S+|\S+ at \S+ dot \S+)", low)
    if m and m.group(1) not in ("my", "your", "his", "her"):
        # A name said all in lower case is still a name (2026-10-07:
        # "dana's email is ..." saved "dana" beside "Dana" from her number).
        name = _as_he_said(transcript, m.group(1)).strip()
        return {"command": {"kind": "contact_add", "name": name.title() if name.islower() and name not in _RELATIONS else name,
                            "email": m.group(2).strip().rstrip(".")}, "say": None}
    # "Delete Sam from my contacts" (2026-10-07: to the planner).
    m = re.fullmatch(r"(?:delete|remove|take|drop|get rid of) ([a-z][a-z' -]{0,30}?) (?:from|out of|off) (?:my )?"
                     r"(?:contacts|contact list|phone book|address book)", low)
    if m and m.group(1) not in ("my", "all", "everyone", "everybody", "all my", "them", "him", "her"):
        return {"command": {"kind": "contact_remove", "name": _as_he_said(transcript, m.group(1)).strip()}, "say": None}
    # WHERE ONE OF HIS PLACES IS (2026-10-07: "my work address is 5 Market
    # St" went to the planner, while "how long to work" told him to give
    # her the address). Only an address that reads as one - a number and
    # a street - so "the meeting is at 3" is never a place.
    _address = r"(?P<addr>\d{1,6}[a-z]? [a-z0-9][a-z0-9 .,'#-]{2,60})"
    m = (re.fullmatch(r"(?:remember (?:that )?)?(?:my |our )(?P<pname>work|office|gym|school|[a-z]+'s (?:house|place|school|work|office)"
                      r"|parents'? (?:house|place))(?: address)? is (?:at )?" + _address, low)
         or re.fullmatch(r"(?:remember (?:that )?)?(?:the |my |our )?(?P<pname>[a-z][a-z' ]{1,25}?) is (?:at|on|located at) " + _address, low))
    if m and not re.search(r"\b(?:meeting|appointment|call|dinner|lunch|party|game|show|it|this|that)\b", m.group("pname")) \
            and re.search(r"\b(?:st|street|ave|avenue|rd|road|blvd|boulevard|dr|drive|ln|lane|way|ct|court|pl|place|pkwy|parkway"
                          r"|hwy|highway|cir|circle|ter|terrace|sq|square)\b", m.group("addr")):
        return {"command": {"kind": "place_add", "name": _as_he_said(transcript, m.group("pname")).strip(),
                            "address": _as_he_said(transcript, m.group("addr")).strip()}, "say": None}
    # "Add Sam to my contacts, his number is 555 222 3333" (2026-10-07: to
    # the planner) - the same contact, said the long way round.
    m = re.fullmatch(r"(?:add|save|put) ([a-z][a-z' -]{0,30}?) (?:to|in|into) (?:my )?(?:contacts|contact list|phone book|address book)"
                     r",? (?:with |and )?(?:(?:his|her|their|the) )?(?:(?P<kind>(?:phone |cell |mobile )?(?:number|phone)|email(?: address)?|e-mail)"
                     r"(?: is| as)? (?P<value>\+?[\d][\d ().-]{5,20}\d|\S+@\S+\.\S+|\S+ at \S+ dot \S+))", low)
    if m and m.group(1) not in ("my", "your", "his", "her", "me"):
        field = "email" if "mail" in m.group("kind") else "phone"
        if (field == "email") == ("@" in m.group("value") or " at " in m.group("value")):
            return {"command": {"kind": "contact_add", "name": _as_he_said(transcript, m.group(1)).strip(),
                                field: m.group("value").strip().rstrip(".")}, "say": None}
    # "MY BIRTHDAY IS MARCH 3RD 1995" (2026-10-07: to the planner). One
    # fact about him, kept in her memory, read by "how old am I".
    m = re.fullmatch(r"(?:my birthday is|my birthday's|i was born on|i was born|my date of birth is|my dob is) "
                     r"(?:on )?(?:the )?((?:[a-z]+\.? \d{1,2}(?:st|nd|rd|th)?|\d{1,2}(?:st|nd|rd|th)? (?:of )?[a-z]+)(?:,? \d{4})?"
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
         or re.fullmatch(r"add " + _who + r" to (?:my )?contacts(?: with| at| as)?(?: (?:the )?(?:phone )?(?:number|phone))? " + _num, low)
         # "Change Dana's number to ..." (2026-10-07): the same contact, updated.
         or re.fullmatch(r"(?:change|update|set|correct) " + _who + r"'s (?:phone )?(?:number|phone|cell|mobile)(?: number)? to " + _num, low))
    if m and m.group("name").split()[0] not in ("my", "your", "the", "a", "his", "her", "their", "our"):
        return {"command": {"kind": "contact_add", "name": _as_he_said(text, m.group("name")).title()
                            if m.group("name").islower() and text.islower() else _as_he_said(text, m.group("name")),
                            "phone": m.group("phone")}, "say": None}
    m = (re.fullmatch(r"(?:save|store|remember|put|add) " + _who + r"(?:'s)? email(?: address)?(?: as| is| to|:)? " + _mail, low)
         or re.fullmatch(_who + r"'s email(?: address)? is " + _mail, low)
         or re.fullmatch(r"add " + _who + r" to (?:my )?contacts(?: with| at| as)?(?: (?:the )?email(?: address)?)? " + _mail, low)
         or re.fullmatch(r"(?:change|update|set|correct) " + _who + r"'s email(?: address)? to " + _mail, low))
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
                 r"with ([a-z' -]+?)"
                 # "Schedule a call with Dana Friday" asked for a person called
                 # "dana friday" (2026-10-07): the day is the window.
                 r"(?: (?:on |this )?(?P<day>today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?"
                 r"(?: (?:next week|this week|about .+))?$", low)
    if m:
        command = {"kind": "meet", "person": m.group(1).strip()}
        day_iso = _spoken_day(m.group("day")) if m.group("day") else None
        if day_iso:
            command.update(from_day=day_iso, to_day=day_iso)
        return {"command": command, "say": None}

    # "Remind me a day before Mom's birthday" (2026-10-07: to the planner)
    # - the day is in his note, so the reminder is arithmetic.
    m = re.fullmatch(r"remind me (?:(?P<n>a|one|two|three|four|five|six|seven|\d{1,2}) (?P<unit>days?|weeks?) before"
                     r"|the (?P<eve>day|morning|night) before|on) "
                     r"(?:my )?(?P<who>[a-z][a-z ]{0,30}?)(?:'s|s') (?:birthday|bday)", low)
    if m:
        return _birthday_reminder(m)
    # "When is Dana's birthday", then "remind me a week before" (2026-10-07:
    # to the planner). The birthday he just asked about, or just told her.
    m = re.fullmatch(r"remind me (?:(?:a|one|two|three|four|five|six|seven|\d{1,2}) (?:days?|weeks?)|the (?:day|morning|night))"
                     r" before(?: it| that| then)?", low)
    if m:
        before = _previous_ask().casefold()
        whose = (re.search(r"\b(?:when(?:'s| is)|what day is) (?:my )?(?P<who>[a-z][a-z ]{0,30}?)(?:'s|s') (?:birthday|bday)",
                           before)
                 or re.match(r"(?:my )?(?P<who>[a-z][a-z ]{0,30}?)(?:'s|s') (?:birthday|bday) is ", before))
        if whose:
            return _interpret(f"{m.group(0).removesuffix(' it').removesuffix(' that').removesuffix(' then')} "
                              f"{whose.group('who')}'s birthday")
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
    # "Remind me tomorrow at 2 about the dentist" (2026-10-07: to the
    # planner) is "remind me tomorrow at 2 to" the same thing.
    m = re.fullmatch(r"remind me ((?:today|tonight|tomorrow|on |at |in |this |next |every |each )[a-z0-9: ]{1,40}?) about (.+)", low)
    if m:
        again = _interpret(f"remind me {m.group(1)} to {m.group(2)}")
        if str(((again or {}).get("command") or {}).get("kind", "")).startswith("remind_"):
            return again
    # "Remind me about the dentist" with nothing kept about the dentist
    # answered "I don't have anything remembered" (2026-10-07): he wanted a
    # reminder, and she asks when rather than look up nothing.
    m = re.fullmatch(r"remind me (?:later |sometime )?about (?P<what>[a-z][a-z0-9' ,-]{1,60})", low)
    # "Remind me about my landlord" is still a lookup: a person or thing of
    # his is what he wants told, and that rule is older than this one.
    if m and m.group("what").strip() not in ("me", "myself", "it", "that", "this", "you") \
            and not re.match(r"(?:my|our)\b", m.group("what")):
        try:
            from aletheia import quick
            known = quick._recall(m.group("what").strip())
        except Exception:  # noqa: BLE001
            known = None
        if not known or re.match(r"(?:I have nothing|I don't have|Nothing|You haven't)", known):
            what = _as_he_said(text, m.group("what").strip())
            return {"command": None,
                    "say": f"When should I remind you about {what}? Say a time, like \"at 3\" or \"tomorrow morning\"."}
    m = re.match(r"(?:what do you know about|what have you got on|"
                 r"remind me about|tell me about) (.+)", low)
    # "What do you know about me" is not a lookup under the key "me" (it
    # answered "I don't have anything remembered about 'me'"); the fast
    # lane says the whole of what she holds about him.
    if m and m.group(1).strip() not in ("me", "myself", "me then", "yourself", "you"):
        return {"command": {"kind": "recall", "about": _as_he_said(text, m.group(1).strip())},
                "say": None}

    # "Read me the DevRev email": the unread message that names them.
    m = (re.fullmatch(r"(?:read me|read|open|show me) (?:the |that |my )?(?P<which>[a-z0-9][a-z0-9 .&'-]{1,40}?) "
                      r"(?:email|e-mail|mail|message from them)", low)
         # "Read me the email FROM Stripe" (bottom rung 2026-09-24: to nobody).
         or re.fullmatch(r"(?:read me|read|open|show me) (?:the |that |my )?(?:email|e-mail|mail|message) from "
                         r"(?P<which>[a-z0-9][a-z0-9 .&'-]{1,40}?)", low)
         # "Any new emails from Stripe", "did Stripe email me" (2026-10-07: to the planner).
         or re.fullmatch(r"(?:any|are there any|do i have any|did i get any|is there an?) (?:new |unread )?(?:emails?|e-mails?|mail|messages?) "
                         r"from (?P<which>[a-z0-9][a-z0-9 .&'-]{1,40}?)", low)
         or re.fullmatch(r"(?:did|has) (?P<which>[a-z0-9][a-z0-9 .&'-]{1,40}?) (?:email|e-mail|write to|reply to|get back to) me(?: yet)?", low))
    # "Read my email" is not an email from somebody called "my" (2026-10-07):
    # a word that names no sender is the inbox, and `email_check` reads it.
    if m and m.group("which") in ("my", "me", "the", "your", "all", "all my", "all the", "any", "some", "an", "new",
                                  "anyone", "anybody", "someone", "somebody", "everyone", "nobody", "no one"):
        return {"command": {"kind": "email_check"}, "say": None}
    if m and m.group("which") not in ("latest", "last", "newest", "first", "new", "unread"):
        return {"command": {"kind": "email_read", "which": _as_he_said(transcript, m.group("which"))},
                "say": None}

    if re.fullmatch(r"(?:the |my )?(?:morning )?brief(?:ing)?|"
                    # The phrasings a person actually uses. "Give me the
                    # brief" and "brief me" both went to the planner.
                    r"(?:give me|read me|run) (?:the |my |a )?(?:morning |daily )?brief(?:ing)?|"
                    r"brief me|catch me up|what did i miss|give me (?:a |the )?(?:summary|rundown|run-down)"
                    r"|(?:sum (?:it|things) up|summari[sz]e (?:my day|today|things))(?: for me)?", low):
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
    # PRICES ON A MARKET (2026-10-07: "how's the stock market", "what's
    # bitcoin at", "how's apple stock" all went to the planner). A search
    # that cites where the number came from; nothing here buys or sells.
    m = (re.fullmatch(r"how(?:'s| is|s| are) (?:the )?(?P<mkt>stock market|market|markets|stocks|dow|dow jones|s ?& ?p(?: 500)?|nasdaq)"
                      r"(?: doing| looking)?(?: today| right now| now)?", low)
         or re.fullmatch(r"how(?:'s| is|s) (?P<co>[a-z][a-z.& ]{1,25}?) stock(?: doing)?(?: today| right now)?"
                         r"|what(?:'s| is|s) (?P<co2>[a-z][a-z.& ]{1,25}?) (?:stock|shares?) (?:at|trading at|worth|price)(?: today| right now)?"
                         r"|what(?:'s| is|s) the (?:stock |share )?price of (?P<co3>[a-z][a-z.& ]{1,25}?) (?:stock|shares)(?: today| right now)?", low)
         or re.fullmatch(r"what(?:'s| is|s) (?P<coin>bitcoin|btc|ethereum|eth|dogecoin|solana|gold|silver|oil) (?:at|worth|trading at|price)(?: today| right now)?"
                         r"|how much is (?:a |one )?(?P<coin2>bitcoin|ethereum|ounce of gold|barrel of oil)(?: worth)?(?: today| right now)?"
                         r"|what(?:'s| is|s) the price of (?:an ounce of |a barrel of )?(?P<coin3>bitcoin|ethereum|gold|silver|oil|gas)(?: today| right now)?", low))
    if m:
        g = m.groupdict()
        if g.get("mkt"):
            q = "stock market today"
        elif g.get("coin") or g.get("coin2") or g.get("coin3"):
            q = f"{g.get('coin') or g.get('coin2') or g.get('coin3')} price today"
        else:
            q = f"{(g.get('co') or g.get('co2') or g.get('co3')).strip()} stock price today"
        return {"command": {"kind": "research", "question": q}, "say": None}
    # "WHAT'S OPEN NOW" (2026-10-07: it read him the PC's windows). Shops
    # and places near him, asked the way a person asks it.
    m = re.fullmatch(r"what(?:'s| is|s)? (?:still )?open (?:right now|now|near me|nearby|around here|late|tonight)"
                     r"(?: near me| nearby| around here)?|(?:is )?anything (?:still )?open (?:right now|now|near me|nearby|around here|late)"
                     r"|what(?:'s| is|s)? open (?:for|to get) (?P<what>breakfast|lunch|dinner|food|coffee)(?: right now| now| near me| nearby)?", low)
    if m:
        what = m.group("what") or "places"
        return {"command": {"kind": "research", "question": f"{what} open now near me"}, "say": None}
    # SPORTS: "did the Cowboys win", "when do the Bulls play" (2026-10-07:
    # to the planner). A search; the team is whatever he named after "the".
    m = re.fullmatch(r"did the (?P<t>[a-z][a-z .'&-]{2,30}?) (?:win|lose)(?: last night| yesterday| today| tonight)?"
                     r"|how did the (?P<t2>[a-z][a-z .'&-]{2,30}?) do(?: last night| yesterday| today| tonight)?"
                     r"|what(?:'s| is|s| was) the (?P<t3>[a-z][a-z .'&-]{2,30}?) (?:score|game score)(?: last night| today)?"
                     r"|who won the (?P<t4>[a-z][a-z .'&-]{2,30}?) game(?: last night| yesterday| today)?"
                     r"|when do (?:the )?(?P<t5>[a-z][a-z .'&-]{2,30}?) play(?: next)?", low)
    if m and not re.search(r"\b(?:i|you|we|my|it|they|he|she|game)\b", next(g for g in m.groups() if g)):
        team = next(g for g in m.groups() if g).strip()
        q = f"when do the {team} play next" if m.group("t5") else f"{team} score last game"
        return {"command": {"kind": "research", "question": q}, "say": None}
    if re.fullmatch(r"(?:any |what are the |give me the |the )?(?:sports )?scores(?: today| tonight| last night)?"
                    r"|any sports (?:scores|news)(?: today)?", low):
        return {"command": {"kind": "research", "question": "sports scores today"}, "say": None}
    # A PLACE'S HOURS: "when does Target close", "is Costco open on Sunday"
    # (2026-10-07: to the planner). A search, the same as "what's open now".
    m = re.fullmatch(r"(?:when|what time) (?:does|do|is) (?:the )?(?P<p>[a-z0-9][a-z0-9 .'&-]{1,40}?) (?:close|open|closing|opening)"
                     r"(?P<when> today| tonight| tomorrow|(?: on)? [a-z]+days?| on the weekend|(?: this)? weekend)?"
                     r"|is (?:the )?(?P<p2>[a-z0-9][a-z0-9 .'&-]{1,40}?) (?:open|closed|still open)"
                     r"(?P<when2> today| tonight| right now| now| tomorrow|(?: on)? [a-z]+days?| on the weekend|(?: this)? weekend| late)?"
                     r"|what are (?:the )?(?P<p3>[a-z0-9][a-z0-9 .'&-]{1,40}?)(?:'s|s')? (?:hours|opening hours)(?: today)?", low)
    if m and not re.search(r"\b(?:it|that|this|my|your|door|window|app|file|tab|browser|calendar|spotify|chrome"
                           r"|garage|fridge|microphone|mic|ticket|application|position|job|pr|pull request)\b",
                           m.group("p") or m.group("p2") or m.group("p3") or ""):
        place = (m.group("p") or m.group("p2") or m.group("p3")).strip()
        when = (m.group("when") or m.group("when2") or "").strip()
        return {"command": {"kind": "research", "question": f"{place} hours {when}".strip()}, "say": None}
    # DIRECTIONS, TRAFFIC AND THE COMMUTE (2026-10-07: all to the planner).
    # "How do I get to work", "directions to the airport", "take me home"
    # and "what's the traffic to work" are the trip, asked another way; the
    # trip reader says how long it is today. With no place named, "the
    # commute" and "traffic" mean work - only when she knows where work is.
    _PLACE_WORDS = (r"\b(?:airport|station|mall|store|shop|market|hospital|clinic|downtown|uptown|office|school|"
                    r"college|campus|university|park|beach|home|work|gym|church|library|restaurant|cafe|hotel|"
                    r"stadium|arena|museum|zoo|center|centre|street|st|avenue|ave|road|rd|boulevard|blvd|drive|"
                    r"costco|walmart|target|airport)\b")
    m = (re.fullmatch(r"(?:(?:give me |get me |show me )?directions|navigate|route me|take me|drive me)"
                      r" (?:to )?(?:the )?(?P<place>home|work)(?: right now| now| please)?", low)
         or re.fullmatch(r"(?:(?:give me |get me |show me )?directions|navigate|route me|drive me) to (?:the )?"
                         r"(?P<place>[a-z0-9][a-z0-9 .'&-]{1,40}?)(?: right now| now| please)?", low)
         or re.fullmatch(r"(?:how do i get|how (?:can|should|would) i get|take me|what(?:'s| is|s) the "
                         r"(?:traffic|drive|route)(?: like)?(?: on the way)?)"
                         r" to (?:the )?(?P<place>[a-z0-9][a-z0-9 .'&-]{1,40}?)(?: right now| now| today| please)?", low))
    if m and (m.group(0).startswith(("directions", "give me", "get me", "show me", "navigate", "route", "drive"))
              or _known_place(m.group("place")) or re.search(_PLACE_WORDS, m.group("place"))):
        return {"command": {"kind": "travel_time", "place": m.group("place").strip()}, "say": None}
    if re.fullmatch(r"(?:what(?:'s| is|s)|how(?:'s| is|s)) (?:the )?(?:traffic|my commute|the commute)(?: like)?(?: right now| now| today| this morning)?"
                    r"|how bad is (?:the )?traffic(?: right now| now| today)?|when should i leave(?: for work)?"
                    r"|(?:is there|any) (?:bad )?traffic(?: on the way to work)?(?: right now| now| today)?", low) \
            and _known_place("work"):
        return {"command": {"kind": "travel_time", "place": "work"}, "say": None}
    # "How far is Chicago" (2026-10-07: to the planner). A place, not a
    # thing in the sky: "how far is the moon" is a question for a model.
    m = re.fullmatch(r"how far (?:away )?is (?:it to )?(.+?)(?: from here| from me| from home)?", low)
    if m and not re.search(r"\b(?:moon|sun|mars|venus|jupiter|space|star|stars|galaxy|horizon|that|it|this)\b", m.group(1)) \
            and not re.search(r"\b(?:\d+ ?k|\d+ ?km|marathon|in (?:miles|km|kilometers|kilometres|feet|meters))\b", m.group(1)):
        # "How far is a 5k in miles" is a distance, not a journey (2026-10-07).
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
    if m and re.match(r"buy (?:some |more )?\S", m.group(1)):
        # "Add buy milk to my list" put "buy milk" on the shopping list.
        m = re.match(r"(?:add|put|get|stick|throw) buy (?:some |more )?(.+?) (?:on|to) (?:the |my )?"
                     r"(?:shopping |grocery )?list$", low)
    if m and not re.search(r"(?:shopping|grocery) list$", low) and _TASK_VERB.match(m.group(1)):
        # "Add call the dentist to my list" went on the SHOPPING list
        # (2026-09-24). A thing to do is a task; a thing to buy is a purchase.
        return _new_task(_as_he_said(text, m.group(1).strip()))
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
                    r"what subscriptions do i have"
                    # "How much am I paying for Netflix", "what bills are due" (2026-10-07:
                    # to the planner) - the tracker answers both.
                    r"|how much (?:is my|am i paying for|do i pay for) (?:my )?(?:netflix|spotify|hulu|disney plus|disney\+"
                    r"|youtube premium|youtube tv|amazon prime|prime|hbo max|max|apple music|icloud|peacock|paramount plus"
                    r"|chatgpt|claude|xbox game pass|game pass|playstation plus|audible|my gym|the gym)(?: a month| per month| monthly)?"
                    r"|what (?:bills|payments|subscriptions) (?:are|is) (?:due|coming up|renewing)(?: soon| this month| this week)?"
                    r"|(?:what|which) bills do i have|my bills|what do i pay (?:each|every|a) month"
                    r"|how much (?:do i|am i) (?:spend(?:ing)?|pay(?:ing)?) on subscriptions(?: a month| per month| each month)?)", low):
        return {"command": {"kind": "subscriptions"}, "say": None}

    # "What's my BANK balance" and "what do I have IN THE BANK" reached no
    # pattern, so `converse` answered them with no finance context and
    # invented one - "I have read-only access to your balances and
    # transactions", about a store with nothing in it. A question she can
    # answer from a store must never be left to a model without it.
    if re.fullmatch(r"(?:how much money do i have|what'?s my balance|"
                    r"(?:what'?s |what is )?my net worth|how am i doing financially"
                    r"|(?:check|show me|read me|tell me) my (?:bank )?(?:balance|balances|accounts)"
                    r"|what'?s my bank balance|what'?s in (?:my|the) bank"
                    r"|what do i have in (?:my|the) bank"
                    r"|how much (?:do i have|money is there)"
                    r"(?: in (?:my|the) bank| in the bank)?"
                    r"|what are my (?:accounts|balances)"
                    r"|my (?:accounts|balances)"
                    # "What's my credit card balance" (2026-10-07: to the planner).
                    r"|what(?:'s| is|s) (?:my|the) (?:credit card|checking|savings|card|account) balance"
                    r"|how much (?:is|do i have) (?:in|on) (?:my )?(?:checking|savings|credit card)(?: account)?"
                    r"|how much do i owe(?: on my (?:credit )?card)?)", low):
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
        # "Cancel both" was a subscription called "both" (2026-10-07).
        r"|both|all|them|those|these|everything|the rest"
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

    m = re.fullmatch(r"(?:cancel|delete|remove) (?:my |the )?(?P<w>(?:meeting|appointment|call|lunch|dinner|coffee|hold) with [a-z' ]{2,30}?)"
                     r"(?: (?:today|tomorrow|on [a-z]+))?", low)
    if m:
        hold, why = _one_of_her_holds(m.group("w"))
        if hold:
            return {"command": {"kind": "hold_release", "title": hold["title"], "start": hold["start"]}, "say": None}
        if why:
            return {"command": None, "say": "More than one hold of mine matches that - say which by its time."}
        return {"command": None,
                "say": "I can't cancel things on your calendar yet - I can only add holds to it. "
                       "If that's a reminder of mine, tell me what it's for and I'll turn it off."}
    if re.fullmatch(r"cancel (?:my |the )?(?:\d{1,2}(?::\d\d)?\s*(?:am|pm|o'?clock)?|noon)"
                    r"(?: (?:today|tomorrow|meeting|appointment|call))?", low) \
            or re.fullmatch(r"cancel (?:my |the )?[a-z' ]{2,30}? (?:appointment|meeting|lunch|dinner|call)"
                            r"(?: (?:today|tomorrow|on [a-z]+|this [a-z]+))?", low) \
            or re.fullmatch(r"(?:clear|empty|wipe|cancel everything on) (?:my |the )?(?:calendar|schedule|day)"
                            r"(?: for)?(?: (?:today|tomorrow|this week|monday|tuesday|wednesday|thursday|friday"
                            r"|saturday|sunday))?|cancel (?:all )?(?:my )?(?:meetings|appointments)(?: (?:today|tomorrow))?", low):
        named = re.sub(r"^cancel (?:my |the )?", "", low)
        hold, why = _one_of_her_holds(named) if low.startswith("cancel") else (None, "")
        if hold:
            # "Cancel my meeting with Sam" after she pencilled it in (2026-10-07):
            # her own hold is hers to take off.
            return {"command": {"kind": "hold_release", "title": hold["title"], "start": hold["start"]}, "say": None}
        if why:
            return {"command": None, "say": "More than one hold of mine matches that - say which by its time."}
        return {"command": None,
                "say": "I can't cancel things on your calendar yet - I can only add holds to it. "
                       "If that's a reminder of mine, tell me what it's for and I'll turn it off."}
    # "MOVE MY DENTIST APPOINTMENT TO FRIDAY" (2026-10-07: to the planner,
    # which has no door to his calendar's events). Said plainly, unless the
    # words pick out one of his tasks, which can be moved.
    m = re.fullmatch(r"(?:move|reschedule|push|shift|bump) (?:my |the )?(?P<what>.*?(?:appointment|meeting|call|lunch|dinner"
                     r"|breakfast|interview|\d{1,2}(?::\d\d)?\s*(?:am|pm|o'?clock))(?: with [a-z' ]+?)?)(?: back)? (?:to|till|until|for) .+", low)
    if m and not _names_one_open_task(m.group("what")):
        hold, why = _one_of_her_holds(m.group("what"))
        to = re.search(r" (?:to|till|until|for) (?P<when>.+)$", low)
        if hold and to and _spoken_time(to.group("when").replace("at ", "")):
            # "Move my 2pm to 3" after she pencilled it in (2026-10-07): her own
            # hold, same day, the new time, the same length.
            import datetime as dt
            from aletheia import calendar as _cal, localtime
            tz = localtime.operator_tz()
            was = _cal.parse_time(hold["start"]).astimezone(tz)
            ends = _cal.parse_time(hold["end"]).astimezone(tz) if hold.get("end") else was + dt.timedelta(hours=1)
            words = to.group("when").replace("at ", "")
            hour, minute = map(int, _spoken_time(words).split(":"))
            if _is_bare_hour(words) and was.hour >= 12 and hour < 12:
                hour += 12
            new = was.replace(hour=hour, minute=minute)
            return {"command": {"kind": "calendar_hold", "title": hold["title"], "start": new.isoformat(),
                                "minutes": max(5, int((ends - was).total_seconds() // 60)),
                                "replaces": hold["start"]}, "say": None}
        if why:
            return {"command": None, "say": "More than one hold of mine matches that - say which by its time."}
        return {"command": None,
                "say": "I can't move things on your calendar yet - I can only add holds to it. "
                       "Move it in your calendar, and if you want a hold at the new time, tell me when."}
    # "CANCEL THE BANK ONE" after reading his reminders was prepared as a
    # cancellation of a SUBSCRIPTION called "bank one" (2026-10-07). A
    # reminder or a task of his that the words name is the thing; only
    # what names neither is left to be a service.
    one = re.fullmatch(r"(?:cancel|stop|turn off|delete|remove) (?:my |the )?(?P<w>[a-z0-9][a-z0-9' -]{1,40}?)(?: one| reminder| alarm| timer)", low)
    # "Cancel the first one" counts whatever she just read out - usually
    # approvals - and has its own branch.
    if one and re.search(r"\b(?:first|second|third|fourth|last|latest|newest|oldest|next|other|that|this|it|pending)\b",
                         one.group("w")):
        one = None
    if one:
        found = None
        # "The 3 minute one" is the 3-minute timer: try his words, then hyphenated.
        for words in dict.fromkeys((one.group("w"), re.sub(r"(\d+) (minute|hour|second)", r"\1-\2", one.group("w")))):
            try:
                from aletheia import intercom
                found, _why = intercom._one_reminder(words)
            except Exception:  # noqa: BLE001
                found = None
            if found is not None:
                return {"command": {"kind": "reminder_off", "which": words}, "say": None}
        if _names_one_open_task(one.group("w")):
            return {"command": {"kind": "task_change", "which": one.group("w"), "drop": True}, "say": None}
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
                    r"check (?:my |the )?inbox|(?:any|do i have any) unread e?mails?|"
                    # "What emails do I have", "what's new in my email" (2026-10-07: to a model)
                    r"what (?:e?mails?|mail) (?:do i have|have i got|came in|did i get)(?: today| this morning)?|"
                    r"what(?:'s| is|s)? new in (?:my |the )?(?:e?mail|inbox)|"
                    # "Did I get any emails" (2026-10-07: to the planner).
                    r"(?:did i get|have i got|have i gotten|did i receive|have i received) (?:any )?(?:new )?(?:e?mails?|mail)"
                    r"(?: today| this morning| yet)?)", low):
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
                     # "Shut up", "be quiet", "stop talking" (2026-10-07: to the planner).
                     r"|(?:quiet|hush|shush|sh+|mute your notifications|be quiet|shut up|stop talking|quiet down|zip it)"
                     r"(?: for (?P<n3>\d+) (?P<unit3>minutes?|mins?|hours?|hrs?))?"
                     r"|(?:snooze|pause) (?:your |the |all )?(?:notifications|notices|alerts)(?: for (?P<n4>\d+) (?P<unit4>minutes?|mins?|hours?|hrs?))?"
                     # "I'm in a meeting", "I'm driving" (2026-10-07: to the planner):
                     # the same hour of quiet, said as the reason for it.
                     r"|(?:i'?m|i am) (?:in a meeting|on a call|on the phone|driving|in an interview|at the doctor'?s?|busy right now|in class)",
                     low)
    # "Don't bother me for an hour" (2026-10-07: to the planner) - the
    # span in words, the way the snooze reads it.
    span = re.fullmatch(r"(?:(?:don'?t|do not) (?:disturb|bother|interrupt) me|(?:turn on|enable|put me on) "
                        r"(?:do not disturb|dnd|quiet mode|focus mode)|(?:be )?quiet|hush) for (?P<span>.+)", low)
    if span and not m and _spoken_minutes(span.group("span")):
        return {"command": {"kind": "notify_snooze",
                            "minutes": max(1, min(_spoken_minutes(span.group("span")), 60 * 24 * 7))}, "say": None}
    if m:
        n = next((m.group(k) for k in ("n", "n2", "n3", "n4") if m.group(k)), "")
        unit = next((m.group(k) for k in ("unit", "unit2", "unit3", "unit4") if m.group(k)), "")
        minutes = int(n) * (60 if unit.startswith(("h",)) else 1) if n else 60
        return {"command": {"kind": "notify_snooze", "minutes": max(1, min(minutes, 60 * 24 * 7))},
                "say": None}

    # A LOST OBJECT is not a file. "Find my keys" planned for a minute and
    # came back "she does not know a folder called on my computer" (2026-09-23).
    # WHERE HE PUT IT (2026-10-07): "I put my keys in the drawer" went to the
    # planner, and "where are my keys" said she had no eyes - with the note
    # that would have answered it never written. A note in his words, read
    # back by the question.
    m = re.fullmatch(r"(?:i (?:put|left|stuck|keep|hid|placed)|i've (?:put|left)|i have (?:put|left)) (?:my |the |our )"
                     r"(?P<thing>[a-z][a-z' ]{1,25}?) (?:in|on|at|under|by|behind|next to|inside|near|in the|on top of) .+"
                     r"|(?:my|the|our) (?P<thing2>[a-z][a-z' ]{1,25}?) (?:are|is) (?:in|on|under|behind|next to|inside|on top of) "
                     r"(?:the|my|our|a) .+", low)
    # An appointment "is on the 15th" is a date, not a shelf (2026-10-07).
    if m and not re.search(r"\b(?:car|calendar|list|schedule|computer|pc|account|name|password|birthday"
                           r"|appointment|appt|meeting|interview|call|lunch|dinner|class|flight|haircut|checkup|exam)\b",
                           m.group("thing") or m.group("thing2") or ""):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    m = re.fullmatch(r"(?:find|where(?:'s| are| is| did i (?:put|leave))|locate|look for) (?:my |the )?"
                     r"(?P<thing>[a-z][a-z' ]{1,25}?)(?: please)?", low)
    if m:
        put = _where_he_put(m.group("thing"))
        if put:
            return {"command": None, "say": put}
        from aletheia import quick
        there = quick._place_where(m.group("thing"))
        if there:
            return {"command": None, "say": there}
    m = re.fullmatch(r"(?:find|where(?:'s| are| is| did i (?:put|leave))|locate|look for) (?:my |the )?"
                     r"(?P<thing>keys|phone|wallet|glasses|remote|car|bag|purse|shoes|charger|headphones|earbuds|passport|watch)"
                     r"(?: please)?", low)
    if m:
        thing = m.group("thing")
        if thing == "car":
            # Where he parked is a note she keeps (2026-10-07: "where's my
            # car" was refused for want of eyes while the note sat there).
            from aletheia import quick
            return {"command": None, "say": quick._parked()}
        return {"command": None,
                "say": (f"I can't see where your {thing} are - I have no eyes in the room. "
                        if thing in ("keys", "glasses", "shoes", "headphones", "earbuds")
                        else f"I can't see where your {thing} is - I have no eyes in the room. ")
                       + "I can find files and places, and I can ring your phone if it's linked."}

    # A PHONE CALL is a door she does not have. "Call the dentist" waited
    # two minutes on her own model (2026-09-22) for a verb nothing here
    # owns; the honest answer names the three doors she does have.
    m = re.fullmatch(r"(?:call|phone|ring|ring up|dial|give (?:a )?call to|facetime|video call|video chat with) "
                     r"(?:my |the )?(?P<who>[a-z][a-z .'-]{1,40}?)"
                     r"(?: for me| now| please| back)?", low)
    if m and _is_a_person_to_ring(m.group("who")):
        who = _as_he_said(transcript, m.group("who"))
        # "Call my dentist" offered to "text or email dentist".
        if re.match(r"(?:call|phone|ring|dial|give|facetime|video) .*\bmy " + re.escape(m.group("who")), low):
            who = f"your {who}"
        elif re.match(r"(?:call|phone|ring|dial|give|facetime|video) .*\bthe " + re.escape(m.group("who")), low):
            who = f"the {who}"
        number = ""
        try:
            from aletheia import contacts as _contacts, speech as _speech
            one = _contacts.resolve(m.group("who"))
            phones = [str(v) for v in (one.get("phones") or []) if v]
            if phones:
                name = str(one["display_name"])
                number = f" {name[:1].upper()}{name[1:]}'s number is {_speech._spoken_number(phones[0])}."
        except Exception:  # noqa: BLE001 - no contact is the plain answer
            pass
        if not who.startswith(("your ", "the ")):
            who = who[:1].upper() + who[1:]
        # The sentences, not "which would you like?": a bare "text" after
        # it had nothing to catch it (2026-10-07).
        his = re.sub(r"^your ", "my ", who)   # the sentence HE says
        return {"command": None,
                "say": f"I can't place phone calls from here.{number} I can text or email {who}, or remind you "
                       f"to call - say \"text {his} that I'll call later\" or \"remind me at 5 to call {his}\"."}

    # A VOLUME LEVEL is not a key. "Set the volume to 50" planned for a
    # minute on her own model and was refused with a list of action ids
    # (2026-09-23); up, down and mute are the keys she has.
    # Now it is: fifty presses down and level/2 up (2026-10-07).
    m = re.fullmatch(r"(?:(?:set|put|turn|change) (?:the )?(?:volume|sound) (?:to|at|up to|down to)|volume(?: to)?)"
                     r" (?P<level>\d{1,3}|half|halfway|max|maximum|full|low|high|quiet)(?: ?%| percent)?", low)
    if m:
        said = m.group("level")
        level = {"half": 50, "halfway": 50, "max": 100, "maximum": 100, "full": 100, "low": 20, "quiet": 20,
                 "high": 80}.get(said)
        level = level if level is not None else min(int(said), 100)
        return {"command": {"kind": "music", "action": "volume_set", "level": level}, "say": None}

    # NAMING SOMETHING TO PLAY is the half that needs his account, and
    # she says so instead of resuming whatever was paused on Thursday and
    # calling it what he asked for.
    # The signal is not the word "some", it is what follows it: "play
    # some MUSIC" is transport and "put on some JAZZ" is a choice.
    # "PUT ON SOME MUSIC" is "play music"; "play something relaxing" is a
    # mood, searched as that kind of music (2026-10-07: both to the planner).
    if re.fullmatch(r"(?:put on|throw on|start) (?:some |the )?(?:music|tunes)(?: please| for me)?", low):
        return {"command": {"kind": "music", "action": "play"}, "say": None}
    mood = re.fullmatch(r"(?:play|put on) (?:me )?something (?P<mood>relaxing|chill|calm|upbeat|happy|fun|mellow|soothing"
                        r"|energetic|quiet|peaceful|sad|romantic|to (?:sleep|study|work|focus|work out) to)(?: please| for me)?", low)
    if mood:
        words = re.sub(r"^to (\w+(?: \w+)?) to$", r"\1", mood.group("mood"))
        return {"command": {"kind": "open_page", "which": f"youtube search {words} music"}, "say": None}
    if re.fullmatch(r"(?:play|put on) (?:me )?(?:the )?(?:news|headlines)(?: for me)?", low):
        from aletheia import quick
        return {"command": None, "say": quick._news() or "I couldn't read the news just now."}
    if re.match(r"(?:play|put on)\s+"
                r"(?!(?:some |the |my )?(?:music|tunes|spotify|something)\b"
                r"|it\b|devils?\b|devil's\b)"
                r"[a-z0-9]", low):
        # "Play Taylor Swift" (2026-10-07): she cannot choose a song in his
        # player, but she can open YouTube's results for it in his browser -
        # his tap, and the receipt says what opened, never "it's playing".
        m = re.fullmatch(r"(?:play|put on) (?:some )?(?P<q>[a-z0-9][a-z0-9 '&.-]{1,60}?)(?: on youtube| for me| please)?", low)
        # "Play my playlist" is HIS list in his player, not a search for
        # the words "my playlist" (2026-10-07). That stays the honest half.
        if m and not re.search(r"\b(?:on spotify|on apple music|on pandora|game|games)\b", low) \
                and not m.group("q").startswith("my "):
            return {"command": {"kind": "open_page", "which": "youtube search " + _as_he_said(text, m.group("q").strip())},
                    "say": None}
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
                 r"\b(?:\s+(?:of|about|for|on|covering|called|named|titled)\s+(?P<topic>.+))?$",
                 low)
    # "...called notes with the text hello there" carries its contents and
    # is made below; only an empty one is asked about.
    if m and re.search(r"\b(?:with (?:the )?(?:text|words|line)|saying|that says|containing)\b", low):
        m = None
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

    # A FILE IN HER WORKSPACE, BY ITS NAME (2026-10-07: "delete the file
    # test.txt" and "rename notes.txt to ideas.txt" went to the planner).
    # Both verbs keep the previous version.
    _fname = r"(?P<path>[\w][\w .-]{0,60}?\.[a-z0-9]{1,5})"
    m = re.fullmatch(r"(?:delete|remove|trash|get rid of) (?:the |my )?(?:file )?" + _fname, low)
    if m:
        return {"command": {"kind": "file_delete", "path": _as_he_said(text, m.group("path"))}, "say": None}
    m = re.fullmatch(r"(?:rename|move) (?:the |my )?(?:file )?" + _fname + r" (?:to|into|as) "
                     r"(?:the |my )?(?P<to>[\w][\w ./-]{0,60}?)(?: folder)?", low)
    # A rename only: "to documents" could be his own Documents folder, which
    # is not her workspace, so a folder target is left for the planner.
    if m and "." in m.group("to").rsplit("/", 1)[-1]:
        return {"command": {"kind": "file_move", "path": _as_he_said(text, m.group("path")),
                            "to": _as_he_said(text, m.group("to"))}, "say": None}

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
    # "SEND MOM A MESSAGE SAYING HAPPY BIRTHDAY" - the name before the
    # noun (2026-10-07: to the planner).
    m = m or re.match(r"(?:send|shoot|drop) (?!an? )(.+?) an? (?:text|message|quick text|quick message)"
                      r"\s+(?:that says|saying|that|telling (?:him|her|them)|:)\s+(.+)", low)
    if m:
        # The message is sent in HIS capitals, not the lowercased sentence
        # the matching reads ("i'm on my way", 2026-10-07).
        return {"command": {"kind": "message_send", "to": m.group(1).strip(),
                            "body": _as_he_said(text, m.group(2).strip())}, "say": None}
    # "TEXT MOM HAPPY BIRTHDAY" - no "that" between them, so the name ran
    # into the message: "I don't have a phone number for mom happy"
    # (2026-10-07). The longest leading words that name a contact he has,
    # or a one-word relation, are the person; the rest is the message.
    m = re.fullmatch(r"(?:send (?:a )?(?:text|message) to|text|message) (?P<rest>.+)", low)
    split = _known_person_first(m.group("rest")) if m else None
    if split:
        return {"command": {"kind": "message_send", "to": split[0],
                            "body": _as_he_said(text, split[1])}, "say": None}
    # "TEXT DANA I'M RUNNING LATE" with no Dana on file (2026-10-07: to the
    # planner). One word, then a word only a sentence starts with, is a
    # name and a message - "text bob happy birthday" is still not guessed
    # at. With no number for Dana the send says so, by name.
    m = re.fullmatch(r"(?:send (?:a )?(?:text|message) to|text|message) (?P<who>(?:my |our )?[a-z][a-z']{1,20}) "
                     r"(?P<body>(?:i'm|im|i|i'll|i've|we're|we|we'll|can you|could you|are you|did you|do you|don't|dont"
                     r"|where|what|when|call me|hey|hi|thanks|thank you|on my way|running late|see you|love you)\b.*)", low)
    if m and m.group("who") not in ("a", "the", "my", "him", "her", "them", "it", "that", "this", "me", "back", "again"):
        return {"command": {"kind": "message_send", "to": m.group("who"),
                            "body": _as_he_said(text, m.group("body"))}, "say": None}
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

    # "EMAIL DANA", "SEND AN EMAIL TO MOM" (2026-10-07: to the planner) name
    # who and not what - asked for whole, the way a bare "text sam" is.
    m = re.fullmatch(r"(?:send (?:an? )?e?mail to|e?mail|write (?:an? )?e?mail to|draft (?:an? )?e?mail to)"
                     r" (?P<who>[a-z][a-z']{1,20}(?: [a-z][a-z']{1,20})?)", low)
    if m and m.group("who").split()[0] not in ("a", "the", "my", "me", "it", "that", "this", "him", "her", "them",
                                                "back", "everyone", "everybody", "all", "now", "address", "addresses",
                                                "check", "inbox", "list", "account", "password"):
        who = _as_he_said(text, m.group("who"))
        who = who.title() if who.islower() else who
        return {"command": None,
                "say": f"What should it say? Say \"email {who} saying you'll be late\" and I'll draft it for you to check."}

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
                            "body": _as_he_said(text, m.group(2).strip())}, "say": None}
    # "Send DANA an email saying I'm running late" - the name before the
    # noun, which is how he says it (2026-09-24, offline: to the planner).
    m = re.match(r"(?:send|draft|write)\s+(.+?)\s+(?:an? |the )?e?mail\s+(?:that says|that|saying|and say|"
                 r"telling (?:him|her|them)|:)\s+(.+)", low)
    if m and not re.search(r"\b(?:remind|reminder)\b", low):
        return {"command": {"kind": "email_draft", "to": m.group(1).strip(),
                            "body": _as_he_said(text, m.group(2).strip())}, "say": None}

    # "EMAIL MOM HAPPY BIRTHDAY" (2026-10-07: to the planner): the same
    # split "text mom happy birthday" makes - a person he has, then the
    # words. "About" is the conversation below, not a message.
    m = re.fullmatch(r"(?:send (?:an? )?e?mail to|e?mail) (?P<rest>.+)", low)
    split = _known_person_first(m.group("rest")) if m and not re.search(
        r"\b(?:about|regarding|remind|reminder)\b", low) else None
    if split:
        return {"command": {"kind": "email_draft", "to": split[0],
                            "body": _as_he_said(text, split[1])}, "say": None}

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

    # NEWS ABOUT A THING (2026-10-07: "sports news", "any news about the
    # election", "what's the latest on apple" to the planner). Her feeds are
    # the headlines; a topic is the same read-only web research.
    m = re.fullmatch(r"(?:any |the latest |latest |what'?s the latest )?news (?:about|on|from) (?P<t>.{2,60})"
                     r"|what'?s the latest (?:on|with) (?P<t2>.{2,60})"
                     r"|(?:the latest )?(?P<t3>sports|tech|technology|business|world|local|science|political|politics|"
                     r"entertainment|finance|financial|stock market|ai) news(?: today)?", low)
    if m:
        if m.group("t3"):
            return {"command": {"kind": "research", "question": f"latest {m.group('t3')} news"}, "say": None}
        topic = re.sub(r"^(?:the|a|an) ", "", (m.group("t") or m.group("t2")).strip(" ?."))
        return {"command": {"kind": "research", "question": f"latest news about {topic}"}, "say": None}

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
        # "Look up the weather in Paris", "google what time it is in Tokyo"
        # (2026-10-07): a question she answers herself is not research.
        if len(question) > 2 and re.match(r"(?:the )?(?:weather|forecast|time|temperature|definition|meaning|"
                                          r"what time|what(?:'s| is) the weather|how many days|what day)\b", question):
            try:
                from aletheia import quick
                own = quick.answer(re.sub(r"^the (definition|meaning) of ", r"define ", question))
            except Exception:
                own = None
            if own:
                return {"command": None, "say": own}
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

    # "Send it", after she drafts something and says it waits for his word
    # (2026-10-07: to the planner). It is "approve it" in his words, with
    # every gate that one has - a send voice may not approve still says so.
    if re.fullmatch(r"(?:yes,? |ok,? |okay,? |go ahead,? (?:and )?)?send (?:it|that|the (?:draft|email|e-mail|text|message))"
                    r"(?: now| please| off)?", low):
        low, sending = "approve it", True
    else:
        sending = False
    m = re.match(r"(?:approve|approved|yes to)\s*"
                 r"(?:that|it|the pending one|the (?P<ord>first|second|third|last)"
                 r"(?: one)?|(?P<what>.+?))?$", low)
    if m:
        pending = [a for a in policy.all_approvals() if a["state"] == "PENDING"]
        if not pending:
            return {"command": None, "say": "There's nothing waiting to send." if sending
                    else "Nothing is waiting for approval."}
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
        r"(?:never ?mind(?: that| it)?|forget (?:it|that)|call it off|"
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
            # "What reminders do I have" - "1 reminder: call the vet" - then
            # "cancel it" said "Nothing is waiting for approval" (2026-10-07).
            # The one reminder she just read out is the "it".
            _said, answered = _previous_turn()
            one = re.match(r"1 (?:reminder|alarm|timer): (.+?) (?:—|-) ", answered)
            if asked_to_cancel and re.fullmatch(r"(?:cancel|scrap|drop)\s+(?:that|it)", low) and one:
                return {"command": {"kind": "reminder_off", "which": one.group(1)}, "say": None}
            # The reminder he set a turn or two ago, with a question between.
            if asked_to_cancel and re.fullmatch(r"(?:cancel|scrap|drop)\s+(?:that|it)", low):
                recent_reminder = _recent_reminder_ask()
                if recent_reminder.get("text"):
                    return {"command": {"kind": "reminder_off", "which": recent_reminder["text"]}, "say": None}
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
                    r"that(?:'s| is| was) (?:wrong|useless|terrible|not what i (?:asked|meant|wanted|said))|"
                    r"(?:no,? )?(?:that's |that is )?not what i (?:asked|meant|wanted|said)|you misunderstood(?: me)?|"
                    r"you got (?:it|that) wrong)(?: thea)?", low):
        return {"command": None, "say": "Sorry. Tell me what I got wrong and I'll fix it."}

    m = re.match(r"(?:add a task|new task|task)\s*(?:to|:)?\s+(.+)", low)
    if m:
        return _new_task(_as_he_said(text, m.group(1).strip()))
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
    # "Push it to 6" (2026-10-07: to the planner) is the same move.
    m = re.fullmatch(r"(?:make (?:that|it)|(?:change|move|push|bump|shift|switch|reschedule) (?:that|it) to|actually,? make (?:that|it)|"
                     r"no,? make (?:that|it))\s+(?:at )?(?P<time>[\w: ]+?)(?: instead| please)?", low)
    if m:
        moved = _moved_reminder(text, m.group("time")) or _moved_hold(m.group("time"))
        if moved:
            return moved
    # "Push it back an hour", "move it 30 minutes earlier" (2026-10-07: to
    # the planner): the reminder he just set, shifted from where it IS.
    m = re.fullmatch(r"(?:push|move|bump|shift|put) (?:it|that|the reminder) (?P<dir>back|later|forward|earlier|up|off)"
                     r"(?: by)? (?P<n>an?|one|half an?|\d{1,3}|two|three|four|five|ten|fifteen|twenty|thirty|forty-five) ?(?P<unit>hours?|minutes?|mins?)"
                     r"|(?:push|move|bump|shift|put) (?:it|that|the reminder)(?: by)? (?P<n2>an?|one|half an?|\d{1,3}|two|three|four|five|ten|fifteen|twenty|thirty|forty-five) ?"
                     r"(?P<unit2>hours?|minutes?|mins?) (?P<dir2>later|earlier|back|forward|sooner)", low)
    if m:
        shifted = _shifted_reminder(m.group("n") or m.group("n2"), m.group("unit") or m.group("unit2"),
                                    m.group("dir") or m.group("dir2"))
        if shifted:
            return shifted
    # "Sorry, I meant 4pm" (2026-10-07: to the planner) - a correction
    # that is nothing but the new time. Only when he led with one, so a
    # bare "4" is never a move.
    if re.match(r"(?:\W*)(?:sorry|i meant|i mean|no|nope|oops|actually|wait|oh)\b", text.lower().strip()) and \
            re.fullmatch(r"(?:at )?(?P<time>\d{1,2}(?::\d{2})? ?(?:am|pm|a\.m\.|p\.m\.)?|noon|midnight|\d{1,3} minutes?)", low):
        tw = re.sub(r"^at ", "", low)
        moved = _moved_reminder(text, tw) or _moved_hold(tw)
        if moved:
            return moved
    # "Add eggs", then "no, I meant milk" (2026-10-07: to the planner) -
    # the thing just put on the list, swapped. Only right after an add,
    # and only for a bare thing.
    if re.match(r"(?:\W*)(?:sorry|i meant|no|nope|oops|actually|wait)\b", text.lower().strip()) \
            and re.fullmatch(r"(?:some |a |an |the )?[a-z][a-z' -]{1,30}", low) and len(low.split()) <= 4 \
            and not re.search(r"\b(?:it|that|this|them|cancel|stop|never ?mind|yes|no|okay|ok)\b", low):
        _said, answered = _previous_turn()
        just = re.match(r"Added to the shopping list: ([^,]+?)\.$", answered)
        if just and " and " not in just.group(1):
            item = re.sub(r"^(?:some|a|an|the) ", "", low)
            return {"command": {"kind": "shopping_add", "item": _as_he_said(text, item),
                                "replaces": just.group(1)}, "say": None}

    # "REMIND ME WHEN I GET HOME" (2026-10-07: to the planner). She has no
    # idea where he is, so a place cannot set anything off; say so, and
    # offer the clock, which she does have.
    m = re.fullmatch(r"remind me (?:when|once|as soon as) i (?:get|arrive|am|'m|leave|get back) "
                     r"(?:home|to (?:work|the office|the store|school)|at (?:home|work|the store)|back|work)"
                     r"(?:,? to (?P<what>.+))?", low) \
        or re.fullmatch(r"remind me to (?P<what>.+?) when i (?:get|arrive|am|'m|leave|get back) "
                        r"(?:home|to (?:work|the office|the store|school)|at (?:home|work|the store)|back)", low)
    if m:
        what = (m.group("what") or "").strip() or "do it"
        return {"command": None,
                "say": "I can't tell where you are, so I can't remind you when you get somewhere. "
                       f"I can do it at a time - say \"remind me at 6 to {what}\"."}

    # "CHANGE MY 3PM REMINDER TO 4PM", "move my pill reminder to 9"
    # (2026-10-07: to the planner). The one-off reminder he names - by its
    # time or its words - on the same day, at the new time.
    m = re.fullmatch(r"(?:change|move|switch|reschedule|push) (?:my |the )?(?P<which>.+?) reminder to (?:at )?"
                     r"(?P<time>[\w: ]+?)(?: instead| please)?", low)
    if m:
        moved = _reminder_moved_to(m.group("which"), m.group("time"))
        if moved:
            return moved

    # "Add bread to the shopping list" - "remove that" (2026-10-07: to the
    # planner). Straight after an ask she can take back, "that" is it.
    if re.fullmatch(r"(?:actually |oh |wait |no,? )?(?:remove|delete|scratch|drop|get rid of|take) (?:that|it)"
                    r"(?: off| out| back off| back out)?(?: (?:of |from )?(?:the |my )?list)?(?: please)?", low) \
            and _last_ask_is_undoable():
        return {"command": {"kind": "undo"}, "say": None}
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
    # A date counts as a day: "a doctor's appointment on the 15th at 10"
    # (2026-10-07) went to the planner, and _spoken_day already reads it.
    _cal_days = (r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|(?:the )?day after tomorrow|tomorrow|today|tonight"
                 r"|the \d{1,2}(?:st|nd|rd|th)|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
                 r" \d{1,2}(?:st|nd|rd|th)?)")
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
    # "I have a dentist appointment Tuesday at 2" (2026-10-07: to the
    # planner) is the same hold, told rather than asked for.
    # "LUNCH WITH SAM TOMORROW AT NOON" (2026-10-07: to the planner) is the
    # same hold with the verb left off; the noun list keeps it a diary entry.
    told = re.fullmatch(r"(?P<lead>(?:add|schedule|put|pencil in|set up|i have|i've got|i got|i have got) )?(?:a |an |my )?"
                        r"(?P<title>[a-z' ]*?(?:appointment|meeting|lunch|dinner|breakfast|call|interview|party"
                        r"|date|class|practice|haircut|checkup|check-up)(?: with [a-z' ]+?)?)"
                        r"(?: on| this| for| next)? (?P<day>" + _cal_days + r")(?: (?P<part>morning|afternoon|evening|night))?"
                        r"(?: at (?P<time>[\w: ]+?))?", low)
    # ...but "call tomorrow" alone is not a diary entry called Call.
    if told and not told.group("lead") and " " not in told.group("title").strip() \
            and not (told.group("time") or told.group("part")):
        told = None
    # ...and "book a dentist appointment friday" is somebody else's diary.
    if told and not told.group("lead") and re.match(
            r"(?:book|make|get|cancel|move|reschedule|find|plan|organi[sz]e|arrange|set|call|text|email|confirm"
            r"|skip|miss|need|want|remind|add|schedule|put|is|was|when|what|did|do)\b", low):
        told = None
    m = m or told
    # "Book a meeting with Dana tomorrow at 11" (2026-10-07) became a web
    # errand to approve. A meeting or call with a person, on a day, is his
    # own diary; "book" stays somebody else's for anything else.
    m = m or re.fullmatch(r"book (?:a |an )?(?P<title>(?:meeting|call|catch-up|catch up) with [a-z' ]+?)"
                          r"(?: on| this| for)? (?P<day>" + _cal_days + r")(?: (?P<part>morning|afternoon|evening|night))?"
                          r"(?: at (?P<time>[\w: ]+?))?", low)
    # "BLOCK OFF FRIDAY AFTERNOON" (2026-10-07: to the planner): a hold
    # called Busy for that part of that day, the same reversible hold.
    if not m:
        b = re.fullmatch(r"(?:block|block off|block out|keep|hold) (?:my )?(?P<day>" + _cal_days + r")"
                         r"(?: (?P<part>morning|afternoon|evening|night))?(?: free| clear| open)?"
                         # "Block out tomorrow morning for deep work" (2026-10-07: to the planner).
                         r"(?: (?:for|to do|to) (?P<what>[a-z][a-z' ]{1,30}))?", low)
        if b:
            what = re.sub(r"^(?:the|my|some) ", "", (b.group("what") or "").strip())
            held = _calendar_hold(text, (what[:1].upper() + what[1:]) if what else "Busy", b.group("day"),
                                  b.group("part"), None)
            if held:
                # A whole day blocked is the working day, nine to five.
                held["command"]["minutes"] = 480 if not b.group("part") else (180 if b.group("part") != "night" else 120)
                return held
        # "BLOCK 2 HOURS TOMORROW MORNING FOR FOCUS" (2026-10-07: to the
        # planner): the same hold, for as long as he says, called what it is for.
        b = re.fullmatch(r"(?:block|block off|block out|hold|reserve|set aside|carve out) (?:out )?"
                         r"(?P<n>an?|one|two|three|four|\d{1,3}|half an) (?P<unit>hours?|minutes?)"
                         r"(?: (?:on |this )?(?P<day>" + _cal_days + r"))?(?: (?P<part>morning|afternoon|evening|night))?"
                         r"(?: at (?P<time>[\w: ]+?))?(?: (?:for|to) (?P<what>[a-z][a-z' ]{1,30}))?", low)
        # "BLOCK OFF 2 TO 4 TOMORROW FOR DEEP WORK" (2026-10-07: to the
        # planner): a hold between two times he names.
        r = (re.fullmatch(r"(?:block|block off|block out|hold|reserve|set aside|keep)(?: my)? (?:from )?(?P<t1>[\d:]+(?: ?[ap]\.?m\.?)?)"
                          r" (?:to|till|until|-) (?P<t2>[\d:]+(?: ?[ap]\.?m\.?)?)(?: (?:on |this )?(?P<day>" + _cal_days + r"))?"
                          r"(?: (?:for|to) (?P<what>[a-z][a-z' ]{1,30}))?", low)
             or re.fullmatch(r"(?:block|block off|block out|hold|reserve|set aside|keep)(?: my)? (?:on |this )?(?P<day>" + _cal_days
                             + r") (?:from )?(?P<t1>[\d:]+(?: ?[ap]\.?m\.?)?) (?:to|till|until|-) (?P<t2>[\d:]+(?: ?[ap]\.?m\.?)?)"
                             r"(?: (?:for|to) (?P<what>[a-z][a-z' ]{1,30}))?", low))
        if r:
            title = re.sub(r"^(?:the|my|some) ", "", (r.group("what") or "busy").strip())
            held = _calendar_hold(text, title[:1].upper() + title[1:], r.group("day") or "today", None, r.group("t1"))
            end = _spoken_time(r.group("t2"))
            if held and end:
                import datetime as dt
                start = dt.datetime.fromisoformat(held["command"]["start"])
                eh, em = map(int, end.split(":"))
                stop = start.replace(hour=eh, minute=em)
                if _is_bare_hour(r.group("t2")):
                    while stop <= start and stop.hour < 12:
                        stop = stop.replace(hour=stop.hour + 12)
                minutes = int((stop - start).total_seconds() // 60)
                if 15 <= minutes <= 12 * 60:
                    held["command"]["minutes"] = minutes
                    return held
        if b and (b.group("day") or b.group("part") or b.group("time")):
            amount = _spoken_amount(b.group("n")) if b.group("n") != "a" and b.group("n") != "an" else 1
            minutes = int(round((amount or 1) * (60 if b.group("unit").startswith("hour") else 1)))
            title = re.sub(r"^(?:the|my|some) ", "", (b.group("what") or "busy").strip())
            held = _calendar_hold(text, title[:1].upper() + title[1:], b.group("day") or "today", b.group("part"),
                                  b.group("time"))
            if held and 15 <= minutes <= 12 * 60:
                held["command"]["minutes"] = minutes
                return held
    if not m:
        # "MY DENTIST APPOINTMENT IS FRIDAY AT 2" (2026-10-07: to the
        # planner) - the same thing as "I have a dentist appointment friday
        # at 2", said the other way round.
        mine = re.fullmatch(r"(?:my|the|our) (?P<what>[a-z][a-z' ]{1,40}?) (?:is|'s) (?P<when>.{3,40})", low)
        if (mine and re.search(r"\b(?:appointment|appt|meeting|interview|call|lunch|dinner|class|game|flight|haircut"
                               r"|checkup|check-up|surgery|exam|recital|practice)\b", mine.group("what"))
                and re.search(r"\d|" + _cal_days, mine.group("when"))):
            again = _interpret(f"i have a {mine.group('what')} {mine.group('when')}")
            if ((again or {}).get("command") or {}).get("kind") == "calendar_hold":
                return again
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

    # HIS MEDICINE, TAKEN (2026-10-07: "I took my medicine" and "did I take
    # my medicine" both went to the planner). A note with the time on it is
    # the record; `quick` reads today's back.
    m = re.fullmatch(r"(?:i )?(?:just |already )?(?:took|had|taken|have taken|'ve taken) (?:my )?(?:morning |evening |night |daily )?"
                     r"(?P<what>medicine|meds|medication|pills?|vitamins?|insulin|inhaler|antibiotics?|[a-z]+ pills?)"
                     r"(?: today| this morning| tonight| just now| already)?", low)
    if m:
        return {"command": {"kind": "note", "text": f"took my {m.group('what')}"}, "say": None}
    # MONEY BETWEEN PEOPLE (2026-10-07: "I owe Sam 20 dollars", "Sam paid me
    # back" each to the planner). Said as a fact, it is a note in his words;
    # "who do I owe" adds the notes up. Nothing here moves any money.
    _amt = r"\$?\d+(?:\.\d{1,2})?(?: ?(?:dollars|bucks))?"
    if re.fullmatch(r"(?:i owe [a-z][a-z ]{0,25}? " + _amt + r"|[a-z][a-z ]{0,25}? owes me " + _amt
                    + r"|i (?:lent|loaned) [a-z][a-z ]{0,25}? " + _amt + r"|i borrowed " + _amt + r" from [a-z][a-z ]{0,25}?"
                    + r"|i paid [a-z][a-z ]{0,25}? back(?: " + _amt + r")?|[a-z][a-z ]{0,25}? paid me back(?: " + _amt + r")?)"
                    + r"(?: for [a-z][a-z ]{0,30})?", low) and not low.startswith(("you ", "she ", "thea ")):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # HIS DAY, LOGGED (2026-10-07: "I drank a glass of water", "I ran 3
    # miles", "I slept 7 hours" went to the planner). A note in his words
    # with the time on it; `quick._logged` adds today's or this week's up.
    m = re.fullmatch(r"(?:i )?(?:just )?(?P<log>(?:drank|had) (?:a|an|one|two|three|four|five|\d{1,2}) (?:glass(?:es)?|cups?|bottles?|mugs?|cans?)"
                     r" of [a-z][a-z ]{1,20}?"
                     r"|(?:ran|walked|jogged|biked|cycled|swam|hiked) (?:for )?(?:\d{1,3}(?:\.\d+)?|a|an|one|two|three|four|five|six|ten|half a|half an) ?"
                     r"(?:miles?|km|kilometers?|kilometres?|k|minutes?|mins?|hours?|laps?)"
                     r"|slept (?:for )?(?:\d{1,2}(?:\.\d+)?|five|six|seven|eight|nine|ten) (?:and a half )?hours?"
                     r"|(?:worked out|exercised|meditated|stretched|did yoga|went to the gym)(?: for (?:\d{1,3}|an?|one|two|half an?) (?:minutes?|mins?|hours?))?)"
                     r"(?: today| this morning| last night| tonight| just now)?", low)
    if m:
        return {"command": {"kind": "note", "text": "I " + m.group("log")}, "say": None}
    # "I went for a 20 minute run" (2026-10-07: to the planner) is "I ran
    # for 20 minutes", kept in the words `quick._logged` adds up.
    m = re.fullmatch(r"(?:i )?(?:just )?(?:went for|did|had) (?:a|an) (?P<n>\d{1,3}|half hour|half an hour)[- ]?(?P<u>minutes?|mins?|hours?|miles?|mile|k|km)?"
                     r"[- ]?(?P<act>run|walk|jog|bike ride|ride|swim|hike|workout)(?: today| this morning| tonight| just now)?", low)
    if m and (m.group("u") or m.group("n").startswith("half")):
        past = {"run": "ran", "walk": "walked", "jog": "jogged", "bike ride": "biked", "ride": "biked",
                "swim": "swam", "hike": "hiked", "workout": "worked out"}[m.group("act")]
        n, unit = m.group("n"), (m.group("u") or "")
        if n.startswith("half"):
            n, unit = "30", "minutes"
        unit = {"min": "minutes", "mins": "minutes", "minute": "minutes", "hour": "hours", "mile": "miles"}.get(unit, unit)
        if n == "1":
            unit = unit.rstrip("s")
        lead = "" if unit in ("miles", "mile", "k", "km") else "for "
        return {"command": {"kind": "note", "text": f"I {past} {lead}{n} {unit}"}, "say": None}
    # "THE GATE CODE IS 4471" (2026-10-07: to the planner). A code or
    # number of his, told as a fact about "the" thing, is a note in his
    # words; a password still is not (`_no_password_in_a_note`).
    if re.fullmatch(r"(?:the|our) [a-z][a-z' ]{1,25}? (?:code|combo|combination|number|extension|locker|room number"
                    r"|gate code|door code|access code) is [a-z0-9#*][a-z0-9#* -]{0,24}", low) \
            and re.search(r"\d", low) and not re.search(r"\b(?:pass(?:word|code|phrase)|pin|ssn|social security)\b", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # WHERE HE PARKED. "I parked on level 3" went to the planner and
    # "where did I park" to a model (2026-10-07). It is a note, in his
    # words, and `quick` reads the newest one back.
    m = re.fullmatch(r"(?:i(?:'ve| have)? parked|i'm parked|my car is(?: parked)?|the car is(?: parked)?)"
                     r" (?:on|at|in|by|near|outside|behind|across from|next to) .+", low)
    if m:
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # WHO SOMEBODY IS TO HIM (2026-10-07): "Dana is my sister" went to the
    # planner; "who is Dana" reads the note back.
    m = re.fullmatch(r"(?P<who>[a-z][a-z'-]{1,20}(?: [a-z][a-z'-]{1,20})?) is my (?:new |old |best |younger |older |little |big )?"
                     r"(?P<rel>[a-z][a-z ]{1,25})", low)
    if m and (m.group("rel") in _RELATIONS or re.fullmatch(
            r"(?:friend|coworker|co-worker|colleague|neighbou?r|landlord|landlady|manager|doctor|dentist|lawyer|"
            r"accountant|cousin|aunt|uncle|niece|nephew|fiancee?|grandmother|grandfather|stepmom|stepdad|"
            r"mother-in-law|father-in-law|sister-in-law|brother-in-law|ex|kid|child|pet|dog|cat|recruiter|"
            r"mechanic|barber|therapist|trainer|coach|teacher|tutor|realtor|agent|plumber|electrician)", m.group("rel"))) \
            and m.group("who").split()[0] not in ("this", "that", "it", "he", "she", "they", "who", "what", "there", "here",
                                          # "When is my dentist" was filed as a note about
                                          # somebody called When (2026-10-07).
                                          "when", "where", "why", "how", "which", "whose", "whats", "wheres", "whens"):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # AN ALLERGY, SAID AS ONE (2026-10-07): "I'm allergic to peanuts" went
    # to the planner, while "what am I allergic to" reads notes. A note in
    # his words is the writer that reader was missing.
    if re.fullmatch(r"(?:i'm|i am|im) (?:very |really |severely |slightly |a (?:bit|little) )?allergic to [a-z][a-z ,'-]{1,60}"
                    r"|i have (?:an? |a severe |a mild )?(?:[a-z]+ )?allerg(?:y|ies) to [a-z][a-z ,'-]{1,60}"
                    r"|my allerg(?:y is|ies are) [a-z][a-z ,'-]{1,60}", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # A FACT ABOUT HIM, SAID AS ONE. "My favorite color is blue", "my wifi
    # password is ...", "Jess's birthday is March 3" went to the planner
    # (2026-10-07). Kept as a note in his words, which is what `quick`
    # reads back. Only keys that name a fact - a favourite, a size, a code,
    # a number, someone's name or birthday - so "my head is killing me"
    # and "my computer is slow" are never filed as facts. His own name,
    # address, email, phone and birthday have their own patterns.
    # "Remember Dana's birthday is March 3" kept "remember" inside the note
    # and inside the name (2026-10-07). The verb is not the fact.
    fact_low = re.sub(r"^(?:remember|note|don'?t forget|keep in mind)(?: that)? ", "", low)
    m = re.fullmatch(r"(?:my |our )?(?P<key>(?:favou?rite|fave) [a-z ]{2,25}|[a-z][a-z' ]{0,30}?(?:'s|s') (?:name|birthday|anniversary)"
                     r"|blood type|shoe size|shirt size|ring size|pants size|dress size|wifi(?: password| name)?|wi-fi(?: password)?"
                     r"|gate code|door code|garage code|locker (?:number|combination|code)|license plate|plate number"
                     # "My doctor is Dr Patel" (2026-10-07: to the planner) -
                     # who someone IS to him, read back by "who's my doctor".
                     r"|(?:doctor|dentist|vet|pediatrician|therapist|lawyer|accountant|landlord|boss|manager|mechanic"
                     r"|barber|hairdresser|hair stylist|trainer|pharmacist|optometrist|eye doctor|gp|realtor|babysitter|nanny)"
                     r"|anniversary|account number|member(?:ship)? number|policy number) (?:is|are) (?P<value>.{1,80})", fact_low)
    if m:
        if re.fullmatch(r"(?:doctor|dentist|vet|pediatrician|therapist|lawyer|accountant|landlord|boss|manager|mechanic"
                        r"|barber|hairdresser|hair stylist|trainer|pharmacist|optometrist|eye doctor|gp|realtor|babysitter|nanny)",
                        m.group("key")) and re.match(
                r"(?:a|an|the|so|really|very|such|being|always|never|kind|super|too|out|sick|away|on|in|at|mad|angry|"
                r"great|awesome|terrible|awful|nice|mean|annoying|late|busy|off|not)\b", m.group("value")):
            # "My boss is a jerk" is how he feels, not who his boss is.
            m = None
    if m and not re.search(r"\b(?:what|who|when|where|why|how|not|wrong)\b", m.group("key") + " " + m.group("value")[:12]) \
            and not fact_low.startswith(("what", "who", "when", "where", "how", "why")):
        if re.search(r"pass(?:word|code|phrase)", m.group("key")) and not re.match(sensitivity_where(), m.group("value")):
            # `sensitivity` blanks a password out of every record she
            # keeps, so a note would read back "[redacted]". Said, not faked.
            return {"command": None, "say": _NO_PASSWORDS}
        return {"command": {"kind": "note", "text": _as_he_said(text, fact_low)}, "say": None}
    # "MY CAR IS A 2015 HONDA CIVIC" (2026-10-07: to the planner) - what he
    # drives or carries, kept only when it names a make or a year, so "my
    # car is a mess" and "my phone is dying" stay how he feels.
    m = re.fullmatch(r"(?:my |our )(?P<key>car|truck|vehicle|van|suv|motorcycle|bike|phone|laptop|computer|tablet|watch)"
                     r" is (?:an? )?(?P<value>.{2,60})", fact_low)
    if m and re.search(r"\b(?:19|20)\d\d\b|\b(?:toyota|honda|ford|chevy|chevrolet|nissan|subaru|tesla|bmw|audi|kia|hyundai"
                       r"|jeep|dodge|ram|gmc|mazda|volkswagen|vw|lexus|volvo|mercedes|acura|buick|cadillac|infiniti|mitsubishi"
                       r"|harley|yamaha|trek|iphone|pixel|galaxy|samsung|apple|macbook|dell|lenovo|thinkpad|surface|ipad"
                       r"|garmin|fitbit)\b", m.group("value")):
        return {"command": {"kind": "note", "text": _as_he_said(text, fact_low)}, "say": None}
    # "Delete my last note" (2026-10-07: to the planner). The newest note,
    # by its own words, through the same `forget` the rest of her memory
    # uses - the journal keeps it and a tombstone hides it.
    if re.fullmatch(r"(?:delete|remove|forget|scratch|erase|undo) (?:my |the |that )?(?:last|latest|most recent|newest) note", low):
        from aletheia import quick
        newest = next(iter(quick._notes(limit=1)), None)
        if not newest:
            return {"command": None, "say": "You don't have any notes."}
        return {"command": {"kind": "forget", "about": str(newest.get("text") or "").strip()}, "say": None}
    # "Delete the note about wifi" (2026-10-07: to the planner). The newest
    # note with those words in it; more than one is asked about, not guessed.
    m = (re.fullmatch(r"(?:delete|remove|forget|scratch|erase) (?:the |my |that )?notes? (?:about|on|with|that says|saying) (?P<w>.+)", low)
         # "Delete the plumber note" (2026-10-07: to the planner) - the
         # same thing, said with the words in front.
         or re.fullmatch(r"(?:delete|remove|forget|scratch|erase) (?:the |my |that )(?P<w>(?!last\b|latest\b|newest\b|first\b|old\b)"
                         r"[a-z0-9][a-z0-9' ]{1,30}?) note", low))
    if m:
        from aletheia import quick
        words = [w for w in re.findall(r"[a-z0-9']+", m.group("w")) if w not in ("the", "my", "a", "an")]
        hits = [str(r.get("text") or "").strip() for r in quick._notes()
                if words and all(w in str(r.get("text") or "").casefold() for w in words)]
        if not hits:
            return {"command": None, "say": f"I don't have a note about {m.group('w')}."}
        if len(hits) > 1:
            return {"command": None, "say": f"{speech.count_phrase(len(hits), 'note')} mention {m.group('w')}: "
                                            + speech.or_list([speech.as_she_says_it(h) for h in hits[:3]])
                                            + ". Which one?"}
        return {"command": {"kind": "forget", "about": hits[0]}, "say": None}

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
                     r"(?:set|change|update|make) my (?:zip|zip code|zipcode|postcode|postal code) (?:to|is)|"
                     r"i live in|i'm in|i am in) (\d{5}(?:-\d{4})?)", low)
    if m:
        return {"command": {"kind": "remember", "domain": "identity", "key": "postal_code",
                            "value": m.group(1)}, "say": None}
    # "SET MY TIME ZONE TO PACIFIC", "I'm on eastern time" (2026-10-07: to
    # the planner). The zone his clock is read in is one line in her memory
    # of him (localtime reads it first); the US names map to their zones.
    m = re.fullmatch(r"(?:(?:set|change|update|switch|make) my (?:time ?zone|clock) (?:to|is) |my time ?zone is |"
                     r"i'?m (?:on|in) (?:the )?|i am (?:on|in) (?:the )?|i live (?:on|in) (?:the )?|we'?re (?:on|in) (?:the )?)"
                     r"(?P<zone>eastern|central|mountain|pacific|alaska|hawaii|arizona)(?: (?:standard |daylight )?time(?: zone)?| time ?zone)?", low)
    if m:
        zone = {"eastern": "America/New_York", "central": "America/Chicago", "mountain": "America/Denver",
                "pacific": "America/Los_Angeles", "alaska": "America/Anchorage", "hawaii": "Pacific/Honolulu",
                "arizona": "America/Phoenix"}[m.group("zone")]
        return {"command": {"kind": "remember", "domain": "identity", "key": "timezone", "value": zone}, "say": None}
    # "I LIVE IN AUSTIN", "I moved to Denver", "set my city to Austin"
    # (2026-10-07: to the planner, and the weather kept asking for a
    # postcode). The town as he said it; the forecast names the place it
    # finds, so a wrong one is heard.
    m = re.fullmatch(r"(?:i live in|i moved to|i just moved to|we live in|we moved to|"
                     r"(?:set|change|update|make) my (?:city|town|location|home(?: town| city)?) (?:to|is)|"
                     r"my (?:city|town|home town|hometown) is) (?P<city>[a-z][a-z .'-]{1,40}?)(?:,? (?P<st>[a-z]{2}))?", low)
    if m and not re.match(r"(?:a|an|the|my|our|this|that|here|there|an apartment|a house|town|the city|the country)\b",
                          m.group("city")):
        city = " ".join(w.capitalize() for w in m.group("city").split())
        st = (m.group("st") or "").upper()
        return {"command": {"kind": "remember", "domain": "identity", "key": "home_city",
                            "value": f"{city}, {st}" if st else city}, "say": None}
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
    # "DELETE EVERYTHING YOU KNOW ABOUT ME" (2026-10-07: to the planner).
    # The same rule, for what she remembers about him.
    if re.fullmatch(r"(?:delete|forget|erase|wipe|clear|remove) (?:everything|all|anything) (?:you know|you remember|you have|you've got"
                    r"|you've learned|you have stored|you've saved) (?:about|on) me|(?:wipe|clear|erase) your memory"
                    r"|forget (?:everything|all of it|me)", low):
        return {"command": None,
                "say": "I won't forget everything about you on one sentence. Say \"what do you know about me\", "
                       "then \"forget\" and the thing, one at a time."}
    # "DELETE ALL MY TASKS", "MARK EVERYTHING DONE" (2026-10-07: to the
    # planner). The same rule: his whole list is not one sentence's to undo.
    if re.fullmatch(r"(?:delete|remove|clear|wipe|cancel|drop) (?:all|every one of|everything on) (?:of )?(?:my |the )?"
                    r"(?:tasks|to[- ]?dos?|task list|to[- ]?do list)|(?:clear|wipe|empty) (?:my |the )?(?:task list|to[- ]?do list|tasks)"
                    r"|mark (?:everything|all(?: of)?(?: my)?(?: tasks)?|every task) (?:as )?(?:done|complete|completed|finished)", low):
        return {"command": None,
                "say": "I won't change your whole task list on one sentence. Say \"what's on my list\" and then "
                       "\"mark the first one done\" or \"delete\" and what it says, one at a time."}
    # "Note to self buy stamps" kept "to self buy stamps" (2026-10-07).
    m = re.match(r"(?:(?:make a |take a |a )?note to (?:my)?self(?: that)?|make a note(?: that| of|:)?|take a note(?: that|:)?|jot down(?: that)?|"
                 # "Write a note that the car needs oil" (2026-10-07: to the planner).
                 r"(?:write|leave|add) (?:me )?a note(?: that| saying| of|:)?|"
                 # "Note: buy a card for Dana" missed this (a colon, not a
                 # space), reached the planner and was refused as SPENDING
                 # (2026-10-07). Writing a line down commits nothing.
                 r"note that|note|write down that|write down|log)(?:\s*[:,]\s*|\s+)(.+)", low)
    if m and m.group(1).strip() in ("it", "that", "this"):
        return {"command": None, "say": 'What should the note say? Say "note that the plumber comes Tuesday".'}
    if m:
        # In his capitals: "dana called" was what a note kept of "Dana called".
        return {"command": {"kind": "note", "text": _as_he_said(text, m.group(1).strip())}, "say": None}
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
        return {"command": {"kind": "note", "text": _as_he_said(text, m.group(1).strip())}, "say": None}

    # "REMIND ME TO EMAIL SAM" with no when (2026-10-07: to the planner,
    # which with nothing thinking kept it "for later"). Every reminder
    # branch above needs a time; asked for, not guessed.
    m = re.fullmatch(r"remind me (?:later |sometime )?(?:to|about) (?P<what>[a-z][a-z0-9' ,-]{1,80}?)(?: later| sometime| at some point)?", low)
    if m and not re.search(r"\b(?:today|tomorrow|tonight|morning|afternoon|evening|noon|midnight|at|in|on|every|each|"
                           r"next|when|if|after|before|once|until|by|monday|tuesday|wednesday|thursday|friday|"
                           r"saturday|sunday|weekend|week|month|daily|weekly|hourly)\b", m.group("what")):
        what = _as_he_said(text, m.group("what").strip())
        return {"command": None, "say": f"When should I remind you to {what}? Say a time, like \"at 3\" or \"tomorrow morning\"."}

    # A THING HE DID, OR A DATE ON SOMETHING OF HIS (2026-10-07: "I changed
    # the oil today", "I gave the dog his medicine", "my license expires
    # June 2027" each went to the planner). Last before the planner, so
    # every verb with its own door keeps it: said as a fact, it is a note in
    # his words, and "when did I last change the oil" reads it back.
    if re.fullmatch(r"i (?:just )?(?:" + _DONE_VERBS + r") (?:the |my |our |his |her |a |an |some )?[a-z][a-z' ]{1,50}"
                    r"(?: (?:today|yesterday|this morning|this afternoon|this evening|tonight|last night|earlier))?", low) \
            or re.fullmatch(r"(?:my|our|the) [a-z][a-z' ]{1,30}? (?:expires?|runs out|is due|renews|ends) (?:on |in )?"
                            r"(?:" + SPOKEN_DATE + r"|" + _MONTH + r"(?: \d{4})?|\d{4})(?:,? \d{4})?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}

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


def _answers_which(low: str) -> dict | None:
    """"Cancel my alarm" -> "Which one - 6:30 or 7:15?" -> "the 7:15 one":
    his sentence is the choice she asked for, so it is the same command
    naming that one. It went to the planner, which had not heard the
    question. None unless her last answer asked "Which one" and his last
    full sentence compiles to a command that names its thing."""
    said = low.strip().rstrip(".!")
    if not said or said.endswith("?") or len(said.split()) > 6:
        return None
    try:
        from aletheia import converse
        last = (converse.recent(limit=1) or [{}])[-1]
    except Exception:
        return None
    if not re.search(r"\bWhich one\b", str(last.get("she_answered") or "")):
        return None
    prev = _previous_ask()
    if not prev or prev.casefold().rstrip(".!?") == said:
        return None
    try:
        cmd = (interpret(f"thea {prev}") or {}).get("command") or {}
    except Exception:
        return None
    if "which" not in cmd:
        return None
    from aletheia import speech
    where = speech.ordinal_index(said)
    if where is not None:
        # "The first one" counts in the list she just read out, not in
        # whatever order the store keeps them.
        asked = re.sub(r"^.*?\bWhich one\b\s*[—-]?\s*", "", str(last.get("she_answered") or ""))
        options = [o.strip() for o in re.split(r",\s*(?:or\s+)?|\s+or\s+", asked.rstrip("?. "))
                   if o.strip()]
        if not 0 <= where < len(options):
            return {"command": {**cmd, "which": said}, "say": None}
        said = options[where].casefold()
    answer = re.sub(r"^(?:(?:no|oh|um|i mean|it's|its|it is|that's|the)[ ,]+)+", "", said)
    answer = re.sub(r"\s+(?:one|alarm|reminder)$", "", answer).strip()
    if not answer:
        return None
    if cmd.get("kind") in ("reminder_off", "reminder_on") and re.search(r"\d", answer):
        # The words already matched both; the time is what tells them apart.
        answer = f"{cmd['which']} {answer}".strip()
    return {"command": {**cmd, "which": answer}, "say": None}


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
