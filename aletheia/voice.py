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
from aletheia import rx as re
import threading

from aletheia import capabilities, policy, speech, tasks

WAKE_WORDS = ("thea", "theia", "tia", "althea", "aletheia")


def strip_wake_word(text: str) -> str:
    t = text.strip()
    # "Hey Thea, can you remind me at 5..." (2026-10-08: to the planner) -
    # the greeting before her name hid her name, so nothing after it matched.
    t = re.sub(r"^(?:hey|hi|ok|okay|yo|oh|hello)[\s,.!]+(?=(?:%s)\b)" % "|".join(WAKE_WORDS), "", t, flags=re.IGNORECASE)
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
    # "Never mind, cancel it" (2026-10-08: to the planner) - only before
    # the words that undo, so "never mind" alone is still its own answer.
    r"|never ?mind[,\s]+(?=(?:cancel|delete|remove|drop|scrap|forget|undo|don'?t|take)\b)"
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
    # "Next Wednesday" said ON a Wednesday has one meaning: a week today
    # (2026-10-08: held for today). Only other weekdays are ambiguous.
    if t.startswith("next ") and t[5:] in WEEKDAYS and WEEKDAYS.index(t[5:]) == today.weekday():
        return (today + dt.timedelta(days=7)).isoformat()
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
    # "Call mom for next Wednesday" (2026-10-08) held "call mom for next"
    # due today. "For" a day is as much a deadline as "by" one.
    m = re.search(r"^(.*?)[,\s]+(?:by|before|due(?: on)?|for)\s+(.+)$", text)
    if m and not _spoken_day(m.group(2).strip().split(" at ")[0]):
        m = None if re.search(r"[,\s]for\s", text) and not re.search(r"[,\s](?:by|before|due)\s", text) else m
    if not m:
        # "Call the plumber tomorrow", "pay the gas bill on friday": a day
        # said last is as much a deadline as "by friday" (2026-10-07).
        # "Call mom this weekend", "pay rent on the 1st" (2026-10-07: the
        # day stayed in the description and no deadline was kept).
        bare = re.search(r"^(\S+\s.*?)\s+(?:on |this )?((?:the )?day after tomorrow|next (?:monday|tuesday|wednesday"
                         r"|thursday|friday|saturday|sunday)|today|tonight|tomorrow|monday|tuesday|wednesday"
                         r"|thursday|friday|saturday|sunday|(?:over )?(?:this |the )?weekend"
                         r"|the \d{1,2}(?:st|nd|rd|th)|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{1,2}(?:st|nd|rd|th)?"
                         r"|in (?:a|an|one|two|three|four|five|six|seven|eight|nine|ten|\d{1,3}) (?:days?|weeks?)"
                         # "Renew my license next month" (2026-10-07: "next
                         # month" stayed in the task and nothing was due).
                         r"|next week|next month|(?:by )?(?:the )?end of (?:the |this )?(?:week|month))"
                         # "Call the bank tomorrow morning" (2026-10-08: the
                         # morning kept the day out of the deadline).
                         r"(?: (?:morning|afternoon|evening|night|first thing))?$",
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
    # "Renew my passport before March" (2026-10-08: kept with no date, so
    # nothing ever came due). Before a month is the last day of the one
    # before it, the next time that month comes round.
    month = re.fullmatch(r"(january|february|march|april|may|june|july|august|september|october|november|december)", when.lower())
    if month:
        import datetime as dt
        from aletheia import localtime
        today = localtime.today()
        number = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
                  "november", "december"].index(month.group(1)) + 1
        first = dt.date(today.year + (1 if number <= today.month else 0), number, 1)
        return rest, (first - dt.timedelta(days=1)).isoformat()
    at = re.search(r"^(.*?)\s+at\s+(.+)$", when)
    day = _spoken_day(at.group(1) if at else when)
    if not day:
        return text, ""
    if at:
        hhmm = _spoken_time(at.group(2))
        if hhmm:
            # "Call mom by Friday at 3" was due at three in the MORNING
            # (2026-10-08). Nobody means a bare 1 to 7 before dawn.
            hour, minute = map(int, hhmm.split(":"))
            if _is_bare_hour(at.group(2)) and 1 <= hour <= 7:
                hhmm = f"{hour + 12:02d}:{minute:02d}"
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
    ahead = (WEEKDAYS.index(words[1]) - today.weekday()) % 7
    if not ahead:
        return None                 # the same weekday: a week today, nothing to ask
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
    # "Where is my remote" (2026-10-08: searched his Documents for "remote").
    "remote", "tv remote", "bag", "purse", "backpack", "shoes", "headphones", "earbuds", "airpods",
    "passport", "watch", "sunglasses", "jacket", "coat", "umbrella", "ring", "badge", "car keys",
    "house keys", "spare key", "controller", "hat",
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
    # "My name is Caleb" is kept in her memory of him; "how do you spell my
    # name" one turn later said she had none (2026-10-08).
    if not first and not last:
        try:
            from aletheia import memory
            first = " ".join(str(memory.recall("identity", "operator_name") or memory.recall("identity", "full_name")
                                 or "").split())
            if " " in first and which not in ("first",):
                first, last = first.split(" ", 1)
        except Exception:  # noqa: BLE001
            first = ""
    parts = ([first] if which == "first" else [last] if which in ("last", "sur") else [first, last])
    parts = [p for p in parts if p]
    if not parts:
        return "I don't have your name on file. Tell me and I'll remember it."
    return "; ".join(f"{p}: " + "-".join(ch.upper() for ch in p if ch.isalpha()) for p in parts) + "."


def _a_contact_named(name: str) -> bool:
    """Whether he has a contact by that name: "how do I reach Comcast" is
    the web's, "how do I reach Sam" is his contacts'."""
    try:
        from aletheia import contacts
        low = name.casefold()
        return any(low == str(c.get("display_name") or "").casefold().split(" ")[0] or low == str(c.get("id") or "").casefold()
                   for c in contacts.all_contacts())
    except Exception:  # noqa: BLE001
        return False


_GROCERY = (r"eggs?|milk|bread|butter|cheese|coffee|tea|sugar|flour|rice|pasta|cereal|oats|oatmeal|yogh?urt|cream|juice|water|soda|beer|wine"
            r"|chicken|beef|pork|bacon|ham|turkey|fish|salmon|tuna|shrimp|tofu|beans|lentils|onions?|garlic|potatoes?|tomatoes?|lettuce"
            r"|spinach|carrots?|apples?|bananas?|oranges?|lemons?|limes?|avocados?|berries|strawberries|grapes|peppers?|broccoli|cucumbers?"
            r"|salt|pepper|oil|olive oil|vinegar|ketchup|mustard|mayo|mayonnaise|honey|jam|peanut butter|snacks?|chips|crackers|cookies"
            r"|ice cream|frozen pizza|pizza|tortillas|bagels?|paper towels|toilet paper|tissues|napkins|dish soap|soap|shampoo|conditioner"
            r"|toothpaste|detergent|laundry detergent|dishwasher (?:pods|tabs)|trash bags|garbage bags|foil|plastic wrap|batteries"
            r"|light ?bulbs|dog food|cat food|cat litter|diapers|wipes|formula|baby food")


def _in_the_kitchen(thing: str) -> str | None:
    """"Do I have eggs": on the shopping list means he's out; a grocery not
    on it is something she can't see. None for anything else."""
    item = re.sub(r"^(?:any |some |enough |a |an |the |more )", "", " ".join(str(thing or "").casefold().split()))
    item = re.sub(r" (?:left|at home|in the (?:house|fridge|pantry|freezer)|in stock)$", "", item)
    if not re.fullmatch(_GROCERY, item):
        return None
    try:
        from aletheia import intercom
        listed = [str(w.get("need") or "") for w in intercom._shopping_items()]
    except Exception:  # noqa: BLE001
        listed = []
    stem = item.rstrip("s")
    hit = next((n for n in listed if re.search(rf"\b{re.escape(stem)}", n.casefold())), None)
    if hit:
        return f"Sounds like you're out - {hit} {'are' if hit.casefold().endswith('s') else 'is'} on your shopping list."
    return (f"I can't see your kitchen, but {item} {'aren' if item.endswith('s') else 'isn'}'t on your shopping list. "
            f"Say \"add {item}\" if you need some.")


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
    # "Do I have any approvals" searched his Documents (2026-10-08). Her
    # own approvals and what waits on him are hers to read.
    if re.fullmatch(r"(?:any |anything )?(?:pending |open )?(?:approvals?|requests?|decisions?|things? waiting(?: on me| for me)?)(?: pending| waiting)?", low):
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
# "And milk too" put "milk too" on the list (2026-10-08): the marker is
# dropped wherever it ends the item, not only after a bare "add".
_ALSO = re.compile(r"(?:and |also )add (.+?)(?: too| as well| also)?"
                   r"|add (.+?)(?: too| as well| also)"
                   r"|(?:and|also) (.+?)(?: too| as well| also)?")


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


def _bought_yet(item: str) -> str | None:
    """Whether he has bought a thing, by his shopping list. None when the
    list does not know - never a guess."""
    want = " ".join(str(item or "").casefold().split())
    stem = want[:-1] if len(want) > 3 and want.endswith("s") else want
    if not stem:
        return None
    try:
        from aletheia import shopping
        rows = shopping.all_workflows()
    except Exception:  # noqa: BLE001
        return None
    hits = [r for r in rows if stem in " ".join(str(r.get("need") or "").casefold().split())]
    open_ = [r for r in hits if str(r.get("state", "")).upper() in ("RESEARCHING", "SELECTED", "PURCHASE_PROPOSED")]
    if open_:
        return f"Not yet - {open_[0].get('need')} is still on your shopping list."
    done = sorted((r for r in hits if str(r.get("state", "")).upper() == "CANCELLED"),
                  key=lambda r: str(r.get("updated_at") or ""), reverse=True)
    if done:
        when = ""
        try:
            from aletheia import speech
            at = str(done[0].get("updated_at") or "")
            when = ", " + speech.humanize_time(at) if at else ""
        except Exception:  # noqa: BLE001
            when = ""
        return f"Yes - {done[0].get('need')} came off your shopping list{when.rstrip()}."
    return None


def _his_words_about(thing: str) -> str | None:
    """"Where is my parking spot" after "my parking spot is B12" (2026-10-08:
    searched his Documents). His own "my X is ..." is the answer."""
    try:
        from aletheia import quick
        rows = quick._notes()
    except Exception:  # noqa: BLE001
        return None
    key = re.escape(re.sub(r"^(?:my|the|our) ", "", " ".join(str(thing or "").casefold().split())))
    for row in rows:
        said = " ".join(str(row.get("text") or "").split()).rstrip(".")
        if key and re.fullmatch(rf"(?:my|our|the) {key} (?:is|are) .+", said, re.I):
            return f"You told me: {speech.as_she_says_it(said)}."
    return None


def _said_as_a_title(text: str, title: str) -> bool:
    """Whether he gave a title its capital ("Severance", "The Bear") - what
    tells a show from "watching the kids"."""
    words = [w for w in re.findall(r"[A-Za-z0-9']+", str(text or "")) if w.casefold() in str(title or "").casefold().split()]
    return any(w[:1].isupper() or w[:1].isdigit() for w in words)


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
_SPAN = (r"(?P<span>(?:every|each) (?:week|month|other day|other week|other (?P<oday>monday|tuesday|wednesday|thursday|friday|"
         r"saturday|sunday)|(?P<n>\d+|two|three|four|five|six) (?P<unit>days|weeks)|couple of weeks)|weekly|monthly|fortnightly)")
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
    elif span in ("every week", "each week", "weekly"):
        # "Remind me to call mom every week" (2026-10-08: to the planner):
        # today's weekday, said back so the day he gets can be heard.
        n, unit = 1, "weeks"
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



#: Occasions he goes to. "The wedding is at the Grand Hotel" is a fact about
#: one of these, not a place he saved or a file.
_EVENT_WORDS = (r"wedding|wedding reception|reception|rehearsal dinner|funeral|memorial|wake|baby shower|bridal shower|shower"
                r"|reunion|graduation|bachelor party|bachelorette party|birthday party|party|recital|ceremony|gala|fundraiser"
                r"|housewarming|open house|christening|baptism|bar mitzvah|bat mitzvah|quinceanera|engagement party")
#: An item on "my list" that starts like this is a thing to DO, not to buy.
_TASK_VERB = re.compile(
    r"^(?:call|phone|ring|email|text|message|write to|pay|book|fix|send|check|finish|schedule|cancel|renew|"
    r"return|pick up|drop off|clean|wash|mow|file|submit|apply|follow up|chase|ask|tell|remind|order|"
    r"print|sign|read|review|update|install|set up|back up|look into|look up|talk to|meet|visit|water|sort|organize|organise|vacuum|take out|bring|replace|feed|prepare|study|research|cook|buy|clear out|tidy|"
    # "Add write the report to my list" went on the SHOPPING list (2026-10-07).
    r"write|draft|plan|go to|practi[cs]e|prep|start|learn|figure out|find|reply to|respond to|answer|confirm|"
    # "I need to catch up with Mike" (2026-10-08: to the planner).
    r"catch up with|reach out to|check in (?:on|with)|get together with|hang out with|grab (?:lunch|coffee|dinner|drinks|a drink|a beer) with|"
    r"register|sign up|fill out|complete|repair|refill|re-fill|paint (?:the|my|a)|wrap (?:the|my|a|presents|gifts)|charge (?:the|my)|edit|proofread|reschedule|get back to|"
    r"make an? (?:appointment|reservation|call|plan|list|dentist|doctor)|do (?:the|my) "
    # "I have to take the car in for service on Monday" (2026-10-07: to the planner).
    r"|take (?:the|my) (?:car|truck|van|dog|cat|kids?|trash|recycling|bins?|garbage|laundry|package|parcel)|get (?:the|my) (?:car|truck|oil|tires?|hair|teeth|flu shot|eyes|brakes|battery|windshield|alignment|transmission|ac|a/c)"
    r"|get (?:a|an) (?:haircut|oil change|flu shot|checkup|check-up|physical)"
    # "I need to iron my suit" (2026-10-08: to the planner).
    r"|iron (?:my|the|a)|steam (?:my|the|a)|press (?:my|the) (?:suit|shirt|dress|pants|slacks)|hem (?:my|the)|polish (?:my|the)|shine (?:my|the)"
    # "I need to get gas" (2026-10-08: the shopping list).
    r"|get (?:gas|fuel|petrol|diesel)|fill up(?: the (?:car|tank|truck))?|fill (?:the )?(?:car|tank|truck) up"
    # "I need to change the air filter" (2026-10-08: to the planner).
    r"|change (?:the|my) (?:air filters?|furnace filters?|water filters?|filters?|oil|sheets|bed|batteries|battery|light ?bulbs?|bulbs?"
    r"|smoke detector batter(?:y|ies)|tires?|wipers?|litter(?: box)?|cat litter)"
    r"|sweep|mop|dust|rake|shovel|trim|weed|unclog|descale|defrost|flip (?:the|my) mattress|empty (?:the|my)|unload|load (?:the|my)"
    # "I need to pack lunches tonight" (2026-10-08: the packing list).
    r"|pack (?:the |school |the kids'? |their |my )?lunch(?:es)?"
    # "I need to move the car by 8 for street cleaning" (2026-10-08: to the planner).
    r"|move (?:the|my) (?:car|truck|van|suv|bins?|trash cans?)"
    # "I need to RSVP to the wedding" (2026-10-08: to the planner).
    r"|rsvp)\b")


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
# What he went and did, said in the past - shared with `quick._went`,
# which reads these notes back.
_WENT = (r"went (?:for a |on a )(?:run|walk|swim|bike ride|ride|hike|jog)|went (?:running|swimming|jogging|hiking|biking|cycling)"
         r"|went to (?:the )?(?:gym|pool|yoga|pilates|spin class|class|church|doctor|dentist|chiropractor|therapy|physical therapy"
         r"|barber|library|park)|worked out|exercised|meditated|did yoga|ran|jogged|swam")
# What a bill of his is called, shared with `quick._BILL_KEYS`.
_BILL_WORDS = (r"rent|mortgage|car payment|(?:car |auto |health |home |renters? |life |pet )insurance(?: payment| bill)?"
               r"|insurance (?:payment|bill)|phone bill|cell(?: phone)? bill|electric(?:ity)? bill|internet bill|wifi bill"
               r"|water bill|gas bill|cable bill|utilities|utility bill|student loans?(?: payment)?|loan payment|daycare|tuition"
               r"|gym membership|hoa(?: fees?)?|childcare|car loan|trash bill|sewer bill|(?:cell |cell phone |mobile )?phone plan|cell plan|phone payment"
               # "My Netflix is 15 a month" (2026-10-07: to the planner).
               r"|netflix|spotify|hulu|disney plus|disney\+|hbo max|hbo|youtube premium|youtube tv|amazon prime|prime membership|apple music|apple tv|icloud|peacock|paramount plus|audible|game pass|xbox game pass|playstation plus|ps plus|chatgpt|chat gpt|claude subscription|(?:[a-z]+ )?subscription")
_DONE_VERBS = ("changed|gave|paid|fed|walked|watered|cleaned|washed|mowed|vacuumed|replaced|renewed|fixed|serviced|filed|submitted"
               "|rotated|flushed|emptied|refilled|filled|charged|backed up|updated|trimmed|cut|groomed|bathed"
               "|dropped off|picked up|returned|mailed|posted|vaccinated|dewormed|descaled|defrosted"
               # "I called mom" (2026-10-07: to the planner). A call he made is
               # his to tell her; "when did I last call mom" reads it back.
               "|called|visited"
               # "I talked to mom", "I saw Sam today" (2026-10-07: to the planner).
               "|talked to|talked with|spoke to|spoke with|saw|met with|met up with|hung out with|texted|caught up with"
               # "I locked the front door" - "did I lock the door" reads it back
               "|locked|closed|shut|unplugged|turned off"
               # "I took out the trash" (2026-10-08: to the planner).
               "|took out")


def _would_spend(said: str) -> bool:
    """`webtask.would_spend`, the one money predicate; True when it cannot
    be asked, so a sentence that might spend is never answered here."""
    try:
        from aletheia import webtask
        return webtask.would_spend(said)
    except Exception:  # noqa: BLE001 - fail closed
        return True


#: Chores he names as a noun: on a list with a day, they are tasks.
_CHORES = (r"(?:the |my )?(?:laundry|dishes|vacuuming|ironing|mowing|yard ?work|homework|taxes|meal prep|groceries"
           r"|grocery shopping|cleaning|chores|trash|recycling|bills|oil change|car wash|errands|packing)")


def _task_just_closed(asked: str) -> dict | None:
    """The task his last ask dropped or ticked off, as a task_new that puts
    it back, or None. Only one closed in the last ten minutes whose words
    are in that ask, so "undo that" never resurrects something older."""
    import datetime as dt
    try:
        from aletheia import tasks
        rows = tasks.all_tasks()
    except Exception:
        return None
    said = " ".join(str(asked or "").casefold().split())
    if not said:
        return None
    now = dt.datetime.now(dt.timezone.utc)
    best = None
    for task in rows:
        if task.get("status") not in ("CANCELLED", "COMPLETED"):
            continue
        try:
            at = dt.datetime.fromisoformat(str(task.get("updated_at") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        what = " ".join(str(task.get("description") or "").casefold().split())
        if what and what in said and now - at < dt.timedelta(minutes=10) and (best is None or at > best[0]):
            best = (at, task)
    if best is None:
        return None
    task = best[1]
    made = _new_task(str(task["description"]))
    if task.get("deadline"):
        made["command"]["deadline"] = task["deadline"]
    return made


def _work_reminders_said(when: str = "get to work", since: str = "started work", lead: str = "Noted.") -> str | None:
    """What he asked to be told when he got to work - or, with `when`
    "leave work", when he left - since he last did; None when nothing, so
    the plain receipt is said."""
    try:
        from aletheia import quick
        rows = list(reversed(quick._notes()))
    except Exception:
        return None
    out = []
    for row in rows:
        said = " ".join(str(row.get("text") or "").split())
        m = re.fullmatch(rf"remind me (to|that) (.+?) when i {re.escape(when)}", said, re.I)
        if said.casefold() == since:
            out = []
        elif m:
            out.append(speech._yours(m.group(2)) if m.group(1).casefold() == "to" else "that " + speech._yours(m.group(2)))
    if not out:
        return None
    done = {"get to work": "got to work", "leave work": "left work"}.get(when, when)
    return f"{lead} You asked me to remind you when you {done}: {speech.and_list(out)}."


def _hours_he_told(place: str) -> str | None:
    """His own note of a place's hours - "my gym opens at 5am" - newest
    first, said back as his; None when he never told her."""
    try:
        from aletheia import quick
        rows = quick._notes()
    except Exception:  # noqa: BLE001
        return None
    place = re.sub(r"^(?:my|the|our) ", "", " ".join(str(place or "").casefold().split()))
    for row in rows:
        said = " ".join(str(row.get("text") or "").split())
        if re.fullmatch(rf"(?:my|the|our) (?:local )?{re.escape(place)} (?:opens|closes|is open|is closed)\b.*", said, re.I):
            return f"You told me {speech.as_she_says_it(said).rstrip('.')}."
    return None


def _an_errand(words: str) -> bool:
    """Whether words after "to" are something to do - "get a card", "pack" -
    rather than the rest of a name: "my flight to Paris"."""
    return bool(_TASK_VERB.match(words) or re.match(r"(?:get|grab|pack|wrap|make|charge|iron|take|confirm|pick|leave|set|put|start|stop)\b", words))


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
    # No day said: today, unless the time has already gone by - "I have a
    # meeting at 1" said at 6 pm was held for 1 pm today (2026-10-07).
    unsaid = not str(day or "").strip()
    day = day or "today"
    day_iso = _spoken_day(day)
    if not day_iso:
        return None
    if str(day).strip().casefold() == "tonight":
        part = part or "night"          # "a party tonight at 8" is eight in the evening
    # "I have a dentist appointment next Thursday at 9", said on a
    # Wednesday, was held for TOMORROW (2026-10-07): "next" went into the
    # title and was stripped there. "Next Thursday" is the one phrase worth
    # asking about, and the answer comes back as the sentence that holds it.
    said_next = re.search(r"\bnext (" + "|".join(WEEKDAYS) + r")\b", str(transcript or "").casefold())
    # Only when the coming one is a day or two away: "next Tuesday" on a
    # Wednesday is plainly the 13th, "next Thursday" on a Wednesday is not.
    near = said_next and (WEEKDAYS.index(said_next.group(1)) - localtime.today().weekday()) % 7 in (1, 2)
    if near and said_next.group(1) == str(day).strip().casefold():
        asked = _ambiguous_next_weekday(f"next {said_next.group(1)}")
        if asked:
            soon = re.search(r"the (\d+\w\w)", asked).group(1)
            again = re.sub(r"\bnext " + said_next.group(1) + r"\b", f"on the {soon}", str(transcript).strip().rstrip(".?!"),
                           count=1, flags=re.IGNORECASE)
            return {"command": None, "say": f"{asked} Say '{again}' and it's held."}
    # "Next Wednesday", said on a Wednesday, was held for TODAY at 2
    # (2026-10-08). The same weekday "next" is a week out, never today.
    if said_next and said_next.group(1) == str(day).strip().casefold() \
            and dt.date.fromisoformat(day_iso) == localtime.today():
        day_iso = (localtime.today() + dt.timedelta(days=7)).isoformat()
    # "Schedule lunch with Sam next Tuesday" held "lunch with sam next"
    # (2026-10-07): the word before the day belongs to the day.
    title = re.sub(r"\s+(?:next|this|on|for|coming)$", "", str(title or "").strip(), flags=re.IGNORECASE) or title
    # "Lunch with Jess at noon tomorrow" was held as "lunch with jess at
    # noon" and read back "at noon at 12 pm" (2026-10-07): the time is the
    # hold's, not its name's.
    title = re.sub(r"\s+at (?:noon|midnight|\d{1,2}(?::\d\d)? ?(?:am|pm|a\.m\.|p\.m\.)?)$", "", str(title).strip(),
                   flags=re.IGNORECASE) or title
    # "Max has a vet appointment friday at 3" was held as "max has a vet
    # appointment" (2026-10-07) and read back "Max has a vet appointment
    # is Friday". Somebody else's appointment is theirs: "Max's vet
    # appointment". His own ("I have a dentist appointment") is just it.
    own = re.fullmatch(r"(?:i|we) (?:have|have got|'ve got|got|made|booked|scheduled|set up|'ve booked|have booked|just made|just booked) (?:a|an|my|our) (.+)"
                       r"|(?:i'?m|we'?re|i am|we are) (?:having|hosting|throwing|going to|off to) (?:a|an|my|our|the) (.+)",
                       str(title), flags=re.IGNORECASE)
    # "The dog has a vet appointment" too (2026-10-08): "the dog's vet appointment".
    theirs = re.fullmatch(r"((?:(?:the|my|our) )?[a-z][a-z']{1,20}) (?:has|has got|'s got) (?:(?:a|an|his|her|their|its) )?(.+)",
                          str(title), flags=re.IGNORECASE)
    if own:
        title = own.group(1) or own.group(2)
    elif theirs and theirs.group(1).casefold() not in ("he", "she", "it", "who", "what", "that", "this", "there", "everyone",
                                                         "somebody", "someone", "nobody"):
        # A name in its capitals ("Leo's", not "leo's"); "mom" stays a word.
        from aletheia import quick
        who = theirs.group(1)
        who = who if (who.casefold() in quick._relation_words() or " " in who) else who[:1].upper() + who[1:]
        title = f"{who}'s {theirs.group(2)}"
    if time_words:
        hhmm = _spoken_time(time_words)
        if not hhmm:
            return None
        hour, minute = map(int, hhmm.split(":"))
        if _is_bare_hour(time_words) and 1 <= hour <= 7:
            hour += 12
        # "A party on the 24th at 8" was held at 8 am (2026-10-07): an
        # evening thing at a bare 8 to 11 is the evening.
        elif _is_bare_hour(time_words) and 8 <= hour <= 11 and re.search(
                r"\b(?:party|dinner|supper|drinks|concert|show|movie|movies|game night|date night|date|gig|play|bar"
                r"|happy hour|club|birthday party|reception|gala|karaoke|poker)\b", str(title).casefold()):
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
    if unsaid and start < dt.datetime.now(localtime.operator_tz()):
        start += dt.timedelta(days=1)
    # "A plumber appointment Thursday at 9", said on a Thursday afternoon,
    # was held for that morning, already gone (2026-10-08). A bare weekday
    # whose hour has passed today is the next one.
    elif str(day).strip().casefold() in WEEKDAYS and start < dt.datetime.now(localtime.operator_tz()):
        start += dt.timedelta(days=7)
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
            # The thing itself is where it is: "my car insurance is due on
            # the 15th" answered "where's my car" (2026-10-07), because "is
            # ... on" was anywhere in the note.
            if re.search(rf"\b{re.escape(stem)}", low) and re.search(
                    rf"\b(?:put|left|keep|hid|placed|parked|moved)\b.*\b{re.escape(stem)}"
                    rf"|\b{re.escape(stem)}\w*(?:'s)? (?:is|are|was|were)(?: (?:still|now|probably))? "
                    r"(?:in|on|at|under|by|behind|next to|inside|near|up|down|out|with)\b"
                    rf"|\b{re.escape(stem)}\w* (?:in|on|at|under|by|behind|next to|inside|near)\b"
                    # "I lent my drill to Bob" answers "where's my drill" too.
                    r"|\b(?:lent|loaned|borrowed)\b", low):
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


def _same_ask_again() -> str | None:
    """"Another one" after a joke, a fact, a coin or a pick: the same ask
    answered again, a different answer where it has more than one. None
    when the last ask was not one of those."""
    from aletheia import quick as _q
    asked, answered = _previous_turn()
    if not asked or (_q.match(asked) or ("",))[0] not in ("joke", "fun_fact", "coin", "dice", "pick_number",
                                                          "meal_idea", "pick_for_me", "quote", "riddle"):
        return None
    if _q.match(asked)[0] in ("coin", "dice", "pick_number"):
        return _q.answer(asked)          # a toss is fair only if it may repeat
    said = None
    for _try in range(6):
        said = _q.answer(asked)
        if said and said.strip() != str(answered or "").strip():
            break
    return said


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


_LOOKING_BACK = threading.local()


def _list_just_read(turns: int = 5):
    """The match for the list she read out in the last few turns, or None:
    "6 things on your shopping list: bread, butter, ..." """
    try:
        from aletheia import converse
        recent = converse.recent(limit=turns) or []
    except Exception:  # noqa: BLE001
        return None
    for turn in reversed(recent):
        m = re.match(r"(?P<n>\d+) things? on your (?:(?P<name>[\w' -]+?) )?list: (?P<items>.+)\.$",
                     " ".join(str(turn.get("she_answered") or "").split()))
        if m:
            return m
    return None


def _the_reminder_just_set() -> dict | None:
    """The reminder his last few asks set, as it stands now, or None.

    Looking back re-reads his earlier sentences through `interpret`, which
    would ask this again for each of them; once is the whole question."""
    if getattr(_LOOKING_BACK, "busy", False):
        return None
    _LOOKING_BACK.busy = True
    try:
        asked = _recent_reminder_ask()
    finally:
        _LOOKING_BACK.busy = False
    if not asked.get("text"):
        return None
    try:
        from aletheia import intercom
        found, _why = intercom._one_reminder(str(asked["text"]))
    except Exception:  # noqa: BLE001
        return None
    return found if found and found.get("kind") == "once" else None


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
        # "Snooze that" acts on a notice, never on what he asked for, so
        # "move it to 2:30" after it still means the reminder (2026-10-08).
        if cmd.get("kind") == "notify_snooze":
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
            from aletheia import localtime
            # In HIS zone: a 9 am reminder is 14:00 UTC, and read in UTC
            # "change that to 7" moved it to seven at night (2026-10-08).
            was = dt.datetime.fromisoformat(str(previous.get("at") or "").replace("Z", "+00:00")) \
                .astimezone(localtime.operator_tz())
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
        if bare and 1 <= hour <= EARLIEST_BARE_HOUR and not was.hour <= EARLIEST_BARE_HOUR:
            # "Make it 4" on a 10 am reminder is four in the afternoon,
            # the way a bare hour is read everywhere else; "make it 7" on a
            # 9 am one is still the morning, the half it was already in.
            # And "move it to 2:30" on a 2 am one is 2:30 am (2026-10-08:
            # it went to the afternoon).
            hour += 12
        same_day = was.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if same_day > dt.datetime.now(tz):
            at = same_day.isoformat()
    except (ValueError, TypeError):
        pass
    return {"command": {"kind": "remind_at", "at": at, "text": previous["text"],
                        "replaces": previous["text"]}, "say": None}


def _her_holds_on(day_word: str) -> list:
    """Her own tentative holds on the weekday or day he named, soonest first:
    (local start, event). Empty when there are none or the store won't read."""
    import datetime as dt
    try:
        from aletheia import calendar, localtime
        tz = localtime.operator_tz()
        iso = _spoken_day(day_word)
        if not iso:
            return []
        day = dt.date.fromisoformat(iso[:10])
        now = dt.datetime.now(dt.timezone.utc)
        rows = []
        for event in calendar.all_events():
            if event.get("status") != "TENTATIVE" or not str(event.get("source") or "").startswith("hold:"):
                continue
            start = calendar.parse_time(event["start"])
            if start > now and start.astimezone(tz).date() == day:
                rows.append((start.astimezone(tz), event))
        return sorted(rows, key=lambda r: r[0])
    except Exception:
        return []


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
    # "Cancel that meeting", one breath after it was pencilled in
    # (2026-10-08: "I can't cancel things on your calendar").
    said = re.sub(r"^(?:my|the|our|that|this) ", "", said)
    said = re.sub(r" (?:today|tomorrow)$", "", said)
    # "My Thursday meeting", "the 3pm on Friday" (2026-10-07): a weekday
    # narrows it to holds on that day.
    weekday = re.search(r"\b(?:on )?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:'s)?\b", said)
    if weekday:
        mine = [(s, e) for s, e in mine if s.strftime("%A").casefold() == weekday.group(1)]
        said = " ".join(re.sub(r"\b(?:on )?" + weekday.group(1) + r"(?:'s)?\b", " ", said).split()) or "meeting"
    if said in ("meeting", "appointment", "call", "thing", "hold", "one") and weekday:
        hits = mine
        return (hits[0][1], "") if len(hits) == 1 else (None, "more than one" if hits else "")
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
    # "Push it to 2" from 11 am is two in the afternoon, not 2 am
    # (2026-10-08): a bare hour before EARLIEST_BARE_HOUR is never meant.
    try:
        was = dt.datetime.fromisoformat(str(previous["start"]).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    hour, minute = map(int, hhmm.split(":"))
    # A bare hour keeps the half of the day the hold was in: dinner at 7
    # "made 8" is eight in the evening.
    if _is_bare_hour(time_words) and hour < 12 and (was.hour >= 12 or hour <= EARLIEST_BARE_HOUR):
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
    if _is_bare_hour(time_words) and hour < 12 and (was.hour >= 12 or hour <= EARLIEST_BARE_HOUR):
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


def _timer_minutes(words: str) -> float | None:
    """The length a timer's own words name: "your 10-minute timer is up"."""
    named = r"(?: [a-z' ]{1,30}?)? timer"
    m = re.search(r"your (?:(\d+) hour )?(\d+(?:\.\d+)?)(?:-| )minute" + named + r"|your (\d+)-hour" + named
                  + r"|your (\d+) and a half minute" + named, str(words or ""))
    if not m:
        return None
    if m.group(3):
        return int(m.group(3)) * 60.0
    if m.group(4):
        return int(m.group(4)) + 0.5
    return int(m.group(1) or 0) * 60 + float(m.group(2))


def _restarted_timer() -> dict:
    """"Restart the timer" (2026-10-07: "I can't pause a timer"): the same
    length again from now - the one running, or the one that just went off."""
    import datetime as dt
    running = _running_once("timer is up")
    if len(running) > 1:
        return {"command": None, "say": f"You have {len(running)} timers running - cancel the one you don't "
                                        "want and set it again."}
    words = running[0][1] if running else ""
    if not words:
        try:
            from aletheia import scheduler
            gone = [spec for spec in scheduler.all_schedules()
                    if spec.get("kind") == "once" and "timer is up" in str((spec.get("command") or {}).get("text") or "")]
            gone.sort(key=lambda spec: str(spec.get("created_at") or ""))
            words = str((gone[-1].get("command") or {}).get("text") or "") if gone else ""
        except Exception:
            words = ""
    minutes = _timer_minutes(words)
    if not minutes:
        return {"command": None, "say": "I don't have a timer to start again. Say \"set a timer for 5 minutes\"."}
    at = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutes)).isoformat()
    command = {"kind": "remind_at", "at": at, "text": words}
    if running:
        command["replaces"] = words
    return {"command": command, "say": None}


def _moved_alarm(time_words: str, was_words: str = "") -> dict:
    """"Change my alarm to 6:30": the one alarm, same day, the new time.
    "Change my 6:30 alarm to 7" names which one when there are several."""
    import datetime as dt
    from aletheia import localtime
    running = _running_once("wake up")
    hhmm = _spoken_time(time_words)
    if not hhmm:
        return _to_the_planner(f"change my alarm to {time_words}")
    if not running and not was_words:
        # Only a repeating alarm (2026-10-08: "you don't have an alarm set"
        # with one set for weekdays): the one repeating alarm moves, same days.
        try:
            from aletheia import scheduler
            repeating = [spec for spec in scheduler.all_schedules()
                         if spec.get("enabled") and spec.get("kind") in ("daily", "weekly")
                         and "wake up" in str((spec.get("command") or {}).get("text") or "").casefold()]
        except Exception:
            repeating = []
        if len(repeating) == 1:
            spec = repeating[0]
            if spec.get("kind") == "daily":
                return {"command": {"kind": "remind_daily", "time": hhmm, "text": "wake up", "replaces": "wake up"},
                        "say": None}
            return {"command": {"kind": "remind_weekly", "days": list(spec.get("weekdays") or []), "time": hhmm,
                                "text": "wake up", "replaces": "wake up"}, "say": None}
        if len(repeating) > 1:
            return {"command": None, "say": f"You have {len(repeating)} repeating alarms - turn off the one you "
                                            f"don't want and set it again for {time_words}."}
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
    except Exception:
        return False
    if found is None:
        return False
    # "Move my dentist appointment to Thursday" moved the task "reschedule
    # my dentist appointment", and "cancel my dentist appointment" dropped
    # it, while the appointment itself sat on her calendar (2026-10-08). A
    # task ABOUT the appointment is not the appointment.
    about = r"(?:reschedule|cancel|move|confirm|book|make|schedule|set up|call (?:about|to (?:reschedule|cancel|confirm)))\b"
    if re.match(about, str(found.get("description") or "").casefold()) and not re.match(about, " ".join(str(words).casefold().split())) \
            and _one_of_her_holds(words)[0]:
        return False
    return True


def _named_list_said(low: str, text: str) -> dict | None:
    """One of his named lists, or None. Never raises."""
    from aletheia import lists
    name_ = r"(?P<name>[a-z][a-z' -]{1,30}?)"
    if re.fullmatch(r"what (?:lists|other lists) do i have|what are my lists|(?:list|read me|show me) my lists"
                    # "How many lists do I have" (2026-10-07: to a model).
                    r"|how many lists (?:do i have|have i got|are there)|(?:do i have|have i got) any (?:other )?lists", low):
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
                    r"give me a (?:sec|second|minute|moment)|"
                    # "Nothing" said after she asked what to do (2026-10-07: to the planner).
                    r"nothing|nothing else|nothing right now|that's all|that's it|that is all)(?: thanks| thea| please)?")
_NO_PASSWORDS = ("I don't keep passwords - anything that looks like one is blanked out of "
                 "everything I write down, so I couldn't read it back to you. "
                 "Your password manager is the place for it.")
_NO_ID_NUMBERS = ("I don't keep Social Security numbers, card numbers, bank account numbers or PINs - "
                  "written down here, they'd be one leak away from somebody else. Your password manager is the place for them.")
#: "My social security number is ..." (2026-10-08: sent to the planner, so
#: the number sat in a queued ask). The numbers that open his money or his
#: identity are refused at the door, said or noted.
_ID_NUMBER = re.compile(r"\b(?:social security(?: number)?|ssn|social|(?:credit|debit|bank) card(?: number)?|card number|cvv|cvc|security code"
                        r"|(?:bank |checking |savings )?account number|routing number|pin(?: number| code)?|tax id|ein|itin)\b"
                        r"(?: for [a-z ]{2,20})? (?:is|are|=|:) ?[#]?\s*[0-9][0-9 -]{2,}", re.I)


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
            # "Did anyone call" after he told her "my mom called": what he
            # told her first, then what she can't see (2026-10-08).
            if "phone's calls" in answer and re.fullmatch(r"(?:did (?:anyone|anybody|someone|somebody) call|who called)(?: me)?", said):
                from aletheia import quick as _q
                told = _q._who_called("")
                if not told.startswith("Nobody"):
                    # His capitals stay: "Dana stopped by", "your mom called".
                    lead = told[:1].lower() if told.startswith(("Your ", "The ")) else told[:1]
                    return f"You told me {lead}{told[1:]}"
            return answer.format(**found.groupdict()) if found.groupdict() else answer
    return None


#: Who has a name, a birthday, a vet: one of his, said without the
#: apostrophe a transcript never hears ("my dogs name is Max", 2026-10-08:
#: to the planner, and "what is my dogs name" found nothing about "dogs").
_WHOSE = (r"dog|cat|puppy|kitten|pet|wife|husband|son|daughter|mom|mum|dad|sister|brother|boss|friend|kid|baby"
          r"|neighbor|neighbour|landlord|girlfriend|boyfriend|partner|fiance|fiancee|grandma|grandpa|aunt|uncle"
          r"|niece|nephew|cousin|car|horse|bird|fish|hamster|rabbit|bunny")
_OWNED = (r"name|birthday|age|vet|doctor|dentist|food|medicine|meds|number|phone number|email|address|teacher|school"
          r"|size|shoe size|favorite [a-z]+|allergies|allergy|breed|weight|appointment|party|anniversary|plate|license plate")


def _event_from_notes(what: str) -> dict | None:
    """"My flight is at 6 am on Friday" as an event: {"title", "start"}, the
    newest note that names `what` with a day and a time still ahead. For
    "remind me 2 hours before my flight" when the flight is a note and not
    on the calendar (2026-10-08). None when no note says both."""
    import datetime as dt
    from aletheia import localtime, quick as _q
    words = [w for w in re.findall(r"[a-z0-9]+", str(what or "").casefold()) if len(w) > 2]
    if not words:
        return None
    tz = localtime.operator_tz()
    now = dt.datetime.now(tz)
    days = r"(today|tonight|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|" + SPOKEN_DATE + r")"
    for row in _q._notes():
        said = " ".join(str(row.get("text") or "").split())
        low = said.casefold()
        # "I have a wedding on Saturday at 4" (2026-10-08) says it too.
        if not all(w in low for w in words) or not re.search(r"\b(?:is|leaves|departs|starts)\b|^i (?:have|'ve got|got) (?:a|an|my)\b", low):
            continue
        day = re.search(r"\b(?:on |this |next )?" + days + r"\b", low)
        clock = re.search(r"\bat (\d{1,2}(?::\d\d)? ?(?:am|pm|a\.m\.|p\.m\.)?|noon|midnight)", low)
        if not day or not clock:
            continue
        iso = _spoken_day(day.group(0).replace("on ", "").replace("this ", "").strip())
        hhmm = _spoken_time(clock.group(1))
        if not iso or not hhmm:
            continue
        hour, minute = map(int, hhmm.split(":"))
        if _is_bare_hour(clock.group(1)) and hour <= EARLIEST_BARE_HOUR:
            hour += 12
        start = dt.datetime.combine(dt.date.fromisoformat(iso), dt.time(hour, minute), tzinfo=tz)
        if start > now:
            bare = re.sub(r"^(?:my|your|the) ", "", " ".join(re.findall(r"[a-z0-9']+", str(what).casefold())))
            # his capitals: "your flight to Paris" (2026-10-08: "to paris")
            his = re.search(re.escape(bare), said, re.I)
            title = "your " + (said[his.start():his.end()] if his else bare)
            return {"title": title, "start": start.isoformat()}
    return None


#: Names that end in s on their own, so "James teacher" is not "Jame's".
_ENDS_IN_S = ("James|Charles|Chris|Thomas|Nicholas|Douglas|Lucas|Marcus|Agnes|Frances|Doris|Lewis|Louis|Dennis"
              "|Phyllis|Iris|Gus|Jess|Russ|Ross|Wes|Les|Carlos|Jesus|Andreas|Elias|Silas|Atlas|Miles|Moses|Amos"
              "|Hayes|Reyes|Gladys|Lois|Alexis|Paris|Tess|Bess|Cass|Jules|Niles|Myles|Ellis|Willis|Curtis|Otis|Rhys")


def _apostrophes(transcript: str) -> str:
    """"My dogs name" -> "my dog's name", keeping his capitals. "My bosses
    name" is the boss's, and "Sarah number" - a capitalised name before
    what a person has - is Sarah's (2026-10-08: both to the planner)."""
    said = re.sub(r"\b((?:my|our|the) (?:" + _WHOSE + r"))s (" + _OWNED + r")\b", r"\1's \2",
                  str(transcript or ""), flags=re.I)
    said = re.sub(r"\b((?:my|our|the) boss)(?:es|s) (" + _OWNED + r")\b", r"\1's \2", said, flags=re.I)
    # "When is sam birthday" (2026-10-08: to a model) - typed lowercase, so
    # the capitalised-name rule below never saw it.
    said = re.sub(r"\b(when is|when's|whens|what day is|how many days until|how long until) "
                  r"(?!(?:my|your|his|her|their|our|the|a|an|it|this|that)\b)([a-z]{2,15}) (birthday|bday)\b",
                  r"\1 \2's \3", said, flags=re.I)
    # "Set an alarm for 6 30 tomorrow", "remind me at 3 30" (2026-10-08: to
    # the planner): a dictated clock time loses its colon.
    said = re.sub(r"\b(at|for|by|until|till|around|from|to) (1[0-2]|0?[1-9]) ([0-5]\d)\b(?! ?(?:minutes?|mins?|hours?|hrs?|seconds?|secs?|days?|weeks?"
                  r"|months?|years?|percent|dollars?|bucks|pounds?|lbs?|miles?|people|times|of|[a-z]+s\b))",
                  r"\1 \2:\3", said, flags=re.I)
    # "A doctors appointment" (2026-10-08: held and read back that way).
    said = re.sub(r"\b(doctor|dentist|vet|lawyer|accountant|barber|hairdresser|optometrist|therapist|orthodontist|dermatologist"
                  r"|chiropractor|pediatrician|surgeon|eye doctor)s (appointment|appt|office|visit|checkup|check-up)\b",
                  r"\1's \2", said, flags=re.I)
    # "My wife ring size is 6", "my wife favorite flower is tulips"
    # (2026-10-08: to the planner) - the apostrophe and its s both dropped.
    said = re.sub(r"\b((?:my|our) (?:wife|husband|mom|mother|dad|father|son|daughter|sister|brother|girlfriend|boyfriend|partner"
                  r"|grandma|grandpa|fiance|fiancee|baby|dog|cat|boss|manager|coworker|landlord|neighbor|neighbour|doctor|dentist|teacher|friend)) (name|weight|breed|vet|ring size|shoe size|dress size|shirt size|pants size|favorite|favourite"
                  r"|birthday|phone number|email|car|middle name|maiden name|allergies|allergy"
                  # "My daughter teacher is Mrs Smith" (2026-10-08: read back as "your daughter teacher").
                  r"|teacher|coach|principal|pediatrician|homework|grades|bus stop|school bus)\b", r"\1's \2", said, flags=re.I)
    # "Whats coming up", "whats the most important thing today" (2026-10-08:
    # each to a model) - typed without the apostrophe, they missed every
    # pattern written "what's". The question word gets it back.
    said = re.sub(r"\b(what|where|who|how|when)s\b", r"\1's", said, flags=re.I)
    # "What is jake wife name" (2026-10-08: to a model) - a friend's wife,
    # both apostrophes dropped. Only right after "what is", where a bare
    # word before "wife name" can be nobody but whose.
    said = re.sub(r"\b(what(?:'s| is) )(?!(?:my|our|your|the|his|her|their)\b)([a-z]{2,15}) (wife|husband|girlfriend|boyfriend|fiance|fiancee|son|daughter|kid|baby|dog|cat|mom|dad|partner) name\b",
                  r"\1\2's \3's name", said, flags=re.I)
    # "Emmas teacher is Mrs Brown", "when is Emmas dentist appointment"
    # (2026-10-08: to the planner). A capitalised name with an s stuck on,
    # before something a person has, is that person's - except a name that
    # really ends in s.
    said = re.sub(r"(?<![\w'])(?!(?:" + _ENDS_IN_S + r")\b)([A-Z][a-z]{1,15}[^s\W])s (teacher|coach|school|class|dentist|doctor|"
                  r"(?:dentist |doctor |vet |school |soccer |piano |dance )?(?:appointment|practice|game|recital|lesson|party)|"
                  r"birthday|number|phone number|email|address|friend|mom|dad|wife|husband|boyfriend|girlfriend)\b",
                  r"\1's \2", said)
    # "Dr patel number is 555 222 3333" (2026-10-08: to the planner) - a
    # doctor typed lowercase still has a number.
    said = re.sub(r"\b(dr\.?|doctor) ([a-z]{2,15}) (number|phone number|office number|email|address)\b", r"\1 \2's \3", said, flags=re.I)
    return re.sub(r"(?<![\w'])(?!(?:My|The|Our|What|When|Where|Who|How|Is|Set|Add|Call|Text|Email)\b)([A-Z][a-z]{1,15}(?<!s)) "
                  r"(number|phone number|cell number|cell|email|email address|birthday|address)\b(?! is (?:a|an|the)\b)",
                  r"\1's \2", said)


def interpret(transcript: str) -> dict:
    """One spoken sentence -> a command to gate-check, or words to say.

    The wrapper exists for one reason: every path below matches against a
    LOWERCASED sentence, and anything it STORES has to keep his capitals.
    Doing it here rather than in thirty patterns means the next pattern
    somebody writes gets it for free.
    """
    transcript = _a_follow_on(_a_polite_ask(_with_the_person_named(_a_clock_said(_apostrophes(transcript)))))
    return _his_capitals(strip_wake_word(transcript),
                         _no_password_in_a_note(_no_reminder_about_a_pronoun(
                             _the_day_before(transcript, _interpret(transcript)))))


def _the_day_before(transcript: str, said: dict) -> dict:
    """"Remind me to buy flowers before Valentine's Day" was set FOR
    Valentine's Day, reading "buy flowers before" (2026-10-08). Before a day
    is the day before it, and the reminder names the day."""
    import datetime as dt
    cmd = (said or {}).get("command") or {}
    if cmd.get("kind") != "remind_at" or not re.search(r" (?:before|by)$", str(cmd.get("text") or "")):
        return said
    m = re.search(r"\b(?P<word>before|by) (?P<day>.+?)[.!?]?$", str(transcript or ""), re.I)
    if not m:
        return said
    try:
        at = dt.datetime.fromisoformat(str(cmd["at"]))
    except (KeyError, ValueError):
        return said
    base = re.sub(r" (?:before|by)$", "", str(cmd["text"]))
    day = re.sub(r"^(?:the )?", "", m.group("day")).strip()
    day = re.sub(r"\bvalentines\b", "Valentine's", day, flags=re.I)
    if re.fullmatch(_HOLIDAYS, day.casefold()):
        day = " ".join(w[:1].upper() + w[1:] for w in day.split())
    day = day[:1].upper() + day[1:] if not re.match(r"\d", day) else "the " + day
    earlier = at - dt.timedelta(days=1)
    if earlier <= dt.datetime.now(at.tzinfo):
        return {**said, "command": {**cmd, "text": f"{base} {m.group('word').casefold()} {day}"}}
    return {**said, "command": {**cmd, "at": earlier.isoformat(), "text": f"{base} - {day} is tomorrow"}}


#: A second half that is plainly its own ask of hers.
_AN_ASK_OF_HERS = re.compile(
    r"(?:remind me|set (?:a|an|the|my) |start (?:a|an|the) |add (?:a task|a reminder|.{1,40} to (?:my|the) )"
    r"|put .{1,40} on (?:my|the) |text |message |email |turn (?:on|off|up|down) |play |pause\b|cancel |wake me"
    r"|note (?:that|:)|make a note|what(?:'s| is| are)? |when(?:'s| is)? |how (?:much|many|long) )")


#: "My sister is visiting", "I have a wedding", "we're having people over",
#: "I'm hosting game night" - something on with other people, said with a
#: when (2026-10-07: every one to the planner). Kept as a note in his words.
_SOCIAL_PLAN = (r"(?:(?:my|our) (?:[a-z]+(?:-in-law| in law)?s?|in-laws|in laws|parents|folks|family|kids|friends?(?: [a-z]+)?"
                r"|(?:cousin|uncle|aunt|brother|sister|niece|nephew|grandma|grandpa|coworker|boss|neighbor) [a-z]+)|[a-z]+ and [a-z]+"
                r"|(?!(?:who|what|which|anyone|anybody|someone|somebody|nobody|everyone|everybody"
                r"|it|that|this|rain|snow|a storm|the storm|storm|weather|winter|summer|spring|fall|the package|package|my package"
                r"|the delivery|delivery|the bill|the rent|rent|the bus|the train)\b)[a-z]+)"
                r" (?:is|are) (?:visiting|coming (?:over|to visit|to stay|to town|in|for a visit)|coming|staying with us|in town|flying in)"
                r"|(?:i|we) (?:have|'ve got|have got|got) (?:a |an |the |my |our )?(?:wedding|party|birthday party|baby shower|bridal shower"
                r"|funeral|reunion|recital|graduation|game night|book club|date night|date|concert|show|game|tournament|bbq|barbecue"
                r"|cookout|potluck|housewarming|work party|holiday party|christmas party|dinner party|sleepover|playdate)"
                r"|(?:i'?m|we'?re|i am|we are) (?:hosting|throwing|having) (?:a |an |the |our |my )?(?:people over|friends over|guests over"
                r"|company over|family over|the family over|[a-z]+ over|wedding|party|birthday party|game night|book club|dinner party"
                r"|bbq|barbecue|cookout|potluck|housewarming|sleepover|playdate)"
                r"|(?:i'?m|we'?re|i am|we are) (?:going to|attending) (?:a |an |the |my |our |[a-z]+'s )?(?:wedding|party|birthday party|funeral"
                r"|reunion|concert|game|show|recital|graduation|baby shower|housewarming|game night)")
_HOLIDAYS = (r"thanksgiving|christmas(?: eve)?|new year'?s(?: eve| day)?|easter|halloween|the fourth|fourth of july|july 4th"
             r"|labor day|memorial day|hanukkah|passover|mother'?s day|father'?s day|valentine'?s(?: day)?")


def two_asks(transcript: str) -> list[str] | None:
    """"Add milk to the list and remind me at 5 to go shopping" is two asks.

    Said as one sentence (2026-10-07) it went to the planner whole. Split at
    an "and" only when the whole is NOT something she reads already and BOTH
    halves are, each on its own - a question she answers from her stores or
    a command with its own verb. Each half then goes through the same door a
    sentence of its own would, gates and all, so a split can never reach
    anything one of the halves could not. The first split that works wins;
    none is a guess. Never raises.
    """
    said = strip_wake_word(str(transcript or "")).strip()
    if not said or len(said.split()) > 40:
        return None

    def handled(half: str) -> bool:
        if len(half.split()) < 2:
            return False
        out = interpret(half) or {}
        if out.get("say"):
            return True
        kind = (out.get("command") or {}).get("kind")
        if kind and kind != "intent":
            return True
        if kind == "intent":
            try:
                from aletheia import quick
                return bool(quick.answer(half))
            except Exception:  # noqa: BLE001
                return False
        return False

    # "Remind me to take my antibiotics every day at 8am, 2pm and 8pm"
    # (2026-10-07: ONE daily reminder at 9 am, with the times in its words).
    # One reminder per time, each through its own door.
    clock = r"(?:\d{1,2}(?::\d\d)?(?: ?[ap]\.?m\.?)?|noon|midnight)"
    several = re.fullmatch(r"remind me (?:to )?(?P<what>.+?)(?P<d1> (?:every day|daily|each day|every morning))? at "
                           rf"(?P<times>{clock}(?:(?:,| and|, and) {clock})+)(?P<d2> (?:every day|daily|each day))?",
                           said, re.IGNORECASE)
    if several and not re.search(r"\bat \d", several.group("what")):
        times = re.split(r",? and |, ", several.group("times"))
        daily = bool(several.group("d1") or several.group("d2"))
        what = several.group("what").strip()
        asks = [f"remind me to {what} every day at {t}" if daily else f"remind me at {t} to {what}" for t in times]
        if 2 <= len(asks) <= 6 and all(handled(a) for a in asks):
            return asks

    # "Remind me at 9 tomorrow and at 5 to call the bank" (2026-10-08: to
    # the planner). The times come first; a day said once is both times'.
    day = r"(?:today|tonight|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    first = re.fullmatch(rf"remind me at (?P<t1>{clock})(?: (?:on )?(?P<w1>{day}))? and (?:again )?(?:at )?(?P<t2>{clock})"
                         rf"(?: (?:on )?(?P<w2>{day}))? (?P<to>to|about) (?P<what>.+)", said, re.IGNORECASE)
    if first and not re.search(r"\bat \d", first.group("what")):
        w1 = first.group("w1") or first.group("w2") or ""
        w2 = first.group("w2") or first.group("w1") or ""
        asks = [" ".join(f"remind me at {t} {w} {first.group('to')} {first.group('what').strip()}".split())
                for t, w in ((first.group("t1"), w1), (first.group("t2"), w2))]
        if all(handled(a) for a in asks):
            return asks

    # "Set a timer for pasta for 10 minutes and one for the oven for 20"
    # (2026-10-07: to the planner): "one" is another timer, and a bare 20
    # takes the first timer's unit.
    second = re.fullmatch(r"(?P<left>.*\btimer\b.*?(?P<u>seconds?|minutes?|mins?|hours?|hrs?)\b.*?)"
                          r",? and (?:one|another(?: one)?) for (?:the |my )?(?P<what>[a-z][a-z ]{0,24}?)"
                          r" for (?P<n>\d{1,3})(?: (?P<u2>seconds?|minutes?|mins?|hours?|hrs?))?",
                          said, re.IGNORECASE)
    if second:
        right = (f"set a timer for {second.group('what')} for {second.group('n')} "
                 f"{second.group('u2') or second.group('u')}")
        if handled(second.group("left")) and handled(right):
            return [second.group("left"), right]

    try:
        whole = interpret(said) or {}
        # Read whole already - but a greedy capture can swallow a second ask:
        # "add a task to water the plants and set a timer for 10 minutes"
        # was ONE task (2026-10-07). Then only a second half that is plainly
        # an ask of hers, with a verb of its own, is split off; "remind me to
        # text mom and call dad" stays one reminder.
        greedy = bool(whole.get("say")) or (whole.get("command") or {}).get("kind") not in (None, "intent")
        for m in re.finditer(r",? (?:and then|and also|and|then also|then|also|plus) ", said, re.IGNORECASE):
            left, right = said[:m.start()].strip(" ,"), said[m.end():].strip(" ,")
            if greedy and not (_AN_ASK_OF_HERS.match(right.casefold())
                               and ((interpret(right) or {}).get("command") or {}).get("kind") not in (None, "intent")):
                continue
            if handled(left) and handled(right):
                return [left, right]
    except Exception:  # noqa: BLE001 - one sentence, as he said it
        return None
    return None


# What "can you ..." is asking her to DO, when the rest is a concrete ask.
# A question about ability ("can you text people", "can you buy things")
# compiles to nothing here and is still answered as one.
_POLITE_DOING = frozenset({
    "remind_at", "remind_daily", "remind_every", "remind_weekly", "remind_monthly", "remind_weekdays",
    "shopping_add", "shopping_off", "shopping_list", "task_new", "task_done", "task_change", "tasks",
    "reminders", "reminder_off", "note", "email_check", "stopwatch", "stopwatch_read", "music",
    "travel_time", "free_time", "notify_snooze", "list_add", "list_read", "list_off", "brief", "contacts",
    # "Can you move my dentist appointment to Wednesday" was answered "Yes,
    # but it is experimental" and nothing moved (2026-10-08).
    "calendar_hold", "hold_release", "calendar_find_free",
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
                     r"|(?:i need|i want|i'd like|i would like) (?:you|u) to (?:please )?"
                     # "I was wondering if you could add a task..." (2026-10-08: to the planner)
                     r"|i (?:was|am|'m) wondering if (?:you|u) (?:could|would|can) (?:please )?"
                     r"|(?:is there any way|is it possible) (?:that )?(?:you|u) (?:could|can) (?:please )?)?"
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
    # "Can you clear my afternoon": her plain word on what she can and
    # can't change is the answer to the ask and to the question alike.
    says_why_not = (cmd.get("kind") is None and (_interpret(rest) or {}).get("say")
                    and re.match(r"(?:move|push|bump|reschedule|cancel|clear|delete|remove) ", rest, re.IGNORECASE))
    if cmd.get("kind") not in _POLITE_DOING and not asks_back and not says_why_not:
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
    if cmd.get("kind") in ("note", "intent") and _ID_NUMBER.search(str(cmd.get("text") or "")):
        return {"command": None, "say": _NO_ID_NUMBERS}
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
    if re.search(r"\blist\b", low) and not re.fullmatch(r"(?:delete|clear|empty|scrap) (?:the|this|that) list"
                                                       r"|what'?s on the list|read (?:me )?the list", low):
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
    # "Remove the last one" counts down the list she read (2026-10-07: it
    # looked for a thing called "last one"); that is read further on.
    if m and (m.group("w") or m.group("w2")) not in ("it", "that", "this", "list", "everything", "all") \
            and speech.ordinal_index(m.group("w") or m.group("w2")) is None:
        return _interpret(f"take {m.group('w') or m.group('w2')} off my {name} list")
    if re.fullmatch(r"what'?s on (?:it|there|the list)(?: now)?|read (?:it|that)(?: back| out)?|what'?s left(?: on it)?"
                    r"|read (?:me )?the list|how many (?:things|items)(?: are)? on (?:it|there)(?: now)?", low):
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


_WHO_HURT = (r"(?:my|our|the) (?:son|daughter|kid|kids|child|baby|toddler|boy|girl|wife|husband|partner|mom|mum|mother|dad|father"
             r"|grandma|grandpa|grandmother|grandfather|brother|sister|friend|roommate|neighbou?r)|(?:he|she|someone|somebody)")


def _emergency(low: str) -> str | None:
    """What to do, said first, when what he says is an emergency
    (2026-10-08: "my son swallowed a battery", "my wife is not breathing"
    and "I smell gas" all went to the planner - which, with the models out,
    answered "it's on my list"). Only the one thing that helps: who to
    call, now. She cannot call anyone herself and never says she will."""
    low = re.sub(r"^(?:help|oh no|oh my god|omg|please help|quick|thea)[,!.]* ", "", low)
    low = re.sub(r",? (?:what (?:do|should) i do|help(?: me)?|please)$", "", low)
    if re.fullmatch(rf"(?:{_WHO_HURT}) (?:just )?(?:swallowed|ate|drank|got into|took) (?:a |an |some |the |my |his |her |a bunch of |too many )?"
                    r"(?:button )?(?:batter(?:y|ies)|magnets?)", low):
        return "A swallowed battery or magnet is an emergency. Go to the ER or call 911 now - don't wait for symptoms."
    if re.fullmatch(r"i (?:just )?(?:took|swallowed) too many (?:pills|tablets|of my (?:pills|meds|medication)|[a-z]+)", low):
        return ("Call 911 or Poison Control at 1-800-222-1222 now. If you took them on purpose, you can also call or "
                "text 988 any hour - you don't have to go through this alone.")
    if re.fullmatch(rf"(?:{_WHO_HURT}) (?:just )?(?:swallowed|ate|drank|got into|took|bit into) (?:a |an |some |the |my |his |her |a bunch of |too many )?"
                    r"(?:bleach|tide pods?|laundry pods?|detergent|dishwasher pods?|cleaner|cleaning stuff|drain cleaner|antifreeze|poison|rat poison|pesticide"
                    r"|weed killer|lighter fluid|gasoline|vape juice|nicotine|e-?cig(?:arette)? liquid|pills|medicine|medication|my pills|my medicine|vitamins"
                    r"|tylenol|advil|ibuprofen|aspirin|nail polish remover|mouthwash|hand sanitizer|essential oils?)", low) \
            or re.fullmatch(r"i (?:accidentally )?(?:drank|swallowed) (?:some )?(?:bleach|cleaner|antifreeze|poison)", low):
        return ("Call Poison Control at 1-800-222-1222 now - they answer any hour. If they're struggling to breathe, "
                "having a seizure or hard to wake, call 911 instead.")
    if re.fullmatch(rf"(?:{_WHO_HURT}|i) (?:is|are|am|'s|'m)? ?(?:not breathing|isn'?t breathing|can'?t breathe|cannot breathe|choking|unconscious|unresponsive"
                    r"|having a seizure|having a heart attack|having a stroke|passed out and won'?t wake up|won'?t wake up|turning blue|bleeding (?:a lot|badly|heavily))", low) \
            or re.fullmatch(rf"(?:{_WHO_HURT}) (?:just )?(?:collapsed|fell and can'?t get up|fell and (?:hit|cracked) (?:his|her|their) head|stopped breathing)", low) \
            or re.fullmatch(r"i think (?:i'?m|i am|(?:" + _WHO_HURT + r") (?:is|'s)) having (?:a heart attack|a stroke|a seizure|an allergic reaction)", low) \
            or re.fullmatch(r"i (?:cut myself (?:really )?badly|can'?t stop the bleeding|am bleeding (?:a lot|badly)|can'?t breathe)", low):
        return "Call 911 now."
    if re.fullmatch(r"(?:there(?:'s| is) a |my |the )?(?:fire|house is on fire|kitchen is on fire|stove is on fire|the house is on fire)(?: in (?:my|the) [a-z ]{2,20})?"
                    r"|(?:my|the|our) (?:house|kitchen|apartment|garage|stove|oven) (?:is )?on fire", low):
        return "Get everyone out now and call 911 from outside. Don't go back in."
    if re.fullmatch(r"i (?:can )?smell gas(?: in (?:the|my) [a-z ]{2,20})?|(?:it )?smells like gas(?: in here)?|(?:there(?:'s| is) a |i think there(?:'s| is) a )?gas leak", low):
        return ("Leave the house now. Don't flip switches or light anything on the way out, and call 911 or your gas "
                "company's emergency line from outside.")
    return None


def _interpret(transcript: str) -> dict:
    text = strip_wake_word(transcript)
    low = _without_preamble(text.lower().strip().rstrip(".?!"))
    # "hey thea, apply to jobs for me": the filler hid her name from the
    # strip above, and her name then hid the sentence from every pattern.
    # Only her name ("hey thea") is a call, not a sentence: she answers it.
    low = re.sub(r"^(?:%s)\b[\s,.!?:;]*" % "|".join(WAKE_WORDS), "", low)
    if not low:
        return {"command": None, "say": "I'm listening."}
    # AN EMERGENCY FIRST, before any rule that could keep it as a note.
    sos = _emergency(low)
    if sos:
        return {"command": {"kind": "note", "text": "Journal: " + _as_he_said(text, low)}, "say": sos}
    # "I need to remember to bring snacks Saturday" (2026-10-08: to the
    # planner) is "I need to bring snacks Saturday": remembering is her job.
    low = re.sub(r"^(i (?:need|have|got|gotta|must|should)(?: to)? |i've got to )(?:remember to |not forget to )", r"\1", low)
    low = re.sub(r"^(?:don't let me forget|i can't forget) to ", "i need to ", low)
    # "My budget for food is 400 a month" (2026-10-08: to the planner) is
    # his food budget, said the way the budget readers already read it.
    low = re.sub(r"^(my|our) (?:monthly )?budget for (groceries|grocery|food|gas|fun|shopping|eating out) is ",
                 lambda b: f"{b.group(1)} {'grocery' if b.group(2).startswith('grocer') else b.group(2)} budget is ", low)
    # "DELETE ALL MY TASKS", "MARK EVERYTHING DONE" (2026-10-07: to the
    # planner). The same rule: his whole list is not one sentence's to undo.
    # FIRST, before any rule that finds one task by its words: with two
    # open tasks "delete all my tasks" dropped one of them (2026-10-08).
    if re.fullmatch(r"(?:delete|remove|clear|wipe|cancel|drop) (?:all|every one of|everything on) (?:of )?(?:my |the )?"
                    r"(?:tasks|to[- ]?dos?|task list|to[- ]?do list)|(?:clear|wipe|empty) (?:my |the )?(?:task list|to[- ]?do list|tasks)"
                    r"|mark (?:everything|all(?: of)?(?: my)?(?: tasks)?|every task)(?: on (?:my |the )?(?:task list|to[- ]?do list|list))?"
                    r" (?:as )?(?:done|complete|completed|finished)"
                    r"|(?:check|tick|cross) off (?:everything|all(?: of)?(?: my)?(?: tasks)?|every task)"
                    r"(?: on (?:my |the )?(?:task list|to[- ]?do list|list))?", low):
        return {"command": None,
                "say": "I won't change your whole task list on one sentence. Say \"what's on my list\" and then "
                       "\"mark the first one done\" or \"delete\" and what it says, one at a time."}
    # "I got a haircut today" (2026-10-08: held on the calendar for 9 am
    # today). "Got" with today is done, not had: kept, and "when did I last
    # get a haircut" reads it.
    # Said without "today" it already ticks off a task or is kept, so the
    # day is dropped and the sentence read the way it always was.
    got = re.fullmatch(r"(?P<did>i (?:just )?got (?:a |an |my )?(?:haircut|hair cut|trim|massage|manicure|pedicure|mani pedi|flu shot"
                       r"|covid shot|booster|tattoo|piercing|facial|teeth cleaned|teeth cleaning|eye exam|physical|checkup|check-up"
                       r"|car wash|oil change)) (?:today|this morning|this afternoon|earlier|earlier today|tonight)", low)
    if got:
        return _interpret(text[:len(got.group("did"))] if text.lower().startswith(got.group("did")) else got.group("did"))
    # "Test", "mic check", "is my computer on", "what's my phone's battery"
    # (2026-10-07: all to a model). The first two are him checking she hears;
    # she runs on the PC, so answering at all says it is on; his phone's
    # battery is on his phone.
    if re.fullmatch(r"(?:test|testing|testing,? (?:one,? two(?:,? three)?|1,? 2(?:,? 3)?|123)|mic check|check,? check)", low):
        return {"command": None, "say": "I hear you."}
    if re.fullmatch(r"is (?:my |the )?(?:computer|pc|laptop|desktop) (?:on|running|awake|up)(?: right now| now)?", low):
        return {"command": None, "say": "Yes - I'm running on it right now."}
    if re.fullmatch(r"(?:what(?:'s| is) |how(?:'s| is) )?(?:my )?phone(?:'s)? battery(?: (?:level|at|like))?"
                    r"|how much battery (?:does|is left on) my phone(?: have)?", low):
        return {"command": None, "say": "I can't see your phone's battery - only the PC's. Ask \"what's the battery\" for that."}
    # "Remind me on weekdays at 8 to stand up", "remind me Mondays at 9"
    # (2026-10-07: to the planner). A plural day IS "every" that day.
    if low.startswith("remind me ") and not re.search(r"\bevery\b", low):
        plural = re.sub(r"\b(?:on )?(weekday|weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)s\b",
                        r"every \1", low, count=1)
        if plural != low:
            again = _interpret(plural)
            if (again.get("command") or {}).get("kind") in ("remind_weekly", "remind_daily"):
                return again
    # "Remind me at 5 every day to walk the dog", "remind me every other
    # week on Monday at 2 to pay the sitter" (2026-10-07: both to the
    # planner). The same schedules in another order; kept only when the
    # reordered sentence comes back a recurring reminder.
    if low.startswith("remind me "):
        _wd = r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?"
        moved = re.sub(r"^remind me at ([\w: ]+?) (every (?:day|morning|evening|night|weekday|" + _wd[1:-3] + r")s?)\b",
                       r"remind me \2 at \1", low, count=1)
        moved = re.sub(r"\bevery (?:other|2|two) weeks? on " + _wd, r"every other \1", moved, count=1)
        if moved != low:
            again = _interpret(moved)
            if (again.get("command") or {}).get("kind") in ("remind_weekly", "remind_daily"):
                return again
    # "Change my address to 12 Oak St", "update my email to ..." (2026-10-07:
    # to the planner). The same fact as "my address is ...", said as a
    # change; only kept when that sentence is one she keeps.
    m = re.fullmatch(r"(?:please )?(?:change|update|set|switch|correct) my (?P<key>[a-z][a-z' ]{1,30}?) to (?P<value>.+)", low)
    if m and m.group("key") not in ("alarm", "reminder", "timer", "status", "mind", "plans", "plan", "password", "pin"):
        # In his capitals: the value is read back as he said it ("12 Oak St").
        his = re.search(r"\bmy (.+?) to (.+?)[.!?]*$", text.strip(), re.IGNORECASE)
        again = _interpret(f"my {his.group(1)} is {his.group(2)}" if his
                           else f"my {m.group('key')} is {m.group('value')}")
        if (again.get("command") or {}).get("kind") in ("remember", "note"):
            return again
    # "Set a daily reminder to take my pills at 9", "add a monthly reminder
    # to pay rent on the 1st", "create a reminder to call mom at 5"
    # (2026-10-07: to the planner). The same ask as "remind me to ...", said
    # as a noun; only kept when it comes back the kind of reminder he named.
    m = re.fullmatch(r"(?:please )?(?:set|add|create|make|put in|schedule|set up) (?:me )?(?:a |an )?(?:new )?"
                     r"(?:(?P<freq>daily|weekly|monthly|recurring|repeating) )?reminder (?P<how>to|for|about) (?P<rest>.+)", low)
    if m and not (m.group("how") == "for" and re.match(
            r"(?:\d|tomorrow|today|tonight|noon|midnight|this|next|in |at |on |monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
            m.group("rest"))):
        freq, rest = m.group("freq") or "", m.group("rest")
        lead = "remind me to " if m.group("how") == "to" else "remind me about "
        tail = ""
        if freq == "daily" and not re.search(r"\bevery\b", rest):
            tail = " every day"
        elif freq in ("monthly", "recurring", "repeating") and re.search(r"\bon the \d{1,2}(?:st|nd|rd|th)\b", rest) \
                and "every month" not in rest:
            tail = " every month"
        want = {"daily": ("remind_daily",), "weekly": ("remind_weekly",), "monthly": ("remind_monthly",)}.get(
            freq, ("remind_daily", "remind_weekly", "remind_monthly", "remind_every") if freq else
            ("remind_at", "remind_daily", "remind_weekly", "remind_monthly", "remind_every"))
        again = _interpret(lead + rest + tail)
        if (again.get("command") or {}).get("kind") in want \
                or not freq and not again.get("command") and str(again.get("say") or "").startswith("When should I remind you"):
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
        # "Delete my reminder" - "You have 2 reminders. Which one: ...?" - "both".
        if re.match(r"You have \d+ reminders\. Which one: ", answered or ""):
            return {"command": {"kind": "reminder_off", "which": "all reminders"}, "say": None}
    _said, answered = _previous_turn()
    # "Delete my reminder" - "Which one: call mom ... or feed the cat ...?" -
    # "feed the cat" / "the cat one" (2026-10-07): the one he named, if it
    # is one she listed.
    which = re.match(r"You have \d+ reminders\. Which one: (.+)\?$", answered or "")
    if which:
        named = re.sub(r"^(?:cancel|delete|remove|turn off|stop)\s+|^the\s+|\s+one$|\s+reminder$", "", low).strip()
        named = re.sub(r"^the\s+|\s+one$", "", named).strip()
        if len(named) >= 3 and named in which.group(1).casefold():
            return {"command": {"kind": "reminder_off", "which": named}, "say": None}
    # "Remind me next Tuesday at noon to call the bank" - "Which Tuesday - the
    # 13th, or the week after on the 20th?" - "the 13th" / "the first one" /
    # "the week after" (2026-10-07: the answer went to the planner).
    pick = re.match(r"Which \w+ — the (\d+\w\w), or the week after on the (\d+\w\w)\? "
                    r"Say 'remind me on the \d+\w\w(.*?)' and it's set", answered or "")
    if pick and len(low.split()) <= 6:
        soon, later, rest = pick.groups()
        day = None
        if re.search(r"\b" + soon[:-2] + r"(?:st|nd|rd|th)?\b", low) or re.search(
                r"\b(?:first|sooner|earlier|this|coming|this one|that one)\b", low):
            day = soon
        if re.search(r"\b" + later[:-2] + r"(?:st|nd|rd|th)?\b", low) or re.search(
                r"\b(?:second|later|after|following|other)\b", low):
            day = later if day is None or "after" in low or "second" in low else day
        if day:
            got = _interpret(f"remind me on the {day}{rest}")
            if str(((got or {}).get("command") or {}).get("kind", "")).startswith("remind_"):
                return got
    # The same for a hold: "Which Thursday - the 8th, or the week after on
    # the 15th? Say 'I have a dentist appointment on the 8th at 9' and it's
    # held." - "the 15th", "the week after", "the first one" (2026-10-07).
    held = re.match(r"Which \w+ — the (\d+\w\w), or the week after on the (\d+\w\w)\? "
                    r"Say '(.+?)' and it's held", answered or "")
    if held and len(low.split()) <= 6:
        soon, later, sentence = held.groups()
        day = None
        if re.search(r"\b" + soon[:-2] + r"(?:st|nd|rd|th)?\b", low) or re.search(
                r"\b(?:first|sooner|earlier|this|coming|this one|that one|yes|that)\b", low):
            day = soon
        if re.search(r"\b" + later[:-2] + r"(?:st|nd|rd|th)?\b", low) or re.search(
                r"\b(?:second|later|after|following|other)\b", low):
            day = later if day is None or "after" in low or "second" in low else day
        if day:
            got = _interpret(sentence.replace(f"on the {soon}", f"on the {day}", 1))
            if ((got or {}).get("command") or {}).get("kind") == "calendar_hold":
                return got
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
        if name == "gift" and low.endswith(" the list"):
            # "Add perfume to Anna's gift list", then "add milk to the list"
            # put milk on the GIFT list (2026-10-07). A gift line names who
            # it is for; "the list" on its own is still his shopping list.
            name = None
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
    also = re.fullmatch(r"(?:and|also|oh and|and also) (remind me .+?)( too| as well| also)?", low)
    if also:
        # "Too" may mean the same time as the one just set: asked that way first.
        if also.group(2):
            got = ((_interpret(also.group(1) + also.group(2)) or {}).get("command") or {})
            if got.get("kind") == "remind_at" and not re.search(r" (?:too|as well|also)$", str(got.get("text") or "")):
                return {"command": got, "say": None}
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
    # "Cancel my reminders", "clear my alarms" - plural, so every one of
    # them (2026-10-07: "cancel my reminders" looked for a reminder called "my").
    m = re.fullmatch(r"(?:turn off|cancel|delete|clear|stop|remove|disable|kill) (?:(?:all|every one of) (?:of )?(?:my |the )?|my |the )"
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
    # "Put them back" after "cancel all my reminders" (2026-10-08: the planner).
    m = re.fullmatch(r"(?:actually,? |no,? |wait,? )?(?:put|turn|switch) (?:that|it|them|those)(?: all)? back(?: on)?"
                     r"|bring (?:that|it|them|those)(?: all)? back|(?:actually,? )?turn (?:that|it|them|those) on again"
                     r"|undo that", low)
    if m:
        previous = _previous_ask()
        before = (_interpret(previous).get("command") or {}) if previous else {}
        if before.get("kind") != "reminder_off":
            # "Cancel all my reminders", "what reminders do I have", "put
            # them back" (2026-10-08): a look at the list sits between.
            try:
                from aletheia import converse
                for turn in reversed(converse.recent(limit=4) or []):
                    said = re.sub(r"^(?:thea|aletheia)[,]?\s+", "", " ".join(str(turn.get("he_asked") or "").split()),
                                  flags=re.IGNORECASE)
                    got = (_interpret(said).get("command") or {}) if said and said.casefold() != low else {}
                    if got.get("kind") == "reminder_off":
                        before = got
                        break
            except Exception:  # noqa: BLE001
                pass
        if before.get("kind") == "reminder_off" and not before.get("once"):
            return {"command": {"kind": "reminder_on", "which": before["which"]}, "say": None}
        # "Delete laundry", "undo that" (2026-10-08: "nothing to undo"). A
        # closed task never reopens, so the same task is added again.
        back = _task_just_closed(previous)
        if back is not None:
            return back
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
    # SOMEBODY'S ADDRESS (2026-10-07): "what's mom's address" read back
    # her phone number - a different question answered confidently - and
    # "mom lives at 12 Oak Street" went to the planner. A contact has no
    # address field; a note in his words does, and is what this reads.
    m = (re.fullmatch(r"(?:my |our )?(?P<who>[a-z][a-z' ]{1,25}?)(?:'s| s|s)? (?:lives at|lives on|address is|new address is)"
                      r" (?P<addr>\d.{3,80})", low)
         # "My mom lives in Denver" (2026-10-07: to the planner).
         or re.fullmatch(r"(?:my |our )?(?P<who>[a-z][a-z' ]{1,25}?) (?:lives|live|is living|moved) (?:in|to) "
                         r"(?P<addr>(?!(?:fear|denial|hope|sin|the past|a dream|my head|her head|his head)\b)[a-z][a-z .,']{2,40})", low))
    if m and not re.match(r"(?:i|he|she|it|they|who|where|what|this|that|the|my|our|work|home|office)\b", m.group("who")):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    m = (re.fullmatch(r"what(?:'s| is|s) (?:the )?(?P<who>(?!the\b|this\b|that\b|your\b|its\b|their\b|his\b|her\b)[a-z][a-z' ]{1,30}?)"
                      r"(?:'s| s) (?:home |mailing |street )?address", low)
         or re.fullmatch(r"where does (?P<who>(?!he\b|she\b|it\b|that\b|this\b)[a-z][a-z' ]{1,30}?) live(?: now)?", low))
    if m and not _is_about_himself(m.group("who")):
        who = m.group("who").strip()
        bare = re.sub(r"^(?:my|our) ", "", who)
        from aletheia import quick
        asked = [[w for w in re.findall(r"[a-z0-9]+", bare) if w != "s"]]
        # "What's my wife's address" when he said "Sarah lives at ...".
        named = quick._name_for_relation(who) if who.startswith(("my ", "our ")) else None
        if named:
            asked.append(re.findall(r"[a-z0-9]+", named.casefold()))
        for words in asked:
            for row in quick._notes():
                said = " ".join(str(row.get("text") or "").split())
                low_said = said.casefold()
                if words and all(re.search(rf"\b{re.escape(w)}", low_said) for w in words) \
                        and re.search(r"\b(?:lives (?:at|on|in)|address is|moved to|is living in)\b", low_said):
                    return {"command": None, "say": f"You told me: {speech.as_she_says_it(said).rstrip('.')}."}
        his = "your " + bare if who.startswith(("my ", "our ")) or bare in _RELATIONS else bare.title()
        says = re.sub(r"^your ", "my ", his)
        return {"command": None, "say": f"I don't have {his}'s address. Say \"{says} lives at\" and the address, and I'll keep it."}
    # "How do I reach Sam" (2026-10-08: to a model) is his details.
    m = re.fullmatch(r"how (?:do|can) i (?:reach|contact|get (?:a )?hold of|get in touch with) (?P<who>my [a-z][a-z ]{1,20}|[a-z]{2,15})", low)
    if m and m.group("who") not in ("you", "them", "him", "her", "it", "support", "someone", "somebody", "anyone") \
            and (m.group("who").startswith("my ") or _a_contact_named(m.group("who"))):
        return {"command": {"kind": "contacts", "which": m.group("who")}, "say": None}
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
            and m.group(1).strip() not in ("the", "a", "an", "your", "their", "this", "that", "its", "his", "her") \
            and not re.match(r"(?:new|up|happening|going on|the latest|latest|good) in\b", m.group(1)) \
            and not re.search(r"\b(?:locker|account|member(?:ship)?|policy|license|licence|plate|wifi|wi-fi|gate|door"
                              r"|garage|room|seat|flight|confirmation|order|tracking|case|ticket|insurance|social security"
                              r"|passport|employee|student|customer|reference|serial|model|pin|bank|routing|card|apartment"
                              r"|unit|house|street|home|work|office|zip|postal|post)$", m.group(1)):
        asked = "email" if low.endswith("email") else "number" if low.endswith("number") else ""
        return {"command": {"kind": "contacts", "which": m.group(1).strip(), **({"asked": asked} if asked else {})},
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
        # "Flip a coin", "again" (2026-10-07): the toss, not a question.
        said = _same_ask_again() if re.fullmatch(r"(?:do (?:that|it) )?again(?: please)?", low) else None
        if said:
            return {"command": None, "say": said}
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
    # RIGHT AFTER SHE READ A LIST (2026-10-07: "how many things is that",
    # "is cheese on it" and "take the first one off" all went to the
    # planner). The list she just read is what "it" and "that" mean.
    read_list = _list_just_read() if re.search(r"\b(?:it|that|there|one|ones|how many)\b", low) else None
    if read_list:
        items = [i.strip() for i in re.split(r", | and ", read_list.group("items")) if i.strip()]
        name = read_list.group("name")
        if re.fullmatch(r"how many (?:things |items )?(?:is that|was that|are there|are on (?:it|there|that)|is it)", low):
            return {"command": None, "say": f"{read_list.group('n')}."}
        m = re.fullmatch(r"(?:is|are) (?:there )?(?:any |some )?(?P<x>[a-z0-9][a-z0-9 '&-]{1,40}?) on (?:it|there|that(?: list)?)", low)
        if m:
            x = m.group("x")
            hit = next((i for i in items if i.casefold() == x or re.sub(r"^(?:a|an|the|some) ", "", i.casefold()) == x), None)
            return {"command": None, "say": f"Yes - {hit} is on it." if hit else f"No, {x} isn't on it."}
        m = re.fullmatch(r"(?:take|cross|tick|check|knock) (?P<w>(?:the )?\w+(?: one)?) off(?: (?:it|the list|that list))?"
                         r"|(?:remove|delete|drop|scratch) (?P<w2>(?:the )?\w+(?: one)?)(?: from (?:it|the list|that list))?", low)
        where = speech.ordinal_index(m.group("w") or m.group("w2")) if m else None
        if where is not None and name and -len(items) <= where < len(items):
            item = items[where]
            if name in ("shopping", "grocery"):
                return {"command": {"kind": "shopping_off", "item": item}, "say": None}
            return {"command": {"kind": "list_off", "list": name, "item": item}, "say": None}
    # "WHAT CHORES DO I HAVE" (2026-10-07: "I have nothing about chores on
    # file" beside a task list). With no list called chores, his chores are
    # his tasks.
    if re.fullmatch(r"what (?:chores|jobs|house ?work|housework) (?:do i have|have i got|are there|need doing)(?: to do)?(?: today| this week)?"
                    r"|what(?:'s| is| are)? (?:on )?my chores?(?: list)?(?: today| this week)?|what are my chores(?: today| this week)?", low):
        try:
            from aletheia import lists as _lists
            has = [held["name"] for held in _lists.all_lists() if re.fullmatch(r"chores?(?: list)?", str(held.get("name") or "").casefold())]
        except Exception:  # noqa: BLE001
            has = []
        if has:
            return {"command": {"kind": "list_read", "list": has[0]}, "say": None}
        return {"command": {"kind": "tasks"}, "say": None}
    named = _named_list_said(low, text)
    if named:
        return named
    # "What do I still need to do today", "what's left to do" (2026-10-08:
    # to a model). His tasks.
    if re.fullmatch(r"what (?:else |still )?do i (?:still )?(?:need|have|got) to (?:do|get done)(?: still)? (?:today|tonight|this morning|this afternoon)"
                    r"|what(?:'s| is|s)? (?:left|still left|remaining|left over) (?:for me )?to (?:do|get done)(?: today| tonight)?"
                    r"|what else (?:do i (?:need|have) to|should i) do(?: today| tonight)?", low):
        return {"command": {"kind": "tasks"}, "say": None}
    # "I'm at the store", then "what do I need" (2026-10-08: to a model).
    # Bare, it is whichever list the last turns were about.
    if re.fullmatch(r"what (?:else )?do i (?:still )?need(?: to (?:do|get))?", low):
        # "...need TO DO" is his tasks whatever came before (2026-10-08: it
        # read the shopping list a turn after a birthday card went on it).
        return {"command": {"kind": "shopping_list" if not low.endswith("to do") and (_in_a_shopping_turns() or low.endswith("get"))
                            else "tasks"}, "say": None}
    # "I left the stove on" (2026-10-08: to the planner). Nothing of hers
    # reaches it; the honest answer is what would.
    m = re.fullmatch(r"i (?:think i |might have |may have )?left (?:the |my )?(?P<thing>stove|oven|iron|hair straightener|straightener"
                     r"|curling iron|space heater|heater|burner|grill|water|tap|faucet|bath)(?: running)? on", low)
    if m:
        return {"command": None,
                "say": f"I can't reach your {m.group('thing')} from here. If nobody's home, call someone nearby who can check it."}
    # "I picked up the dry cleaning" ("Done: ..."), then "what's left on my
    # list" read the empty SHOPPING list (2026-10-08). "My list" with no
    # kind is the one the last turns were about; tasks unless shopping.
    if re.fullmatch(r"what'?s? ?(?:is )?(?:left|still|remaining) on (?:my|the) list", low) and not _in_a_shopping_turns():
        return {"command": {"kind": "tasks"}, "say": None}
    if re.fullmatch(r"(what'?s?( is)? on )?(my |the )?(shopping|grocery) list"
                    r"|how many (things|items) (are )?on (my |the )?(shopping |grocery )?list"
                    r"|what do i need (to buy|from the (shop|store|grocery store))"
                    r"|read (me )?(my |the )?(shopping|grocery) list"
                    # "What's on the grocery list" (2026-10-07: to a model).
                    r"|(show me|what'?s in|check) (my |the )?(shopping|grocery) list"
                    # "What's left on my shopping list" (2026-10-07: to a model).
                    r"|what'?s? ?(is )?(left|still|remaining) on (my |the )?(shopping |grocery )?list"
                    r"|what (else )?do i (still )?need (to (get|buy)|from the (shop|store|grocery store))", low):
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

    # "Add 2 pounds of chicken" (2026-10-08: to the planner): an amount of a
    # thing, with no list named, is the shopping list - the amount kept.
    m = re.fullmatch(r"add (?P<item>(?:a|an|one|two|three|four|five|six|a few|a couple(?: of)?|\d+(?:\.\d+)?|half a)"
                     r" (?:pounds?|lbs?|kilos?|kg|cans?|bags?|boxes?|bottles?|dozen|gallons?|packs?|packages?|loaves|loaf|jars?"
                     r"|cartons?|bunch(?:es)?|heads?|sticks?|rolls?|cases?|liters?|litres?|ounces?|oz)"
                     r"(?: of)? [a-z][a-z' -]{1,30})", low)
    if m and not re.search(r"\b(?:to|on|for|from|into|task|reminder|note|calendar)\b", m.group("item")):
        return {"command": {"kind": "shopping_add", "item": _as_he_said(text, m.group("item"))}, "say": None}
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

    # "I want to read more books", "I'm trying to drink more water"
    # (2026-10-08: to the planner). A habit he wants is a goal, kept in the
    # words "my goal is" so "what are my goals" reads it back.
    # "I practiced Spanish for 20 minutes" (2026-10-08: to the planner) is
    # kept for "how long did I practice Spanish this week".
    if re.fullmatch(r"i (?:just )?(?:practi[cs]ed|studied|played|read|stretched|meditated|walked|cleaned|worked on) (?:my |some |the )?[a-z][a-z' ]{1,25}?"
                    r" for (?:about |around )?(?:\d+(?:\.\d+)?|an?|half an) (?:minutes?|mins?|hours?|hrs?)(?: today| this morning| tonight)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I want to run a marathon" (2026-10-08: to the planner) is a goal.
    m = re.fullmatch(r"i (?:really )?(?:want|wanna|would like|'d like|hope|plan|'m going|am going|'m trying|am trying) to "
                     r"(?P<g>(?:run a (?:marathon|half marathon|5k|10k|half)"
                     r"|quit (?:smoking|vaping|drinking|caffeine|sugar|soda)|stop (?:smoking|vaping|drinking|biting my nails)"
                     r"|visit (?:japan|italy|europe|paris|london|[a-z]{3,15})|travel (?:more|to [a-z ]{3,20})|write a book|get in shape"
                     r"|get my (?:degree|license|black belt|certification)|finish my (?:degree|book|thesis))(?: (?:this|next) year| by [a-z0-9 ]{3,20})?)", low)
    if m and "?" not in text:
        goal = _as_he_said(text, m.group("g"))
        return {"command": {"kind": "note", "text": "My goal is to " + goal},
                "say": f"Good one. I've kept it with your goals: {goal}."}
    m = re.fullmatch(r"i (?:really )?(?:want|wanna|would like|'d like|need|'m trying|am trying|'m going|am going) to "
                     r"(?P<g>(?:read|exercise|work out|drink|sleep|eat|walk|run|save|spend|meditate|cook|stretch|study|practice"
                     r"|go to bed|get up|wake up|go outside|get outside|call my|be|get|stay|spend less time|spend more time)"
                     r" [a-z0-9 ',-]{0,60}?\b(?:more|less|better|healthier|in shape|fit|earlier|on time|every day|each day"
                     r"|daily|regularly|every morning|every night|this year|this month)(?: [a-z ]{1,30})?)", low)
    if m and "?" not in text and not re.search(r"\b(?:you|your|thea)\b", m.group("g")):
        goal = _as_he_said(text, m.group("g"))
        return {"command": {"kind": "note", "text": "My goal is to " + goal},
                "say": f"Good one. I've kept it with your goals: {goal}."}
    # "I should start going to bed earlier", "I'm trying to cut back on
    # coffee", "my resolution is to drink less soda" (2026-10-08: a task,
    # the planner, and a plain note "what are my resolutions" never read).
    m = re.fullmatch(r"i (?:really )?(?:should|need to|have to|gotta|want to) (?P<g>(?:start|stop|quit) [a-z]+ing\b[a-z0-9 ',-]{0,40})", low) \
        or re.fullmatch(r"i(?:'m| am) (?:really )?trying to (?P<g>(?:cut back on|cut down on|cut out|give up|quit|lose|eat less|eat more|limit|stop|drink less|drink more)"
                        r" [a-z0-9 ',-]{2,40})", low) \
        or re.fullmatch(r"my (?:new year'?s? |new years )?resolutions? (?:is|are|for this year is|this year is) to (?P<g>[a-z0-9 ',-]{3,60})", low)
    if m and "?" not in text and not re.search(r"\b(?:you|your|thea|the car|it|that)\b", m.group("g")):
        goal = _as_he_said(text, m.group("g"))
        return {"command": {"kind": "note", "text": "My goal is to " + goal},
                "say": f"Good one. I've kept it with your goals: {goal}."}
    # "My dream car is a Porsche 911", "I'm saving up for a new couch", "I
    # usually leave my keys on the hook" (2026-10-08: all to the planner).
    if re.fullmatch(r"my dream (?:car|house|home|job|vacation|trip|destination|bike|truck|guitar|watch|city|career) is (?:a |an |the |to )?[a-z0-9][a-z0-9 .'&-]{1,40}", low) \
            or re.fullmatch(r"(?:i(?:'m| am)|we(?:'re| are)) saving (?:up )?(?:money )?for (?:a |an |the |our |my )?(?!it\b|that\b)[a-z][a-z0-9 '-]{2,40}", low) \
            or re.fullmatch(r"i (?:usually|always|normally) (?:leave|keep|put|hang) my (?:[a-z]+ ){0,2}(?:keys|wallet|glasses|sunglasses|phone|badge|bag|purse|charger|headphones|earbuds|umbrella|jacket|coat|shoes|passport|remote)"
                            r" (?:on|in|by|at|under|next to|behind) (?:the |my )?[a-z][a-z ]{1,30}", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    m = re.fullmatch(r"i (?:always|keep|constantly|am always|'m always) (?:lose|losing|misplace|misplacing|forget where i put|forgetting where i put) my (?P<thing>[a-z][a-z ]{1,20})", low)
    if m:
        thing = m.group("thing")
        return {"command": None, "say": f"I can help with that. Say \"I put my {thing} on the hook\" (or wherever) when you set them down, "
                                        f"or \"I usually leave my {thing}\" and where, and \"where are my {thing}\" will find them."}
    # "I want to watch Oppenheimer", "I want to read Dune", "I'm reading
    # Project Hail Mary" (2026-10-08: to the planner, and "I'm reading" to a
    # model). A title goes on his watch or reading list; what he is reading
    # is a note, which "what am I reading" reads.
    m = re.fullmatch(r"i (?:really )?(?:want|wanna|would like|'d like|need) to (?P<v>watch|see|read) (?P<t>[a-z0-9].{1,60}?)"
                     r"(?: (?:sometime|someday|soon|at some point|one day|eventually|next|after this(?: one)?|after that))?", low)
    if m and not re.match(r"(?:a|an|some|something|anything|more|less|it|that|this|them|tv|television|the news|the game"
                          r"|the match|a movie|a show|youtube|netflix|my|your|his|her|their|what|how|if|whether|you|him)\b", m.group("t")) \
            and not re.search(r"\b(?:tonight|today|tomorrow|later|now|this weekend|with (?:you|me))$", m.group("t")):
        listed = "reading" if m.group("v") == "read" else "watch"
        return {"command": {"kind": "list_add", "list": listed, "item": _as_he_said(text, m.group("t"))}, "say": None}
    # "I started a new book called Dune", "I just started reading Dune"
    # (2026-10-08: to the planner) - the same note as "I'm reading Dune".
    m = re.fullmatch(r"i (?:just )?(?:started|began|picked up|am starting|'m starting) (?:reading |(?:a |the )?(?:new )?book (?:called |named )?)"
                     r"(?P<t>[a-z0-9].{1,60})", low) or re.fullmatch(r"(?:i'?m|i am) (?:currently |now |still )?reading (?P<t>[a-z0-9].{1,60})", low)
    if m and not re.match(r"(?:it|that|this|them|a |an |some|the news|my |your |about |up on |through |over )", m.group("t")) \
            and "?" not in text:
        return {"command": {"kind": "note", "text": "I'm reading " + _as_he_said(text, m.group("t"))},
                "say": "Noted. Ask me \"what am I reading\" and I'll tell you."}
    # "I started a new show called Severance", "I'm watching The Bear",
    # "I'm on episode 4 of Severance", "I rated Severance 9 out of 10"
    # (2026-10-08: to the planner). A title said with its capital.
    m = re.fullmatch(r"i (?:just )?(?:started|began|am starting|'m starting) (?:watching |(?:a |the )?(?:new )?(?:show|series|tv show) (?:called |named )?)"
                     r"(?P<t>[a-z0-9].{1,60})", low) or re.fullmatch(r"(?:i'?m|i am) (?:currently |now |still )?watching (?P<t>[a-z0-9].{1,60})", low)
    if m and "?" not in text and _said_as_a_title(text, m.group("t")) \
            and not re.match(r"(?:it|that|this|them|tv|the news|the game|the kids|the dog|you|my |your |a |an |some|out )", m.group("t")) \
            and not re.match(r"[a-z]{2,15}(?:'s|s)? (?:house|place|apartment|dog|dogs|cat|cats|kids|pets|plants|baby)\b", m.group("t")):
        return {"command": {"kind": "note", "text": "I'm watching " + _as_he_said(text, m.group("t"))},
                "say": "Noted. Ask me \"what am I watching\" and I'll tell you."}
    # "I'm on page 200 of Dune", "I'm on chapter 3 of Dune" (2026-10-08: to a model).
    m = re.fullmatch(r"(?:i'?m|i am) (?:on|up to|at) (?P<ep>(?:season \d{1,2},? )?episode \d{1,3}|season \d{1,2}|page \d{1,4}|chapter \d{1,3})"
                     r" (?:of|in) (?P<t>[a-z0-9].{1,60})", low)
    if m and "?" not in text:
        return {"command": {"kind": "note", "text": f"I'm on {m.group('ep')} of {_as_he_said(text, m.group('t'))}"}, "say": None}
    m = re.fullmatch(r"i (?:rated|gave|would give|'d give) (?P<t>[a-z0-9].{1,50}?) (?:a )?(?P<n>\d{1,2}(?:\.\d)?(?: out of (?:5|10|100)| stars?|/(?:5|10)))", low)
    if m and "?" not in text and _said_as_a_title(text, m.group("t")):
        return {"command": {"kind": "note", "text": f"I rated {_as_he_said(text, m.group('t'))} {m.group('n')}"}, "say": None}
    if re.fullmatch(r"what (?:movies|shows|films|tv shows|things|stuff) (?:do|did) i (?:want|say i wanted) to (?:watch|see)\s*\??", low):
        return {"command": {"kind": "list_read", "list": "watch"}, "say": None}
    if re.fullmatch(r"what books? (?:do|did) i (?:want|say i wanted) to read\s*\??", low):
        return {"command": {"kind": "list_read", "list": "reading"}, "say": None}

    # "I'm going on vacation to Hawaii December 10 to 17", "my vacation is
    # December 10 to 17", "I'm flying out at 7am on December 10" (2026-10-08:
    # to the planner). Kept in his words; "when is my vacation", "how long
    # is my vacation" and "what time is my flight" read them.
    _range_day = r"(?:" + _MONTH + r"\.? \d{1,2}(?:st|nd|rd|th)?|\d{1,2}(?:st|nd|rd|th)?(?: of " + _MONTH + r")?)"
    if re.fullmatch(r"(?:(?:i'?m|i am|we'?re|we are) (?:going|heading|off) on (?:a |our |my )?(?:vacation|holiday|trip|cruise|honeymoon)"
                    r"|(?:my|our) (?:vacation|holiday|trip|cruise|honeymoon) is)"
                    r"(?: (?:to|in) [a-z][a-z .'-]{1,30}?)? (?:from )?" + _range_day
                    + r"(?:,? \d{4})?(?: (?:to|through|thru|until|till|-) " + _range_day + r")?", low) \
            or re.fullmatch(r"(?:i'?m|i am|we'?re|we are) (?:flying|leaving|heading) (?:out|off|home|back)(?: to [a-z][a-z .'-]{1,30}?)?"
                            r" (?:at \d{1,2}(?::\d\d)? ?(?:am|pm)? )?(?:on )?" + _range_day
                            + r"(?: at \d{1,2}(?::\d\d)? ?(?:am|pm)?)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    if re.fullmatch(r"what (?:do|should) i (?:need to |have to )?pack(?: for (?:my |the |our )?(?:trip|vacation|holiday))?\s*\??", low):
        return {"command": {"kind": "list_read", "list": "packing"}, "say": None}

    # "I keep forgetting to drink water", "I might go to the gym later"
    # (2026-10-08: to the planner): the one sentence that would help.
    m = re.fullmatch(r"i (?:keep|always) forget(?:ting)? to (?P<do>[a-z][a-z0-9' ]{2,40})", low)
    if m:
        do = _as_he_said(text, m.group("do"))
        return {"command": None, "say": f"I can nudge you. Say \"remind me every 2 hours to {do}\" or "
                                        f"\"remind me every day at 9 to {do}\", and I'll keep at it."}
    m = re.fullmatch(r"i (?:might|may|could|will probably) (?P<do>go to the gym|go for a (?:run|walk|swim|ride)|work out|go shopping"
                     r"|go to the store|go out|head out)(?: later| tonight| today| this afternoon| this evening)?", low)
    if m:
        do = _as_he_said(text, m.group("do"))
        return {"command": None, "say": f"Want a nudge? Say \"remind me at 5 to {do}\" with the time you want."}
    # "I pay 15 a month for Netflix" (2026-10-08: refused at the money door
    # as an order to spend). It is what he already pays - a fact, kept the
    # way "my Netflix is 15 a month" is, which the bill readers read. Only a
    # bill they know, and only with how often: nothing here buys anything.
    m = re.fullmatch(r"(?:i|we) (?:pay|spend) \$?(?P<amt>\d[\d,]*(?:\.\d\d)?)(?: dollars| bucks)? (?P<per>a|per|each|every) "
                     r"(?P<unit>month|year|week) (?:for|on) (?:my |our |the )?(?P<what>[a-z][a-z +']{1,30})", low)
    if m:
        from aletheia import quick
        if re.fullmatch(quick._BILL_KEYS, m.group("what").strip()):
            per = "a" if m.group("per") in ("a", "per", "each", "every") else m.group("per")
            what = _as_he_said(text, m.group("what").strip())
            return {"command": {"kind": "note", "text": f"my {what} is {m.group('amt')} {per} {m.group('unit')}"},
                    "say": None}
    # "I need gas", "I need a nap", "I need to lose weight" (2026-10-08: all
    # to the planner). Gas is an errand; the other two are his, said kindly
    # with the one thing she can do about each.
    # "I need a passport photo" (2026-10-08: on the shopping list) is an
    # errand, not shopping.
    m = re.fullmatch(r"i (?:need|have to get|gotta get|need to get) (?:a |an |my |new )?(?P<w>passport photos?|new passport|passport renewed|visa|background check"
                     r"|fingerprints taken|eye exam|physical|vaccine|flu shot|blood test|blood work|x-ray)", low)
    if m:
        return _new_task(f"get {'a ' if m.group('w') in ('passport photo', 'visa', 'background check', 'eye exam', 'physical', 'vaccine', 'flu shot', 'blood test', 'x-ray') else ''}{m.group('w')}")
    # "I need new tires" (2026-10-08: on the shopping list). Car work is
    # done at a shop, so it is a job on his list, not a thing to pick up.
    m = re.fullmatch(r"(?:i|we) (?:need|gotta get|need to get|have to get|should get) (?:a |an |some |new )*"
                     r"(?P<job>tires|tyres|brakes|brake pads|an? alignment|alignment|an? tune[- ]up|tune[- ]up|an? inspection"
                     r"|inspection|an? emissions test|emissions test|an? smog check|smog check|tire rotation|a tire rotation"
                     r"|new battery|a new battery|car battery|an? car wash|car wash)(?: on (?:my|the) car)?", low)
    if m:
        job = re.sub(r"^(?:an?|new) ", "", m.group("job")).replace("tune up", "tune-up")
        said = {"tires": "new tires", "tyres": "new tyres", "brakes": "new brakes", "brake pads": "new brake pads",
                "inspection": "the car inspected", "car battery": "a new car battery", "battery": "a new car battery",
                "car wash": "a car wash"}.get(job, ("an " if job[0] in "aeiou" else "a ") + job)
        return _new_task("get " + said + ("" if "car" in said else " for the car"))
    if re.fullmatch(r"(?:i|we) (?:need|gotta get|need to get|have to get|should get) (?:some )?(?:gas|fuel|petrol|diesel)"
                    r"(?: in the car| for the car)?", low):
        return _new_task("get gas")
    if re.fullmatch(r"i (?:really )?need (?:a nap|to nap|a rest|some rest|to rest|a break|some sleep|to lie down)", low):
        return {"command": None,
                "say": "Go for it. Say \"set a timer for 20 minutes\" and I'll wake you."}
    if re.fullmatch(r"i (?:really )?(?:need|want|have) to (?:lose|drop) (?:some )?weight", low):
        return {"command": None,
                "say": "Tell me what you weigh - \"I weigh 190\" - and your goal - \"my goal weight is 175\" - "
                       "and I'll keep track of how it's going."}
    # "The dog needs to go to the vet", "my dog is due for shots in
    # November" (2026-10-08: both to the planner). A trip is a job on his
    # list; a when is kept, and "when are the dog's shots due" reads it.
    m = re.fullmatch(r"(?:my|our|the) (?P<pet>dog|cat|puppy|kitten|pup|pet) (?:needs to go|has to go|should go|needs to get) to the "
                     r"(?P<where>vet|groomer|groomers|kennel)", low)
    if m:
        return _new_task(f"take the {m.group('pet')} to the {m.group('where').rstrip('s')}")
    if re.fullmatch(r"(?:my|our|the) (?:dog|cat|puppy|kitten|pup|pet)(?:'s)? (?:is due for|needs|will need|shots are due|vaccines are due)"
                    r"(?: (?:its|his|her|their|a|an|the))?(?: [a-z ]{2,30}?)? (?:in|on|by|next) [a-z0-9 ]{2,20}", low) \
            and not low.endswith("?"):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "My car needs an oil change at 45000 miles" (2026-10-08: to the
    # planner). Kept; "when does my car need an oil change" reads it.
    if re.fullmatch(r"(?:my|our|the) (?:car|truck|van|suv|bike|motorcycle|furnace|ac|a/c|water heater|lawn mower|mower)"
                    r" (?:needs|is due for|will need) (?:an? |its |new )?[a-z0-9 ,'-]{3,60}", low) \
            and re.search(r"\d", low) and not low.endswith("?"):
        # Only with a when ("at 45000 miles", "in 2027"): "my car needs an
        # oil change" alone is a job, and the task rule below has it.
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I'm out of my medicine" (2026-10-08: to the planner; "my" kept it off
    # the shopping list). A prescription is refilled, not bought off a list.
    m = re.fullmatch(r"(?:we(?:'re| are)|i(?:'m| am)|im) (?:all |almost |nearly |running )?(?:out of|low on) (?:my |the )?"
                     r"(?P<rx>medicine|medication|meds|pills|prescription|inhaler|insulin|blood pressure (?:pills|meds|medicine)"
                     r"|[a-z]+ (?:pills|meds|tablets)|contacts|contact lenses)", low)
    if m:
        return _new_task(f"refill my {m.group('rx')}")
    # "I have 10 pills left", "I take 2 a day" (2026-10-08: to the planner).
    # Kept; "how many pills do I have left" and "when will I run out" read them.
    if re.fullmatch(r"i(?:'ve| have)(?: got)? (?:about |only |just )?\d{1,3} (?:pills|tablets|capsules|doses)(?: of (?:my )?[a-z ]{2,30})? left", low) \
            or re.fullmatch(r"i take (?:\d|one|two|three|four) (?:pills?|tablets?|capsules?|doses?)?(?: of (?:it|them|my [a-z ]{2,30}))? ?(?:a|per|each|every) day", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}

    # "WE'RE OUT OF COFFEE", "we need paper towels", "I need to buy
    # batteries": a thing to buy, said as a need (2026-10-07: the planner,
    # and the last one refused as SPENDING). It goes on the list; buying
    # it stays his. Anything that starts with a verb is not a thing.
    m = (re.fullmatch(r"(?:we(?:'re| are)|i(?:'m| am)) (?:all )?out of (?:the |some )?(?P<item>[a-z][a-z '-]{1,40})", low)
         # "I ran out of coffee" (2026-10-08: to the planner)
         or re.fullmatch(r"(?:i|we) (?:just |totally |completely )?(?:ran|run) out of (?:the |our |my |some )?(?P<item>[a-z][a-z '-]{1,40})", low)
         # "I used the last of the milk" (2026-10-08: to the planner)
         or re.fullmatch(r"(?:i|we) (?:just )?(?:used|finished|ate|drank|had) (?:up )?the last of (?:the |our |my )?(?P<item>[a-z][a-z '-]{1,40})", low)
         or re.fullmatch(r"(?:we|i) need (?:to (?:buy|get|pick up) )?(?:more |some |a new |new |a |an )?(?P<item>[a-z][a-z '-]{1,40})", low)
         or re.fullmatch(r"(?:we(?:'re| are)|i(?:'m| am)) (?:running )?(?:low on|almost out of) (?:the )?(?P<item>[a-z][a-z '-]{1,40})", low)
         # "The cat food is running low" (2026-10-08: to the planner).
         or re.fullmatch(r"(?:the |our |my )(?P<item>(?!(?:phone|battery|batteries|gas|tank|tires?|signal|data|storage|money|time|budget|balance"
                         r"|funds|account|savings|patience|water pressure|oil|car|laptop|tablet)\b)[a-z][a-z '-]{1,30}?) (?:is|are) (?:running low|getting low|almost gone|almost out|running out)", low))
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
    # "A new phone charger" is a thing, though "phone" can be a verb (2026-10-08)
    # "I need a new phone" (2026-10-08: to the planner) is a phone.
    if m and not (_TASK_VERB.match(m.group("item")) and not re.match(
            r"(?:phone|ring)$|(?:phone|ring|text|paint|file|water|wash|clean|print) (?:charger|case|cable|cord|stand|mount|holder|screen protector"
            r"|light|book|books|brush|brushes|folder|folders|bottle|bottles|filter|cloth|wipes|supplies|paper|cartridge|ink)s?\b", m.group("item"))) \
            and not re.match(r"(?:to|break|help|you|time|rest|sleep|nap|money|cash|job|minute|second|hand|hug|"
                             r"vacation|holiday|day off|shower|ride|lift|doctor|dentist|lawyer|therapist|advice|"
                             r"idea|ideas|plan|answer|answers|space|quiet|coffee break|drink|win|friend|friends|"
                             r"date|haircut|change|reminder|timer|alarm|it|that|this|them|him|her"
                             # "I need motivation" went on the SHOPPING list (2026-10-07).
                             r"|motivation|inspiration|encouragement|support|focus|energy|peace|patience|confidence|courage"
                             r"|luck|love|attention|clarity|closure|sunshine|exercise|therapy|fresh air|a walk|walk|nap"
                             r"|more time|more sleep|a minute|a moment|a sec|a second|a day|a week|a drink|a raise|raise"
                             r"|a new job|new job|a job|work|motivating|cheering up|to vent|someone|somebody|company"
                             r"|out|in|food|to eat|to sleep|to rest|to relax|relaxation|a vacation"
                             # "I need to get an oil change", "...my hair cut" went on the
                             # SHOPPING list (2026-10-07): a service, or a thing of his, is
                             # an errand.
                             r"|my|our|oil change|tune-?up|car wash|check-?up|physical|flu shot|vaccine|shots?|massage"
                             r"|manicure|pedicure|tattoo|blood test|blood work|x-?ray|eye exam|inspection|appointment"
                             # "I need to get gas" (2026-10-08: the shopping list) is a stop on the way.
                             r"|gas|fuel|petrol|diesel"
                             # "I need a filling" (2026-10-08: the shopping list) is the dentist.
                             r"|filling|root canal|crown|tooth pulled|wisdom teeth|teeth whitened|x-?rays?|prescription"
                             r"|prescription refill|refill|hearing test|allergy test"
                             # "I need a dog sitter" (2026-10-08: the shopping list) is a person to find.
                             r"|(?:dog |pet |cat |house |baby ?)?sitter|babysitter|dog walker|nanny|plumber|electrician|handyman"
                             r"|bloodwork|labs?|lab work"
                             # "I need to get a passport" (2026-10-08: the shopping list) is paperwork.
                             r"|passport|visa|driver'?s license|license|licence|real id|id card|permit|birth certificate"
                             r"|social security card|marriage license|title|registration|insurance card)\b", m.group("item")) \
            and not re.search(r"\b(?:done|cleaned|fixed|repaired|checked|changed|replaced|serviced|inspected|washed|installed"
                              # "I need to get the gutters cleaned" (2026-10-08: the
                              # shopping list, as "the gutters cleaned") is a job.
                              r"|painted|removed|looked at|tested|pumped|trimmed|sharpened|tuned|refilled|renewed|signed|notarized"
                              # "We need to get the guest room ready" (2026-10-08: the
                              # shopping list, as "the guest room ready").
                              r"|ready|set up|organi[sz]ed|sorted|packed|wrapped|ready for [a-z ]{2,20})$", m.group("item")):
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
    # "Forget the last thing I told you" (2026-10-08) looked for a note
    # ABOUT "the last thing i told you". It is the newest note.
    if re.fullmatch(r"(?:forget|delete|erase|scratch) (?:the last thing|what) i (?:just )?(?:told you|said)"
                    r"(?: to remember)?|forget what i just told you", low):
        from aletheia import quick as _quick
        rows = _quick._notes(1)
        if not rows:
            return {"command": None, "say": "You haven't told me anything to forget."}
        return {"command": {"kind": "forget", "about": str(rows[0].get("text") or "")}, "say": None}
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
                    # "What did I ask you to remind me about" (2026-10-07: to a model).
                    r"|what (?:did|have) i (?:ask|asked|told|tell) you to remind me (?:of|about|to do)"
                    r"|what (?:are|were) you (?:going to|gonna|supposed to) remind me (?:of|about)"
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
                    # "What recurring reminders do I have" (2026-10-08: read as a thing he owns).
                    r"|what (?:recurring|repeating|regular) reminders (?:do i have|have i (?:got|set))(?: set)?"
                    # "How many reminders do I have" (2026-10-07: to a model)
                    r"|how many (?:reminders|alarms|timers) (?:do i have|have i got|are (?:there|set|running))(?: set| running| on)?", low):
        # "What alarms do I have" was answered "2 reminders: wake up -
        # tomorrow at 6:30 am and wake up - ...": asked about alarms, it
        # says alarms.
        if re.search(r"\balarms?\b", low) and not re.search(r"\b(?:reminders?|timers?)\b", low):
            return {"command": {"kind": "reminders", "which": "wake up"}, "say": None}
        if re.search(r"\b(?:recurring|repeating|regular)\b", low):
            return {"command": {"kind": "reminders", "which": "recurring"}, "say": None}
        return {"command": {"kind": "reminders"}, "say": None}
    # "Stop the timer" (2026-10-07: to the planner). A timer is a reminder
    # whose words end "timer is up"; two running are asked about by name.
    if re.fullmatch(r"(?:cancel|stop|delete|turn off|remove|kill|end|clear) (?:the |my |that |this )?timers?", low):
        return {"command": {"kind": "reminder_off", "which": "timer is up"}, "say": None}
    # "Cancel the pasta timer" fell through to the planner (2026-10-07):
    # a named timer is the reminder whose words end "<name> timer is up".
    m = re.fullmatch(r"(?:cancel|stop|delete|turn off|remove|kill|end|clear) (?:the |my |that )?"
                     r"([a-z][a-z ]{0,20}?) timer", low)
    if m and m.group(1) not in ("the", "my", "that", "this", "a"):
        return {"command": {"kind": "reminder_off", "which": f"{m.group(1)} timer is up"}, "say": None}
    # A focus session is a named timer (2026-10-07: "start a focus session",
    # "help me focus" and "end the focus session" all reached the planner).
    m = re.fullmatch(r"(?:start|begin|do|let'?s do|set up) (?:a |an |my )?(?:focus|pomodoro|deep work|work) "
                     r"(?:session|block|timer|sprint)(?: for (\d{1,3}) (?:minutes?|mins?))?"
                     r"|(?:help me focus|i need to focus|i want to focus|pomodoro)(?: for (\d{1,3}) (?:minutes?|mins?))?"
                     r"|(?:i need to focus|i want to focus|help me focus|start a focus session) for (?:(\d) hours?|an? (hour)|(half) an hour)", low)
    if m:
        n = (m.group(1) or m.group(2) or (str(int(m.group(3)) * 60) if m.group(3) else None)
             or ("60" if m.group(4) else None) or ("30" if m.group(5) else None) or "25")
        return _interpret(f"set a timer for focus for {n} minutes")
    # "Start a 25 minute pomodoro", "take a 5 minute break" (2026-10-08:
    # both to the planner): the length said first, and a break is a timer.
    m = re.fullmatch(r"(?:start|begin|do|set|let'?s do|set up) (?:a |an )?(\d{1,3})[ -]?(?:minutes?|mins?) (?:focus|pomodoro|deep work|work)"
                     r"(?: (?:session|block|timer|sprint))?", low)
    if m:
        return _interpret(f"set a timer for focus for {m.group(1)} minutes")
    m = re.fullmatch(r"(?:(?:i'?m |i am |let'?s |let me )?(?:take|taking|have|having) (?:a |an )(\d{1,3})[ -]?(?:minutes?|mins?) break"
                     r"|(?:i'?m |i am )?(?:going on |taking )?(?:a )?break for (\d{1,3}) (?:minutes?|mins?))", low)
    if m:
        return _interpret(f"set a timer for the break for {m.group(1) or m.group(2)} minutes")
    if re.fullmatch(r"(?:end|stop|cancel|finish|quit|kill) (?:the |my |this )?(?:focus|pomodoro|deep work) "
                    r"(?:session|block|timer|sprint)|i'?m done focusing", low):
        return {"command": {"kind": "reminder_off", "which": "focus timer is up"}, "say": None}
    if re.fullmatch(r"how (?:long|much time)(?: is)?(?: left| remaining)?(?: have i been focusing| in (?:my|the|this) "
                    r"(?:focus|pomodoro) (?:session|block)| on (?:my|the) focus(?: session)?)", low):
        said = _timer_left(named="focus")
        return {"command": None, "say": "No focus session is running." if said.startswith("You don't have") else said}
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
                             r"(?:(?:weekday|weekend|daily|morning|everyday|work|school|wake ?up) )?alarms?(?: (?:for|at) (?:tomorrow|the morning|(?P<after>[\w: ]+)))?", low)
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

    # "Add mom's birthday June 3", "save Sam's birthday as May 2" (2026-10-07:
    # to the planner) - the same fact as "mom's birthday is June 3".
    m = re.fullmatch(r"(?:add|save|put|remember|note|put down|write down) (?P<who>(?:my )?[a-z][a-z' ]{1,30}?)'s birthday"
                     r"(?: (?:is|as|on|for|to))? (?P<date>(?:the )?(?:\d|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec).{0,30})", low)
    if m:
        got = _interpret(f"{_as_he_said(text, m.group('who'))}'s birthday is {_as_he_said(text, m.group('date'))}")
        if ((got or {}).get("command") or {}).get("kind") in ("note", "remember"):
            return got

    # "Remind me on my birthday to celebrate" (2026-10-07: to the planner):
    # the date is on file, so it is a reminder on that date.
    m = re.fullmatch(r"remind me (?:on|for) my (?:next )?birthday (?P<rest>(?:at [\w: ]+ )?(?:to|that|about) .+)", low)
    if m:
        try:
            from aletheia import quick
            held = quick._birthday_on_file()
        except Exception:  # noqa: BLE001
            held = None
        if not held:
            return {"command": None, "say": "I don't have your birthday. Say \"my birthday is March 3rd\" and then ask again."}
        import datetime as dt
        month = dt.date(2000, held[0], 1).strftime("%B").lower()
        got = _interpret(f"remind me on {month} {held[1]} {_as_he_said(text, m.group('rest'))}")
        if str(((got or {}).get("command") or {}).get("kind", "")).startswith("remind_"):
            return got

    # "Alarm at 7", "7am alarm", "alarm for 6:30 tomorrow" (2026-10-07: to
    # the planner) - the bare noun with a time is "set an alarm for" it.
    m = re.fullmatch(r"(?:an? )?alarm (?:at|for) (?P<t>.+)|(?:an? )?(?P<t2>\d{1,2}(?::\d\d)?\s*(?:am|pm|a\.m\.|p\.m\.)?)"
                     r" alarm(?P<when> tomorrow| today| tonight)?", low)
    if m:
        got = _interpret(f"set an alarm for {m.group('t') or (m.group('t2') + (m.group('when') or ''))}")
        if str(((got or {}).get("command") or {}).get("kind", "")).startswith("remind_"):
            return got
    if re.fullmatch(r"turn (?:my |the )?alarms? (?:back )?on|turn on (?:my |the )?alarms?", low):
        return {"command": {"kind": "reminder_on", "which": "all alarms"}, "say": None}

    # THE REMINDER HE JUST SET (2026-10-07: all three to the planner):
    # "what time is that reminder", "remind me to text dad too" (the same
    # time), and "change call mom to call grandma" (the same time, new words).
    just = _the_reminder_just_set() if re.search(r"\breminder\b|\b(?:too|as well|also)$|^(?:no,? |actually,? )?(?:change|make) "
                                                 r"|\bset for$|\bgo off$", low) else None
    if just:
        at = str(just.get("at") or "")
        words = str((just.get("command") or {}).get("text") or "")
        if re.fullmatch(r"(?:what time is|when is|when's) (?:that|the|my|this) reminder(?: set)?(?: for)?"
                        r"|(?:what time|when) (?:did you set|is) (?:it|that) (?:set )?for|when does (?:it|that) go off", low):
            return {"command": None, "say": f"That's {speech.humanize_time(at)}: {words}."}
        m = re.fullmatch(r"(?:and )?(?:also )?remind me to (?P<what>.+?) (?:too|as well|also)", low)
        if m and at:
            return {"command": {"kind": "remind_at", "at": at, "text": _as_he_said(text, m.group("what"))}, "say": None}
        m = re.fullmatch(r"(?:no,? |actually,? )?(?:change|make) (?:it|that|the reminder )?(?P<old>.+?) (?:to|into) (?P<new>[a-z].+)", low)
        if m and at and m.group("old").strip() in (words.casefold(), "it", "that") \
                and not _spoken_time(m.group("new").replace("at ", "")) \
                and not re.match(r"(?:today|tomorrow|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday"
                                 r"|morning|afternoon|evening|noon|midnight|\d)", m.group("new")):
            return {"command": {"kind": "remind_at", "at": at, "text": _as_he_said(text, m.group("new")),
                                "replaces": words}, "say": None}

    # "Change it to every hour" right after "remind me every 30 minutes to
    # stretch" (2026-10-08: to the planner).
    m = re.fullmatch(r"(?:no,? |actually,? )?(?:change|make|set) (?:it|that|the reminder) (?:to )?(?P<every>every .+)", low)
    if m and _every_minutes(m.group("every")):
        before = _recent_ask_of("remind_every", "text")
        if before.get("text"):
            return {"command": {"kind": "remind_every", "minutes": _every_minutes(m.group("every")),
                                "text": before["text"], "replaces": before["text"]}, "say": None}
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
        # "Remind me every Monday at 3 to call mom" and "...pick up Leo at 3
        # every weekday" were set for 3 am (2026-10-07). Nobody means that.
        if m.group(2) and _is_bare_hour(m.group(2)) and int(hhmm[:2]) <= EARLIEST_BARE_HOUR:
            hhmm = f"{int(hhmm[:2]) + 12:02d}{hhmm[2:]}"
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
        said_time, what = m.group("time"), m.group("text").strip()
        # "Remind me every day to take my pills at 9" kept "at 9" in the
        # reminder's words (2026-10-07). A time at the end is the when.
        late = re.fullmatch(r"(?P<what>.+?) at (?P<time>\d{1,2}(?::\d{2})?(?: ?(?:am|pm|a\.m\.|p\.m\.))?|noon|midnight)", what)
        if not said_time and late and _spoken_time(late.group("time")):
            said_time, what = late.group("time"), late.group("what")
        hhmm = (_spoken_time(said_time) if said_time
                else {"morning": "09:00", "evening": "19:00", "night": "21:00"}.get(m.group("part"), DEFAULT_REMINDER_TIME))
        if hhmm and said_time and _is_bare_hour(said_time) and int(hhmm[:2]) < 12 \
                and (m.group("part") in ("evening", "night") or int(hhmm[:2]) <= EARLIEST_BARE_HOUR):
            hhmm = f"{int(hhmm[:2]) + 12:02d}{hhmm[2:]}"      # "every night at 10" is ten at night
        if hhmm:
            return {"command": {"kind": "remind_daily", "time": hhmm,
                                "text": _as_he_said(text, what)}, "say": None}
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

    # THE DAY SAID FIRST (2026-10-08: "tomorrow I need to go to the bank"
    # and "add call mom to tomorrow" both to the planner). The same sentence
    # with the day where the rules below look for it.
    m = re.fullmatch(r"(?P<day>today|tomorrow|tonight|this weekend|(?:on )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)),? "
                     r"(?P<rest>(?:i (?:need|have|got) to|i've got to|i gotta|i should|i must|remind me to) .{3,120})", low)
    if m:
        return _interpret(f"{m.group('rest')} {re.sub(r'^on ', '', m.group('day'))}")
    m = re.fullmatch(r"(?:add|put) (?P<what>(?!it\b|that\b|this\b)[a-z].{2,80}?) (?:to|on|for) (?P<day>today|tomorrow|(?:monday|tuesday|wednesday"
                     r"|thursday|friday|saturday|sunday))(?:'s)?(?: (?:list|to ?do list|tasks|plan))?", low)
    if m and _TASK_VERB.match(m.group("what")) and not re.search(r"\b(?:to|on) (?:my|the) (?:[a-z]+ )?(?:list|tasks|to ?dos?|to-dos?)\b", m.group("what")):
        return _new_task(_as_he_said(text, f"{m.group('what')} {m.group('day')}"))
    # A TASK SAID AS A NEED (2026-10-07): "I need to call the bank
    # tomorrow" and "don't let me forget to pay rent" went to the planner.
    # Only when what follows starts like a thing to do - "I need to know"
    # and "I have to say" are not tasks.
    # "Maybe I should call mom", "I should probably clean the garage"
    # (2026-10-08: to the planner) are the same; going to bed is not a task.
    m = re.fullmatch(r"(?:(?:maybe|i think|honestly|ok(?:ay)?),? )?"
                     r"(?:i (?:need|have|got) to|i've got to|i gotta|i must|i (?:probably |really )?should(?: really| probably)?|"
                     r"(?:don'?t|do not) let me forget to|make sure i|remember i (?:need|have) to)"
                     r" (?P<what>.{3,120})", low)
    if m and re.match(r"(?:go to (?:bed|sleep)|call it a (?:night|day)|get (?:some )?sleep|go home)\b", m.group("what")):
        return {"command": None, "say": "Safe trip home." if m.group("what").startswith("go home")
                else "Goodnight. I'll keep going quietly."}
    if m and (_TASK_VERB.match(m.group("what")) or low.startswith(("don't let me", "dont let me", "do not let me"))):
        # "I need to call mom by 5" was a task due on November 5th
        # (2026-10-08). A bare hour after "by" is a clock, and a deadline
        # on a clock is a reminder a little before it.
        bym = re.fullmatch(r"(?P<thing>.+?) by (?P<clock>\d{1,2}(?::\d\d)?(?: ?[ap]\.?m\.?)?|noon)"
                           r"(?P<tail> (?:for|because|so|before) [a-z].{1,40}| today| tonight| this (?:morning|afternoon|evening))?", m.group("what"))
        if bym:
            day = " tonight" if (bym.group("tail") or "").strip() == "tonight" else ""
            timed = _interpret(f"remind me to {bym.group('thing')} at {bym.group('clock')}{day}")
            got = (timed or {}).get("command") or {}
            if got.get("kind") == "remind_at" and got.get("at"):
                import datetime as _dtby
                at = _dtby.datetime.fromisoformat(got["at"])
                early = at - _dtby.timedelta(minutes=15)
                if early > _dtby.datetime.now(at.tzinfo):
                    at = early
                return {"command": {**got, "at": at.isoformat(),
                                    "text": _as_he_said(text, f"{bym.group('thing')} by {bym.group('clock')}"
                                                        + (bym.group("tail") if re.match(r" (?:for|before) ", bym.group("tail") or "") else ""))}, "say": None}
        if re.search(r"\bat \d{1,2}(?::\d\d)?(?: ?[ap]\.?m\.?)?\b", m.group("what")):
            # A clock time makes it a reminder: "pick up the kids at 3".
            timed = _interpret(f"remind me to {m.group('what')}")
            if ((timed or {}).get("command") or {}).get("kind") == "remind_at":
                return timed
        if re.search(r"\bevery (?:\d+ |other |two |three |four )?(?:day|days|morning|night|evening|week|weeks|month"
                     r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday|weekday)s?\b", m.group("what")):
            # "I need to take out the trash every Tuesday" became a task
            # called "take out the trash every" due Tuesday (2026-10-08). A
            # thing done every so often is a repeating reminder - one tick
            # off a task would end it for good.
            again = _interpret(f"remind me to {m.group('what')}")
            if ((again or {}).get("command") or {}).get("kind", "").startswith("remind_"):
                return again
        return _new_task(_as_he_said(text, m.group("what")))
    # "I'm going to call mom tomorrow" (2026-10-07: to the planner). Said
    # as a plan, it is a task only when it names a day - "I'm going to make
    # dinner" is narration, not something to keep.
    m = re.fullmatch(r"(?:i'?m going to|i'?m gonna|i am going to|i'?ll|i will|i plan to|i'?m planning to) (?P<what>.{3,120})", low)
    if m and _TASK_VERB.match(m.group("what")) and not re.search(r"\b(?:you|thea|it)\b", m.group("what")) \
            and _split_deadline(m.group("what"))[1]:
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
        # Steps he told her ("I walked 5000 steps") are his to have back.
        try:
            from aletheia import quick
            found = quick.match(said)
            kept = (quick._counted(said) if found and found[0] == "counted"
                    # A heart rate he told her (2026-10-07) is read back too.
                    else quick._reading(said) if found and found[0] == "reading"
                    # "Did I hit my step goal today" (2026-10-08).
                    else quick._step_goal(said) if found and found[0] == "step_goal" else None)
        except Exception:  # noqa: BLE001
            kept = None
        if kept and not kept.startswith("You haven't"):
            return {"command": None, "say": kept}
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
    if re.fullmatch(r"(?:restart|reset|redo|repeat) (?:the |my |that )?timer(?: again)?|start (?:the |my |that )?timer (?:again|over)"
                    r"|(?:do|set) (?:that|it|the timer) again|same timer again|again", low) \
            and (low != "again" or "timer" in _previous_turn()[1].casefold()):
        return _restarted_timer()
    if re.fullmatch(r"(?:pause|hold|freeze|resume|unpause) (?:the |my |that )?timers?", low):
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
    # "Remind me to take my meds at 8 tonight" (2026-10-08) kept "at 8" in
    # the words and set it an hour on: the time can come before the day.
    m = (re.fullmatch(r"remind me (?:to|that) (?P<text>.+?) at (?P<time>\d{1,2}(?::\d\d)?(?: ?[ap]\.?m\.?)?|noon|midnight),?"
                      r" (?:on |this )?(?P<day>" + _days + r")" + _part, low)
         or re.fullmatch(r"remind me (?:to|that) (?P<text>.+?),? (?:on |this )?(?P<day>" + _days + r")" + _part
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
            # The time he gave travels too (2026-10-07: "next tuesday at
            # noon" was offered back as the 13th with no noon in it).
            when = (f" at {m.group('time').strip()}" if m.group("time")
                    else f" in the {m.group('part')}" if m.group("part") else "")
            return {"command": None,
                    "say": f"{asked} Say 'remind me on the {soon}{when} to {what}' and it's set."}
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
        if when <= dt.datetime.now(tz) and m.group("day") == "tonight" and m.group("time"):
            when += dt.timedelta(days=1)                # "at 8 tonight" said at midnight: 8 tomorrow night
        elif when <= dt.datetime.now(tz) and m.group("day") == "tonight":
            # Said at ten at night, "tonight" still means tonight: an hour on.
            when = (dt.datetime.now(tz) + dt.timedelta(hours=1)).replace(second=0, microsecond=0)
        elif when <= dt.datetime.now(tz) and m.group("day") in ("today", ""):
            when += dt.timedelta(days=1)
        elif when <= dt.datetime.now(tz) and re.fullmatch(
                r"(?:on )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)", m.group("day") or ""):
            # "On Thursday", said on a Thursday afternoon, is next Thursday:
            # 9 this morning is gone (2026-10-08: set for the past).
            when += dt.timedelta(days=7)
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
    # "Remind me to leave 20 minutes before lunch with Dana" (2026-10-08:
    # to the planner) is the same lead, with the errand said first.
    # "Remind me before my meeting to print the slides" (2026-10-08: to the
    # planner) names no lead: fifteen minutes, said back in the reminder.
    bare = re.fullmatch(r"remind me (?:right |just )?before (?P<what>(?:my |the )?(?:next )?[a-z][a-z0-9' ]{1,30}?) to (?P<task>[a-z].{2,80})", low)
    if bare and _an_errand(bare.group("task")):
        return _interpret(f"remind me to {_as_he_said(text, bare.group('task'))} 15 minutes before {bare.group('what')}")
    m = re.fullmatch(r"remind me (?:to (?P<task>.+?) )?(?P<n>\w+(?: an)?) (?P<unit>minutes?|mins?|hours?) before (?:my |the )?(?:next )?"
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
                told = None if upcoming else _event_from_notes(what)
                if told and cal.parse_time(told["start"]) > now + lead:
                    upcoming = [told]
            if not upcoming:
                return {"command": None,
                        "say": ("Nothing on your calendar coming up" if generic
                                else f"I don't see {what} on your calendar coming up") + " to remind you before."}
            event = upcoming[0]
            at = (cal.parse_time(event["start"]) - lead).astimezone(dt.timezone.utc).isoformat()
            said = f"{int(amount) if float(amount).is_integer() else amount} {m.group('unit').rstrip('s')}"
            plural = "s" if amount != 1 else ""
            soon = f"{event.get('title') or 'your next event'} in {said}{plural}"
            if m.group("task"):
                soon = f"{_as_he_said(text, m.group('task'))} - {soon}"
            return {"command": {"kind": "remind_at", "at": at, "text": soon}, "say": None}

    # "Remind me to buy flowers two days before our anniversary", "remind me
    # a week before my anniversary", "remind me to get a card the day before
    # Mom's birthday" (2026-10-08: to the planner). The date is in his note.
    # "Remind me the day before my flight to pack" (2026-10-08: read as a
    # calendar event called "flight to pack") is the same sentence with the
    # errand said last.
    late = re.fullmatch(r"remind me (?P<when>(?:the day|the night|the morning|a day|one day|(?:\d|two|three|four|five|six|seven|ten) days"
                        r"|a week|one week|two weeks) before (?:my |our |the )?(?:(?:wedding )?anniversary|vacation|trip|holiday|cruise"
                        r"|honeymoon|flight|[a-z]+(?:'s|s') (?:birthday|bday|anniversary))) to (?P<task>.+)", low)
    # "Remind me the day before my flight to Paris" (2026-10-08: "I'll remind
    # you 8 October 2027: Paris") - Paris is where the flight goes.
    if late and _an_errand(late.group("task")):
        return _interpret(f"remind me to {_as_he_said(text, late.group('task'))} {late.group('when')}")
    m = re.fullmatch(r"remind me (?:to (?P<task>.+?) )?(?P<lead>the day|the night|the morning|a day|one day"
                     r"|(?P<n>\d|two|three|four|five|six|seven|ten) days|a week|one week|two weeks) before (?:my |our |the )?"
                     r"(?P<what>(?:wedding )?anniversary|vacation|trip|holiday|cruise|honeymoon|flight"
                     r"|[a-z][a-z' ]{0,30}?(?:'s|s') (?:birthday|bday|anniversary)"
                     # "Remind me 3 days before my car insurance is due"
                     # (2026-10-08: read as a calendar event of that name).
                     r"|(?P<bill>" + _BILL_WORDS + r")"
                     # "Two weeks before my registration is due", "a week before
                     # my license expires" (2026-10-08: to the planner).
                     r"|(?P<doc>(?:car |vehicle )?registration|(?:driver'?s )?licen[sc]e|passport|lease|warranty"
                     r"|membership|inspection|(?:car )?tags|visa|permit))"
                     r"(?P<due> (?:is |are )?(?:due|up)| expires| ends| runs out)?", low)
    if m and m.group("due") and not (m.group("bill") or m.group("doc")):
        m = None
    if m and (m.group("task") or not re.search(r"\b(?:birthday|bday)$", m.group("what"))):
        import datetime as dt
        from aletheia import localtime, quick as _q
        tz = localtime.operator_tz()
        now = dt.datetime.now(tz)
        what = m.group("what")
        day = _q._date_in_notes(what, now.date())
        if day is None:
            whose = "your " + what if not re.match(r"[a-z]+(?:'s|s') ", what) or what.split("'")[0] in _q._relation_words() else what
            return {"command": None, "say": f"I don't know when {_as_he_said(text, whose)} is. Tell me the date once and I'll remember it."}
        lead = m.group("lead")
        days = (14 if lead == "two weeks" else 7 if "week" in lead else 0 if lead == "the morning"
                else (_spoken_amount(m.group("n")) if m.group("n") else 1) or 1)
        hour = {"the night": 19, "the morning": 8}.get(lead, 9)
        at = dt.datetime.combine(day - dt.timedelta(days=int(days)), dt.time(hour, 0), tzinfo=tz)
        if at <= now:
            try:
                day = day.replace(year=day.year + 1)
            except ValueError:            # February 29
                day = day.replace(year=day.year + 1, day=28)
            at = dt.datetime.combine(day - dt.timedelta(days=int(days)), dt.time(hour, 0), tzinfo=tz)
        said = what.replace("my ", "your ", 1) if what.startswith("my ") else what
        if not re.match(r"[a-z]+(?:'s|s') ", said) or re.split(r"'s?\b", said)[0] in _q._relation_words():
            said = "your " + said
        said = _as_he_said(text, said) if not said.startswith("your ") else said
        when = ("today" if days == 0 else "tomorrow" if days == 1 else f"in {int(days)} days, on {day.strftime('%A')}")
        # A bill "is due"; a document says what he said of it: "expires",
        # "ends", "is up" - and "is due" when he said nothing.
        verb = re.sub(r"^(?:is|are) ", "", (m.group("due") or "").strip())
        is_ = ("is due" if m.group("bill") or (m.group("doc") and not verb)
               else (verb if verb in ("expires", "ends", "runs out") else f"is {verb}") if m.group("doc") else "is")
        text = (f"{_as_he_said(text, m.group('task'))} - {said} {is_} {when}" if m.group("task") else f"{said} {is_} {when}")
        return {"command": {"kind": "remind_at", "at": at.isoformat(), "text": text}, "say": None}

    # "REMIND ME THE DAY BEFORE MY DENTIST APPOINTMENT" (2026-10-07: to the
    # planner). The same lookup, a day-sized lead: the day before at nine,
    # the night before at seven, the morning of at eight. A birthday or an
    # anniversary is not on the calendar and has its own branch below.
    m = re.fullmatch(r"remind me (?P<lead>the day|the night|the morning|a day|one day|(?P<n>\d|two|three|four|five) days|a week|one week)"
                     r" before (?:my |the )?(?:next )?(?P<what>[a-z][a-z0-9' ]{2,40}?)(?: to (?P<task>[a-z].{2,80}))?", low)
    # "Remind me the day before the wedding to get a card" (2026-10-08: read
    # as an event called "wedding to get a card"). The errand rides along
    # when it is one; "my flight to Paris" is still the flight.
    if m and m.group("task") and not _an_errand(m.group("task")):
        m = re.fullmatch(r"remind me (?P<lead>the day|the night|the morning|a day|one day|(?P<n>\d|two|three|four|five) days|a week|one week)"
                         r" before (?:my |the )?(?:next )?(?P<what>[a-z][a-z0-9' ]{2,40})(?P<task>)", low)
    if m and not re.search(r"\b(?:birthday|anniversary|bday)\b", m.group("what")):
        import datetime as dt
        from aletheia import calendar as cal, localtime, speech as _sp_before
        tz = localtime.operator_tz()
        what = m.group("what").strip()
        generic = what in ("meeting", "appointment", "event", "call", "thing", "one")
        now = dt.datetime.now(tz)
        try:
            upcoming = sorted((e for e in cal.all_events()
                               if e.get("status") != "CANCELLED" and cal.parse_time(e["start"]) > now),
                              key=lambda e: cal.parse_time(e["start"]))
        except Exception:
            upcoming = []
        if not generic:
            words = [w for w in re.findall(r"[a-z0-9]+", what) if len(w) > 2]
            upcoming = [e for e in upcoming if all(w in str(e.get("title") or "").lower() for w in words)]
            told = None if upcoming else _event_from_notes(what)
            upcoming = [told] if told else upcoming
        if not upcoming:
            return {"command": None,
                    "say": ("Nothing on your calendar coming up" if generic
                            else f"I don't see {what} on your calendar coming up") + " to remind you before."}
        event = upcoming[0]
        start = cal.parse_time(event["start"]).astimezone(tz)
        lead = m.group("lead")
        if lead == "the morning":
            when = start.replace(hour=8, minute=0, second=0, microsecond=0)
        else:
            days = 7 if "week" in lead else (_spoken_amount(m.group("n")) if m.group("n") else 1) or 1
            when = (start - dt.timedelta(days=int(days))).replace(hour=19 if lead == "the night" else 9,
                                                                   minute=0, second=0, microsecond=0)
        if when <= now or when >= start:
            # "dentist appointment is too soon for that" (2026-10-07): a
            # sentence with its capital, and what is still possible.
            title_ = str(event.get('title') or 'That')
            return {"command": None, "say": f"{title_[:1].upper() + title_[1:]} is {_sp_before.humanize_time(start.isoformat())}, "
                                            f"so that time has already gone. Say \"remind me in an hour about my {re.sub(r'^(?:[Yy]our|[Mm]y) ', '', title_)}\" "
                                            f"or another time, and I'll set that instead."}
        clock = start.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").lower()
        about = f"{event.get('title') or what} {start.strftime('%A')} at {clock}"
        if m.group("task"):
            about = f"{_as_he_said(text, m.group('task'))} - {about}"
        return {"command": {"kind": "remind_at", "at": when.isoformat(), "text": about}, "say": None}

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

    # "Remind me about the meeting next Tuesday at noon" was set for
    # TOMORROW at noon, with "next tuesday" left in the words (2026-10-07).
    # The day is the when; "about" keeps his words for the reminder.
    m = re.fullmatch(r"remind me (?:about|of) (?P<what>.+?),? (?P<day>(?:next |this |on )?(?:monday|tuesday|wednesday|thursday|friday"
                     r"|saturday|sunday)(?: (?:morning|afternoon|evening|night))?)(?P<at> at [\w: ]+)?", low) \
        or re.fullmatch(r"remind me (?P<day>(?:next |this |on )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
                        r"(?: (?:morning|afternoon|evening|night))?)(?P<at> at [\w: ]+)? (?:about|of) (?P<what>.+)", low)
    if m:
        again = _interpret(f"remind me {m.group('day')}{m.group('at') or ''} to {m.group('what')}")
        if (again.get("command") or {}).get("kind") == "remind_at":
            again["command"]["text"] = _as_he_said(text, m.group("what").strip())
            return again
        if again.get("command") is None and again.get("say"):
            return {"command": None, "say": again["say"].replace(f" to {m.group('what')}'", f" about {m.group('what')}'")}
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
    # "Remind me to buy milk when I'm at the store" (2026-10-07: to the
    # planner) is what the shopping list is FOR - the list is the reminder
    # he reads at the store, so the thing goes on it.
    m = re.fullmatch(r"remind me to (?:buy|get|pick up|grab) (?:some |more |a |an )?(?P<w>[a-z][a-z' ]{1,30}?) "
                     r"(?:when i(?:'m| am)? (?:at|go to|get to|next go to|am next at|'m next at) |at |next time i(?:'m| am)? at |next time i go to )"
                     r"the (?:grocery |hardware )?(?:store|shop|supermarket|market)", low)
    if m:
        return {"command": {"kind": "shopping_add", "item": _as_he_said(text, m.group("w").strip())}, "say": None}
    m = re.match(r"remind me (?:to|that) (.+?) when i(?:'m| am| get| arrive| go| come| leave)? "
                 r"(?:get |am |arrive |go |come )?(?:back )?(?:home|back|there|at work|to work|at the office|to the office|in"
                 r"|at the (?:store|gym|office|grocery store|doctor'?s?)|to the (?:store|gym|office|grocery store)"
                 r"|leave(?: work| home| the house| the office)?|out|$)$", low) \
        or re.match(r"remind me (?:to|that) (.+?) when i leave(?: work| home| the house| the office)?$", low) \
        or re.match(r"remind me (?:to|that) (.+?) on (?:my|the) way (?:home|to work|back|out|in|to the [a-z]+)$", low)
    # "Remind me to email Bob when I get to work" (2026-10-08: "I can't tell
    # where you are", beside the home one that works): "I'm at work" says it.
    work = re.fullmatch(r"remind me (to|that) (.+?) when i(?:'m| am| get| arrive)? (?:get |am )?(?:to|at) (?:work|the office)", low) \
        or re.fullmatch(r"remind me (?:when|once|as soon as) i (?:get|arrive) (?:to|at) (?:work|the office),? (to|that) (.+)", low)
    if work:
        how, what = (work.group(1), work.group(2))
        said = _as_he_said(text, what.strip())
        return {"command": {"kind": "note", "text": f"remind me {how} {said} when I get to work"},
                "say": f"I can't see where you are, so tell me \"I'm at work\" when you get there and I'll remind you "
                       f"{how} {speech._yours(said)}."}
    # "Remind me to buy milk when I leave work" (2026-10-08: "I can't tell
    # where you are"): "I'm leaving work" says it, the way arriving does.
    leave = re.fullmatch(r"remind me (to|that) (.+?) (?:when|before|as soon as) i (?:leave|get off|finish|head out of) (?:work|the office)", low)
    if leave:
        said = _as_he_said(text, leave.group(2).strip())
        return {"command": {"kind": "note", "text": f"remind me {leave.group(1)} {said} when I leave work"},
                "say": f"I can't see where you are, so tell me \"I'm leaving work\" when you go and I'll remind you "
                       f"{leave.group(1)} {speech._yours(said)}."}
    # "Remind me when I get home to start laundry" (2026-10-08: "I can't
    # tell where you are") is "remind me to start laundry when I get home".
    turned = re.fullmatch(r"remind me (?:when|once|as soon as) i(?:'m| am)? (?:get |come |am )?(?:back )?(?P<where>home|leave work|leave the office),? "
                          r"(?P<how>to|that) (?P<what>.+)", text.strip().rstrip(".!"), re.I)
    if turned:
        where = "get home" if turned.group("where").casefold() == "home" else "leave work"
        again = _interpret(f"remind me {turned.group('how')} {turned.group('what')} when I {where}")
        if again and (again.get("command") or {}).get("kind") == "note":
            return again
    home = re.fullmatch(r"remind me (to|that) (.+?) when i(?:'m| am| get| arrive| come)? (?:get |am |come )?(?:back )?(?:home|back)", low)
    if home:
        # "Remind me to call mom when I get home" (2026-10-08): she can't
        # see where he is, but he tells her - "I'm home" says it then.
        what = _as_he_said(text, home.group(2).strip())
        return {"command": {"kind": "note", "text": _as_he_said(text, low)},
                "say": f"I can't see where you are, so tell me \"I'm home\" when you get there and I'll remind you "
                       f"{home.group(1)} {speech._yours(what)}."}
    if m:
        return {"command": None,
                "say": "I can't tell where you are yet, so a place can't set off a reminder. "
                       f"Give me a time - 'remind me at 6 to {_as_he_said(text, m.group(1).strip())}' - and I'll do that."}
    m = re.match(r"remind me (?:to|that) (.+?) "
                 r"(?:at ([\w: ]+)|in (\d+|an?|half an?|one|two|three|four|five|ten|fifteen|twenty|thirty|forty five) (minutes?|hours?))$", low)
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
            said = m.group(3)
            amount = 0.5 if said.startswith("half") else 1 if said in ("a", "an") else _spoken_amount(said)
            if amount is None:
                return _to_the_planner(text)
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
                    # "What's my to do list" (2026-10-07: searched memory for
                    # "to do list" and said it had nothing).
                    r"what(?:'s| is|s)? (?:my|the) (?:task|todo|to-do|to do) list|"
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
    # "Actually do it Saturday" (2026-10-07: to the planner) is the same move.
    m = re.fullmatch(r"(?:no,? )?(?:make|set|do|i'?ll do) (?:it|that) (?:due )?(?:on |for |by )?(?P<day>today|tomorrow|tonight|(?:this |next )?"
                     r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))(?: instead)?"
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
    m = re.fullmatch(r"(?:move|push|reschedule|bump|change|shift|postpone|delay|defer|put off|push back) (?:the |my )?(?:task )?(?P<w>.+?)" + _task_tail
                     + r" (?:to|till|until|for|back to) (?P<day>today|tomorrow|tonight|(?:this |next )?(?:monday|tuesday"
                       # "Move renew my license to next week", "to November
                       # 15" (2026-10-08: to the planner).
                       r"|wednesday|thursday|friday|saturday|sunday)|next week|(?:this |the )weekend|" + SPOKEN_DATE + r")", low) \
        or re.fullmatch(r"(?:make|set) (?:the |my )?(?:task )?(?P<w>.+?)" + _task_tail + r" (?:due|for) "
                        r"(?P<day>today|tomorrow|tonight|(?:this )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))", low) \
        or re.fullmatch(r"(?:the |my )?(?P<w>.+?) (?:task )?(?:is|should be) due (?:on |by )?"
                        r"(?P<day>today|tomorrow|tonight|(?:this |next )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))", low)
    which = m.group("w") if m else ""
    if which in ("it", "that", "this", "that one"):
        # "Push that to next week" a turn after the task was added (2026-10-08)
        which = _the_task_just_added() or which
    if m and _names_one_open_task(which):
        said = m.group("day")
        if said.startswith("next "):
            asked = _ambiguous_next_weekday(said)
            if asked:
                return {"command": None, "say": asked}
        if said in ("next week", "this weekend", "the weekend"):
            import datetime as dt
            from aletheia import localtime
            today = localtime.today()
            ahead = (7 - today.weekday()) if said == "next week" else ((5 - today.weekday()) % 7 or 7)
            day = (today + dt.timedelta(days=ahead)).isoformat()
        else:
            day = _spoken_day("today" if said == "tonight" else said)
        if day:
            return {"command": {"kind": "task_change", "which": which, "deadline": day}, "say": None}
    elif m and re.search(r"\btask\b|\bon my (?:list|to-?do list)\b", low):
        # "Move my dentist task to friday" with no such task went to the
        # planner (2026-10-07). He said task: the answer is the list's.
        try:
            from aletheia import intercom
            _found, why = intercom._one_task(m.group("w"))
        except Exception:
            why = ""
        if why:
            return {"command": None, "say": why}
    m = re.fullmatch(r"(?:rename|retitle|reword) (?:the )?(?:task )?(?P<w>.+?)" + _task_tail + r" (?:to|as) (?P<new>.+)", low) \
        or re.fullmatch(r"change (?:the )?(?:task )?(?P<w>.+?)" + _task_tail + r" to say (?P<new>.+)", low)
    if m and _names_one_open_task(m.group("w")):
        return {"command": {"kind": "task_change", "which": m.group("w"),
                            "description": _as_he_said(text, m.group("new").strip())}, "say": None}
    if m and re.search(r"\btask\b", low):
        # "Rename the insurance task to call Geico" with no such open task
        # (2026-10-08: to the planner) - the list says why.
        try:
            from aletheia import intercom
            _found, why = intercom._one_task(m.group("w"))
        except Exception:  # noqa: BLE001
            why = ""
        if why:
            return {"command": None, "say": why}
    m = re.fullmatch(r"(?:delete|remove|drop|cancel|scrap|forget about|get rid of|take) (?:the )?(?:task )?(?P<w>.+?)"
                     + _task_tail + r"(?: off(?: my (?:list|tasks|task list|to-?do list))?)?", low)
    # Not "cancel the first one": counting is about whatever she just read
    # out, and that is usually approvals.
    # "Cancel the passport task" has its own branch further down.
    if m and m.group("w") not in ("it", "that", "this", "everything", "all") \
            and not re.search(r" (?:task|one|item)(?: from (?:my|the) (?:task )?list)?$", low) \
            and not re.search(r"\b(?:first|second|third|last|latest|newest|oldest|next|other)\b", m.group("w")) \
            and (_names_one_open_task(m.group("w"))
                 # "Delete the task call the vet" (2026-10-07: to the planner) says it is
                 # a task; the store answers which one, or that none matches.
                 or re.match(r"(?:delete|remove|drop|cancel|scrap) (?:the |my )?task (?:called |named )?", low)):
        which = re.sub(r"^(?:called|named) ", "", m.group("w"))
        return {"command": {"kind": "task_change", "which": which, "drop": True}, "say": None}

    # A THING ON THE SHOPPING LIST, TICKED OFF (2026-10-07): "check off
    # milk" marked a TASK called milk done, and "got the milk" / "bought
    # eggs" went to the planner. Only when that thing is on the list; a task
    # by that name is still the task.
    m = re.fullmatch(r"(?:tick|check|cross|mark) off (?:the |some )?(?P<w>.+?)", low) \
        or re.fullmatch(r"(?:i )?(?:got|bought|picked up|grabbed) (?:the |some )?(?P<w>[a-z][a-z' ]{1,30}?)"
                        r"(?: already| now)?", low)
    if m and _on_the_shopping_list(m.group("w")) and not _names_one_open_task(m.group("w")):
        return {"command": {"kind": "shopping_off", "item": m.group("w").strip()}, "say": None}
    # "I got the batteries" with batteries on his Target list (2026-10-08:
    # to the planner). The one other list that holds exactly that line.
    if m and not _names_one_open_task(m.group("w")):
        try:
            from aletheia import lists as _lists
            bare = lambda x: re.sub(r"^(?:a|an|the|some|my) ", "", " ".join(str(x).casefold().split()))
            holds = [held["name"] for held in _lists.all_lists()
                     if any(bare(line) == bare(m.group("w")) for line in (_lists.items(held["name"]) or []))]
        except Exception:  # noqa: BLE001
            holds = []
        if len(holds) == 1:
            return {"command": {"kind": "list_off", "list": holds[0], "item": m.group("w").strip()}, "say": None}
    # "Move chicken to the shopping list", "move the tent from my camping
    # list to my packing list" (2026-10-08: to the planner). Only when the
    # line is on exactly one other list, or on the list he named.
    mv = re.fullmatch(r"(?:move|put|switch|transfer) (?:the |some )?(?P<w>[a-z][a-z' ]{1,30}?)"
                      r"(?: from (?:my |the )?(?P<src>[a-z][a-z' ]{1,25}?) list)? (?:to|onto|over to) (?:my |the )?(?P<dst>[a-z][a-z' ]{1,25}?) list", low)
    if mv and mv.group("w") not in ("it", "that", "them", "this", "everything"):
        bare = lambda x: re.sub(r"^(?:a|an|the|some|my) ", "", " ".join(str(x).casefold().split()))
        dst = "shopping" if mv.group("dst") in ("shopping", "grocery", "groceries") else mv.group("dst")
        try:
            from aletheia import lists as _lists
            holds = [held["name"] for held in _lists.all_lists()
                     if any(bare(line) == bare(mv.group("w")) for line in (_lists.items(held["name"]) or []))]
        except Exception:  # noqa: BLE001
            holds = []
        if _on_the_shopping_list(mv.group("w")):
            holds.append("shopping")
        src = mv.group("src")
        if src:
            src = "shopping" if src in ("shopping", "grocery", "groceries") else src
            holds = [h for h in holds if h.casefold() == src]
        holds = [h for h in holds if h.casefold() != dst.casefold()]
        if len(holds) == 1:
            item = _as_he_said(text, mv.group("w").strip())
            if dst == "shopping":
                return {"command": {"kind": "shopping_add", "item": item, "moved_from": holds[0]}, "say": None}
            return {"command": {"kind": "list_add", "list": dst, "item": item, "moved_from": holds[0]}, "say": None}
    # "What do I need at Target" with a Target list (2026-10-08: to a
    # model). That list; without one, the shopping list.
    w = re.fullmatch(r"what (?:do i|else do i) (?:still )?need (?:at|from) (?:the )?(?P<shop>[a-z][a-z' &-]{1,25}?)", low)
    if w and w.group("shop") not in ("store", "shop", "shops", "grocery store", "supermarket", "me", "you"):
        try:
            from aletheia import lists as _lists
            named = [held["name"] for held in _lists.all_lists()
                     if re.sub(r" list$", "", str(held.get("name") or "").casefold()) == w.group("shop")]
        except Exception:  # noqa: BLE001
            named = []
        if named:
            return {"command": {"kind": "list_read", "list": named[0]}, "say": None}
        # "From Sarah" is a person, not a shop: only a shop by name.
        if re.fullmatch(r"target|costco|walmart|aldi|kroger|safeway|publix|wegmans|trader joe'?s|whole foods|sam'?s club|cvs|walgreens"
                        r"|ikea|home depot|lowe'?s|best buy|the pharmacy|pharmacy|hardware store|grocery|market|farmers market|bakery", w.group("shop")):
            return {"command": {"kind": "shopping_list"}, "say": None}
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
    # "DID I BUY MILK" (2026-10-07: refused as an instruction to spend). A
    # question about his shopping, answered from the list: still on it is
    # "not yet", ticked off is "yes" with when. Neither is None - the
    # planner, which is what it did before.
    m = re.fullmatch(r"(?:did|have) i (?:already )?(?:buy|bought|get|got|pick up|picked up|grab|grabbed) "
                     r"(?:the |some |any )?(?P<w>[a-z][a-z' ]{1,30}?)(?: yet| already| today)?", low)
    if m:
        said = _bought_yet(m.group("w"))
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
    # HIS WORK DAY, LOGGED (2026-10-07: "I'm starting work" went to the
    # planner and "I'm done with work for the day" looked for a TASK called
    # "work for the day"). A note at the moment he says it; "how long did I
    # work today" subtracts the two.
    if re.fullmatch(r"(?:ok(?:ay)?,? )?(?:i'?m |i am )?(?:starting work|starting my (?:work ?day|shift)|clocking in|logging on(?: for work)?"
                    r"|at work(?: now)?|on the clock)(?: now)?|(?:i )?(?:just )?(?:clocked in|started work|got to work|made it to work)(?: now)?", low):
        return {"command": {"kind": "note", "text": "started work"}, "say": _work_reminders_said()}
    if re.fullmatch(r"(?:ok(?:ay)?,? )?(?:i'?m |i am )?(?:all )?(?:done|finished|through|off) (?:with |for )?(?:work|the day|my shift|my work ?day)"
                    r"(?: for (?:the day|today|now|tonight))?|(?:i'?m |i am )?(?:clocking out|logging off|off work)(?: for (?:the day|today))?"
                    r"|(?:i )?(?:just )?(?:clocked out|finished work|got off work)(?: for (?:the day|today))?", low):
        return {"command": {"kind": "note", "text": "finished work"},
                "say": _work_reminders_said("leave work", "finished work")}
    # "I usually go to bed at 11", "I go to bed at 11 usually" (2026-10-07:
    # to the planner). His habit, in his words; "what time do I usually go
    # to bed" reads it until there are nights enough to work it out.
    if re.fullmatch(r"(?:i (?:usually|normally|always|tend to) (?:go to bed|go to sleep|wake up|get up)"
                    r" (?:at |around |by )?\d{1,2}(?::\d\d)? ?(?:am|pm)?(?: (?:most nights|every night|on weekdays))?"
                    r"|i (?:go to bed|go to sleep|wake up|get up) (?:at |around |by )?\d{1,2}(?::\d\d)? ?(?:am|pm)?"
                    r" (?:usually|normally|most nights|most mornings|every night|every morning|on weekdays))", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I'm leaving work" (2026-10-07) was answered "Safe trip home" and not
    # kept, so "how long was I at work" counted on to midnight. It is the
    # end of his work day as well as a goodbye.
    if re.fullmatch(r"(?:ok(?:ay)?,? )?(?:i'?m |i am )?(?:just )?(?:leaving|left|heading out of|out of) (?:work|the office)(?: now| for the day| for today)?"
                    r"|(?:i'?m |i am )?(?:off work|done for the day)(?: now)?", low):
        from aletheia import quick
        bye = quick._farewell("leaving work")
        return {"command": {"kind": "note", "text": "finished work"},
                "say": _work_reminders_said("leave work", "finished work", lead=(bye or "Safe trip home.").split(".")[0] + ".") or bye}
    # THE DEVICES (2026-10-08: "my phone storage is full" and "my laptop
    # battery is dying" went to the planner).
    # Kept, so "what needs fixing" reads them; a printer out of ink is also
    # the thing to buy.
    m = re.fullmatch(r"(?:my|the|our) (?P<dev>laptop|computer|pc|desktop|mac|macbook|phone|iphone|tablet|ipad|printer|tv|router|modem|wifi|wi-fi|internet|watch|kindle|xbox|playstation)"
                     r"(?P<part> battery| storage| screen| keyboard| charger| connection| hard drive| memory)? (?:is|keeps|has been) (?:really |so |super |kind of |kinda )?"
                     # Not "slow" or "freezing": a complaint about how it runs is a
                     # question for a model that can help ("my computer is slow").
                     r"(?P<how>dying|full|out of (?:ink|toner|paper|storage|space)|almost full)"
                     r"(?: again| lately| today)?", low)
    if m:
        # "My phone is dying" is a low battery, not a broken phone.
        if m.group("how") == "dying" and not m.group("part") and m.group("dev") in ("phone", "iphone", "laptop", "tablet", "ipad", "watch", "kindle", "macbook"):
            return {"command": None, "say": "Better find a charger."}
        out = re.fullmatch(r"out of (ink|toner|paper)", m.group("how"))
        if out and m.group("dev") == "printer":
            got = _interpret(f"add printer {out.group(1)} to my shopping list")
            if ((got or {}).get("command") or {}).get("kind"):
                return got
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I forgot my password" (2026-10-08: to the planner). She keeps none, so
    # the honest answer is where it is.
    if re.fullmatch(r"(?:ugh,? )?i (?:forgot|can'?t remember|cannot remember|lost) my (?:[a-z]+ )?password(?: (?:for|to) [a-z][a-z .]{1,20})?(?: again)?", low):
        return {"command": None,
                "say": "I don't keep passwords, so I can't look it up. The \"forgot password\" link on the sign-in page will reset it, "
                       "or your password manager has it."}
    # "I have a cavity", "my dentist is on Main Street" (2026-10-08: to the planner).
    if re.fullmatch(r"i (?:have|'ve got|got) (?:a |an |another |two |2 )?(?:cavity|cavities|chipped tooth|cracked tooth|toothache|tooth ache|abscess|ear infection|sinus infection"
                    r"|pink eye|strep(?: throat)?|uti|ingrown toenail|sprained (?:ankle|wrist)|pulled muscle|rash|sunburn|blister)(?: again)?", low):
        return {"command": {"kind": "note", "text": "Journal: " + _as_he_said(text, low)},
                "say": "Sorry, that's no fun. I've put it in your journal, so you can tell the doctor how long it's been."}
    m = re.fullmatch(r"(?:my|the|our) (?P<who>dentist|doctor|vet|pharmacy|gym|barber|hairdresser|salon|mechanic|chiropractor|therapist)"
                     r"(?:'s office)? is (?:on|over on|down on) (?P<where>(?:the )?[a-z0-9][a-z0-9 .'&-]{2,40})", low)
    if m and not re.search(r"\b(?:vacation|leave|holiday|break|call|duty|time|it|me|my side|board|track|the phone|hold|the way)$", low):
        # The place store "the gym is at 20 Oak Ave" already keeps; "on" is
        # the same thing said another way.
        again = _interpret(f"the {m.group('who')} is at {text[len(text) - len(m.group('where')):] if text.lower().endswith(m.group('where')) else m.group('where')}")
        if ((again or {}).get("command") or {}).get("kind") not in (None, "intent"):
            return again
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "My basil is dying" (2026-10-08: to the planner) - kept, the way "how
    # is my garden" reads it back.
    if re.fullmatch(r"(?:my|the|our) (?:[a-z]+ )?(?:basil|tomato|tomatoes|plant|plants|garden|flowers|roses|herbs|lawn|grass|tree|trees|hedge|succulent|cactus|orchid|fern|peppers|mint|lettuce)"
                    r" (?:is|are|looks?|seems?) (?:really |kind of |kinda |a bit )?(?:dying|wilting|drooping|dead|turning (?:yellow|brown)|brown|yellow|sad|thriving|doing (?:great|well|badly))", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "My dog is due for shots" (2026-10-08: to the planner).
    if re.fullmatch(r"(?:my|our|the) (?:dog|cat|puppy|kitten|pet)(?:'s)? (?:is )?(?:due|overdue) for (?:his |her |its |their )?"
                    r"(?:shots|vaccines|vaccinations|rabies shot|booster|checkup|check-up|flea (?:and tick )?(?:medicine|meds|treatment)|heartworm (?:medicine|pill|test)|grooming|nail trim|dental cleaning)"
                    r"(?: (?:in|on|by|next|this) [a-z0-9 ,]{2,25})?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I have chicken and rice" (2026-10-08: to the planner): what is in the
    # kitchen, kept so "what should I make for dinner" can build on it. Every
    # item must be a food, so "I have a meeting and a call" is never a pantry.
    m = re.fullmatch(r"(?:all )?i (?:have|'ve got|got|have got) (?:some )?(?P<items>[a-z][a-z, ]{2,60}?)(?: in the (?:fridge|freezer|pantry|kitchen)| at home| left)?", low)
    if m:
        from aletheia import quick
        if quick._food_said(m.group("items")):
            return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # THE TRIP ITSELF (2026-10-08: "my flight got delayed 2 hours", "I
    # landed", "my bag is lost" and "I checked a bag" went to the planner;
    # "my hotel checkout is at 11" was refused as spending money).
    m = re.fullmatch(r"(?:my|our|the) flight (?:got|is|was|has been|just got) (?:delayed|pushed back)(?: by)?(?: (?P<n>\d{1,2}|an|one|two|three|half an) (?P<u>hours?|hour|minutes?|mins?))?(?: again)?", low)
    # ...but a bare "my flight is delayed" is a complaint a model can look
    # into, as it always was; an amount, or "got", is a fact to keep.
    if m and not m.group("n") and not re.search(r"\b(?:got|has been)\b", low):
        m = None
    if m:
        from aletheia import quick as _q
        later = ""
        n = {"an": 1, "one": 1, "two": 2, "three": 3}.get(m.group("n") or "", m.group("n"))
        for row in _q._notes()[:20]:
            t = re.match(r"(?:my|our|the) flight (?:leaves|departs|is) (?:at )?(?P<h>\d{1,2})(?::(?P<mm>\d\d))? ?(?P<ap>am|pm)(?P<rest> today| tonight| tomorrow)?",
                         str(row.get("text") or "").casefold())
            if t and n and m.group("n") != "half an":
                mins = int(t.group("h")) % 12 * 60 + (720 if t.group("ap") == "pm" else 0) + int(t.group("mm") or 0)
                mins += int(n) * (60 if m.group("u").startswith("hour") else 1)
                if mins < 24 * 60:
                    h, mm = divmod(mins, 60)
                    later = f", so it leaves at {(h % 12) or 12}{f':{mm:02d}' if mm else ''} {'am' if h < 12 else 'pm'}{t.group('rest') or ''}"
                break
        return {"command": {"kind": "note", "text": _as_he_said(text, low) + later}, "say": None}
    if re.fullmatch(r"(?:my|our|the) flight (?:got|was|has been|just got) (?:cancell?ed|canceled)", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)},
                "say": "Sorry - that's a pain. The airline's app is usually the fastest way to rebook."}
    if re.fullmatch(r"(?:i|we) (?:just )?(?:landed|touched down|arrived)(?: in [a-z][a-z .]{1,25}| safely| safe)?|(?:my|our) flight (?:just )?landed(?: in [a-z][a-z .]{1,25})?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": "Welcome - glad you made it."}
    if re.fullmatch(r"(?:my|our) (?:bag|bags|luggage|suitcase|checked bag) (?:is|are|got|was|were) (?:lost|missing|delayed|damaged|left behind)", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)},
                "say": "Report it at the airline's baggage desk before you leave the airport - they'll give you a file number. Tell me the number and I'll keep it."}
    if re.fullmatch(r"i (?:just )?checked (?:a |my |one |two |2 |three |3 )?(?:bags?|suitcases?|luggage)", low) \
            or re.fullmatch(r"(?:my |our |the )?(?:hotel )?(?:check[- ]?out|check[- ]?in|checkout|checkin) (?:time )?is (?:at |by )?(?:\d{1,2}(?::\d\d)?(?: ?(?:am|pm))?|noon)(?: tomorrow| today| on [a-z]+)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # AWAY FROM HOME (2026-10-08: "I need someone to watch the dog while I'm
    # gone", "I need to stop the mail" and "I'm back from vacation" went to
    # the planner or "I can't think").
    m = re.fullmatch(r"i (?:need|have|gotta|got to|should)(?: to)?(?: find| get)? (?:someone|somebody|a sitter|a dog sitter|a pet sitter|a house sitter)"
                     r" (?:to )?(?P<what>watch|feed|walk|look after|take care of|check on) (?P<who>(?:the |my |our )?(?:dog|dogs|cat|cats|pets?|kids|plants|house|fish))"
                     r"(?: while i(?:'m| am) (?:gone|away|out of town|on vacation|on my trip)| (?:next|this) week(?:end)?)?", low)
    if m:
        return _new_task(f"find someone to {m.group('what')} {re.sub(r'^(?:my |our )', 'the ', m.group('who')) if re.match(r'(?:my|our|the) ', m.group('who')) else 'the ' + m.group('who')}")
    m = re.fullmatch(r"i (?:need|have|gotta|got to|should)(?: to)? (?P<v>stop|hold|pause|put a hold on) (?:the |my )?(?P<what>mail|newspaper|paper|deliveries|delivery|packages)"
                     r"(?: while i(?:'m| am) (?:gone|away|on vacation)| (?:next|this) week)?", low)
    if m:
        return _new_task(f"{'hold' if m.group('v') in ('hold', 'put a hold on') else m.group('v')} the {m.group('what')}")
    if re.fullmatch(r"(?:i'?m|i am|we'?re|we are|just got) (?:back|home) from (?:my |our |the )?(?:vacation|trip|holiday|honeymoon|cruise|camping|business trip|work trip|[a-z]+ trip)", low):
        from aletheia import quick as _qa
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": _qa._arrival()}
    # "I have a package to drop off at UPS", "I need to get my suit dry
    # cleaned" (2026-10-08: to the planner) are errands.
    m = re.fullmatch(r"i (?:have|got|'ve got) (?P<n>a|an|some|two|three|\d) (?P<thing>package|packages|parcel|parcels|box|boxes|return|returns|letter|letters)"
                     r" to (?P<v>drop off|mail|ship|send|return|post)(?P<rest> (?:at|to) (?:the )?[a-z][a-z' ]{1,30})?(?: today| tomorrow)?", low)
    if m:
        return _new_task(f"{m.group('v')} {m.group('n')} {m.group('thing')}" + (" " + _as_he_said(text, m.group("rest").strip()) if m.group("rest") else ""))
    m = re.fullmatch(r"i (?:need|have|gotta|got|should)(?: to)? (?:get|take) (?P<what>(?:my|the|our) [a-z][a-z' ]{1,25}?) (?:to be )?"
                     r"(?P<done>dry cleaned|cleaned|fixed|repaired|altered|hemmed|tailored|serviced|resized|framed|sharpened|tuned|reupholstered|re-?soled|shortened|taken in|let out)"
                     r"(?: (?:today|tomorrow|this week|next week|soon))?", low)
    if m:
        return _new_task(_as_he_said(text, f"get {m.group('what')} {m.group('done')}"))
    # "My paycheck came in", "I split dinner with Sam" (2026-10-08: to the planner).
    if re.fullmatch(r"(?:my|the) (?:paycheck|pay|check|direct deposit|deposit|refund|tax refund|bonus|reimbursement|commission)"
                    r" (?:just )?(?:came in|came through|cleared|hit|landed|went through|was deposited|got deposited|posted|arrived|showed up)"
                    r"(?: (?:today|this morning|yesterday))?|i (?:just )?got paid(?: today| this morning| yesterday)?"
                    r"|i (?:split|went halves on|went halfsies on) (?:the |a )?(?:dinner|lunch|breakfast|bill|check|tab|cab|uber|ride|pizza|groceries|rent|hotel|room|tickets?)"
                    r" with [a-z][a-z' ]{1,25}?(?: today| tonight| last night| yesterday)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # PACKAGES AND REFUNDS (2026-10-08: "my headphones arrived", "the refund
    # should be in 5 days" and "my amazon order is late" went to the planner).
    if re.fullmatch(r"(?:my|the|our) (?:new )?(?!(?:sister|brother|mom|dad|mother|father|wife|husband|son|daughter|kids?|parents|friend|guests?"
                    r"|boss|family|cousin|aunt|uncle|grandma|grandpa|niece|nephew|neighbou?r|period|time|turn|day|moment)\b)[a-z][a-z' ]{1,25}?"
                    r" (?:just )?(?:arrived|came|showed up|got here|was delivered|were delivered|got delivered|finally came|finally arrived)"
                    r"(?: today| yesterday| this morning| this afternoon)?"
                    r"|(?:my|the|our) (?:tax )?(?:refund|check|paycheck|deposit|reimbursement|package|parcel|order|delivery|[a-z]+ order|[a-z]+ refund)"
                    r" (?:should|will|is supposed to|is going to|is gonna) (?:be(?: here| there| back)?|arrive|come|show up|post|clear|hit|land)"
                    r"(?: (?:in|by|on|within|next|this) [a-z0-9 ]{1,25})?"
                    r"|(?:my|the|our) (?:[a-z]+ )?(?:order|package|parcel|delivery|refund) (?:is|was|got) (?:late|delayed|lost|missing|stuck|stolen|damaged|cancell?ed)"
                    r"(?: again)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I'm going to the gym", "I just got back from the gym" (2026-10-08):
    # answered and forgotten, so "how many times did I go to the gym this
    # week" said none right after both. One visit, kept once.
    gym = re.fullmatch(r"(?:ok(?:ay)?,? )?(?:(?:i'?m|i am|im) )?(?:just )?(?P<out>going|heading|off|headed|leaving for) to the gym(?: now)?"
                       r"|(?:ok(?:ay)?,? )?i (?:just )?(?:got back|came back|got home|came home) from the gym"
                       r"|(?:ok(?:ay)?,? )?(?:i'?m |i am |im |just )?(?:back|home) from the gym", low)
    if gym:
        import datetime as _dt
        from aletheia import quick
        said = quick._farewell(text) if gym.group("out") else quick._arrival()
        now = _dt.datetime.now(_dt.timezone.utc)
        for row in quick._notes():
            try:
                at = _dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00"))
            except ValueError:
                continue
            if at.tzinfo and now - at < _dt.timedelta(hours=6) and re.search(r"\bgym\b", str(row.get("text") or "").casefold()):
                return {"command": None, "say": said}
        return {"command": {"kind": "note", "text": "I went to the gym"}, "say": said}
    # "Mark everything on my to do list done" is the whole list - refused
    # further on, never a task called "everything on my to do list".
    m = (re.fullmatch(r"(?:mark|tick|check|cross) (?:off )?(?:the )?(?!everything\b|all\b|every task\b)(.+?)"
                      r"(?: one| task)? (?:as )?(?:done|complete[d]?|finished)",
                      low)
         or re.fullmatch(r"(?:tick|check|cross) off (?:the )?(?!everything\b|all\b|every task\b)(.+?)"
                         r"(?: one| task)?", low)
         or re.fullmatch(r"(?:i(?:'ve)? )?(?:finished|completed) (?:the )?(.+?)"
                         r"(?: one| task)?", low)
         # "I'm done with the dishes" (2026-10-07: to a model).
         or re.fullmatch(r"(?:i'?m|i am|im) (?:all )?(?:done|finished|through) with (?:the )?(?!it$|that$|this$|you$|work$|today$)(.+?)"
                         r"(?: one| task)?", low)
         # "I did 50 pushups" is a count, not a task (2026-10-07: it ticked
         # off a task called "50 pushups"); it is kept as a note further on.
         # "I did legs today", "I did yoga" (2026-10-08: "that wasn't on your
         # task list") are workouts, kept further on.
         or re.fullmatch(r"i (?:did|have done) (?:the )?(?!\d)(?!(?:legs|arms|chest|back|abs|shoulders|upper body|lower body|leg day|arm day|chest day"
                         r"|yoga|pilates|cardio|a workout|weights|crossfit|hiit|push day|pull day|full body)\b)(.+?)(?: one| task)?", low)
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

    # "I'm working on the budget" (2026-10-08: to a model). Kept, so "what was
    # I working on" has an answer after an interruption. "I'm working on it" is a
    # reply to her, not news.
    if re.fullmatch(r"i'?m (?:still |just )?(?:working on|in the middle of|halfway through) (?!it\b|that\b|this\b|something\b|stuff\b|things\b)"
                    r"(?:the |my |a |an |our |some )?[a-z][a-z0-9&.' -]{1,60}", low) and "?" not in text:
        return {"command": {"kind": "note", "text": _as_he_said(text, low)},
                "say": "Noted. Ask me \"what was I working on\" and I'll tell you."}

    # "I started my new job on September 1", "I started working at Acme in
    # March" (2026-10-07: the planner, and a task tick). The day his job
    # began is a note in his words; "how long have I been at my job" reads it.
    if re.fullmatch(r"i (?:just |only )?(?:started|began) (?:my |a |the )?(?:new )?(?:job|work|working|position|role)"
                    r"(?: (?:at|with|for) [a-z0-9][a-z0-9&.' -]{1,30}?)?"
                    r" (?:on |in |back in |last |this )?(?:today|yesterday|week|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday"
                    r"|" + SPOKEN_DATE + r"|" + _MONTH + r"(?: \d{1,2}(?:st|nd|rd|th)?)?)(?:,? \d{4})?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
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
         or re.fullmatch(r"(?:i )?(?:just |already )?(?P<w>(?![a-z]*eed\b|used\b)[a-z]+ed (?:the |my |a )?.+)", low))
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

    # "When do I have an hour free this week", "how much free time do I have
    # today" (2026-10-07: to the planner). The same doors, with the length.
    m = re.fullmatch(r"(?:when|where) (?:do|will|can) i (?:have|get|find) (?:an? |(?P<n>\d{1,3}|two|three|half an) )?"
                     r"(?P<u>hours?|minutes?|mins?)(?: free| open| to myself)?(?: (?P<when>today|tomorrow|this week|next week"
                     r"|this weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?", low)
    if m:
        n = {"two": 2, "three": 3, "half an": 0.5}.get(m.group("n") or "", None)
        n = n if n is not None else (int(m.group("n")) if (m.group("n") or "").isdigit() else 1)
        minutes = int(n * 60) if m.group("u").startswith("hour") else int(n)
        when = m.group("when") or "this week"
        if when in ("this week", "next week", "this weekend"):
            return {"command": {"kind": "calendar_find_free", "when": when, "minutes": max(15, minutes)}, "say": None}
        day, _part = _spoken_when(when)
        if day:
            return {"command": {"kind": "free_time", "day": day, "minutes": max(15, minutes)}, "say": None}
    m = re.fullmatch(r"how much (?:free|spare|open) time (?:do i have|have i got|is there)(?: left)?(?: (?P<when>today|tomorrow"
                     r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?", low)
    if m:
        day, _part = _spoken_when(m.group("when") or "today")
        if day:
            return {"command": {"kind": "free_time", "day": day}, "say": None}
    # "Cancel everything tomorrow", "clear my afternoon" (2026-10-07: to the
    # planner). His calendar is not hers to empty; said plainly.
    if re.fullmatch(r"(?:cancel|clear|wipe|drop) (?:everything|all|all my plans|my plans|my (?:morning|afternoon|evening|day|night|schedule))"
                    r"(?: (?:today|tomorrow|tonight|on [a-z]+|this [a-z]+|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?", low):
        return {"command": None,
                "say": "I can't cancel things on your calendar yet - I can only add holds to it, so clear it there. "
                       "If I pencilled something in, say \"cancel my\" and what it is, and I'll take it off."}
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
        # "Do I have anything on Tuesday" with a doctor's appointment on it
        # answered "Free Tuesday 9 am to 2 pm and 3 pm to 5 pm" (2026-10-07):
        # what IS on the day is the answer, and the free time only when
        # nothing is.
        said_day = (m.group(1) or "today").strip()
        if day and not part and said_day in ("today", "tomorrow", "monday", "tuesday", "wednesday", "thursday",
                                             "friday", "saturday", "sunday"):
            from aletheia import quick
            try:
                on = quick._agenda_and_reminders(said_day)
            except Exception:
                on = None
            if on and (not on.startswith("Nothing on your calendar") or ", but " in on):
                return {"command": None, "say": on}
        # "Do I have anything tomorrow morning" with the dentist at 9 said
        # "Free this morning 10 am to 12:15 pm" (2026-10-08). The same rule
        # for a part of a day: what is on it first.
        if day and part:
            from aletheia import quick
            try:
                on = quick._agenda_part(f"what do i have {said_day}")
            except Exception:
                on = None
            if on and not on.startswith("Nothing on your calendar"):
                return {"command": None, "say": on}
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
    # "Do I have class tomorrow" is his week, not a file (2026-10-08: a file
    # search for "class tomorrow"). A day at the end is never in a file name.
    if m and re.match(r"(?:do i have|have i got) ", low) and re.search(
            r" (?:today|tonight|tomorrow|this weekend|next week|(?:on |this |next )?(?:monday|tuesday|wednesday|thursday"
            r"|friday|saturday|sunday))$", m.group(1)):
        m = None
    # "Do I have eggs" a turn after "I'm out of eggs" searched his
    # Documents (2026-10-08). Food and household things are the kitchen.
    if m and re.match(r"(?:do i have|have i got) ", low):
        pantry = _in_the_kitchen(m.group(1))
        if pantry:
            return {"command": None, "say": pantry}
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
    # "Reply saying thanks" right after she read him an email (2026-10-07:
    # to the planner). The reply is a draft to its sender, waiting on his tap
    # like every other email. "Forward it" has no door, and says so.
    _said, answered = _previous_turn()
    read = re.match(r"From (?P<who>.+?) — (?P<subject>.+?): ", answered or "")
    if read:
        m = re.fullmatch(r"(?:reply|respond|write back|answer)(?: to (?:it|that|him|her|them))?(?: and)?"
                         r"(?: saying| say| that|:|,)? (?P<body>.+)", low)
        if m and not re.fullmatch(r"(?:to )?(?:it|that|him|her|them)", m.group("body")):
            who = read.group("who")
            address = re.search(r"<([^<>@\s]+@[^<>\s]+)>", who)
            subject = read.group("subject").strip()
            return {"command": {"kind": "email_draft", "to": address.group(1) if address else who.strip(),
                                "subject": subject if subject.lower().startswith("re:") else f"Re: {subject}",
                                "body": _as_he_said(text, m.group("body"))}, "say": None}
        if re.fullmatch(r"forward (?:it|that|this|the email)(?: to .+)?", low):
            return {"command": None, "say": "I can't forward mail. I can write a new email: say \"email Dana saying\" "
                                            "and what it should say."}
        if re.fullmatch(r"(?:archive|delete|trash|bin) (?:it|that|this|that one|this one)", low):
            return {"command": None,
                    "say": "I only read your email and write drafts - I can't delete, archive or mark messages. "
                           "Do that in your mail app."}
    # Deleting or marking mail is his: she reads it and drafts it, no more.
    if re.fullmatch(r"(?:delete|trash|archive|mark|flag|star|unsubscribe from) (?:that|this|the|my|the last|my last|all)? ?"
                    r"(?:e-?mails?|mail)(?: as (?:read|unread|spam|important))?(?: from .+)?"
                    # "Mark it as read" right after an email (2026-10-07: to the planner).
                    r"|mark (?:it|that|them|those|everything|all) (?:as )?(?:read|unread|spam|important)", low):
        return {"command": None,
                "say": "I only read your email and write drafts - I can't delete, archive or mark messages. "
                       "Do that in your mail app."}

    # "Where does my wife work" searched his Documents (2026-10-08). What
    # he said about where somebody works, or plainly not told.
    m = re.fullmatch(r"where (?:does|do) (?P<who>my [a-z][a-z' ]{1,20}?|[a-z]{2,15}) (?P<v>work|go to school|study|go to college|teach|volunteer)\s*\??", low)
    if m and m.group("who") not in ("you", "i", "we", "they", "he", "she", "it", "people"):
        who, v = m.group("who"), m.group("v")
        verb = {"work": "works", "go to school": "goes to", "study": "studies", "go to college": "goes to", "teach": "teaches",
                "volunteer": "volunteers"}[v]
        stem = verb.split()[0]
        from aletheia import quick
        for row in quick._notes():
            note = " ".join(str(row.get("text") or "").split()).rstrip(".")
            if re.match(rf"{re.escape(who)} {re.escape(stem)}\b", note.casefold()):
                return {"command": None, "say": f"You told me: {speech.as_she_says_it(note)}."}
        mine = re.sub(r"^my ", "your ", who) if who.startswith("my ") else _as_he_said(transcript, who)
        return {"command": None, "say": f"You haven't told me where {mine} {verb.split()[0]}. Say \"{_as_he_said(transcript, who)} {verb.split()[0]} at\" and where, and I'll keep it."}
    # "Where were my headphones" searched his Documents for "were my
    # headphones" (2026-10-08).
    m = re.fullmatch(r"where(?:'s| is| are| were| was)? (?:my |the )?(.+?)(?: (?:today|tonight|tomorrow|this weekend|this week|right now|now))?\s*\??", low)
    # "Note that the wifi code is on the fridge", then "where's the wifi
    # code" searched his Documents (2026-10-07). A note saying where it is
    # answers before a file search does.
    if m:
        put = _where_he_put(m.group(1))
        # "Where are the kids" searched his Documents for "kids" (2026-10-07).
        # A person is never a file.
        if not put and re.fullmatch(r"kids|children|boys|girls|son|daughter|wife|husband|partner|mom|dad|mum|parents"
                                    r"|grandma|grandpa|family|baby|sister|brother", m.group(1)):
            put = (f"You haven't told me where your {m.group(1)} {'is' if m.group(1) in ('son', 'daughter', 'wife', 'husband', 'partner', 'mom', 'dad', 'mum', 'grandma', 'grandpa', 'baby', 'sister', 'brother', 'family') else 'are'}. "
                   "I can't see where anybody is - tell me and I'll remember.")
        if put:
            return {"command": None, "say": put}
        # "The gym is at 20 Oak Ave", then "where is the gym" searched his
        # Documents for a file called gym. A place she keeps answers first.
        from aletheia import quick
        there = quick._place_where(m.group(1)) or _his_words_about(m.group(1))
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
    # "Am I busy tomorrow morning" (2026-10-08: to the planner) is the same
    # question the other way round, answered with the same free time.
    m = re.fullmatch(r"(?:when am i free|am i free|are we free|am i busy|are we busy|am i booked|will i be busy|"
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

    # "My landlord number is 555 222 3333" (2026-10-08: to the planner) is
    # "my landlord's number". His own phone, work and account numbers are not.
    m = re.fullmatch(r"my (?P<who>[a-z]{3,20}(?: [a-z]{3,20})?) (?:phone |cell )?number is (?P<n>\+?\d[\d ().-]{5,20}\d)", low)
    if m and not re.search(r"\b(?:phone|cell|mobile|home|work|office|fax|account|member|policy|routing|license|passport|social|ssn|id|card"
                           r"|order|tracking|confirmation|case|claim|reference|seat|room|locker|flight|plate|serial|pin|group|cell phone)\b", m.group("who")):
        return _interpret(f"my {m.group('who')}'s number is {m.group('n')}")
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
    # "I was born in 1995" (2026-10-08: to the planner). The year joins the
    # birthday he gave without one; on its own it is kept as the year.
    m = re.fullmatch(r"i was born in (?:the year )?((?:19|20)\d\d)", low)
    if m:
        try:
            from aletheia import memory
            day = str(memory.recall("identity", "birthday") or "").strip()
        except Exception:
            day = ""
        if day and not re.search(r"\b\d{4}\b", day):
            return {"command": {"kind": "remember", "domain": "identity", "key": "birthday",
                                "value": f"{day}, {m.group(1)}"}, "say": None}
        return {"command": {"kind": "remember", "domain": "identity", "key": "birth_year",
                            "value": m.group(1)}, "say": None}
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
    # "My email is caleb at example dot com", said out loud (2026-10-08: to the planner).
    m = re.fullmatch(r"my (?:email|e-mail|email address) is (?P<user>[a-z0-9][a-z0-9._+-]{0,40}) at (?P<host>[a-z0-9-]{1,40}(?: dot [a-z0-9-]{1,20}){1,3})", low)
    if m:
        return {"command": {"kind": "remember", "domain": "identity", "key": "email",
                            "value": m.group("user") + "@" + m.group("host").replace(" dot ", ".")}, "say": None}
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
                     # "...the meeting next Tuesday at noon" kept "next Tuesday"
                     # in the words and set it for TOMORROW (2026-10-07).
                     r"(?:next |this |on )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?: (?:morning|afternoon|evening|night))?"
                     r"(?: at [\w: ]+)?|"
                     r"at [\w: ]+|in (?:\d+|an?|half an) (?:minutes?|mins?|hours?))", low)
    if m:
        when = m.group(2).replace("tonight", "today night").replace("this ", "today ")
        again = _interpret(f"remind me to {m.group(1)} {when}")
        if (again.get("command") or {}).get("kind") in ("remind_at",):
            again["command"]["text"] = _as_he_said(text, m.group(1).strip())
            return again
        if again.get("command") is None and again.get("say") and m.group(2).startswith("next "):
            # "Which Tuesday" asked back, in his own "about" words.
            return {"command": None, "say": again["say"].replace(f" to {m.group(1)}'", f" about {m.group(1)}'")}
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
    # "Set a reminder for my mom's birthday", "remind me about Sam's
    # birthday" (2026-10-08: to the planner, and a lookup): on the day, the
    # way "remind me on my mom's birthday" is already planned.
    m = re.fullmatch(r"(?:(?:set|make|add|create|put in|give me) (?:a |me a )?reminder (?:for|about|of|on)|remind me (?:about|of))"
                     r" (?P<whose>(?:my |our )?[a-z][a-z' ]{0,25}?(?:'s|s'|s)) (?:birthday|bday)", low)
    if m and m.group("whose").strip() not in ("it's", "its", "this", "that's", "thats"):
        whose = re.sub(r"(?<=[a-z])s$", "'s", m.group("whose").strip()) if not m.group("whose").endswith(("'s", "s'")) else m.group("whose")
        return _interpret(f"remind me on {whose} birthday")
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
                    r"brief me|catch me up(?: on (?:today|everything|things))?"
                    # "What did I miss today" (2026-10-07: to the planner).
                    r"|what did i miss(?: today| this morning| while i was (?:out|gone|away|asleep)| overnight)?"
                    # "What do I need to know today" (2026-10-07: to a model).
                    r"|what do i need to know(?: today| this morning| for today)?|what should i know (?:today|this morning|for today)"
                    r"|give me (?:a |the )?(?:summary|rundown|run-down)"
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
    # "How far is Chicago from New York" (2026-10-08) measured to a place
    # called "Chicago From New York". From home it is the trip; between
    # two other places she has nothing to measure with, and says so.
    m = (re.fullmatch(r"how (?:far|long a drive|many miles) is (?:it )?(?:from )?(?P<a>[a-z][a-z .'-]{1,40}?) (?:from|to) (?P<b>[a-z][a-z .'-]{1,40}?)", low)
         or re.fullmatch(r"(?:what(?:'s| is|s) )?the distance (?:between|from) (?P<a>[a-z][a-z .'-]{1,40}?) (?:and|to) (?P<b>[a-z][a-z .'-]{1,40}?)", low))
    if m:
        a, b = m.group("a").strip(), m.group("b").strip()
        here = ("here", "home", "my house", "me", "my place", "where i am", "it")
        if a in here or b in here:
            return {"command": {"kind": "travel_time", "place": b if a in here else a}, "say": None}
        return {"command": None,
                "say": f"I can only measure from your home to places you've saved, so I can't say how far "
                       f"{_as_he_said(text, a)} is from {_as_he_said(text, b)}."}
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
    if m and (m.group("p") or m.group("p2") or "").startswith("my "):
        # "What time does my gym close" with only "my gym opens at 5am"
        # kept (2026-10-08: to a model): what he told her, and what he didn't.
        told = _hours_he_told(m.group("p") or m.group("p2"))
        if told:
            asked = "close" if re.search(r"\bclos", low) else "open"
            if not re.search(rf"\b{asked[:4]}", told.casefold()):
                told = told.rstrip(".") + f", but not when it {asked}s."
            return {"command": None, "say": told}
    if m and not re.search(r"\b(?:it|that|this|my|your|door|window|app|file|tab|browser|calendar|spotify|chrome"
                           r"|garage|fridge|microphone|mic|ticket|application|position|job|pr|pull request)\b",
                           m.group("p") or m.group("p2") or m.group("p3") or ""):
        place = (m.group("p") or m.group("p2") or m.group("p3")).strip()
        when = (m.group("when") or m.group("when2") or "").strip()
        # "The pharmacy closes at 9 on weekdays" he told her answers it
        # before a search does (2026-10-08: searched with the note kept).
        told = _hours_he_told(place)
        if told:
            return {"command": None, "say": told}
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
                    r"|(?:is there|any) (?:bad )?traffic(?: on the way to work)?(?: right now| now| today)?"
                    r"|how long (?:is|will be|'s) (?:my|the) commute(?: today| this morning)?", low):
        if _known_place("work"):
            return {"command": {"kind": "travel_time", "place": "work"}, "say": None}
        # No address, but he told her how long the commute is and when he
        # starts (2026-10-07): that is the answer, added up and said as his.
        if low.startswith("when should i leave"):
            from aletheia import quick
            told = quick._leave_for_work()
            if told:
                return {"command": None, "say": told}
        from aletheia import quick
        half = quick._commute_told(low.startswith("when should i leave")) \
            if re.match(r"when should i leave|how long (?:is|will be|'s) (?:my|the) commute", low) else None
        if half:
            return {"command": None, "say": half}
        # "How long is my commute" with no work on file (2026-10-07: to a
        # model, which knows no better). The one thing that would let her.
        return {"command": None, "say": "I don't know where work is. Say \"work is at\" and the address, "
                                        "and I'll time the drive."}
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
    # "Add call the bank to my list for tomorrow" (2026-10-07: to the
    # planner) - the day goes on the task as its deadline.
    m = re.fullmatch(r"(?:add|put|stick) (?P<what>.+?) (?:on|to) (?:the |my )?(?P<todo>(?:to ?do|to-do|task) )?list"
                     r" (?P<day>(?:for |by |on |due )?(?:today|tonight|tomorrow|(?:this |next )?(?:monday|tuesday|wednesday"
                     r"|thursday|friday|saturday|sunday)))", low)
    # A chore said as a noun ("add laundry to my list for tomorrow",
    # 2026-10-08: to the planner) is as much a task as a verb is; nothing
    # bought has a day.
    if m and (m.group("todo") or _TASK_VERB.match(m.group("what")) or re.fullmatch(_CHORES, m.group("what"))):
        day = m.group("day")
        # "Laundry tomorrow" lost its day (one word before it); "laundry by
        # tomorrow" keeps it as the deadline.
        day = day if re.match(r"(?:for|by|on|due) ", day) else f"by {day}"
        return _new_task(_as_he_said(transcript, m.group("what")).strip() + " " + re.sub(r"^on ", "by ", day))
    m = re.match(r"(?:add|put|get|stick|throw) (.+?) (?:on|to) (?:the |my )?"
                 r"(?:shopping |grocery )?list$", low)
    if m and re.match(r"buy (?:some |more )?\S", m.group(1)):
        # "Add buy milk to my list" put "buy milk" on the shopping list.
        m = re.match(r"(?:add|put|get|stick|throw) buy (?:some |more )?(.+?) (?:on|to) (?:the |my )?"
                     r"(?:shopping |grocery )?list$", low)
    if m and not re.search(r"(?:shopping|grocery) list$", low) and (_TASK_VERB.match(m.group(1))
                                                                   or re.fullmatch(_CHORES, m.group(1))):
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
    # "AM I OVER BUDGET" (2026-10-07: to the planner, with his budget a
    # note and his spending notes beside it). Added up from what he said.
    if re.fullmatch(r"(?:am i (?:over|under|within|on) (?:my |the )?(?:[a-z ]{1,15} )?budget(?: this (?:week|month))?"
                    r"|how much (?:is |do i have )?left (?:in|of|on) (?:my|the) (?:[a-z ]{1,15} )?budget(?: this (?:week|month))?"
                    r"|how(?:'s| is) my (?:[a-z ]{1,15} )?budget(?: looking| doing)?(?: this (?:week|month))?"
                    r"|how much (?:of my|budget do i have) (?:[a-z ]{1,15} )?(?:budget )?(?:is )?left)\s*\??", low):
        from aletheia import quick
        told = quick._budget(low)
        if told:
            return {"command": None, "say": told}
    if re.fullmatch(r"(?:what (?:did|have) i spen[dt](?: .*)?"
                    r"|how much (?:did|have) i spen[dt](?: .*)?"
                    r"|what(?:'s| is| are)? my (?:spending|expenses|"
                    r"transactions)(?: .*)?"
                    r"|show me my (?:spending|transactions|expenses)(?: .*)?"
                    r"|where (?:did|is) my money (?:go|going)(?: .*)?)"
                    r"\s*\??", low):
        # "I spent 40 dollars on groceries" is kept as a note (2026-10-07),
        # and "how much did I spend this week" answered that there was no
        # bank - a writer with no reader. What he told her is added up first.
        from aletheia import quick
        told = quick._spent(low)
        if told:
            return {"command": None, "say": told}
        return {"command": {"kind": "money", "about": "spending"}, "say": None}

    if re.fullmatch(r"(?:when is the car due|car service|"
                    r"does the car need anything|check the car|"
                    # Mileage is the number on the record she already
                    # reads, and asking for it went to the planner.
                    r"(?:what(?:'s| is|s)? )?(?:my |the )?car'?s? "
                    r"(?:mileage|milage)|"
                    r"how many miles (?:are |are there |do i have |have i got )?on (?:my|the) car|"
                    # "What's my mileage" (2026-10-08: to a model)
                    r"what(?:'s| is|s)? my (?:mileage|milage)|"
                    r"what(?:'s| is|s)? the mileage(?: on (?:my|the) car)?)", low):
        # "My car's mileage is 45000" is a note (2026-10-07); with no
        # vehicle on record, what he told her is the answer.
        from aletheia import quick
        for row in quick._notes():
            said = " ".join(str(row.get("text") or "").split())
            if re.match(r"(?:my|the|our) (?:car|truck|van|suv)(?:'s|s)? (?:mileage|milage|odometer|miles?) (?:is|are|reads?|says?) .*\d"
                        r"|(?:my|the|our) (?:car|truck|van|suv) (?:has|is at|is on|just hit|hit) (?:about |around |over )?\d[\d,]*", said.casefold()):
                return {"command": None, "say": f"You told me: {speech.as_she_says_it(said).rstrip('.')}."}
        return {"command": {"kind": "car"}, "say": None}
    # "MY CAR NEEDS AN OIL CHANGE" (2026-10-07: to the planner) - a thing to
    # do, on his list, in words he would say back.
    m = re.fullmatch(r"(?:my|the|our) (?P<v>car|truck|van|suv|bike|motorcycle) needs (?:an? |its |some |to get (?:an? )?)?"
                     r"(?P<what>oil change|tune[- ]up|new tires|tires|brakes|new brakes|inspection|smog check|emissions test|alignment"
                     r"|wash|car wash|service|servicing|tire rotation|battery|new battery|wipers|new wipers|registration|detailing"
                     r"|to be (?:washed|serviced|inspected|registered))(?: soon| this week| this month)?", low)
    if m:
        what = re.sub(r"^to be ", "", m.group("what"))
        if what in ("washed", "serviced", "inspected", "registered"):
            return _new_task(f"get the {m.group('v')} {what}")
        return _new_task(f"get the {m.group('v')} {'an ' if what[0] in 'aeiou' else 'a ' if not what.endswith('s') else ''}{what}")
    # "THE SMOKE DETECTOR NEEDS A NEW BATTERY", "the gutters need cleaning"
    # (2026-10-07: to the planner) - a job about the house, on his list in
    # words he would say back. "The plants need watering every 3 days" is
    # the reminder he would have asked for.
    m = re.fullmatch(r"(?:my|the|our) (?P<t>smoke (?:detector|alarm)|carbon monoxide (?:detector|alarm)|furnace|ac|a/c|air conditioner"
                     r"|dishwasher|washer|washing machine|dryer|fridge|refrigerator|freezer|sink|toilet|faucet|shower|bathtub|tub|gutters?"
                     r"|lawn|grass|roof|fence|deck|plants?|garden|house|kitchen|bathroom|garage|yard|hedges?|pool|hot tub|water heater"
                     r"|air filter|filter|oven|stove|microwave|windows?|carpets?|floors?|car seat|printer|bike|lights?|light bulb|doorbell)"
                     r" needs? (?P<what>.{3,40}?)(?P<when> soon| this week| this weekend| this month| this fall| this spring| today| tomorrow)?"
                     r"(?: every (?P<n>\d{1,2}|other|two|three|four|five|six|seven) days?)?", low)
    if m:
        thing, what = m.group("t"), m.group("what")
        verbs = {"cleaning": "clean", "cleaned": "clean", "fixing": "fix", "fixed": "fix", "mowing": "mow", "mowed": "mow",
                 "watering": "water", "watered": "water", "painting": "paint", "painted": "paint", "replacing": "replace",
                 "replaced": "replace", "repairing": "repair", "repaired": "repair", "servicing": "service",
                 "serviced": "service", "emptying": "empty", "emptied": "empty", "trimming": "trim", "trimmed": "trim",
                 "changing": "change", "changed": "change", "descaling": "descale", "defrosting": "defrost",
                 "weeding": "weed", "vacuuming": "vacuum", "unclogging": "unclog", "sealing": "seal", "staining": "stain",
                 # "The plants need water" (2026-10-08: to the planner).
                 "water": "water", "raking": "rake", "fertilizing": "fertilize", "fertilizer": "fertilize", "a trim": "trim",
                 "a cut": "mow", "cutting": "mow" if thing in ("lawn", "grass") else "cut"}
        word = re.sub(r"^to be ", "", what)
        if m.group("n"):
            if word in verbs:
                n = {"other": "2", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7"}.get(m.group("n"), m.group("n"))
                return _interpret(f"remind me to {verbs[word]} the {thing} every {n} days")
        elif word in verbs:
            return _new_task(f"{verbs[word]} the {thing}{m.group('when') or ''}")
        else:
            new = re.fullmatch(r"(?:a |an )?new (?P<part>[a-z][a-z ]{1,20})", what)
            if new:
                return _new_task(f"replace the {thing} {new.group('part')}{m.group('when') or ''}")
    # "PICK UP LEO AT 3" (2026-10-07: to the planner). An errand with a time
    # on it, said as a note to himself, is the reminder he would have asked for.
    if re.fullmatch(r"(?:pick up|drop off|collect|get) (?!milk\b|groceries\b)[a-z][a-z' ]{1,25} (?:at|by) \d{1,2}(?::\d\d)?(?: ?(?:am|pm))?"
                    r"(?: today| tomorrow)?", low):
        got = _interpret("remind me to " + text.strip())
        if got and (got.get("command") or {}).get("kind") == "remind_at":
            return got

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
        # "Clear my calendar Friday" (2026-10-08: "I can't cancel things",
        # though the holds she pencilled in are hers to take off). Name them,
        # one by one - emptying a day is not one word.
        day_word = re.search(r"\b(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)$", low)
        held = _her_holds_on(day_word.group(1)) if day_word else []
        if held:
            from aletheia import speech as _sp_clear
            names = [f"{e.get('title') or 'a hold'} at {t.strftime('%I:%M %p').lstrip('0').replace(':00 ', ' ').lower()}" for t, e in held]
            return {"command": None,
                    "say": f"On {day_word.group(1).capitalize()} I pencilled in {_sp_clear.and_list(names)}. Say \"cancel\" and which, and I'll take it off. "
                           "Anything else that day is on your own calendar, so clear it there."}
        return {"command": None,
                "say": "I can't cancel things on your calendar yet - I can only add holds to it. "
                       "If that's a reminder of mine, tell me what it's for and I'll turn it off."}
    # "Remind me to take my antibiotics 3 times a day" (2026-10-07: asked
    # "when should I remind you to take my antibiotics 3 times a day").
    m = re.fullmatch(r"remind me (?:to )?(?P<what>.+?) (?:(?:\d|two|three|four|five|six) times|twice) (?:a|per|each|every) day", low)
    if m:
        what = m.group("what")
        return {"command": None,
                "say": f'At what times? Say "remind me to {what} every day at 8 am, 2 pm and 8 pm" and I\'ll set one for each.'}
    # "I'm going to the doctor tomorrow at 10" (2026-10-07: to the planner)
    # is "I have a doctor appointment tomorrow at 10", which is held.
    m = re.fullmatch(r"(?:i'?m|i am|we'?re|we are) (?:going to|seeing|off to|headed to|heading to) (?:the |my |our )?"
                     r"(?P<who>doctor|doctor'?s|dentist|vet|eye doctor|optometrist|dermatologist|therapist|chiropractor"
                     r"|physical therapist|physio|barber|hairdresser|salon|orthodontist|pediatrician|allergist|cardiologist)"
                     r"(?P<when> (?:today|tonight|tomorrow|on [a-z0-9 ]+?|this [a-z]+|next [a-z]+|monday|tuesday|wednesday|thursday"
                     r"|friday|saturday|sunday)(?: morning| afternoon| evening)?(?: at \d{1,2}(?::\d\d)?(?: ?[ap]m)?)"
                     r"| at \d{1,2}(?::\d\d)?(?: ?[ap]m)?(?: (?:today|tomorrow|on [a-z0-9 ]+?|monday|tuesday|wednesday|thursday"
                     r"|friday|saturday|sunday))?)", low)
    if m:
        who = re.sub(r"'?s$", "", m.group("who"))
        held = _interpret(f"i have a {who} appointment{m.group('when')}")
        if (held.get("command") or {}).get("kind") == "calendar_hold":
            return held
    # "Remind me to renew my registration in March" (2026-10-07: to the
    # planner) is the first of that month, the way "next month" already is.
    months = r"(?P<mon>january|february|march|april|may|june|july|august|september|october|november|december)"
    m = (re.fullmatch(r"remind me (?P<what>to .{2,80}?) in (?:early )?" + months, low)
         or re.fullmatch(r"remind me in (?:early )?" + months + r" (?P<what>to .{2,80})", low))
    if m and not re.search(r"\b(?:on|at|by|every|each)\b \d|\bevery\b", m.group("what")):
        import datetime as _dt_mon
        from aletheia import localtime as _lt_mon
        # This month's first has passed; "in October" said in October is not next year.
        if _dt_mon.datetime.now(_lt_mon.operator_tz()).strftime("%B").casefold() != m.group("mon"):
            return _interpret(f"remind me {m.group('what')} on {m.group('mon')} 1")
    # "I loved the Thai place", "I'm thinking about getting a dog", "I want
    # to try that new Thai place" (2026-10-07: every one to the planner).
    # What he thinks and wants, kept in his words for the question later.
    if re.fullmatch(r"(?:i|we) (?:really |absolutely |totally |kind of |kinda )?(?:loved|liked|hated|enjoyed|didn'?t like|did not like"
                    r"|didn'?t enjoy|did not enjoy) (?!it\b|that\b$|this\b$|them\b|you\b|him\b|her\b)(?:the |that |this |our |my )?"
                    r"[a-z0-9][a-z0-9' -]{1,40}", low) \
            or re.fullmatch(r"(?:i'?m|i am|we'?re|we are) (?:thinking|thinkin) (?:about|of) (?:getting|buying|doing|trying|starting|taking"
                            r"|learning|moving|going|adopting|selling|switching|joining|quitting|making"
                            # "I'm thinking about changing jobs" (2026-10-08: "I can't think").
                            r"|changing|leaving|retiring|proposing|having|asking for|applying|renting|remodeling|renovating|redoing|painting"
                            r"|upgrading|downsizing|refinancing|planting|building|opening|hiring|cutting|dropping|cancelling|canceling) [a-z0-9][a-z0-9' -]{1,50}", low) \
            or re.fullmatch(r"(?:i|we) (?:want|wanna|would like|'d like|need) to (?:try|check out|go to|visit) (?:the |that |this |a |an )?"
                            r"(?!it\b|again\b|that\b$|harder\b|bed\b|sleep\b|home\b|work\b|school\b|the bathroom\b|the toilet\b)"
                            r"[a-z0-9][a-z0-9' -]{2,50}", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I lost 2 pounds" (2026-10-07: to the planner) - a change in his
    # weight, kept for "how much weight have I lost".
    if re.fullmatch(r"i(?:'ve| have)? (?:lost|dropped|gained|put on) (?:another |about |almost |over )?\d{1,3}(?:\.\d)? ?"
                    r"(?:pounds?|lbs?|kg|kilos?)(?: (?:this|last) (?:week|month)| since [a-z ]{2,20}| so far)?", low):
        return {"command": {"kind": "note", "text": re.sub(r"^i(?:'ve| have) ", "i ", re.sub(r" (?:another|about|almost|over) ", " ", low))},
                "say": None}
    # "My car has 45000 miles on it" (2026-10-07: to the planner) - read
    # back by "what's my car's mileage".
    if re.fullmatch(r"(?:my|the|our) (?:car|truck|van|suv) (?:has|is at|is on|just hit|hit) (?:about |around |over )?"
                    r"\d[\d,]*k?(?: thousand)? miles(?: on it)?(?: now)?", low):
        return {"command": {"kind": "note", "text": low}, "say": None}
    # "I'm at 45200 miles", "I have 45,000 miles on my car" (2026-10-08: to a
    # model). A number that size is the car's, kept as the car's.
    m = re.fullmatch(r"i(?:'m| am) (?:at|on) (?:about |around |over )?(?P<n>\d{1,3},?\d{3}|\d{2,3}k)(?: miles)?(?: on (?:my|the) car)?(?: now)?"
                     r"|i (?:have|'ve got|got) (?:about |around |over )?(?P<n2>\d[\d,]*k?) miles on (?:my|the) (?:car|truck|van|suv)(?: now)?"
                     # "My car has 45000 miles" (2026-10-08: to the planner).
                     r"|(?:my|the|our) (?:car|truck|van|suv) (?:has|has got|is at|is over|has over) (?:about |around |over |just over )?(?P<n3>\d[\d,]*k?) miles(?: on it)?(?: now)?", low)
    if m and ("miles" in low or "car" in low):
        return {"command": {"kind": "note", "text": f"my car is at {m.group('n') or m.group('n2') or m.group('n3')} miles"}, "say": None}
    # "The car is making a weird noise" (2026-10-08: to the planner).
    m = re.fullmatch(r"(?:my|the|our) (?P<v>car|truck|van|suv|bike|motorcycle|washer|dryer|fridge|furnace|dishwasher|ac|a/c|heater)"
                     r" (?:is making|makes|has been making|keeps making) (?:an? |this |some )?(?P<how>[a-z]+ )?(?:noise|sound)s?(?: again| lately)?", low)
    if m:
        return _new_task(f"get the {m.group('v')} looked at - it's making {'an' if (m.group('how') or 's')[0] in 'aeiou' else 'a'} {(m.group('how') or 'strange ')}noise")
    # "Put gym on my calendar every Monday at 6" (2026-10-07: to the
    # planner). Her holds are one at a time; a weekly reminder is what she
    # can do every week, offered in words he can say back.
    m = re.fullmatch(r"(?:put|add|schedule|block(?: off)?|pencil in) (?:a |an |my )?(?P<what>[a-z][a-z' ]{1,30}?)(?: on| to| in)?(?: my| the)?"
                     r"(?: calendar)? every (?P<day>monday|tuesday|wednesday|thursday|friday|saturday|sunday|day|weekday|week)"
                     r"(?: (?:at|from) (?P<t>[0-9: ]{1,5}(?:am|pm)?|noon))?", low)
    if m:
        what, day = _as_he_said(text, m.group("what")), m.group("day")
        when = f"every {day.capitalize() if day not in ('day', 'weekday', 'week') else day}" + (f" at {m.group('t').strip()}" if m.group("t") else "")
        return {"command": None,
                "say": f"I can only pencil things in one at a time, not every week. I can remind you {when} - "
                       f"say \"remind me {when} to {what}\"."}
    # "Rename my Thursday meeting to standup" (2026-10-07: to the planner).
    # Her own hold, the same time and length, under the new name.
    m = re.fullmatch(r"(?:rename|retitle|change the name of|call) (?:my |the )?(?P<what>[a-z0-9][a-z0-9:' ]{0,40}?) (?:to|as) "
                     r"(?P<new>[a-z0-9][a-z0-9 ,.'&-]{1,60})", low)
    if m and not _names_one_open_task(m.group("what")):
        hold, why = _one_of_her_holds(m.group("what"))
        if hold:
            import datetime as dt
            from aletheia import calendar as _cal_name
            was = _cal_name.parse_time(hold["start"])
            ends = _cal_name.parse_time(hold["end"]) if hold.get("end") else was + dt.timedelta(hours=1)
            return {"command": {"kind": "calendar_hold", "title": _as_he_said(text, m.group("new")), "start": was.isoformat(),
                                "minutes": max(5, int((ends - was).total_seconds() // 60)),
                                "replaces": hold["start"], "was_title": hold["title"]}, "say": None}
        if why:
            return {"command": None, "say": "More than one hold of mine matches that - say which by its time."}
    # "Push my 2pm back an hour" (2026-10-07: to the planner). Her own hold
    # moves by that much, the same length; anything else is said plainly.
    m = re.fullmatch(r"(?:push|move|bump|shift|slide) (?:my |the )?(?P<what>[a-z0-9][a-z0-9:' ]{0,30}?) "
                     r"(?P<dir>back|forward|up|later|earlier) (?:by )?(?P<n>an?|half an|\d{1,3}) "
                     r"(?P<u>hours?|minutes?|mins?)", low)
    if m and (m.group("what") in ("it", "that", "this", "them", "everything", "all")
              or "reminder" in m.group("what") or "alarm" in m.group("what") or "timer" in m.group("what")):
        m = None  # her own reminder: moved further down
    if m and not _names_one_open_task(m.group("what")):
        import datetime as dt
        n = {"a": 1, "an": 1, "half an": 0.5}.get(m.group("n")) or int(m.group("n"))
        delta = dt.timedelta(hours=n) if m.group("u").startswith("hour") else dt.timedelta(minutes=n)
        if m.group("dir") in ("forward", "up", "earlier"):
            delta = -delta
        hold, why = _one_of_her_holds(m.group("what"))
        if hold:
            from aletheia import calendar as _cal_push
            was = _cal_push.parse_time(hold["start"])
            ends = _cal_push.parse_time(hold["end"]) if hold.get("end") else was + dt.timedelta(hours=1)
            return {"command": {"kind": "calendar_hold", "title": hold["title"], "start": (was + delta).isoformat(),
                                "minutes": max(5, int((ends - was).total_seconds() // 60)),
                                "replaces": hold["start"]}, "say": None}
        if why:
            return {"command": None, "say": "More than one hold of mine matches that - say which by its time."}
        return {"command": None,
                "say": "I can't move things on your calendar yet - I can only add holds to it. "
                       "Move it in your calendar, and if you want a hold at the new time, tell me when."}
    # "I can't make it to my 3pm" (2026-10-07: to the planner).
    m = re.fullmatch(r"i (?:can't|cannot|can not|won't|will not) make (?:it to )?(?:my |the )"
                     r"(?P<what>[a-z0-9][a-z0-9:' ]{0,30}?)(?: (?:today|tomorrow|tonight))?", low)
    if m and m.group("what") not in ("it", "deadline", "rent", "payment", "it in time"):
        hold, why = _one_of_her_holds(m.group("what"))
        if hold:
            return {"command": None,
                    "say": f'That one is a hold of mine. Say "cancel my {m.group("what")}" and I\'ll take it off.'}
        return {"command": None,
                "say": "I can't change things on your calendar yet - I can only add holds to it, so cancel it there. "
                       "If someone should hear you can't make it, say \"email\" or \"text\" and who, and what to say."}
    # "I moved my doctors appointment to the 21st", "my meeting got pushed
    # to 4" (2026-10-08: to the planner). Said as news, it is the same move;
    # only when the move itself is one she can make.
    past = re.fullmatch(r"(?:i |they |we |he |she |the [a-z]+ )?(?:moved|rescheduled|pushed|changed|bumped|shifted)"
                        r" (?P<rest>(?:my |the |our )[a-z][a-z' ]{1,40}? (?:back )?(?:to|till|until) .+)", low) \
        or re.fullmatch(r"(?P<w>(?:my |the |our )[a-z][a-z' ]{1,40}?) (?:got|was|has been|is|just got) (?:moved|rescheduled"
                        r"|pushed|changed|bumped|shifted)(?: back)? (?P<t>(?:to|till|until) .+)", low)
    if past:
        again = _interpret("move " + (past.group("rest") if past.groupdict().get("rest") else f"{past.group('w')} {past.group('t')}"))
        if ((again or {}).get("command") or {}).get("kind") in ("calendar_hold", "task_change"):
            return again
    # "MOVE MY DENTIST APPOINTMENT TO FRIDAY" (2026-10-07: to the planner,
    # which has no door to his calendar's events). Said plainly, unless the
    # words pick out one of his tasks, which can be moved.
    m = re.fullmatch(r"(?:move|reschedule|push|shift|bump) (?:my |the )?(?P<what>.*?(?:appointment|meeting|call|lunch|dinner"
                     r"|breakfast|interview|\d{1,2}(?::\d\d)?\s*(?:am|pm|o'?clock))(?: with [a-z' ]+?)?)(?: back)? (?:to|till|until|for) .+", low)
    # "Move my haircut to 11" after she pencilled the haircut in (2026-10-07:
    # to the planner) - any word that names one of her own holds.
    if not m:
        m = re.fullmatch(r"(?:move|reschedule|push|shift|bump) (?:my |the )?(?P<what>[a-z][a-z' ]{1,30}?)(?: back)? "
                         r"(?:to|till|until) .+", low)
        if m and not _one_of_her_holds(m.group("what"))[0]:
            m = None
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
            if _is_bare_hour(words) and hour < 12 and (was.hour >= 12 or hour <= EARLIEST_BARE_HOUR):
                hour += 12
            new = was.replace(hour=hour, minute=minute)
            return {"command": {"kind": "calendar_hold", "title": hold["title"], "start": new.isoformat(),
                                "minutes": max(5, int((ends - was).total_seconds() // 60)),
                                "replaces": hold["start"]}, "say": None}
        # "Move my doctors appointment to the 21st" (2026-10-08: refused as
        # his calendar's): her own hold, the new day, its own time unless he
        # named one, the same length.
        day_to = re.fullmatch(r"(?:on )?(?P<day>.+?)(?: at (?P<t>.+))?", to.group("when")) if (hold and to) else None
        day_iso = _spoken_day(day_to.group("day")) if day_to and not _spoken_time(day_to.group("day")) else None
        if hold and day_iso:
            import datetime as dt
            from aletheia import calendar as _cal, localtime
            tz = localtime.operator_tz()
            was = _cal.parse_time(hold["start"]).astimezone(tz)
            ends = _cal.parse_time(hold["end"]).astimezone(tz) if hold.get("end") else was + dt.timedelta(hours=1)
            hour, minute = was.hour, was.minute
            if day_to.group("t"):
                hhmm = _spoken_time(day_to.group("t"))
                if not hhmm:
                    return None
                hour, minute = map(int, hhmm.split(":"))
                if _is_bare_hour(day_to.group("t")) and 1 <= hour <= 7:
                    hour += 12
            new = dt.datetime.combine(dt.date.fromisoformat(day_iso), dt.time(hour, minute), tzinfo=tz)
            # "Move it to Thursday", said on a Thursday afternoon, moved a
            # 9 am hold into the morning already gone (2026-10-08). A weekday
            # whose hour has passed is next week's.
            if new <= dt.datetime.now(tz) and re.fullmatch(r"(?:on )?(?:this )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
                                                           day_to.group("day").strip()):
                new += dt.timedelta(days=7)
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
    # "DELETE THE DRAFT" went to the planner and "cancel the draft" was
    # prepared as cancelling a SUBSCRIPTION called draft (2026-10-07). A
    # draft waiting on an approval is that approval's to deny; a held one
    # is put away unsent.
    m = re.fullmatch(r"(?:delete|discard|cancel|scrap|drop|throw away|throw out|trash|bin|get rid of|kill|toss|lose)"
                     r" (?:the |that |this |my )?(?:last |latest |newest )?(?:e-?mail )?draft(?: e-?mail)?"
                     r"(?: (?:to|for|about) (?P<w>[a-z0-9][a-z0-9 '.@-]{1,40}))?"
                     r"|(?:delete|discard|scrap|cancel) (?:the |my )?e-?mail (?:draft )?(?:to|for) (?P<w2>[a-z0-9][a-z0-9 '.@-]{1,40})"
                     r"|don'?t send (?:it|that|the (?:draft|e-?mail))(?: after all)?", low)
    if m:
        which = (m.group("w") or m.group("w2") or "").strip()
        from aletheia import mail
        try:
            held = mail.held_drafts()
        except Exception:
            held = []
        waiting = [a for a in policy.all_approvals() if a["state"] == "PENDING"
                   and str(a.get("capability") or "") == "email.send"]
        if not held and len(waiting) == 1 and not which:
            return {"command": {"kind": "deny", "id": waiting[0]["id"], "because": "draft discarded by voice"}, "say": None}
        if not held and waiting:
            return {"command": None, "say": _offer_choice(waiting, verb="deny")}
        if not held:
            return {"command": None, "say": "There's no draft waiting."}
        return {"command": {"kind": "draft_discard", **({"which": which} if which else {})}, "say": None}
    m = re.fullmatch(r"cancel (?:my |the )?(.+?)"
                     r"(?: membership| subscription| plan)?", low)
    if (m and 2 <= len(m.group(1)) <= 60
            and not _HERS_NOT_A_SERVICE.search(m.group(1))):
        # "Cancel my haircut" after she pencilled it in (2026-10-07: it was
        # prepared as cancelling a SUBSCRIPTION called haircut). Her own
        # hold that the words name is the thing.
        hold, why = _one_of_her_holds(m.group(1))
        if hold:
            return {"command": {"kind": "hold_release", "title": hold["title"], "start": hold["start"]}, "say": None}
        if why:
            return {"command": None, "say": "More than one hold of mine matches that - say which by its time."}
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

    # "Skip tomorrow's pill reminder", "pause my reminders for today"
    # (2026-10-07: to the planner). Neither is a door she has; said plainly,
    # with the two that are.
    m = re.fullmatch(r"(?:skip|cancel just|don'?t remind me about) (?:(?P<d1>tomorrow|today|tonight)'?s? |(?P<d0>the next|my next|the) )?(?:my )?"
                     r"(?P<w>[a-z][a-z' ]{1,30}?) (?P<sort>reminder|alarm)"
                     r"(?: (?P<d2>tomorrow|today|tonight|this time|once|just once|next time))?", low)
    if m and m.group("w") not in ("next", "the next"):
        once = m.group("d1") or m.group("d2") or "next"
        once = "next" if once in ("this time", "once", "just once", "next time") else once
        which = "wake up" if m.group("sort") == "alarm" and m.group("w") in ("my", "the", "morning") else m.group("w")
        return {"command": {"kind": "reminder_off", "which": which, "once": once}, "say": None}
    if re.fullmatch(r"(?:pause|suspend|hold|stop|mute|silence) (?:all )?(?:my |the )?(?:reminders|alarms)"
                    r"(?: for (?:today|tonight|the day|the rest of the day|now|a while|the weekend|this week))?", low):
        return {"command": None,
                "say": "I can't pause reminders yet. Say \"what reminders do I have\", then \"turn off\" and the one "
                       "you don't want."}
    # DO NOT DISTURB is the one switch of hers this can honestly mean: her
    # own notices go quiet for a while (`notify_snooze`). Windows' Focus
    # Assist is not a door she has, and "turn on do not disturb" waited 78 s
    # on her own model to ask what he meant (2026-09-23).
    m = re.fullmatch(r"(?:turn on|enable|switch on|put me on|set|go|activate) (?:do not disturb|dnd|quiet mode|focus mode|"
                     r"silent mode)(?: mode)?(?: for (?P<n>\d+) (?P<unit>minutes?|mins?|hours?|hrs?))?"
                     # A bare "do not disturb" (2026-10-07: to the planner).
                     r"|(?:do not disturb|dnd)(?: mode)?(?: on| please)?"
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
        return {"command": {"kind": "notify_snooze", "quiet": True,
                            "minutes": max(1, min(_spoken_minutes(span.group("span")), 60 * 24 * 7))}, "say": None}
    if m:
        n = next((m.group(k) for k in ("n", "n2", "n3", "n4") if m.group(k)), "")
        unit = next((m.group(k) for k in ("unit", "unit2", "unit3", "unit4") if m.group(k)), "")
        minutes = int(n) * (60 if unit.startswith(("h",)) else 1) if n else 60
        # Quiet, not only one notice put away: "I'm in a meeting" snoozed
        # the latest and she spoke the next one into his meeting (2026-10-07).
        return {"command": {"kind": "notify_snooze", "minutes": max(1, min(minutes, 60 * 24 * 7)),
                            **({} if m.group(0).startswith(("snooze", "pause")) else {"quiet": True})},
                "say": None}

    # A LOST OBJECT is not a file. "Find my keys" planned for a minute and
    # came back "she does not know a folder called on my computer" (2026-09-23).
    # WHERE HE PUT IT (2026-10-07): "I put my keys in the drawer" went to the
    # planner, and "where are my keys" said she had no eyes - with the note
    # that would have answered it never written. A note in his words, read
    # back by the question.
    # "I moved the keys to the hook" (2026-10-08: to the planner).
    m = re.fullmatch(r"(?:i (?:put|left|stuck|keep|hid|placed|moved)|i've (?:put|left|moved)|i have (?:put|left|moved)) (?:my |the |our )"
                     r"(?P<thing>[a-z][a-z' ]{1,25}?) (?:in|on|at|under|by|behind|next to|inside|near|in the|on top of|to|into|onto) .+"
                     r"|(?:my|the|our) (?P<thing2>[a-z][a-z' ]{1,25}?) (?:are|is) (?:in|on|under|behind|next to|inside|on top of) "
                     r"(?:the|my|our|a) .+", low)
    # An appointment "is on the 15th" is a date, not a shelf (2026-10-07).
    if m and not re.search(r"\b(?:car|calendar|list|schedule|computer|pc|account|name|password|birthday"
                           r"|appointment|appt|meeting|interview|call|lunch|dinner|class|flight|haircut|checkup|exam"
                           # "The party is on the 24th at 7" (2026-10-08: kept as where he put it).
                           r"|party|wedding|shower|game|concert|recital|practice|conference|review|test|recital|reunion|trip|vacation)\b",
                           m.group("thing") or m.group("thing2") or "") \
            and not re.search(r"\b(?:on|in) the \d{1,2}(?:st|nd|rd|th)\b", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I can not find my phone", "the remote is missing" (2026-10-08: to the
    # planner) ask the same thing.
    lost = re.fullmatch(r"i can not find (?:my |the )?(?P<t>[a-z][a-z' ]{1,25}?)|(?:my|the|our) (?P<t2>(?:tv |car |house |spare )?(?:keys?|phone|wallet|glasses|sunglasses|remote|bag|purse|backpack|shoes?|charger|headphones|earbuds|airpods|passport|watch|ring"
                        r"|jacket|coat|umbrella|laptop|ipad|tablet|badge|license|id|credit card|debit card|card|controller|scissors|tape measure|drill|hat))"
                        r" (?:is|are) (?:missing|gone|lost|nowhere to be found)", low)
    if lost:
        return _interpret(f"where is my {lost.group('t') or lost.group('t2')}")
    m = re.fullmatch(r"(?:find|where(?:'s| are| is| were| was| did i (?:last )?(?:put|leave|have|see|use|set))|locate|look for|i lost|i(?:'ve| have) lost|i can'?t find|i cannot find"
                     r"|have you seen|i misplaced) (?:my |the )?"
                     r"(?P<thing>[a-z][a-z' ]{1,25}?)(?: (?:today|tonight|tomorrow|this weekend|this week|right now|now))?(?: please)?", low)
    if m:
        put = _where_he_put(m.group("thing"))
        if put:
            return {"command": None, "say": put}
        from aletheia import quick
        there = quick._place_where(m.group("thing"))
        if there:
            return {"command": None, "say": there}
        told = _his_words_about(m.group("thing"))
        if told:
            return {"command": None, "say": told}
    m = re.fullmatch(r"(?:find|where(?:'s| are| is| were| was| did i (?:last )?(?:put|leave|have|see|use|set))|locate|look for|i lost|i(?:'ve| have) lost|i can'?t find|i cannot find"
                     r"|have you seen|i misplaced) (?:my |the )?"
                     r"(?P<thing>keys|phone|wallet|glasses|remote|car|bag|purse|shoes|charger|headphones|earbuds|passport|watch"
                     r"|jacket|coat|umbrella|sunglasses|airpods|backpack|ring|badge|hat|controller|car keys|house keys|spare key|tv remote)"
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
                        if thing in ("keys", "glasses", "shoes", "headphones", "earbuds", "sunglasses", "airpods", "car keys", "house keys")
                        else f"I can't see where your {thing} is - I have no eyes in the room. ")
                       + (f"Next time, tell me where you put them - say \"my {thing} are on the counter\" - and I'll remember."
                          if thing in ("keys", "glasses", "shoes", "headphones", "earbuds", "sunglasses", "airpods", "car keys", "house keys")
                          else f"Next time, tell me where you put it - say \"my {thing} is on the counter\" - and I'll remember.")}

    # "I found my keys" (2026-10-07: to the planner).
    m = re.fullmatch(r"(?:i )?found (?:my |the )?(?P<it>keys|phone|wallet|glasses|remote|bag|purse|shoes|charger|headphones|earbuds|passport|watch)(?: again)?!*", low)
    if m:
        them = "them" if m.group("it") in ("keys", "glasses", "shoes", "headphones", "earbuds") else "it"
        return {"command": None, "say": f"Good. Tell me where you put {them} next time and I'll remember."}
    # A PHONE CALL is a door she does not have. "Call the dentist" waited
    # two minutes on her own model (2026-09-22) for a verb nothing here
    # owns; the honest answer names the three doors she does have.
    m = re.fullmatch(r"(?:call|phone|ring|ring up|dial|give (?:a )?call to|facetime|video call|video chat with) "
                     r"(?:my |the )?(?P<who>[a-z][a-z .'-]{1,40}?)"
                     r"(?: for me| now| please| back)?", low)
    if m and _is_a_person_to_ring(m.group("who")) and not _would_spend(low):
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
                    r"|who (?:sings|is) this(?: song)?"
                    # "What was that song" (2026-10-08: to a model).
                    r"|what (?:was|is) (?:that|this|the last) song(?: called)?|what song (?:was|did) (?:that|just play|just played)"
                    r"|who (?:sang|sings) that(?: song)?", low):
        return {"command": None,
                "say": "I can't see what's playing - the media keys only play, pause "
                       "and skip. The player's window has the name."}
    # "Add this song to my favorites", "like this song" (2026-10-08: to the
    # planner): the same account a particular song needs.
    if re.fullmatch(r"(?:add|save|put) (?:this|that|the) song (?:to|in|on) (?:my )?(?:favorites|favourites|liked songs|library|playlist|[a-z ]{1,20} playlist)"
                    r"|(?:like|heart|save|favorite|favourite) (?:this|that|the) song", low):
        return {"command": None,
                "say": "I can't save songs yet - the media keys only play, pause and skip. That needs your "
                       "Spotify account connected, which is a separate thing you'd set up once."}

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
    # "TELL DANA I'LL BE LATE", "let mom know dinner's at 7" (2026-10-07: to
    # the planner). Only when the words start with someone he has - a saved
    # contact or a relation - so "tell me a joke" and "tell the story" are
    # not texts. It is a text, sent the way "text Dana ..." is: his tap first.
    m = re.fullmatch(r"(?:tell|let) (?P<rest>.+)", low)
    split = _known_person_first(m.group("rest")) if m else None
    if split and low.startswith("let "):
        know = re.fullmatch(r"know (?:that )?(.+)", split[1])
        split = (split[0], know.group(1)) if know else None
    elif split:
        said = re.sub(r"^that ", "", split[1])
        split = (split[0], said) if said and not re.match(r"(?:me|us|about|a |an |the |him|her|them)\b", said) else None
    if split and split[0] not in ("me", "us", "him", "her", "them"):
        return {"command": {"kind": "message_send", "to": split[0],
                            "body": _as_he_said(text, split[1])}, "say": None}
    # "TEXT DANA I'M RUNNING LATE" with no Dana on file (2026-10-07: to the
    # planner). One word, then a word only a sentence starts with, is a
    # name and a message - "text bob happy birthday" is still not guessed
    # at. With no number for Dana the send says so, by name.
    # "Tell Jess I'm running late" with no Jess on file is the same text
    # (2026-10-07: to the planner) - only with a body that starts the way
    # a message does, so "tell Jess about the party" is not guessed at.
    m = re.fullmatch(r"(?:send (?:a )?(?:text|message) to|text|message|tell) (?P<who>(?:my |our )?[a-z][a-z']{1,20}) "
                     r"(?:that )?(?P<body>(?:i'm|im|i|i'll|i've|we're|we|we'll|can you|could you|are you|did you|do you|don't|dont"
                     r"|where|what|when|call me|hey|hi|thanks|thank you|on my way|running late|see you|love you)\b.*)", low)
    if m and low.startswith("tell ") and re.match(r"(?:where|what|when|can you|could you|are you|did you|do you)\b", m.group("body")):
        m = None          # "tell me what you think" is not a message
    if m and m.group("who") not in ("a", "the", "my", "him", "her", "them", "it", "that", "this", "me", "back", "again",
                                    "us", "you", "thea", "everyone", "everybody", "someone", "somebody"):
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
    # "Check in is at 3" (2026-10-08: "I don't have an open conversation
    # with is at 3") is the hotel's time, not somebody to chase.
    if m and not re.search(r"\b(?:remind|task|application)\b", low) \
            and not re.match(r"(?:is|was|are|at|time|starts|opens|by|tomorrow|today)\b", m.group(1)):
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
            if not noted:
                # "Note that the dog needs a bath", "what notes do I have",
                # "forget that" (2026-10-08: "nothing was waiting") - a
                # question between does not change which note "that" is.
                try:
                    from aletheia import converse
                    turns = list(reversed(converse.recent(limit=3) or []))
                except Exception:  # noqa: BLE001
                    turns = []
                for turn in turns[1:2] if turns and re.match(
                        r"(?:what|which|how|when|where|who|do|did|is|are)\b", " ".join(str(turns[0].get("he_asked") or "").split()).casefold()
                        .removeprefix("thea ")) else []:
                    noted = re.match(r"(?:thea,? )?(?:remember that|note that|make a note(?: that| of)?|take a note(?: that)?|"
                                     r"jot down(?: that)?|write down(?: that)?)\s+(.+)",
                                     " ".join(str(turn.get("he_asked") or "").split()).casefold().rstrip(".!"))
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
    # "I'll do it later" (2026-10-07: to the planner, "I could not plan
    # that"). Nothing to do: it stays where it is, and a nudge is one
    # sentence away.
    if re.fullmatch(r"(?:ok(?:ay)?,? )?(?:i'?ll|i will|i'?m gonna|i'?m going to) (?:do|get to|deal with|handle|look at) "
                    r"(?:it|that|this|them) (?:later|tomorrow|tonight|in a bit|in a minute|another time|after)"
                    r"|(?:maybe |ok(?:ay)? )?later|not (?:right )?now|not now,? (?:maybe )?later", low):
        return {"command": None, "say": "No rush. Say \"remind me about that tonight\" if you want a nudge."}
    # "OK", "cool", "got it" with nothing waiting went to the planner and came
    # back "I could not plan that" (2026-10-07): a nod answered with an error.
    # With an approval pending, the yes/no rules above decide what it means.
    if _A_NOD.fullmatch(low) \
            and not any(a.get("state") == "PENDING" for a in policy.all_approvals()):
        return {"command": None, "say": "Okay."}
    # "ANOTHER ONE" after a joke, a fact, a coin or a pick (2026-10-07: to
    # the planner). The same ask again, and a different answer when the
    # ask has more than one.
    if re.fullmatch(r"(?:another(?: one)?|one more(?: time)?|tell me another(?: one)?|again|do it again|"
                    r"another (?:joke|fact|fun fact|one please)|one more please|more)(?: thea| please)?", low):
        said = _same_ask_again()
        if said:
            return {"command": None, "say": said}
    # "Call me back in 10 minutes" (2026-10-07: to the planner). She can't
    # place a call; the nudge is what she can do.
    m = re.fullmatch(r"(?:call|ring|ping|get back to|check (?:back )?(?:in )?with) me(?: back)? in (\d{1,3}|an?|one|two|five|ten|fifteen|twenty|thirty) "
                     r"(minutes?|mins?|hours?)", low)
    if m:
        return _interpret(f"remind me in {m.group(1)} {m.group(2)} to pick up where we left off")
    # Small talk with one honest line each (2026-10-07: all to the planner).
    if re.fullmatch(r"sing (?:me )?(?:a song|something)(?: thea)?", low):
        return {"command": None, "say": "I'd better not - I can't carry a tune. Say \"play some music\" and I'll put something on."}
    if re.fullmatch(r"do you (?:dream|sleep|eat|have feelings|get tired|get bored)", low):
        return {"command": None, "say": "No - I'm software running on your PC. I keep going while you sleep, which is the useful part."}
    if re.fullmatch(r"what(?:'s| is) the meaning of life", low):
        return {"command": None, "say": "Forty-two, if you ask a book. If you ask me: the people you love and the things you build."}
    if re.fullmatch(r"are you (?:busy|free|available)(?: right now| now)?(?: thea)?", low):
        return {"command": None, "say": "Never too busy for you. What do you need?"}
    # "I'LL BE HOME AT 6" (2026-10-07: to the planner) is a note in his
    # words, and "when will I be home" reads today's back.
    if re.fullmatch(r"i(?:'ll| will) be (?:home|back|back home|there|at work|in) (?:at|by|around|about|before|after) "
                    r"(?:\d{1,2}(?::\d\d)?(?: ?(?:am|pm))?|noon|midnight|lunch|dinner)(?: today| tonight)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    if re.fullmatch(r"(?:when|what time) (?:will|am) i (?:be )?(?:home|back|getting home|getting back)(?: today| tonight)?", low):
        try:
            import datetime as dt
            from aletheia import localtime as _lt, quick as _q, speech as _sp
            tz = _lt.operator_tz()
            today = dt.datetime.now(tz).date()
            for row in _q._notes():
                said = " ".join(str(row.get("text") or "").split())
                if not re.match(r"i(?:'ll| will) be (?:home|back)", said.casefold()):
                    continue
                at = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00")).astimezone(tz)
                if at.date() == today:
                    return {"command": None, "say": f"You said {_sp.as_she_says_it(said).rstrip('.')}."}
        except Exception:  # noqa: BLE001 - unreadable goes on as before
            pass
    # "I'M AT THE GYM" (2026-10-07: to a model). A note, which "when did I
    # last go to the gym" counts as a visit.
    if re.fullmatch(r"(?:i'?m|i am|just got) (?:at|to) the (?:gym|pool|park|library|office|doctor'?s?|dentist'?s?"
                    # "I'm at the airport" (2026-10-08: "I can't think just now").
                    r"|airport|hotel|mall|store|grocery store|post office|bank|vet|beach|stadium|train station|bus station)(?: now)?", low):
        # "I'm at the store" is the moment the list is for (2026-10-08: it
        # said "Noted." with things on his shopping list).
        say = None
        if re.search(r"\b(?:store|grocery store)\b", low):
            try:
                from aletheia import quick as _qs
                say = _qs.answer(text)
            except Exception:  # noqa: BLE001
                say = None
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": say}
    # "I STARTED A NEW JOB TODAY" (2026-10-07: to the planner). A note, so
    # "where do I work" and "when did I start my job" have it.
    if re.fullmatch(r"i (?:just )?(?:started|start|began) (?:a |my )?(?:new )?(?:job|work|position|role)(?: at [a-z0-9][a-z0-9 .&'-]{1,40})?"
                    r"(?: today| yesterday| this week| last week| on (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))?"
                    r"|i (?:just )?(?:started|start) (?:working )?at [a-z0-9][a-z0-9 .&'-]{1,40}?(?: today| yesterday| this week)?"
                    r"|i (?:just )?got (?:a|the) (?:new )?job at [a-z0-9][a-z0-9 .&'-]{1,40}", low):
        say = None
        if re.match(r"i (?:just )?got ", low):
            # news, so it gets its congratulations too (2026-10-08)
            try:
                from aletheia import quick as _q
                say = _q.answer(re.sub(r" at [a-z0-9][a-z0-9 .&'-]{1,40}$", "", low))
            except Exception:  # noqa: BLE001
                say = None
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": say}
    if re.fullmatch(r"when did i (?:start|begin) (?:my |the |this )?(?:new )?(?:job|work|position|role)(?: at [a-z0-9 .&'-]{1,40})?", low):
        try:
            from aletheia import quick as _q, speech as _sp
            for row in _q._notes():
                said = " ".join(str(row.get("text") or "").split())
                if re.match(r"i (?:just )?(?:started|began|got (?:a|the) (?:new )?job)", said.casefold()) \
                        and re.search(r"\b(?:job|work|position|role|at)\b", said.casefold()):
                    return {"command": None, "say": f"You told me {_sp.humanize_time(str(row.get('ts') or ''))}: "
                                                    f"{_sp.as_she_says_it(said).rstrip('.')}."}
        except Exception:  # noqa: BLE001
            pass
    # SAVING UP (2026-10-07: "I want to save 5000 for a vacation" and "I
    # saved 200 this week" went to the planner). Notes in his words, added
    # up by "how much have I saved".
    if re.fullmatch(r"i(?:'m| am)? (?:want to|wanna|need to|trying to|going to|gonna|plan to|saving up|saving) (?:save (?:up )?)?\$?\d[\d,]*(?:\.\d\d)?k?"
                    r"(?: dollars| bucks)?(?: (?:for|towards?) (?:a |an |my |the )?[a-z][a-z ]{1,30})?(?: by [a-z0-9 ]{2,20})?", low) \
            or re.fullmatch(r"i (?:just )?(?:saved|put away|set aside|put|moved|transferred) \$?\d[\d,]*(?:\.\d\d)?(?: dollars| bucks)?"
                            r"(?: (?:into|in|to) (?:my |the )?(?:savings(?: account)?|[a-z]+ fund))?(?: today| this week| this month| last week)?"
                            r"(?: for (?:a |an |my |the )?[a-z][a-z ]{1,30})?", low) \
            and (low.startswith("i saved") or re.search(r"savings|fund|\bfor\b", low)):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I'M COOKING DINNER" (2026-10-07: to a model). One line, and the one
    # thing she can do for a cook.
    if re.fullmatch(r"(?:i'?m|i am|we'?re|we are) (?:cooking|making|starting|about to (?:cook|make)) (?:dinner|lunch|breakfast|brunch|supper)"
                    r"(?: now| tonight| right now)?", low):
        return {"command": None, "say": "Enjoy it. Say \"set a timer for 10 minutes\" if you need one."}
    # HIS VERDICT ON A JOKE (2026-10-07: "that's not funny" went to the
    # planner). One line; "another one" is how he gets a different one.
    if re.fullmatch(r"(?:that(?:'s| is| was)|not) (?:not )?(?:funny|very funny|that funny)(?: thea)?|(?:bad|terrible|lame|awful) joke"
                    r"|that(?:'s| is| was) (?:a )?(?:bad|terrible|lame|awful|dad) joke", low):
        if re.search(r"\bnot\b|bad|terrible|lame|awful|dad", low):
            return {"command": None, "say": "Fair. Say \"another one\" and I'll try a better one."}
    if re.fullmatch(r"(?:that(?:'s| is| was) (?:funny|hilarious|a good one|good)|good one|lol|haha+|ha ha(?: ha)?)(?: thea)?", low):
        return {"command": None, "say": "Glad that one landed."}
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

    # "I finished everything" with nothing open (2026-10-08: the planner
    # offered to mark everything done, on an empty list).
    if re.fullmatch(r"i (?:finished|did|completed|got through|crossed off) (?:everything|it all|all of it|all my tasks|my (?:whole )?(?:list|to-?do list))"
                    r"(?: today| on my list)?", low):
        from aletheia import contracts
        if not [t for t in tasks.all_tasks() if str(t.get("status")) not in contracts.TASK_TERMINAL]:
            return {"command": None, "say": "Nice work. There's nothing open on your list."}
    # "Set a bedtime reminder" (2026-10-08: to the planner) needs only a time.
    if re.fullmatch(r"(?:set|make|add|create|give me) (?:a |an |my )?(?:bedtime|bed time|go to bed|sleep) reminder", low):
        return {"command": None, "say": "What time? Say \"remind me to go to bed at 10:30 every night\" and it's set."}
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
        if hhmm and found is not None and found.get("kind") == "daily":
            # "Change my pill reminder to 9" when it repeats daily (2026-10-07:
            # it became a one-off at 9 PM and the 8 am one was switched off).
            # Still daily; a bare hour keeps the half of the day it was in.
            said_text = str((found.get("command") or {}).get("text") or m.group("what"))
            hour, minute = map(int, hhmm.split(":"))
            try:
                was = int(str(found.get("time") or "0:0").split(":")[0])
            except ValueError:
                was = 0
            if _is_bare_hour(m.group("time")) and hour < 12 and (was >= 12 or hour <= EARLIEST_BARE_HOUR):
                hour += 12
            return {"command": {"kind": "remind_daily", "time": f"{hour:02d}:{minute:02d}", "text": said_text,
                                "replaces": said_text}, "say": None}
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
    # "It's at Olive Garden" right after a hold (2026-10-08: to the
    # planner): the same hold, with the place.
    place = re.fullmatch(r"(?:it'?s|it is|that'?s|that is|it'?ll be|it will be)(?: going to be)? (?:at|in) (?P<place>(?!\d{1,2}(?::\d\d)?(?: ?[ap]m)?$)"
                         r"(?!(?:the )?(?:morning|afternoon|evening|night|noon)$)[a-z0-9][a-z0-9'&., -]{1,50})", low)
    if place:
        held = _hold_as_it_is_now(_recent_ask_of("calendar_hold", "start"))
        if held and held.get("title"):
            command = {"kind": "calendar_hold", "title": held["title"], "start": held["start"],
                       "location": _as_he_said(text, place.group("place").strip().rstrip(".")), "replaces": held["start"]}
            if held.get("minutes"):
                command["minutes"] = held["minutes"]
            return {"command": command, "say": None}
    # "Make it 30 minutes" after "how long is my meeting with Tom"
    # (2026-10-08: to a model): the hold he just made, a new length.
    length = m and re.fullmatch(r"(?:(?P<n>an?|one|half an?|\d{1,3}|two|three|four|five|ten|fifteen|twenty|thirty"
                                r"|forty|forty-five|ninety) ?(?P<unit>hours?|minutes?|mins?)|(?P<hh>an? hour and a half|one and a half hours))"
                                r"(?: long)?", m.group("time").strip())
    if length:
        held = _hold_as_it_is_now(_recent_ask_of("calendar_hold", "start"))
        if held and held.get("title"):
            n = length.group("n") or ""
            amount = 1.5 if length.group("hh") else {"a": 1, "an": 1, "one": 1, "half a": 0.5, "half an": 0.5}.get(n)
            amount = amount if amount is not None else (int(n) if n.isdigit() else _spoken_amount(n))
            if amount:
                minutes = int(amount * 60) if length.group("hh") or length.group("unit").startswith("h") else int(amount)
                if 5 <= minutes <= 24 * 60:
                    return {"command": {"kind": "calendar_hold", "title": held["title"], "start": held["start"],
                                        "minutes": minutes, "replaces": held["start"]}, "say": None}
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
    # "Remember my locker is 42", then "no, it's 24" (2026-10-07: to the
    # planner). The fact just kept, said again with the right value - the
    # newest note is the one every reader reads.
    m = re.fullmatch(r"(?:(?:no|nope|sorry|oops|actually|wait|i mean|i meant)[, ]+)+(?:it'?s|it is|it was|make (?:it|that)|i meant) "
                     r"(?P<value>[a-z0-9][a-z0-9 .:/'-]{0,40})", text.lower().strip().rstrip(".!"))
    if m:
        said, answered = _previous_turn()
        kept = re.fullmatch(r"(?:remember (?:that )?|note (?:that )?)?(?P<key>(?:my|our|the) [a-z][a-z0-9' ]{1,30}?) (?:is|are) (?P<old>.+)",
                            " ".join(str(said or "").lower().split()).rstrip("."))
        if kept and answered.strip() == "Noted." and m.group("value") != kept.group("old"):
            return {"command": {"kind": "note", "text": _as_he_said(text, f"{kept.group('key')} is {m.group('value')}")},
                    "say": None}
    # "No wait I meant bread" - the lead-in said without a comma (2026-10-07:
    # to the planner) - is the same correction.
    fixed = re.sub(r"^(?:(?:no|nope|wait|oh|sorry|oops|actually|i meant|i mean)\s+)+", "", low) \
        if re.match(r"(?:no|nope|wait|oh|sorry|oops|actually)\s+(?:\w+\s+)?i mean", low) else low
    if re.match(r"(?:\W*)(?:sorry|i meant|no|nope|oops|actually|wait)\b", text.lower().strip()) \
            and re.fullmatch(r"(?:some |a |an |the )?[a-z][a-z' -]{1,30}", fixed) and len(fixed.split()) <= 4 \
            and not re.search(r"\b(?:it|that|this|them|cancel|stop|never ?mind|yes|no|okay|ok)\b", fixed):
        _said, answered = _previous_turn()
        just = re.match(r"Added to the shopping list: ([^,]+?)\.$", answered)
        if just and " and " not in just.group(1):
            item = re.sub(r"^(?:some|a|an|the) ", "", fixed)
            return {"command": {"kind": "shopping_add", "item": _as_he_said(text, item),
                                "replaces": just.group(1)}, "say": None}
    # "Add a task to call Sam", then "no I meant call Pam" (2026-10-08: to
    # the planner): the task just added, renamed.
    if re.match(r"(?:\W*)(?:sorry|i meant|no|nope|oops|actually|wait)\b", text.lower().strip()) \
            and re.fullmatch(r"[a-z][a-z0-9' -]{2,60}", fixed) and not re.search(
                r"\b(?:it|that|this|them|cancel|stop|never ?mind|yes|okay|ok)\b", fixed):
        _said, answered = _previous_turn()
        just = re.match(r"Added a task: (.+?)\.$", answered or "")
        if just and _TASK_VERB.match(fixed):
            return {"command": {"kind": "task_change", "which": just.group(1),
                                "description": _as_he_said(text, fixed)}, "say": None}

    # "CALL IN SICK FOR ME" (2026-10-07: to the planner). She can't phone
    # anybody; she can draft the email, which he sees before it goes.
    if re.fullmatch(r"(?:can you |please )?call (?:in sick|out sick|my (?:work|boss|job)(?: and tell them i'?m sick)?)(?: for me)?(?: today| tomorrow)?(?: please)?", low):
        return {"command": None,
                "say": "I can't make phone calls. I can write it - say \"email my boss that I'm out sick today\" "
                       "and I'll draft it for you to look at before it goes."}

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

    # "Remind me to bring an umbrella if it rains" (2026-10-07: to the
    # planner). A reminder fires on the clock; nothing she runs watches the
    # sky for one, so say that and offer the morning instead.
    m = re.fullmatch(r"remind me (?:to )?(?P<what>.+?) (?:if|when) it(?:'s| is)? (?:going to |gonna |supposed to )?"
                     r"(?:rains?|raining|snows?|snowing|storms?|stormy|cold|hot|freezing|windy|sunny)(?: tomorrow| today| later)?", low)
    if m:
        what = _as_he_said(transcript, m.group("what").strip())
        return {"command": None,
                "say": "I can't set a reminder off by the weather - nothing I run watches it for one. "
                       f"I can remind you in the morning anyway: say \"remind me tomorrow at 7 to {what}\"."}

    # "Change my reminder to 30 minutes", "push the reminder back 10
    # minutes", "move my reminder to 3:30" (2026-10-08: to the planner, and
    # the last said "I don't see a reminder for my"). No name is the one
    # coming up - or the one he just set, when there are several.
    m = re.fullmatch(r"(?:change|move|switch|reschedule|push|make|set|bump) (?:my |the |that |this )?reminder"
                     r"(?: (?P<dir>back|later|forward|earlier|up) (?:by )?| (?:to |for |till |until )?(?:in )?)"
                     r"(?:(?P<n>\d{1,3}|an?|half an|one|two|five|ten|fifteen|twenty|thirty|forty five|forty-five) (?P<u>minutes?|mins?|hours?)(?: from now| later)?"
                     r"|(?:at )?(?P<t>\d{1,2}(?::\d\d)?(?: ?(?:am|pm))?|noon))(?: instead| please)?", low)
    if m and not (m.group("dir") and m.group("t")):
        import datetime as _dtr
        from aletheia import localtime as _ltr, speech as _spr
        tz = _ltr.operator_tz()
        upcoming = [(at.astimezone(tz), words) for at, words in _running_once("")]
        if not upcoming:
            return {"command": None, "say": "You don't have a reminder coming up to move."}
        pick = upcoming if len(upcoming) == 1 else [u for u in upcoming
                                                    if u[1] == (_recent_ask_of("remind_at", "text") or {}).get("text")]
        if len(pick) != 1:
            return {"command": None, "say": "Which one - " + _spr.or_list([w for _, w in upcoming[:4]]) + "?"}
        was, words = pick[0]
        if m.group("t"):
            moved = _reminder_moved_to(words, m.group("t"))
            if moved:
                return moved
        else:
            n = {"a": 1, "an": 1, "one": 1, "two": 2, "five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30,
                 "forty five": 45, "forty-five": 45, "half an": 0.5}.get(m.group("n")) or int(m.group("n"))
            delta = _dtr.timedelta(hours=n) if m.group("u").startswith("hour") else _dtr.timedelta(minutes=n)
            if m.group("dir") in ("forward", "earlier", "up"):
                at = was - delta
            elif m.group("dir"):
                at = was + delta
            else:
                at = _dtr.datetime.now(tz) + delta
            if at > _dtr.datetime.now(tz):
                return {"command": {"kind": "remind_at", "at": at.replace(second=0, microsecond=0).isoformat(), "text": words,
                                    "replaces": words}, "say": None}
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
    # "Parent teacher conference is on the 22nd at 4" (2026-10-08: kept as a
    # note) is a hold told the other way round.
    told_as = re.fullmatch(r"(?:the |my |our )?(?P<t>[a-z' ]{0,30}?(?:appointment|meeting|interview|conference|recital|practice"
                           r"|party|performance review|review|presentation|exam|test|lesson|rehearsal|concert|checkup|physical|haircut))"
                           r" is (?:on )?(?P<rest>(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|the \d{1,2}(?:st|nd|rd|th)"
                           r"|(?:january|february|march|april|may|june|july|august|september|october|november|december) \d{1,2}(?:st|nd|rd|th)?)"
                           r" at \d{1,2}(?::\d\d)?(?: ?[ap]m)?)", low)
    if told_as and not re.match(r"(?:what|when|where|who|which|how)\b", low):
        again = _interpret(f"i have a {told_as.group('t')} {told_as.group('rest')}")
        if ((again or {}).get("command") or {}).get("kind") == "calendar_hold":
            again["command"]["title"] = _as_he_said(text, again["command"]["title"])
            return again
    # "Tacos for dinner on Monday" was a 6:30 hold called "tacos for dinner",
    # and "Tuesday is taco night" went to the planner (2026-10-08). A dish on
    # a day is the meal plan; dinner WITH somebody or AT a place stays a hold.
    dish = re.fullmatch(r"(?P<w>[a-z][a-z ,'&-]{1,40}?) for (?:dinner|supper) (?:on )?(?P<d>monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|tonight)(?: night)?"
                        r"|(?P<d2>monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|tonight)(?: night)? is (?P<w2>[a-z][a-z ,'&-]{1,30}?) night", low)
    if dish and not re.search(r"\b(?:with|at|reservations?|out|party|meeting|date)\b", dish.group("w") or dish.group("w2") or ""):
        what = dish.group("w") or f"{dish.group('w2')} night"
        return _interpret(f"we are having {what} {dish.group('d') or dish.group('d2')}")
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
                        # "I have a test on Friday" (2026-10-08: to the planner).
                        r"|test|exam|quiz|midterm|final|presentation|recital|tournament"
                        # "I have a performance review on the 20th" (2026-10-08: to the planner).
                        r"|performance review|annual review|review meeting|evaluation|training|orientation|webinar|workshop|conference"
                        r"|date|class|practice|haircut|checkup|check-up"
                        # "I have a physical on November 3" (2026-10-08: to the planner).
                        r"|physical|eye exam|colonoscopy|mammogram|blood work|bloodwork|lab work|ultrasound|mri|x-ray|surgery|procedure|vaccine|cleaning"
                        # "I have a parent teacher conference thursday at 4" (2026-10-08: to the planner).
                        r"|conference|lesson|rehearsal|concert|performance"
                        # "My son has a soccer game Saturday at 10" (2026-10-08: to the planner).
                        r"|game|match|meet|tryouts?|scrimmage|swim meet|track meet"
                        # "I have a one on one with Linda tomorrow at 10" (2026-10-08: to the planner).
                        r"|one on one|one-on-one|1 on 1|1:1|standup|stand-up|sync|check-in|catch up|catch-up)(?: (?:with|at) [a-z' ]+?)?)"
                        r"(?: on| this| for| next)? (?P<day>" + _cal_days + r")(?: (?P<part>morning|afternoon|evening|night))?"
                        r"(?: at (?P<time>[\w: ]+?))?", low)
    # ...and "I have tickets to the Packers game on Sunday" is not his game
    # to hold at nine: a game is a hold only with the time it starts.
    # "The game is tomorrow at 7" is one he watches (kept as a note).
    if told and re.search(r"\b(?:game|match|meet|scrimmage)$", told.group("title").strip()) and (
            not told.group("time") or re.fullmatch(r"(?:the |a )?(?:game|match|meet|scrimmage)", told.group("title").strip())):
        told = None
    # ...but "call tomorrow" alone is not a diary entry called Call.
    if told and not told.group("lead") and " " not in told.group("title").strip() \
            and not (told.group("time") or told.group("part")):
        told = None
    # ...and "book a dentist appointment friday" is somebody else's diary.
    if told and not told.group("lead") and re.match(
            r"(?:book|make|get|cancel|move|reschedule|find|plan|organi[sz]e|arrange|set|call|text|email|confirm"
            r"|skip|miss|need|want|remind|add|schedule|put|is|was|when|what|did|do"
            # "Who am I meeting tomorrow" became a hold called "who am I
            # meeting" (2026-10-07). A question is never an instruction.
            r"|who|whom|whose|where|which|why|how|am|are|can|could|will|would|should|does|have|has|whats|wheres|whos"
            r"|tell|show|read|list)\b", low):
        told = None
    # "I'm making dinner tonight" became a 9 pm hold called "i'm making
    # dinner" (2026-10-07). Cooking is not a diary entry.
    if told and re.match(r"(?:i'?m|we'?re|i am|we are) (?:making|cooking|eating|having) (?:dinner|lunch|breakfast|brunch)\b"
                         r"|(?:i'?m|we'?re|i am|we are) (?:making|cooking) "
                         r"|(?:i'?m|we'?re|i am|we are) (?:having|eating) [a-z][a-z ]{1,30} for (?:dinner|lunch|breakfast)\b", low):
        told = None
    # "I am nervous about my interview tomorrow" became a 9 am hold called
    # "I am nervous about my interview" (2026-10-08). A feeling about a thing
    # is not the thing.
    if told and re.match(r"(?:i'?m|im|i am|i feel|i'?m feeling|i am feeling|we'?re|we are) (?:so |really |very |a bit |kind of |kinda |a little |pretty )?"
                         r"(?:nervous|worried|anxious|scared|excited|stressed|freaking out|psyched|pumped|dreading|ready|not ready|prepared|unprepared|looking forward)\b", low):
        told = None
    # "I'm meeting Jake for lunch on Friday" is lunch with Jake, not a hold
    # called "I'm meeting Jake for lunch" (2026-10-08): the meeting rule below.
    if told and re.match(r"(?:i'?m|i am|we'?re|we are) (?:meeting|seeing) ", told.group("title")):
        told = None
    # "My mom had surgery today" became a 9 am hold called "mom had surgery"
    # (2026-10-08). What already happened is news, not a diary entry.
    if told and not told.group("lead") and re.search(r"\b(?:had|went|was|were|did|got|finished|missed|skipped|cancell?ed)\b",
                                                     told.group("title")):
        told = None
    m = m or told
    # "I HAVE A MEETING WITH DANA AT 2" names no day (2026-10-07: to the
    # planner): told about with a time, it is today's.
    m = m or re.fullmatch(r"(?P<lead>i have|i've got|i got|i have got) (?:a |an |my )?"
                          r"(?P<title>[a-z' ]*?(?:appointment|meeting|lunch|dinner|breakfast|call|interview|party"
                          r"|date|class|practice|haircut|checkup|check-up)(?: with [a-z' ]+?)?)"
                          r" at (?P<time>\d{1,2}(?::\d\d)?(?: ?(?:am|pm))?|noon)(?P<day>)(?: (?:this )?(?P<part>morning|afternoon|evening|tonight))?", low)
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
            held = _calendar_hold(text, title[:1].upper() + title[1:], r.group("day") or "", None, r.group("t1"))
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
            held = _calendar_hold(text, title[:1].upper() + title[1:], b.group("day") or "", b.group("part"),
                                  b.group("time"))
            if held and 15 <= minutes <= 12 * 60:
                held["command"]["minutes"] = minutes
                return held
    if not m:
        # "LEO HAS SOCCER PRACTICE AT 5 TODAY" (2026-10-07: to the planner) -
        # the day said after the time. The same sentence with the day first.
        swap = re.fullmatch(r"(?P<head>.+? (?:has|have|has got|'ve got|got) .+?) at (?P<time>\d{1,2}(?::\d\d)?(?: ?(?:am|pm))?|noon)"
                            r" (?P<day>today|tonight|tomorrow|(?:on |this |next )?(?:mon|tues|wednes|thurs|fri|satur|sun)day)", low)
        if swap:
            again = _interpret(f"{swap.group('head')} {swap.group('day')} at {swap.group('time')}")
            if ((again or {}).get("command") or {}).get("kind") == "calendar_hold":
                # The sentence was rebuilt lowercased: "meeting with dana"
                # (2026-10-08). His capitals go back on the title.
                again["command"]["title"] = _as_he_said(text, again["command"]["title"])
                return again
        # "I'M MEETING SAM FOR COFFEE AT 10 TOMORROW" (2026-10-07: to the
        # planner, and "who am I meeting tomorrow" found nothing). The same
        # hold, called what it is and who with.
        mt = re.fullmatch(r"(?:i'?m|i am|we'?re|we are) (?:meeting(?: up with)?|seeing|having (?P<what0>coffee|lunch|dinner|drinks"
                          r"|breakfast|brunch) with) (?P<who>(?:the (?=[a-z]{3}))?(?!(?:a|an|the|him|her|them|up|you|it|someone|somebody)\b)[a-z][a-z']{1,20}"
                          r"(?: (?!(?:" + _cal_days + r"|on|this|next|for|at)\b)[a-z][a-z']{1,20})?)(?: for (?P<what>coffee|lunch|dinner|drinks|breakfast|brunch|a drink|a beer|a walk))?"
                          r"(?: (?:on |this |next )?(?P<day>" + _cal_days + r"))?(?: (?P<part>morning|afternoon|evening|night))?"
                          r"(?: at (?P<time>\d{1,2}(?::\d\d)?(?: ?(?:am|pm))?|noon))?(?: (?:on |this |next )?(?P<day2>" + _cal_days + r"))?", low)
        if mt and (mt.group("day") or mt.group("day2") or mt.group("time")) and not (mt.group("day") and mt.group("day2")):
            what = re.sub(r"^an? ", "", mt.group("what0") or mt.group("what") or "meeting")
            held = _calendar_hold(text, f"{what} with {_as_he_said(text, mt.group('who'))}", mt.group("day") or mt.group("day2") or "",
                                  mt.group("part"), mt.group("time"))
            if held:
                held["command"]["title"] = held["command"]["title"][:1].upper() + held["command"]["title"][1:]
                return held
        # "MY DENTIST APPOINTMENT IS FRIDAY AT 2" (2026-10-07: to the
        # planner) - the same thing as "I have a dentist appointment friday
        # at 2", said the other way round.
        mine = re.fullmatch(r"(?:my|the|our) (?P<what>[a-z][a-z' ]{1,40}?) (?:is|'s) (?P<when>.{3,40})", low)
        if (mine and re.search(r"\b(?:appointment|appt|meeting|interview|call|lunch|dinner|class|game|flight|haircut"
                               r"|checkup|check-up|surgery|exam|recital|practice"
                               # "The groomer is on Saturday at 9" (2026-10-08: a note).
                               r"|groomer|grooming|vet|party|wedding|shower|concert|playdate|sleepover|rehearsal)\b", mine.group("what"))
                and re.search(r"\d|\bnoon\b|" + _cal_days, mine.group("when"))):
            what = mine.group("what")
            if re.fullmatch(r"(?:[a-z]+'s )?(?:groomer|vet)", what):
                what += " appointment"
            again = _interpret(f"i have a {what} {mine.group('when')}")
            if ((again or {}).get("command") or {}).get("kind") == "calendar_hold":
                # "Our HOA meeting" (2026-10-08: held as "hoa meeting").
                again["command"]["title"] = _as_he_said(text, again["command"]["title"])
                return again
    # "Book 30 minutes with Sam at 4", "schedule a call with Dana tomorrow
    # at 10" (2026-10-08: offered as a WEB task, and to the planner). A hold
    # on his own calendar, as long as he said.
    bk = re.fullmatch(r"(?:book|schedule|set up|grab|pencil in|put in|add|block(?: off| out)?) (?:me )?(?:a |an )?"
                      r"(?:(?P<n>\d{1,3}|fifteen|thirty|forty-five|forty five|ninety) ?(?:-| )?(?:minutes?|mins?)(?: (?P<k>meeting|call|chat|sync))?"
                      r"|(?P<k2>meeting|call|chat|catch[- ]up|sync|one on one|1:1|video call|zoom|zoom call))"
                      r" with (?P<who>(?!(?:me|him|her|them|you|someone|somebody)\b)[a-z][a-z' ]{1,30}?)(?: on my calendar)?"
                      r" (?P<when>(?:today|tomorrow|tonight|on [a-z]+|this [a-z]+|next [a-z]+|monday|tuesday|wednesday|thursday|friday|saturday|sunday"
                      r"|at \d|at noon)(?: .{0,30})?)", low)
    if bk:
        kind = (bk.group("k") or bk.group("k2") or "meeting").replace("catch up", "catch-up")
        again = _interpret(f"i have a {kind} with {bk.group('who')} {bk.group('when')}")
        cmd = (again or {}).get("command") or {}
        if cmd.get("kind") == "calendar_hold":
            n = bk.group("n")
            if n:
                cmd["minutes"] = int(n) if n.isdigit() else {"fifteen": 15, "thirty": 30, "forty-five": 45,
                                                              "forty five": 45, "ninety": 90}[n]
            cmd["title"] = f"{kind} with {_as_he_said(text, bk.group('who').strip())}"
            return again
    if m:
        # "My wife and I are having dinner with the Smiths Friday at 7"
        # (2026-10-08) was a hold called "wife and I are having dinner with
        # the Smiths". The plan is the dinner.
        title = re.sub(r"^(?:(?:my|our) )?[a-z]{2,15} and i (?:are|'re|will be) (?:having|going to|going for|getting|grabbing|doing) (?:a |an |the )?",
                       "", m.group("title"))
        # "The kids have a dentist appointment Friday at 3" (2026-10-08) was
        # a hold called "the kids have a dentist appointment".
        kids = re.match(r"(?P<who>the kids|(?:my )?(?:son|daughter|kids|wife|husband|mom|dad)) (?:has|have|has got|have got|is having|are having|is getting) (?:a |an |their |his |her )?(?P<what>.+)$", title)
        if kids:
            whose = {"the kids": "the kids'", "my kids": "the kids'", "kids": "the kids'"}.get(kids.group("who"), re.sub(r"^my ", "", kids.group("who")) + "'s")
            title = f"{whose} {kids.group('what')}"
        # "My neighbor is having a party Saturday" (2026-10-08: held at 9 am
        # on HIS calendar as "neighbor is having a party") is their party.
        if re.match(r"(?:(?:my|our|the) )?(?!(?:i|we)\b)[a-z]{2,15}s?(?: next door)? (?:is|are) having (?:a |an |their |her |his )?(?:party|barbecue|bbq|cookout|garage sale|yard sale"
                    r"|baby|birthday party|housewarming|get together|get-together|bonfire)\b", title):
            return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
        held = _calendar_hold(text, title, m.group("day") or "", m.group("part"), m.group("time"))
        if held:
            return held
    # "Add a meeting with the team on Thursday at 3 for an hour" (2026-10-07:
    # to the planner). The length is said last; the rest is a hold as ever.
    dur = re.fullmatch(r"(?P<rest>.+?) for (?P<d>an hour(?: and a half)?|half an hour|a half hour|an hour and a half"
                       r"|(?:\d{1,3}|one|two|three|ninety|forty-five|thirty) (?:minutes?|mins?|hours?))", low)
    if dur and re.match(r"(?:add|schedule|put|book|block|set up|i have|i've got|we have|pencil in)\b", dur.group("rest")):
        again = _interpret(dur.group("rest"))
        cmd = (again or {}).get("command") or {}
        if cmd.get("kind") == "calendar_hold":
            d = dur.group("d")
            words = {"one": 1, "two": 2, "three": 3, "thirty": 30, "forty-five": 45, "ninety": 90}
            n = re.match(r"(\d+|one|two|three|thirty|forty-five|ninety)", d)
            minutes = (90 if "and a half" in d else 30 if "half" in d else 60 if d.startswith("an hour")
                       else int(n.group(1)) * 60 if n and n.group(1).isdigit() and "hour" in d
                       else int(n.group(1)) if n and n.group(1).isdigit()
                       else words.get(n.group(1), 1) * (60 if "hour" in d else 1) if n else 60)
            if 5 <= minutes <= 12 * 60:
                return {**again, "command": {**cmd, "minutes": minutes,
                                             "title": cmd.get("title") or ""}}

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
    # "I took ibuprofen at 2" (2026-10-07: to the planner) - a medicine by
    # name, in his words with the time he said.
    from aletheia import quick as _quick
    if re.fullmatch(r"(?:i )?(?:just )?(?:took|had|have taken|'ve taken) (?:my |an? |some |one |two |\d+ )?(?:" + _quick._DRUGS + r")"
                    r"(?: pills?| tablets?| capsules?)?(?: (?:at|around|about) \d{1,2}(?::\d\d)?(?: ?(?:am|pm))?| just now| today"
                    r"| this morning| tonight| earlier)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # HIS IDEAS, GOALS, THANKS AND JOURNAL (2026-10-07: "I have an idea
    # for...", "I want to learn Spanish", "I'm grateful for my family",
    # "journal entry: ..." each went to the planner). A note with a word on
    # the front that `quick._kept` reads back; nothing addressed to her
    # ("grateful for your help", "proud of you") is a journal line.
    m = re.fullmatch(r"(?:i (?:just )?(?:have|had|got|'ve got) (?:an|a new|another) idea(?: for| about|:)? ?|"
                     r"(?:save|keep|remember|note|write down|jot down) (?:this|an|my|a|the) (?:new )?idea(?: for| about)?:? ?|"
                     r"(?:new )?idea: ?)(?P<idea>[a-z0-9].{3,200})", low)
    if m:
        return {"command": {"kind": "note", "text": "Idea: " + _as_he_said(text, m.group("idea"))}, "say": None}
    m = re.fullmatch(r"i(?: want|'d like| would like| really want| need) to learn (?P<learn>(?!(?:more )?about you\b|what )[a-z].{1,80})", low)
    if m:
        return {"command": {"kind": "note", "text": "I want to learn " + _as_he_said(text, m.group("learn"))}, "say": None}
    m = re.fullmatch(r"(?:my|one of my) (?:main |big |new )?(?:goals?|new year'?s resolutions?|resolutions?)"
                     r"(?: (?:this|for this|for the) (?:year|month|week)| for (?:20\d\d|next year))? (?:is|are) (?P<goal>(?!to be honest)(?:to |\d).{2,150})", low)
    if m and not re.fullmatch(r"(?:what|unclear|nothing|none|secret|private)\b.*", m.group("goal")):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    m = re.fullmatch(r"(?:i'?m |i am |i feel |feeling )?(?:really |so |very )?(?:grateful|thankful) (?:for|that) (?P<thanks>(?!you\b|your\b|that\b$|it\b$)[a-z].{1,150})", low)
    if m:
        return {"command": {"kind": "note", "text": "Grateful for " + _as_he_said(text, m.group("thanks"))}, "say": None}
    m = re.fullmatch(r"(?:journal entry|dear diary|journal|diary entry|add to my journal|write in my journal|log in my journal)[:,]? (?P<entry>[a-z0-9].{3,400})"
                     r"|(?P<day>today was (?:a |an )?(?:really |pretty |very |so )?(?:good|great|bad|rough|long|hard|productive|tough|amazing|awful|weird|fun|busy|quiet|nice|terrible)(?: day)?(?: .{1,150})?)"
                     r"|(?P<proud>i'?m (?:really |so )?proud (?:of (?!you\b|your\b)|that )[a-z].{2,150})", low)
    if m:
        entry = m.group("entry") or m.group("day") or m.group("proud")
        # "I'm proud of myself" was answered "Noted." (2026-10-07): a
        # feeling said out loud gets a word back, and still goes in.
        say = None
        if m.group("proud"):
            say = "You should be. I've put it in your journal."
        elif m.group("day") and re.search(r"\b(?:bad|rough|hard|tough|awful|terrible|long)\b", m.group("day")):
            say = "Sorry it was a rough one. I've put it in your journal."
        elif m.group("day") and re.search(r"\b(?:good|great|amazing|fun|productive|nice)\b", m.group("day")):
            say = "Glad to hear it. I've put it in your journal."
        return {"command": {"kind": "note", "text": "Journal: " + _as_he_said(text, entry)},
                "say": say}
    # HOW HE FEELS (2026-10-08): "I'm feeling stressed" got a kind word and
    # was gone, so "how have I been feeling lately" had nothing to read. It
    # goes in his journal in his words, and the kind word is still said.
    m = re.fullmatch(r"(?:i'?m|im|i am|i feel|i'?m feeling|im feeling|i am feeling|feeling)"
                     r" (?:really |so |very |pretty |a bit |kind of |kinda |a little |super |quite )?"
                     r"(?P<mood>stressed(?: out)?|anxious|happy|great|sad|down|exhausted|overwhelmed|lonely|excited"
                     r"|calm|relaxed|depressed|awful|terrible|amazing|nervous|worried|burned out|burnt out|tired"
                     r"|motivated|unmotivated|productive|frustrated|angry|upset|hopeful|proud of myself|better|much better|a lot better"
                     # "I am in a good mood today", "I'm excited for the weekend",
                     # "I'm nervous about my interview tomorrow" (2026-10-08).
                     r"|in a (?:good|great|bad|terrible|weird|funny|grumpy|rotten) mood|scared|dreading [a-z][a-z ]{1,30}"
                     # "I feel sick" (2026-10-08: a kind word and nothing kept, so
                     # "how long have I been sick" had nothing to count from).
                     # A bare "I'm sick" stays out: it is as often "sick of this".
                     r"|unwell|under the weather|crummy|run down|feverish|not feeling well|not feeling good)"
                     r"(?: (?:about|for|to|over) (?!you\b|your\b)[a-z0-9][a-z0-9 ',-]{1,60}?)?"
                     r"(?: (?:today|right now|now|tonight|this morning|lately|again))?"
                     r"|(?:i (?:had|have had|'ve had) a(?:n)? (?:really |pretty |very |so )?"
                     r"(?:good|great|bad|rough|long|hard|productive|tough|amazing|awful|weird|fun|busy|terrible) day(?: today)?)"
                     r"|i (?:don't|do not) feel (?:well|good|so good|great)(?: today| right now)?"
                     r"|(?:i feel|i'?m feeling|i am feeling|feeling) (?:really |so |kind of |kinda |pretty |a bit |a little )?(?:sick|ill)(?: today| right now| again)?", low)
    if m:
        try:
            say = _quick.answer(text)
            if not say and m.group("mood"):
                # The kind word for the feeling, with what it is about left off.
                say = _quick.answer(f"i am {m.group('mood')}")
        except Exception:  # noqa: BLE001
            say = None
        if re.search(r"\b(?:sick|ill|unwell|under the weather|crummy|run down|feverish|not feeling (?:well|good)|feel (?:well|good|so good|great))\b", low):
            say = "Rest up. I've put it in your journal, so you can tell the doctor how long it's been."
        elif not say and m.group("mood") and re.match(r"(?:nervous|worried|anxious|scared|dreading)", m.group("mood")):
            say = "That's normal - it means it matters to you. You'll do fine. I've put it in your journal."
        elif not say and m.group("mood") and re.match(r"(?:excited|happy|great|amazing|in a (?:good|great) mood)", m.group("mood")):
            say = "Love that. I've put it in your journal."
        return {"command": {"kind": "note", "text": "Journal: " + _as_he_said(text, low)},
                "say": say or "Noted. I've put it in your journal."}
    # "I miss my dad", "wish me luck" (2026-10-08: both to the planner).
    if re.fullmatch(r"i (?:really |just )?miss (?:my |our )?[a-z][a-z' ]{1,25}?(?: so much| a lot)?", low) \
            and not re.search(r"\b(?:you|the bus|the train|my flight|my turn|it)\b", low):
        return {"command": {"kind": "note", "text": "Journal: " + _as_he_said(text, low)},
                "say": "I'm sorry - missing someone is hard. I've put it in your journal."}
    if re.fullmatch(r"(?:wish me luck|fingers crossed|cross your fingers(?: for me)?|here goes nothing|wish me luck (?:today|tonight|tomorrow))", low):
        return {"command": None, "say": "Good luck - you've got this."}
    # HIS BIG NEWS (2026-10-08: "I got promoted" got its congratulations and
    # was gone, so "when did I get promoted" went to a model). Kept in his
    # journal; the kind word is still quick's.
    # "I got the job at Google" is the same news (2026-10-08: plain "Noted").
    news = re.sub(r" (?:at|with) [a-z0-9][a-z0-9&.' -]{1,30}$", "", low.rstrip("!"))
    g = _quick._groups("life_news", news)
    if g.get("win") or g.get("win2") or g.get("setback") or g.get("quit"):
        try:
            say = _quick.answer(news)
        except Exception:  # noqa: BLE001
            say = None
        return {"command": {"kind": "note", "text": "Journal: " + re.sub(r"\bi\b", "I", _as_he_said(text, low.rstrip("!")))},
                "say": say or "Noted. I've put it in your journal."}
    # BEING ILL (2026-10-08): "I have a cold" got "rest up" and was gone, so
    # "how long have I had this cold" had nothing to count from.
    m = re.fullmatch(r"i(?:'ve| have)(?: got| had)? (?:a |an |the )?(?:headache|migraine|cold|fever|flu|sore throat|stomach ?ache|cough)"
                     r"(?: (?:since (?:this morning|last night|yesterday|lunch|[a-z]+day)|all (?:day|morning|week)|again|today|right now|now))?", low)
    if m:
        try:
            say = _quick.answer(text)
        except Exception:  # noqa: BLE001
            say = None
        return {"command": {"kind": "note", "text": "Journal: " + _as_he_said(text, low)},
                "say": say or "Noted. I've put it in your journal."}
    # MORE SYMPTOMS (2026-10-08: "I feel dizzy", "my back hurts", "I've been
    # coughing for 3 days" to the planner). The same journal, so "what
    # symptoms have I had" and "what should I tell the doctor" can read them.
    m = re.fullmatch(r"i(?:'m| am| feel|'m feeling| am feeling)(?: really| a bit| kind of| so| very)? (?P<s>dizzy|nauseous|nauseated|lightheaded|light-headed"
                     r"|feverish|congested|stuffy|achy|queasy|short of breath)(?: (?:today|again|right now|now|this morning|all day))?"
                     r"|my (?P<part>back|lower back|head|throat|stomach|tummy|knee|knees|neck|shoulder|tooth|ear|ears|foot|feet|leg|arm|chest|wrist"
                     r"|ankle|hip|eye|eyes|jaw|hand) (?:hurts|is hurting|is sore|aches|is aching|has been hurting|is bothering me)"
                     r"(?: (?:today|again|since [a-z ]{3,20}|for (?:a few|\d+|two|three|four|five|a couple(?: of)?) (?:days|weeks)|for (?:a|about a|over a) (?:week|month)|all (?:day|week)))?"
                     r"|i(?:'ve| have) been (?P<v>coughing|sneezing|throwing up|vomiting|wheezing|feeling dizzy|feeling sick|feeling nauseous)"
                     r"(?: (?:for (?:a few|\d+|two|three|four|five|a couple of) (?:days|hours|weeks)|since [a-z ]{3,20}|all (?:day|night|week)|today|again))?"
                     r"|i (?:just )?(?:threw up|vomited|fainted|passed out)(?: (?:today|this morning|last night|again))?"
                     # "I pulled a muscle", "I sprained my ankle", "I think I have
                     # food poisoning" (2026-10-08: to the planner).
                     r"|i (?:just |think i |might have )?(?:pulled|strained|sprained|twisted|tweaked|hurt|bruised|jammed|stubbed|pinched|threw out)"
                     r" (?:a|my) (?:muscle|back|lower back|ankle|knee|wrist|shoulder|neck|toe|finger|thumb|hamstring|calf|groin|hip|nerve|elbow|foot)"
                     r"(?: (?:today|yesterday|at the gym|playing [a-z]+|running|lifting|again))?"
                     r"|i (?:think i |might )?(?:have|'ve got|got|caught) (?:food poisoning|the flu|covid|strep|a stomach bug|a bug|a cold|pink eye|an ear infection|a sinus infection)", low)
    if m:
        urgent = (m.group("part") == "chest" or re.search(r"\b(?:fainted|passed out|short of breath)\b", low))
        return {"command": {"kind": "note", "text": "Journal: " + _as_he_said(text, low)},
                "say": ("If it's sudden or severe, call 911 now. I've put it in your journal." if urgent
                        else "Sorry, that's no fun. I've put it in your journal, so you can tell the doctor how long it's been.")}
    # WHAT HE LIKES (2026-10-08: "I love hiking" to the planner) - kept in
    # his words; "what do I like" reads it with his favorites.
    m = re.fullmatch(r"i (?:really |also |just )?(?:like|love|enjoy|adore|am into|'m into|am a big fan of|'m a big fan of) "
                     r"(?P<what>(?!(?:you|u|it|that|this|them|him|her|the way|how|what|when|your|it's|thea|these|those|my)\b)[a-z0-9].{1,50})", low)
    if m and "?" not in text:
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # WHAT SOMEONE LIKES (2026-10-07: "Sam likes coffee", "my mom loves
    # tulips" went to the planner). A note in his words, read back by "what
    # does Sam like" - and by "what did I tell you about Sam".
    m = re.fullmatch(r"(?P<who>(?:my |our )?[a-z][a-z']{1,20}) (?:really |also )?(?:likes|loves|hates|adores|prefers|enjoys"
                     r"|doesn'?t like|does not like|can'?t stand|is into|is obsessed with|is a fan of|collects) (?P<what>[a-z0-9].{1,60})", low)
    if m and m.group("who") not in ("he", "she", "it", "this", "that", "who", "what", "everyone", "everybody", "nobody",
                                    "somebody", "someone", "thea", "you", "one", "which", "anyone", "anybody") \
            and not low.endswith("?") and not re.match(r"(?:what|who|which)\b", m.group("what")):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # MONEY BETWEEN PEOPLE (2026-10-07: "I owe Sam 20 dollars", "Sam paid me
    # back" each to the planner). Said as a fact, it is a note in his words;
    # "who do I owe" adds the notes up. Nothing here moves any money.
    _amt = r"\$?\d+(?:\.\d{1,2})?(?: ?(?:dollars|bucks))?"
    if re.fullmatch(r"(?:i owe [a-z][a-z ]{0,25}? " + _amt + r"|[a-z][a-z ]{0,25}? owes me " + _amt
                    + r"|i (?:lent|loaned) [a-z][a-z ]{0,25}? " + _amt + r"|i borrowed " + _amt + r" from [a-z][a-z ]{0,25}?"
                    + r"|i paid [a-z][a-z ]{0,25}? back(?: " + _amt + r")?|[a-z][a-z ]{0,25}? paid me back(?: " + _amt + r")?"
                    # "Jake paid me 20" (2026-10-08: to the planner) - part of it back.
                    + r"|[a-z][a-z ]{0,25}? (?:paid|gave) me " + _amt + r"(?: back)?)"
                    + r"(?: for [a-z][a-z ]{0,30})?", low) and not low.startswith(("you ", "she ", "thea ")):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "My blood pressure was 120 over 80" (2026-10-07: to the planner), and
    # a reading of his heart rate or blood sugar: a note with the time on it,
    # read back by `quick._reading`. Never a judgement on the number.
    m = re.fullmatch(r"(?:my )?(?:blood pressure|bp) (?:was|is|reading was|came out|came out at|was at)? ?"
                     r"(?P<sys>\d{2,3}) ?(?:over|/) ?(?P<dia>\d{2,3})(?: today| this morning| just now| at the doctor'?s?)?", low) \
        or re.fullmatch(r"(?:my )?(?:heart rate|resting heart rate|pulse|blood sugar|glucose|blood glucose|a1c|temperature|temp|oxygen|o2)"
                        r" (?:was|is|reading was|was at|came out at) \d{1,3}(?:\.\d)?(?: %| percent| bpm)?(?: today| this morning| just now)?", low)
    if m:
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
                     r"(?: today| this morning| last night| tonight| just now|(?P<ago> yesterday))?", low)
    if m:
        return {"command": {"kind": "note", "text": "I " + m.group("log") + (m.group("ago") or "")}, "say": None}
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
    # "My password for netflix is hunter2" (2026-10-08: to the planner, the
    # one shape of it the fact rule did not know). She does not keep them.
    if re.fullmatch(r"(?:my |the |our )?(?:[a-z]+ )?pass(?:word|code|phrase) (?:for|to|on|at) (?:my |the )?[a-z0-9 .'-]{2,30}? (?:is|=) \S.*", low):
        return {"command": None, "say": _NO_PASSWORDS}
    # "The wifi password is sunshine22", "my password is hunter2" (2026-10-08:
    # to the planner). "My password is wrong" is a complaint, not one.
    if re.fullmatch(r"(?:my |the |our )?(?:[a-z]+ )?pass(?:word|code|phrase) (?:is|=) (?!(?:wrong|not|incorrect|locked|too|bad|weak|old|different|the same|changed|reset|expired"
                    r"|broken|invalid|missing|forgotten|lost|on|in|written|somewhere|saved|stored)\b)\S+", low):
        return {"command": None, "say": _NO_PASSWORDS}
    # WHERE HE PARKED. "I parked on level 3" went to the planner and
    # "where did I park" to a model (2026-10-07). It is a note, in his
    # words, and `quick` reads the newest one back.
    m = re.fullmatch(r"(?:i(?:'ve| have)? parked|i'm parked|my car is(?: parked)?|the car is(?: parked)?)"
                     r" (?:on|at|in|by|near|outside|behind|across from|next to) .+", low)
    if m:
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # A GRADE OR A SCORE (2026-10-08: "I got an A on my test" went to the
    # planner). A note; "how did I do on my test" reads it back.
    if re.fullmatch(r"(?:i |we )?(?:just )?(?:got|scored|made|received)(?: an?)? (?:[a-f][+-]?|\d{1,3}(?:\.\d)?(?:%| percent)?"
                    r"|\d{1,3} ?(?:/|out of) ?\d{1,3}) on (?:my |the |our |his |her )?[a-z][a-z' ]{1,30}"
                    r"|(?:i |we )?(?:just )?(?:passed|failed|aced|bombed) (?:my |the |our )[a-z][a-z' ]{0,20}"
                    r"(?:test|exam|quiz|midterm|final|class|course|interview)", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # HIS WORK DAYS (2026-10-08: "I work Monday to Friday" went to the
    # planner). A note; "do I work Saturday" reads it.
    _day = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?"
    if re.fullmatch(r"i (?:usually |only |normally )?work (?:on )?(?:weekdays|weekends|" + _day
                    + r"(?:(?:,? (?:to|through|thru|and|-) |, )" + _day + r")*)(?: (?:and|but) .{1,40})?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # HOW OLD SOMEBODY OF HIS IS (2026-10-08: "my sister is 28" went to the
    # planner). A note; "how old is my sister" reads it back.
    if re.fullmatch(r"(?:my|our) (?:" + _WHOSE + r"|son|daughter|kids?|grandson|granddaughter|stepson|stepdaughter)"
                    r"(?: [a-z]+)? (?:is|just turned|turned|will be) \d{1,3}(?: years old| yrs old)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # HIS PETS (2026-10-08, every one to the planner): "my cat is named
    # Luna" is kept the way "my cat's name is Luna" already was; "Luna is
    # 4" is an age when Luna is a name he said with its capital; "the dog
    # threw up" and "Max needs his flea medicine on the 15th" are notes.
    m = re.fullmatch(r"(?:my|our) (?P<pet>dog|cat|puppy|kitten|pet|bird|hamster|rabbit|bunny|fish|horse|parrot|turtle|lizard|snake"
                     r"|guinea pig|ferret)(?:'s)? (?:is named|is called|name is|goes by) (?P<name>[a-z][a-z'-]{1,20}(?: [a-z][a-z'-]{1,20})?)", low)
    if m:
        name = _as_he_said(text, m.group("name"))
        return {"command": {"kind": "note", "text": f"my {m.group('pet')}'s name is {name[:1].upper() + name[1:]}"}, "say": None}
    # "We adopted a puppy named Bear" (2026-10-08: to the planner).
    m = re.fullmatch(r"(?:we|i) (?:just )?(?:adopted|got|rescued|brought home) (?:a |an |our |my )?(?:new )?(?P<pet>dog|cat|puppy|kitten|bird|hamster"
                     r"|rabbit|bunny|fish|turtle|guinea pig) (?:named|called) (?P<name>[a-z][a-z'-]{1,20})(?: today| yesterday)?", low)
    if m:
        name = _as_he_said(text, m.group("name"))
        return {"command": {"kind": "note", "text": f"my {m.group('pet')}'s name is {name[:1].upper() + name[1:]}"},
                "say": f"Welcome home, {name[:1].upper() + name[1:]}! I've kept the name."}
    # "Max weighs 60 pounds" (2026-10-08: to the planner).
    m = re.fullmatch(r"(?P<who>(?:my|our|the) (?:dog|cat|puppy|kitten|baby|son|daughter)|[a-z][a-z'-]{1,20}) (?:now )?weighs \d{1,3}(?:\.\d)? ?(?:pounds|lbs?|kg|kilos|ounces|oz)", low)
    if m and (re.match(r"(?:my|our|the) ", m.group("who")) or re.search(r"\b" + re.escape(m.group("who").capitalize()) + r"\b", text)) \
            and m.group("who") not in ("it", "that", "this", "he", "she", "i", "who", "what", "everything"):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "The cat needs flea medicine" (2026-10-08: to the planner) is an
    # errand for the pet.
    m = re.fullmatch(r"(?P<who>(?:my|our|the) (?:dog|cat|puppy|kitten|pet|bird|fish|hamster|rabbit)) needs (?:more |new |some |a |his |her |its )?"
                     r"(?P<what>(?:flea|tick|heartworm|worm|allergy|ear|eye)? ?(?:medicine|medication|meds|pills|drops|treatment)|food|treats|a bath"
                     r"|a haircut|a groom(?:ing)?|a walk|shots|vaccines?|a new collar|a collar|a leash|litter|a vet visit|to go to the vet)", low)
    if m and m.group("what") not in ("a walk", "a bath"):
        what = re.sub(r"^to go to the vet$", "a vet visit", m.group("what"))
        return _new_task(f"get {m.group('who').replace('my ', 'the ').replace('our ', 'the ')} {what}")
    m = re.fullmatch(r"(?:my |our )?(?P<who>dog|cat|puppy|kitten|[a-z][a-z'-]{1,20}) (?:is|just turned|turned) \d{1,2}(?: years old| yrs old| (?:weeks|months) old)?", low)
    if m and (m.group("who") in ("dog", "cat", "puppy", "kitten") if low.startswith(("my ", "our ")) else
              re.search(r"\b" + re.escape(m.group("who").capitalize()) + r"\b", text)) \
            and m.group("who") not in ("it", "that", "this", "he", "she", "there", "what", "who", "i", "you", "we", "they", "time",
                                       "score", "temp", "number", "answer", "count", "total", "rate", "speed", "weight", "dinner",
                                       "lunch", "breakfast", "everyone", "everybody", "someone", "somebody", "nobody", "today",
                                       "tomorrow", "mine", "yours", "one", "two", "three", "four", "five", "six", "seven", "eight",
                                       "nine", "ten", "dog", "cat", "puppy", "kitten"):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    m = re.fullmatch(r"(?P<who>(?:my|our|the) (?:dog|cat|puppy|kitten|pet|bird|horse|rabbit|bunny)|[a-z][a-z'-]{1,20})"
                     r" (?:just |has |keeps |has been |is |was )?(?:threw up|thrown up|throwing up|vomited|vomiting|is limping|limping|was limping"
                     r"|isn'?t eating|is not eating|won'?t eat|wouldn'?t eat|stopped eating|has diarrh(?:o)?ea|had diarrh(?:o)?ea"
                     r"|got into the trash|ate (?:something(?: weird| bad| strange| off)?|a sock|(?:some |a (?:bunch|lot) of |a |an )?(?P<bad>chocolate|grapes|raisins|gum|xylitol"
                     r"|onions?|garlic|a lily|lilies|antifreeze|rat poison|mouse poison|my medicine|medicine|pills|ibuprofen|advil|tylenol|aspirin|marijuana|weed))"
                     r"|has fleas|got fleas|is scratching a lot)"
                     r"(?: (?:today|again|this morning|last night|tonight|all day))?", low)
    if m and (re.match(r"(?:my|our|the) ", m.group("who")) or re.search(r"\b" + re.escape(m.group("who").capitalize()) + r"\b", text)) \
            and m.group("who") not in ("it", "that", "he", "she", "i", "we", "they", "baby", "everyone", "everybody", "someone",
                                       "somebody", "nobody", "who", "what"):
        # "My dog ate chocolate" (2026-10-08) was a plain "Noted." - it can be
        # an emergency, and the one useful thing is who to call, now.
        urgent = None
        if m.group("bad") and re.match(r"(?:my|our|the) (?:dog|cat|puppy|kitten|pet)", m.group("who")):
            urgent = ("That can be dangerous for a pet. Call your vet or the ASPCA Animal Poison Control Center "
                      "at 888-426-4435 now - don't wait for symptoms.")
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": urgent}
    m = re.fullmatch(r"(?P<who>(?:my|our|the) (?:dog|cat|puppy|kitten|pet)|[a-z][a-z'-]{1,20}) needs (?:his|her|its|their|a|the|to get (?:his|her|its|a|the)) "
                     r"[a-z][a-z' ]{2,40}? (?:on|by) (?:the )?(?:\d{1,2}(?:st|nd|rd|th)?|(?:mon|tues|wednes|thurs|fri|satur|sun)day"
                     r"|" + _MONTH + r" \d{1,2}(?:st|nd|rd|th)?)", low)
    if m and (re.match(r"(?:my|our|the) ", m.group("who")) or re.search(r"\b" + re.escape(m.group("who").capitalize()) + r"\b", text)) \
            and m.group("who") not in ("it", "that", "he", "she", "i", "we", "they", "everyone", "everybody", "someone",
                                       "somebody", "nobody", "who", "what", "this"):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I have to work late tonight" (2026-10-08: to the planner). "What
    # time do I get off tonight" reads it.
    if re.fullmatch(r"i(?:'m| am| have to| need to|'ve got to| got to| gotta| will| will be|'ll be|'ll)? (?:be )?work(?:ing)? "
                    r"(?:late|(?:until|till) \d{1,2}(?::\d\d)? ?(?:am|pm)?)(?: tonight| today| tomorrow)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "The electric bill was 140" (2026-10-08: to the planner). A note;
    # "how much was the electric bill" reads it.
    if re.fullmatch(r"(?:the|my|our|this month'?s) (?:[a-z]+ ){0,2}(?:bill|payment|invoice) (?:was|is|came to|came out to|ended up being)"
                    r" (?:about |around |only |almost )?\$?\d[\d,]*(?:\.\d\d)?(?: dollars| bucks)?(?: this month| this time)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "My usual coffee order is an oat latte" (2026-10-08: to the planner).
    m = re.fullmatch(r"(?:my|our) (?:usual |regular |normal |go-to |default )?(?P<k>coffee|drink|starbucks|tea|lunch|pizza|burger|sandwich|takeout|chipotle|smoothie)"
                     r" (?:order|usual) is (?:usually |always )?(?P<v>.{2,60})", low)
    if m:
        return {"command": {"kind": "note", "text": f"my {m.group('k')} order is {_as_he_said(text, m.group('v'))}"}, "say": None}
    # "I tried a new place called Nobu and loved it" (2026-10-08: to the planner).
    if re.fullmatch(r"(?:i|we) (?:tried|went to|ate at|had (?:dinner|lunch|breakfast|brunch) at|checked out) (?:a |this |the |that )?(?:new )?"
                    r"(?:(?:place|restaurant|spot|cafe|bar|bakery|diner)(?: called| named)? )?[a-z0-9][a-z0-9 '&.-]{1,30}?"
                    r" (?:and|but) (?:i |we )?(?:really |absolutely |kind of |kinda )?(?:loved|liked|hated|enjoyed|didn'?t like|did not like|wasn'?t a fan of) it", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I called the insurance company", then "they said the claim was
    # approved" (2026-10-08: to the planner). Kept under who he called, so
    # "what did the insurance company say" reads it.
    m = re.fullmatch(r"(?:they|he|she) (?:said|told me|say|says) (?:that )?(?P<x>[a-z0-9].{2,120})", low)
    if m:
        try:
            from aletheia import converse
            turns = list(reversed(converse.recent(limit=3) or []))
        except Exception:  # noqa: BLE001
            turns = []
        for turn in turns[:2]:
            said = re.sub(r"^(?:hey |ok |okay )?thea,? ", "", " ".join(str(turn.get("he_asked") or "").split()), flags=re.I)
            who = re.fullmatch(r"i (?:just |finally )?(?:called|talked to|spoke (?:to|with)|met with|heard (?:back )?from|got a call from"
                               r"|emailed|texted|got off the phone with) (?P<who>(?:the |my )?[a-z][a-z' &.-]{1,40}?)(?: today| back| earlier| this morning)?\.?",
                               said, re.I)
            if who:
                name = who.group("who")
                return {"command": {"kind": "note", "text": f"{name} said {_as_he_said(text, m.group('x'))}"}, "say": None}
    # "I have a deadline on Friday" (2026-10-08: kept undated, so "what
    # deadlines do I have this week" said nothing was due). The weekday is
    # only true this week, so the note keeps the date it meant.
    m = re.fullmatch(r"i (?:have|'ve got|got) (?:a |an )?(?:big |hard |work )?deadline (?:on |this |by )?(?P<day>today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)", low)
    if m and _spoken_day(m.group("day")):
        import datetime as dt
        on = dt.date.fromisoformat(_spoken_day(m.group("day"))[:10])
        return {"command": {"kind": "note", "text": f"I have a deadline {on.strftime('%A')} {on.day} {on.strftime('%B')}"}, "say": None}
    # "The project is due next Friday" (2026-10-08: to the planner). "Next
    # Friday" is ambiguous, so it is kept in his words, undated.
    if re.fullmatch(r"(?:my|our|the) [a-z][a-z' ]{1,30}? (?:is|are) due (?:next (?:week|month|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|at the end of the (?:week|month)|end of (?:the )?(?:week|month)|in (?:a|one|two|three|\d) (?:days?|weeks?))", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "My smoke detector is beeping" (2026-10-08: a plain "Noted.").
    if re.fullmatch(r"(?:the|my|our) (?:smoke detector|smoke alarm|carbon monoxide detector|co detector|fire alarm) (?:is|keeps) (?:beeping|chirping)(?: again)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)},
                "say": "A chirp every minute or so is almost always a low battery - a fresh one usually stops it. If it's a long, loud alarm, get out and call 911."}
    # THINGS BROKEN AND FIXED (2026-10-08: "the dishwasher is broken" and
    # "the landlord fixed the sink" both to the planner). Notes; "what's
    # broken" and "is the sink fixed" read them.
    if (re.fullmatch(r"(?:the|my|our) [a-z][a-z' ]{1,25}? (?:is|are|was|keeps) (?:broken|leaking|not working|busted|clogged|acting up|making a (?:weird |strange |loud )?noise"
                     # "The smoke detector is beeping" (2026-10-08: to the planner).
                     r"|beeping|chirping|dripping|flickering|squeaking|squealing|rattling|not draining|not turning on|not starting|tripping"
                     # "My laptop is slow", "my phone screen cracked" (2026-10-08: to the planner).
                     r"|frozen|cracked|crashing|freezing|overheating|not charging"
                     # "The garage door is stuck" (2026-10-08: to the planner).
                     r"|stuck|jammed|loose|wobbly|off track)(?: again| open| shut| closed)?", low)
            or re.fullmatch(r"i (?:just )?replaced the batter(?:y|ies) in (?:the|my|our) [a-z][a-z' ]{1,25}", low)
            or re.fullmatch(r"(?:the|my|our) [a-z][a-z' ]{1,25}? (?:won't|will not|doesn't|does not) (?:charge|turn on|start|connect|work|load|boot|drain|flush)(?: anymore)?", low)
            or re.fullmatch(r"(?:the|my|our) [a-z][a-z' ]{1,25}? (?:broke|stopped working|died|quit working|cracked|shattered|froze)(?: today| again| yesterday)?", low)
            or re.fullmatch(r"(?!(?:who|what|when|how|did|has|have)\b)(?:i|we|the [a-z]{3,15}|my [a-z]{3,15}|[a-z]{3,15}) (?:finally |just )?(?:fixed|repaired|unclogged) (?:the|my|our) [a-z][a-z' ]{1,25}", low)
            or re.fullmatch(r"(?:the|my|our) [a-z][a-z' ]{1,25}? (?:is|got|was) (?:fixed|repaired|working again)(?: now| today)?", low)) \
            and not re.search(r"\b(?:heart|leg|arm|back|bone|nose|wrist|ankle|finger|toe|record|promise|news|ice|build|ci|pipeline|repo|tests?"
                              r"|day|week|traffic|internet|wifi|line|service|business|game|battery|plant|plants|fish|dog|cat)\b", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I got my oil changed today at 45000 miles" (2026-10-08: to the
    # planner). Ticks off "get my oil changed" when that is on his list -
    # the task keeps his sentence, miles and all - and is kept otherwise.
    m = re.fullmatch(r"i (?:just )?(?:got|had) (?:the|my|our) (?P<thing>[a-z][a-z' ]{1,25}?) (?P<done>changed|replaced|checked|balanced|topped off|done"
                     r"|washed|detailed|serviced|inspected|cleaned|tuned up|rotated|aligned|fixed|repaired)"
                     r"(?: today| yesterday| this morning)?(?: at [0-9,]{3,9}(?:k)? miles)?(?: today| yesterday| this morning)?", low)
    if m:
        try:
            from aletheia import intercom as _icm
            found, _why = _icm._one_task(f"{m.group('thing')} {m.group('done')}")
        except Exception:
            found = None
        if found is not None:
            return {"command": {"kind": "task_done", "which": f"{m.group('thing')} {m.group('done')}"}, "say": None}
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "The claim was approved", "I'm waiting on a refund from Amazon", "the
    # furnace was serviced today" (2026-10-08: all to the planner or a model).
    if re.fullmatch(r"(?:the|my|our) (?:insurance )?(?:claim|refund|application|loan|permit|request|appeal|return|reimbursement|rebate|visa|passport)"
                    r"(?: [a-z]{2,15})? (?:was|got|has been|is|came) (?:finally )?(?:approved|denied|rejected|processed|accepted|declined|issued|cancell?ed"
                    r"|paid|paid out|received|through|back|in|sent|closed|on hold|pending|under review)(?: today| yesterday)?", low) \
            or re.fullmatch(r"(?:i'?m|i am|we'?re|we are) (?:still )?waiting (?:on|for) (?:a |an |the |my |our )?[a-z][a-z0-9' ]{2,40}", low) \
            and not re.search(r"\b(?:you|it|this|that|them|him|her)$", low) \
            or re.fullmatch(r"i (?:just )?(?:got|had) (?:the|my|our) [a-z][a-z' ]{1,25}? (?:washed|detailed|serviced|inspected|cleaned|tuned up|rotated|aligned|fixed|repaired)(?: today| yesterday)?", low) \
            or re.fullmatch(r"(?:the|my|our) [a-z][a-z' ]{1,25}? (?:was|were|got|has been|have been) (?:serviced|inspected|cleaned|tuned up|flushed|replaced|installed"
                            r"|painted|pumped|sealed|treated|rotated)(?: today| yesterday| this morning| last week)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # WHAT HE THOUGHT OF SOMETHING (2026-10-08: "Dune was amazing" to the
    # planner). Kept; "what did I think of Dune" reads it.
    m = re.fullmatch(r"(?P<what>[a-z0-9][a-z0-9' :&-]{1,40}?) (?:was|is) (?:really |so |pretty |kind of |kinda |very |super |just )?"
                     r"(?P<how>amazing|great|good|bad|terrible|boring|ok|okay|fine|awesome|incredible|meh|disappointing|overrated"
                     r"|underrated|fantastic|excellent|awful|brilliant|slow|confusing|beautiful|hilarious|funny|sad|scary|mid|so good|so bad)"
                     r"(?: too)?", low)
    said_as = re.match(re.escape(m.group("what")), text.strip(), re.I) if m else None
    content = [w for w in (said_as.group(0).split() if said_as else []) if w.casefold() not in ("the", "a", "an")]
    if m and content and (
            # a title, said with its capitals: "Dune", "The Bear"
            (all(w[:1].isupper() or w[:1].isdigit() for w in content)
             and content[0].casefold() not in ("it", "that", "this", "today", "yesterday", "he", "she", "they", "everything",
                                               "life", "work", "i", "you", "we", "there", "what", "how", "who", "dinner",
                                               "lunch", "breakfast", "weather", "my", "your", "tonight", "everyone", "thea", "aletheia"))
            or re.search(r"\b(?:movie|film|show|book|series|episode|album|game|season|play|concert|restaurant)$", m.group("what"))):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # HOW MANY THEY HAVE (2026-10-08: "Jake has two kids" went to the
    # planner). A family or pets, counted; a name said with its capital or
    # a person of his, so "the house has two bathrooms" is not one.
    m = re.fullmatch(r"(?P<who>my [a-z][a-z'-]{1,20}|[a-z][a-z'-]{1,20}) (?:has|have|has got) (?P<n>no|one|two|three|four|five|six|seven|eight|\d{1,2}|a|an)"
                     r" (?:little |young |grown |adult |grown-up )?(?P<what>kids?|children|child|sons?|daughters?|boys?|girls?|grandkids?|grandchildren"
                     r"|brothers?|sisters?|siblings?|dogs?|cats?|pets?|twins)", low)
    if m and (m.group("who").startswith("my ") or re.search(r"\b" + re.escape(m.group("who").capitalize()) + r"\b", text)) \
            and m.group("who") not in ("i", "he", "she", "they", "we", "you", "it", "who"):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I got a speeding ticket" (2026-10-08: to the planner). Kept, so
    # "when did I get the ticket" has an answer.
    if re.fullmatch(r"i (?:just )?(?:got|received) (?:a |another )?(?:speeding|parking|traffic|red light) (?:ticket|fine|citation)"
                    # "I got a parking ticket for 40" (2026-10-08: to the planner).
                    r"(?: (?:for|of) \$?\d{1,4}(?:\.\d\d)?(?: dollars| bucks)?)?"
                    r"(?: (?:today|yesterday|this morning|last night|on the way [a-z ]{2,20}))?|i (?:just )?got pulled over(?: today| yesterday)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": "Ugh, sorry. I've noted it."}
    # "My car got towed" (2026-10-08: to the planner). Kept, with where to start.
    if re.fullmatch(r"(?:my|our) (?:car|truck|van) (?:got|was|has been|just got) towed(?: today| last night| this morning| from [a-z ]{2,30})?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)},
                "say": "Ugh, sorry - I've noted it. The local police non-emergency line can tell you which lot has it, "
                       "and bring your license and registration to get it back."}
    # "I got in a fender bender" (2026-10-08: to the planner).
    if re.fullmatch(r"i (?:just )?(?:got in|got into|was in|had|have been in) (?:a |an )?(?:little |small |minor |bad |car )?(?:fender bender|accident|wreck|crash|car crash|collision)"
                    r"(?: (?:today|yesterday|this morning|last night|on the way [a-z ]{2,20}))?|(?:someone|somebody|a car|a truck) (?:hit|rear[- ]ended|backed into|sideswiped) (?:me|my car|my truck)(?: today| yesterday)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)},
                "say": "Oh no - I hope you're okay. I've noted it."}
    # "My car insurance is with Geico", "the body shop says it will take a
    # week" (2026-10-08: both to the planner).
    if re.fullmatch(r"(?:my|our) (?:[a-z]+ )?(?:insurance|bank|phone plan|cell plan|phone service|internet|mortgage|car loan|loan|401k|retirement account|ira|pension|checking account|savings account)"
                    r" (?:is|are) (?:with|through|at) (?!it\b|that\b)[a-z][a-z0-9 .&'-]{1,30}", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    m = re.fullmatch(r"the (?P<who>body shop|mechanic|shop|dealer|dealership|garage|repair shop|tire shop|vet|landlord|contractor|plumber|electrician|repair guy|tech|technician)"
                     r" (?:says|said|told me) (?:that )?(?P<x>(?:it|the|my|they|we|he|she)\b.{3,80})", low)
    if m:
        return {"command": {"kind": "note", "text": f"the {m.group('who')} said {_as_he_said(text, m.group('x'))}"}, "say": None}
    # WHO CALLED (2026-10-08: "my mom called" went to the planner). A note
    # in his words; "who called today" reads the day's back. Only a person
    # of his or a name, so "the meeting got called off" is not one.
    m = re.fullmatch(r"(?P<who>my [a-z][a-z'-]{1,20}(?: [a-z][a-z'-]{1,20})?|[a-z][a-z'-]{1,20}"
                     # "The school called" (2026-10-08: to the planner).
                     r"|the (?:school|doctor'?s?(?: office)?|dentist'?s?(?: office)?|bank|pharmacy|vet|landlord|plumber|electrician"
                     r"|daycare|insurance company|office|hospital|clinic|mechanic|garage|nurse|coach|teacher|principal|recruiter))"
                     r" (?:just |finally )?"
                     r"(?:called|rang|texted|stopped by|came by|dropped by|came over|phoned)(?: me)?"
                     r"(?: (?:today|earlier|this morning|this afternoon|tonight|just now|back|about [a-z0-9' ]{2,40}))?", low)
    if m and (m.group("who").startswith(("my ", "the ")) or re.search(r"\b" + re.escape(m.group("who")).capitalize()
                                                              + r"\b", text)) \
            and m.group("who").split()[-1] not in ("it", "that", "this", "he", "she", "they", "who", "someone", "somebody",
                                                   "anyone", "nobody", "i", "you", "we", "meeting", "game"):
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
                                          "when", "where", "why", "how", "which", "whose", "whats", "wheres", "whens",
                                          "what's", "where's", "when's", "who's", "how's"):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # WHAT HE DOESN'T EAT, AND HIS KIDS (2026-10-07: "I don't like
    # mushrooms", "I'm vegetarian", "I have 3 kids", "my kids are Emma, Leo
    # and Sam" all went to the planner, and the questions after them to a
    # model). Notes in his words; "I don't like this" stays how he feels.
    m = re.fullmatch(r"i (?:really |just )?(?:don't like|do not like|dont like|don't really like|can't stand|cannot stand|can't eat|cannot eat|don't eat|never eat|dislike)"
                     r" (?P<thing>[a-z][a-z ,'-]{2,40})", low)
    if m and not re.match(r"(?:it|this|that|these|those|you|him|her|them|me|when|how|what|where|why|the way|being|to |my |your |his "
                          r"|their |our |people|anyone|anybody|someone|everyone|going|doing|having|getting|feeling|working|know|think"
                          r"|care|want|need|have|like it|get|see|mind|feel|remember|understand|trust|believe|agree)",
                          m.group("thing")) \
            and not re.search(r"\b(?:it|this|that|you|anymore|any more)$", m.group("thing")):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    if re.fullmatch(r"(?:i'm|i am|im) (?:a )?(?:vegetarian|vegan|pescatarian|gluten[- ]free|lactose intolerant|dairy[- ]free|kosher|halal)", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    if re.fullmatch(r"(?:i|we) (?:have|got) (?:\d{1,2}|one|two|three|four|five|six|seven|eight) (?:kids|children|sons|daughters|grandkids"
                    r"|grandchildren|brothers|sisters|siblings|kid|child|son|daughter|brother|sister)", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    m = re.fullmatch(r"(?:my|our) (?:kids|children|grandkids|grandchildren|sons|daughters)(?:'|'s)?(?: names)? are (?P<names>[a-z]+(?:, [a-z]+)*,? and [a-z]+)", low)
    if m and not (set(re.findall(r"[a-z]+", m.group("names"))) - {"and"}) & {
            "loud", "annoying", "sick", "tired", "happy", "grown", "great", "fine", "good", "bad", "crazy", "home", "asleep",
            "awake", "young", "older", "little", "big", "wild", "hungry", "bored", "cute", "smart", "busy", "ready", "done",
            "gone", "out", "away", "safe", "healthy", "well", "okay", "ok", "grumpy", "cranky", "upset", "sad", "excited",
            "noisy", "messy", "quiet", "adults", "teenagers", "twins", "fighting", "sleeping", "playing", "screaming", "amazing",
            "awesome", "sweet", "funny", "spoiled", "growing", "fast", "late", "early", "here", "there", "back"}:
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I GOT MARRIED IN 2018" (2026-10-07: to the planner, and "how long have
    # I been married" to a model). A note with the year, which
    # `quick._married` counts from.
    if re.fullmatch(r"(?:i|we) (?:got|were|was) married (?:in|on|back in) (?:[a-z]+ (?:\d{1,2}(?:st|nd|rd|th)?,? )?)?(?:19|20)\d\d"
                    r"|(?:i've|i have|we've|we have) been married (?:for |since )?(?:\d{1,2} years|(?:19|20)\d\d)", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # A PROMISE, A PACKAGE, A NEW THING (2026-10-07: "I promised Sarah I'd
    # help her move Saturday", "I have a package coming tomorrow" and "I got
    # a new phone" all went to the planner). Notes in his words.
    if re.fullmatch(r"i (?:promised|told) (?!(?:you|myself|her|him|them)\b)[a-z][a-z']{1,20}(?: [a-z][a-z']{1,20})? "
                    r"(?:(?:that )?i(?:'d| would| will|'ll) |to |i'd )[a-z][a-z ,'-]{3,80}", low) \
            and re.match(r"i promised", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    if re.fullmatch(r"(?:i have|i've got|i got|there's|there is) (?:a |an |my )?(?:package|parcel|delivery|order) (?:coming|arriving|due)"
                    r"(?: (?:on |this |next )?[a-z0-9 ]{3,25})?"
                    r"|(?:i'?m|i am|we'?re) expecting (?:a |an )?(?:package|parcel|delivery)(?: (?:on |this |next )?[a-z0-9 ]{3,25})?"
                    r"|(?:my|the|a) (?:[a-z]+ )?(?:package|parcel|delivery|order) (?:is coming|arrives|is arriving|comes|is due|should arrive|will arrive"
                    r"|is supposed to (?:come|arrive|be here|get here)|should (?:come|be here|get here)|will (?:come|be here|get here))"
                    r" (?:on |this |next )?[a-z0-9 ]{3,25}", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    if re.fullmatch(r"(?:i|we) (?:just )?(?:got|bought) (?:a |an |my )?new (?:phone|car|truck|laptop|computer|tv|television|bike|watch"
                    r"|tablet|ipad|iphone|couch|bed|mattress|fridge|washer|dryer|dishwasher|puppy|dog|cat|kitten|house|apartment)", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "MY DAUGHTER IS SICK" (2026-10-07: to the planner). Kept, and one
    # kind line - with the pronoun the relation carries.
    m = re.fullmatch(r"(?:my|our) (?P<rel>son|daughter|wife|husband|partner|kid|kids|mom|mum|dad|mother|father|brother|sister"
                     r"|baby|grandma|grandpa|girlfriend|boyfriend|dog|cat)(?:'s| is| are) (?:really |pretty |a bit |home )?"
                     r"(?:sick|ill|unwell|not feeling well|under the weather|in the hospital|in hospital|home sick|down with [a-z ]{2,20})", low)
    if m:
        rel = m.group("rel")
        who = ("she" if rel in ("daughter", "wife", "mom", "mum", "mother", "sister", "grandma", "girlfriend")
               else "they" if rel in ("kids", "partner", "baby", "kid", "dog", "cat") else "he")
        feels = "feel" if who == "they" else "feels"
        return {"command": {"kind": "note", "text": _as_he_said(text, low)},
                "say": f"I'm sorry. I hope {who} {feels} better soon - I've noted it."}
    # "My sister just had surgery" (2026-10-08: to the planner, and "my mom
    # had surgery today" was a 9 am hold). Kept, with one kind line.
    m = re.fullmatch(r"(?:my|our) (?P<rel>son|daughter|wife|husband|partner|kid|mom|mum|dad|mother|father|brother|sister|baby|grandma|grandpa"
                     r"|grandmother|grandfather|aunt|uncle|cousin|friend|girlfriend|boyfriend|mother in law|father in law|dog|cat)"
                     r" (?:just )?(?:had|came out of|got out of|is out of|is recovering from) (?:her |his |their |an? )?"
                     r"(?:surgery|operation|procedure|knee surgery|back surgery|hip surgery|heart surgery|shoulder surgery)"
                     r"(?: today| yesterday| this morning| last night)?", low)
    if m:
        rel = m.group("rel")
        who = ("she" if rel in ("daughter", "wife", "mom", "mum", "mother", "sister", "grandma", "grandmother", "aunt", "girlfriend", "mother in law")
               else "they" if rel in ("partner", "baby", "kid", "cousin", "friend", "dog", "cat") else "he")
        return {"command": {"kind": "note", "text": _as_he_said(text, low)},
                "say": f"I'm sorry. I hope {who} {'recover' if who == 'they' else 'recovers'} quickly - I've noted it."}
    # WHEN SOMEBODY'S DAY STARTS, AND WHERE THEY ARE (2026-10-07: "Emma's
    # school starts at 8" and "the kids are at grandma's this weekend" went
    # to the planner; "where are the kids" then searched his files).
    if re.fullmatch(r"(?:(?:my |our )?[a-z][a-z']{1,20}(?:'s|s'|s) |the |my |our )?(?:school|class|classes|practice|game|shift|bus|daycare"
                    r"|lesson|lessons|recital|rehearsal|work|camp|pickup|pick-up|drop-off|dropoff)"
                    r" (?:starts|begins|ends|finishes|gets out|lets out|is over|comes|leaves|is)(?: at| around| by)? "
                    r"\d{1,2}(?::\d\d)?(?: ?(?:am|pm))?(?: (?:on )?(?:weekdays|mondays?|tuesdays?|wednesdays?|thursdays?|fridays?|every day))?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    m = re.fullmatch(r"(?P<who>the kids|my kids|our kids|the boys|the girls|my (?:son|daughter|wife|husband|partner|mom|dad|parents)"
                     r"|[a-z]{2,15}) (?:is|are|will be|'s|'re) (?:at|staying at|staying with|with|over at) "
                     r"(?P<where>(?:the |my |our |a )?[a-z][a-z' ]{1,30}?)(?: (?:this|next|for the|tonight|today|tomorrow|until|till)[a-z ]{0,20})?", low)
    if m and not re.search(r"\d", low) and m.group("who") not in (
            "it", "this", "that", "he", "she", "they", "we", "dinner", "lunch", "breakfast", "work", "school", "practice", "everything",
            "nobody", "everyone", "someone", "who", "what", "where", "there", "here", "the meeting", "my meeting", "class", "party"):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # THE CAR (2026-10-07: "the check engine light is on" and "my car is due
    # for inspection in November" went to the planner). A warning light is
    # a job to get it looked at; a due date is a note `quick._life_when`
    # reads back.
    m = re.fullmatch(r"(?:my |the |our )?(?:car'?s? |truck'?s? )?(?P<light>check engine|tire pressure|tyre pressure|oil|battery|brake"
                     r"|abs|engine|coolant|maintenance|service engine soon|low fuel|airbag)(?: warning)? light (?:is|came|has come|just came|keeps coming)"
                     r"(?: back)? on", low)
    if m:
        light = m.group("light")
        job = {"tire pressure": "check the tire pressure", "tyre pressure": "check the tire pressure",
               "low fuel": "get gas"}.get(light, f"get the {light} light looked at")
        return _new_task(job)
    # "My tire is low", "I have a flat tire" (2026-10-08: to the planner).
    m = re.fullmatch(r"(?:my |the |our |a )?(?:car'?s? )?(?:front |back |rear )?(?:left |right )?(?:front |back |rear )?(?:tire|tyre)s? "
                     r"(?:is|are|looks?|seems?|is looking|went|keeps going) (?:a (?:bit|little) |really |kind of |kinda )?(?P<how>low|flat|soft|going flat|getting low|bald)(?: again)?"
                     r"|i (?:have|got|'ve got|just got) a (?P<flat>flat)(?: tire| tyre)?(?: again)?", low)
    if m:
        how = m.group("how") or ""
        return _new_task("get the flat tire fixed" if m.group("flat") or how in ("flat", "going flat")
                         else "get new tires" if how == "bald" else "put air in the tires")
    # "The oil change is due at 45000 miles" (2026-10-08: to the planner).
    # Kept; "how many miles until my oil change" reads it against his mileage.
    if re.fullmatch(r"(?:my |the |our )?(?:next )?(?:car'?s? )?(?:oil change|service|tune-?up|tire rotation|inspection|timing belt)"
                    r" (?:is )?(?:due|needed) (?:at|by|around) [\d,]+(?:k)? ?(?:miles|mi|km)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    if re.fullmatch(r"(?:my |the |our )(?:car|truck|van|suv)(?:'s| is)? (?:due|overdue) for (?:an? |its |her |his )?"
                    r"(?:inspection|service|oil change|tune-?up|smog check|emissions test|tire rotation|registration)"
                    r"(?: (?:in|on|by|next|this|at) [a-z0-9 ,]{2,30})?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # AN ALLERGY, SAID AS ONE (2026-10-07): "I'm allergic to peanuts" went
    # to the planner, while "what am I allergic to" reads notes. A note in
    # his words is the writer that reader was missing.
    if re.fullmatch(r"(?:i'm|i am|im) (?:very |really |severely |slightly |a (?:bit|little) )?allergic to [a-z][a-z ,'-]{1,60}"
                    r"|i have (?:an? |a severe |a mild )?(?:[a-z]+ )?allerg(?:y|ies) to [a-z][a-z ,'-]{1,60}"
                    r"|my allerg(?:y is|ies are) [a-z][a-z ,'-]{1,60}", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "The furnace filter is 16x25x1", "my tire size is 225/65R17"
    # (2026-10-08: to the planner) - a size he will need at the store.
    m = re.fullmatch(r"(?:the |my |our )?(?P<what>(?:furnace |air |ac |hvac |fridge |refrigerator |water )?filter|tires?|tire size|wiper blades?|wipers"
                     r"|light bulbs?|bulbs?|mattress|bed|ring|shoe|shirt|pants|jeans|dress|bra|glove|hat|coat|jacket)"
                     r"(?: size)? (?:is|are|is a|takes|take|uses|use) (?:a |an |size )?(?P<size>\d[\dx./r -]{1,15}[a-z0-9]{0,4}|(?:small|medium|large|x-?large|xl|xxl|king|queen|twin|full))", low)
    if m and (re.search(r"\d.*[x/r]|\d", m.group("size")) or re.search(r"\bsize\b", low) or m.group("what") in ("mattress", "bed")):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # WHEN SOMETHING HAPPENS AT HIS HOUSE (2026-10-07: "the trash goes out
    # on Tuesdays", "recycling is every other Wednesday", "the kids have
    # soccer on Saturdays at 9", "the babysitter is coming at 6" - all to
    # the planner). A note in his words, read back by "when is soccer".
    _days = r"(?:mondays?|tuesdays?|wednesdays?|thursdays?|fridays?|saturdays?|sundays?|weekends?|weekdays?)"
    _at = r"(?: (?:at|around|by) \d{1,2}(?::\d\d)?(?: ?(?:am|pm))?)?"
    m = (re.fullmatch(r"(?:the )?(?P<thing>trash|garbage|recycling|rubbish|bins?|compost|yard waste|cleaner|cleaners|cleaning lady"
                      r"|gardener|lawn guy|mail|newspaper|street cleaning|piano lessons?|[a-z]+ practice|[a-z]+ lessons?|[a-z]+ class)"
                      r" (?:goes out|go out|is|are|comes|come|happens|gets picked up|is picked up|is collected|day is)"
                      r" (?:on |every |each )?(?:other )?(?:" + _days + r"|day)(?: night| nights| morning| mornings| evening| evenings)?" + _at, low)
         or re.fullmatch(r"(?:the kids|my kids|our kids|my son|my daughter|we|[a-z]{2,15}) (?:have|has|go to|goes to) "
                         r"(?P<thing2>[a-z][a-z ]{1,20}?) (?:on |every |each )(?:other )?" + _days + _at, low)
         # "My son has soccer practice tuesdays at 5" (2026-10-07: to the
         # planner) - a plural day is "every" that day; "I have book club
         # on the first Thursday of every month".
         or re.fullmatch(r"(?:the kids|my kids|our kids|my son|my daughter|we|i|[a-z]{2,15}) (?:have|has|go to|goes to) "
                         r"(?P<thing5>[a-z][a-z ]{1,20}?) (?:mondays|tuesdays|wednesdays|thursdays|fridays|saturdays|sundays|weekends|weekdays)" + _at, low)
         or re.fullmatch(r"(?:the kids|my kids|our kids|my son|my daughter|we|i|[a-z]{2,15}) (?:have|has|go to|goes to) "
                         r"(?P<thing6>[a-z][a-z ]{1,20}?) (?:on )?(?:the |every )?(?:first|second|third|fourth|last) "
                         r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|day|weekend) of (?:every|each|the) month" + _at, low)
         or re.fullmatch(r"(?:the |my |our )?(?P<thing3>babysitter|sitter|nanny|cleaner|cleaners|plumber|electrician|handyman"
                         r"|contractor|delivery|repair ?man|technician|movers|guests|in-laws|my parents|[a-z]{2,15}) (?:is|are) "
                         r"(?:coming|arriving|coming over|getting here) (?:at \d{1,2}(?::\d\d)?(?: ?(?:am|pm))?|tonight|tomorrow"
                         r"(?: at \d{1,2}(?::\d\d)?(?: ?(?:am|pm))?)?|(?:on )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
                         + _at + r")", low)
         # "The dentist is the 15th at 10" (2026-10-07: to the planner).
         or re.fullmatch(r"(?:the |my |our )?(?P<thing4>dentist|doctor|vet|haircut|interview|meeting|party|wedding|game|recital"
                         r"|concert|game|recital|surgery|checkup|check-up|physical|[a-z]+ appointment) is (?:on )?(?:"
                         + SPOKEN_DATE + r"|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday"
                         r"|" + _MONTH + r" \d{1,2}(?:st|nd|rd|th)?)" + _at, low)
         # "School starts August 20", "Leo's school pictures are on the 14th"
         # and "Leo has a field trip Thursday" (2026-10-08: to the planner).
         or re.fullmatch(r"(?:the |my |our |[a-z]{2,15}'s )?(?P<thing7>[a-z][a-z ]{1,25}?) (?:starts?|begins?|ends?|finishes|opens|closes"
                         r"|is|are|is over|gets out|lets out) (?:on |back )?(?:" + SPOKEN_DATE
                         # "My next checkup is in January" (2026-10-08: to the planner)
                         + r"|in " + _MONTH + r"(?: \d{4})?|next (?:week|month|year)|in (?:the )?(?:spring|summer|fall|autumn|winter)"
                         + r"|" + _MONTH + r" \d{1,2}(?:st|nd|rd|th)?|tomorrow|(?:this |next )?(?:monday|tuesday|wednesday|thursday"
                         r"|friday|saturday|sunday))" + _at, low)
         or re.fullmatch(r"(?:the kids|my kids|our kids|my son|my daughter|[a-z]{2,15}) (?:has|have) (?:a |an )(?P<thing8>[a-z][a-z ]{1,25}?)"
                         r" (?:on )?(?:" + SPOKEN_DATE + r"|" + _MONTH + r" \d{1,2}(?:st|nd|rd|th)?|today|tomorrow|(?:this |next )?"
                         r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))", low)
         # "I have class at 9 on Mondays and Wednesdays" (2026-10-08: to the
         # planner): a time, then the plural days, joined.
         or re.fullmatch(r"(?:the kids|my kids|our kids|my son|my daughter|we|i|[a-z]{2,15}) (?:have|has|go to|goes to) "
                         r"(?P<thing10>[a-z][a-z ]{1,20}?) at \d{1,2}(?::\d\d)?(?: ?(?:am|pm))? (?:on |every )?"
                         r"(?:mondays|tuesdays|wednesdays|thursdays|fridays|saturdays|sundays|weekends|weekdays)"
                         r"(?:(?:,| and|, and) (?:mondays|tuesdays|wednesdays|thursdays|fridays|saturdays|sundays))*", low)
         # "My daughter has practice every Tuesday and Thursday at 5"
         # (2026-10-08: to the planner): the days first, then the time.
         or re.fullmatch(r"(?:the kids|my kids|our kids|my son|my daughter|we|i|[a-z]{2,15}) (?:have|has|go to|goes to) "
                         r"(?P<thing11>[a-z][a-z ]{1,20}?) (?:on |every )(?:mondays?|tuesdays?|wednesdays?|thursdays?|fridays?|saturdays?|sundays?|weekends|weekdays)"
                         r"(?:(?:,| and|, and) (?:mondays?|tuesdays?|wednesdays?|thursdays?|fridays?|saturdays?|sundays?))*"
                         r"(?: at \d{1,2}(?::\d\d)?(?: ?(?:am|pm))?)?", low)
         # "The kids have soccer at 5 on Saturday": no article, and the time
         # before the day (2026-10-08: to the planner).
         or re.fullmatch(r"(?:the kids|my kids|our kids|my son|my daughter|[a-z]{2,15}) (?:has|have) (?:a |an )?(?P<thing9>[a-z][a-z ]{1,20}?)"
                         r" at \d{1,2}(?::\d\d)?(?: ?(?:am|pm))? (?:on |this |next )?(?:" + SPOKEN_DATE + r"|today|tonight|tomorrow"
                         r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday)", low))
    if m and ((m.groupdict().get("thing5") or m.groupdict().get("thing6") or m.groupdict().get("thing10")
               or m.groupdict().get("thing11"))
              and low.startswith(("i have ", "we have ", "i go to "))
              or not re.match(r"(?:it|this|that|he|she|they|who|what|i|you)\b", low)):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # SOMEBODY ELSE'S ALLERGY, AND WHEN SOMEBODY WAS BORN (2026-10-07: "my
    # daughter is allergic to nuts" and "Leo was born on May 3 2018" went
    # to the planner, and "how old is Leo" had nothing to read).
    m = re.fullmatch(r"(?:my |our )?(?P<who>[a-z][a-z']{1,20}(?: [a-z][a-z']{1,20})?) (?:is|are) (?:very |severely |really )?allergic to "
                     r"[a-z][a-z ,'-]{1,60}"
                     r"|(?:my |our )?(?P<who2>[a-z][a-z']{1,20}(?: [a-z][a-z']{1,20})?) (?:was|were) born (?:on |in )?"
                     r"(?:" + _MONTH + r"\.? \d{1,2}(?:st|nd|rd|th)?|\d{1,2}(?:st|nd|rd|th)? (?:of )?" + _MONTH + r")(?:,? (?:19|20)\d\d)?"
                     # "My mom was born in 1965" (2026-10-07: to the planner).
                     r"|(?:my |our )?(?P<who3>[a-z][a-z']{1,20}(?: [a-z][a-z']{1,20})?) (?:was|were) born in (?:19|20)\d\d", low)
    if m and (m.group("who") or m.group("who2") or m.group("who3")).split()[0] not in (
            "i", "he", "she", "it", "they", "who", "what", "which", "that", "this", "everyone", "everybody", "nobody", "someone",
            "you", "we"):
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
    m = re.fullmatch(r"(?:my |our )?(?P<key>(?:favou?rite|fave) [a-z ]{2,25}|[a-z][a-z' ]{0,30}?(?:'s|s') (?:name|birthday|anniversary"
                     # "Leo's teacher is Mrs. Brown", "Leo's school is Lincoln
                     # Elementary" (2026-10-07: to the planner).
                     r"|teacher|school|coach|pediatrician|doctor|dentist|class|grade|team|best friend|nickname|shoe size"
                     r"|clothes size|shirt size|bedtime|daycare|babysitter|nanny|tutor|vet|middle name|last name"
                     # "Anna's favorite flower is tulips" (2026-10-08: to the planner).
                     r"|(?:favou?rite|fave) [a-z]{2,20}(?: [a-z]{2,20})?)"
                     r"|blood type|shoe size|shirt size|ring size|pants size|dress size|wifi(?: password| name| network(?: name| password)?)?|wi-fi(?: password| network)?"
                     r"|gate code|door code|garage code|(?:gym |school |work |bike )?locker(?: number| combination| combo| code)?|bike lock(?: code| combo| combination)?"
                     r"|license plate|plate number"
                     # "My hotel is the Hilton downtown" (2026-10-08: to the planner).
                     r"|hotel|airbnb|rental car|rental|hotel address|campsite|cabin"
                     # "My doctor is Dr Patel" (2026-10-07: to the planner) -
                     # who someone IS to him, read back by "who's my doctor".
                     r"|(?:doctor|dentist|vet|pediatrician|therapist|lawyer|accountant|landlord|boss|manager|mechanic"
                     r"|barber|hairdresser|hair stylist|trainer|pharmacist|optometrist|eye doctor|gp|realtor|babysitter|nanny"
                     # "My professor is Dr. Smith" (2026-10-08: to the planner).
                     r"|professor|[a-z]+ professor|advisor|adviser|academic advisor|ta|[a-z]+ teacher|teacher|tutor|coach|counselor|principal)"
                     r"|anniversary|account number|member(?:ship)? number|(?:insurance |car insurance |auto insurance |home insurance |health insurance )?policy number"
                     # "My deductible is 500" (2026-10-08: to the planner).
                     r"|deductible|copay|co-pay|premium|insurance premium|out of pocket max(?:imum)?"
                     # "My GPA is 3.5", "my credit score is 720" (2026-10-08: to the planner).
                     r"|gpa|credit score|sat score|act score|golf handicap|handicap"
                     # "Our mortgage rate is 6.5 percent" (2026-10-08: to the planner).
                     r"|(?:mortgage|interest|loan|car loan|savings|cd) rate|apr|closing date|move(?:-in| in)? date|moving date|contractor|movers?"
                     # "My flight number is UA 452" (2026-10-07: to the
                     # planner) - held to a digit below.
                     r"|(?P<coded>(?:flight|confirmation|booking|reservation|tracking|order|case|ticket|claim|seat|gate"
                     r"|frequent flyer|rewards|loyalty|room|parking spot|spot) (?:number|code|#)"
                     # "My flight confirmation is XJ4K2" (2026-10-08: to the planner).
                     r"|(?:flight|hotel|booking|rental car|car rental|airbnb|trip) confirmation(?: number| code| #)?"
                     # "My insurance member id is ABC123", "my library card
                     # number is 12345" (2026-10-08: to the planner).
                     r"|(?:insurance |health insurance |dental |vision |gym |library |costco )?(?:member(?:ship)?|library card"
                     r"|card|passport|driver'?s license|license|licence|vin|patient|group) (?:id|number|#)"
                     # "My parking spot is B12", "my hotel room is 512" (2026-10-08: to the planner)
                     r"|parking spot|parking space|spot|hotel room|room|seat|desk|cubicle|apartment|apartment number|unit|suite|gate"
                     # "My tax refund is 1200" (2026-10-08: to the planner)
                     r"|(?:federal |state )?tax refund|refund|tax bill|property tax(?:es)?|income|annual income|bonus|raise|pay raise|take[- ]home pay|hourly rate|pay rate"
                     r"|(?:netflix|hulu|spotify|amazon|work|school|email|[a-z]+) (?:login|username|user name))"
                     # "My budget is 2000 a month", "my goal is to run a marathon"
                     # (2026-10-07: to the planner). Held to a number or an aim
                     # below, so "my budget is tight" stays how he feels.
                     r"|(?:monthly |weekly |daily |grocery |food |eating out |gas |fun |shopping |step |calorie |water |reading |savings )?(?:budget|goal)"
                     r"|goal weight|target weight|bedtime|employee (?:id|number)|student (?:id|number)"
                     r"|insurance(?: company| provider)?|pharmacy|gym"
                     # "My emergency contact is my mom", "my prescription is
                     # lisinopril 10mg" (2026-10-07: to the planner).
                     r"|emergency contact|prescriptions?|medications?|meds|daily medication"
                     r"|(?:car|truck|van|suv)(?:'s|s)? (?:mileage|milage|odometer)"
                     # "My rent is 1500", "my car insurance is 120 a month"
                     # (2026-10-07: to the planner) - held to a number below.
                     r"|(?P<bill>" + _BILL_WORDS + r")) (?:is|are) (?P<value>.{1,80})", fact_low)
    if m and (m.group("bill") or m.group("coded")) and not re.search(r"\d", m.group("value")):
        m = None
    # "My locker is 42" (2026-10-07: to the planner) - a locker with no
    # number in it is where he left something, not which one is his.
    if m and re.search(r"(?:budget|goal|weight|bedtime|locker)$", m.group("key")) \
            and not (re.search(r"\d", m.group("value")) or m.group("value").startswith(("to ", "a ", "an "))
                     and m.group("key").endswith("goal")):
        m = None
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
    # HIS PAY (2026-10-07: "my paycheck is 2000 every two weeks", "I get paid
    # every other Friday", "I make 25 an hour" and "I got paid today" all went
    # to the planner). A note in his words, held to a number or a day, so
    # "my pay is terrible" stays how he feels.
    if (re.fullmatch(r"(?:my |our )?(?:new |current )?(?:paycheck|pay ?check|pay|salary|income|take[- ]home(?: pay)?|hourly rate|wage|wages)"
                     r" (?:is|are) (?:about |around )?\$?\d[\d,.k]*.{0,40}", fact_low)
            or re.fullmatch(r"i (?:make|earn|get paid|bring home|take home|get) (?:about |around )?\$?\d[\d,.k]*(?: dollars| bucks)?"
                            r" (?:an? |per |every |each )(?:hour|week|month|year|two weeks|other week)(?: after tax(?:es)?| before tax(?:es)?)?", fact_low)
            or re.fullmatch(r"i get paid (?:every|each|on|the|twice|weekly|biweekly|bi-weekly|monthly|fortnightly)\b.{0,40}", fact_low)
            or re.fullmatch(r"(?:my )?pay ?day is (?:on )?(?:every |each |the )?[a-z0-9 ]{2,30}", fact_low)
            or re.fullmatch(r"i (?:just )?got (?:my )?(?:paid|paycheck|pay ?check)(?: today| this morning)?", fact_low)) \
            and not re.search(r"\b(?:terrible|awful|bad|low|late|not|never|enough)\b", fact_low):
        return {"command": {"kind": "note", "text": _as_he_said(text, fact_low)}, "say": None}
    # "HOW MUCH DO I MAKE A YEAR" from the pay he told her, worked out.
    if re.fullmatch(r"how much (?:do i|money do i) (?:make|earn|get paid|bring home)(?: (?:an? |per )(?:hour|week|month|year))?"
                    r"|what(?:'s| is) my (?:yearly |annual |monthly |weekly )?(?:income|salary|pay)(?: (?:a|per) (?:year|month|week))?"
                    r"|when(?:'s| is) (?:my )?(?:next )?(?:pay ?day|pay ?check)|when do i (?:next )?get paid(?: next| again)?"
                    # "How many days until payday" (2026-10-07: to a model).
                    r"|how (?:many days|long) (?:is it )?(?:until|till|til|to) (?:my )?(?:next )?(?:pay ?day|paycheck|i get paid)"
                    r"|when did i (?:last )?get paid(?: last)?"
                    # "How much did I get paid" (2026-10-07: to a model, after "I got paid 1800 today").
                    r"|how much (?:did i (?:get paid|make|earn)|was my (?:last )?(?:paycheck|pay ?check))(?: today| this week| last time)?", low.rstrip("?")):
        from aletheia import quick
        told = quick._pay(low)
        if told:
            return {"command": None, "say": told}
    # "MY FLIGHT IS AT 6AM FRIDAY" (2026-10-07: to the planner, so "when is
    # my flight" had nothing to read). A trip he is told about is a note in
    # his words, which `quick._when_mine` reads back - only with a time or a
    # day in it, so "my flight is delayed" stays news.
    m = re.fullmatch(r"(?:my|our) (?:(?:return|outbound|connecting|early|late|next) )?(?P<trip>flight|plane|train|bus|ferry|cruise"
                     r"|shuttle|ride|uber|lyft|pickup|pick-up|check-in|checkout|check-out)"
                     r" (?:is|leaves|departs|takes off|lands|arrives|gets in|boards|comes)(?: back)? (?P<when>.{2,60})", fact_low)
    if m and re.search(r"\d|\b(?:today|tonight|tomorrow|noon|midnight|monday|tuesday|wednesday|thursday|friday|saturday"
                       r"|sunday|morning|afternoon|evening|next week)\b", m.group("when")) \
            and not re.search(r"\b(?:delayed|late|cancell?ed|early|full|over|done|gone)\b", m.group("when")):
        return {"command": {"kind": "note", "text": _as_he_said(text, fact_low)}, "say": None}
    # "I LENT MY DRILL TO BOB" (2026-10-07: to the planner, and "who has my
    # drill" with nothing to read). A thing, not money - money is the
    # ledger's ("I lent Sam 20 dollars").
    m = (re.fullmatch(r"i (?:lent|loaned|gave|handed) (?:my |our |the )(?P<thing>[a-z][a-z' ]{1,25}?) to (?P<who>[a-z][a-z' ]{1,25})", fact_low)
         or re.fullmatch(r"i (?:lent|loaned) (?P<who>[a-z][a-z']{1,20}(?: [a-z][a-z']{1,20})?) (?:my|our|the) (?P<thing>[a-z][a-z' ]{1,25})", fact_low)
         or re.fullmatch(r"(?P<who>[a-z][a-z']{1,20}(?: [a-z][a-z']{1,20})?) (?:borrowed|has|took|is borrowing|has got) "
                         r"(?:my|our) (?P<thing>[a-z][a-z' ]{1,25})", fact_low))
    if m and not re.search(r"\d|\b(?:dollars?|bucks|money|cash|euros?|pounds?|ride|hand|call|break|chance|hug|kiss|lift"
                           r"|attention|word|heart|back|number|money)\b", m.group("thing")) \
            and m.group("who").split()[0] not in ("who", "what", "he", "she", "they", "it", "this", "that", "somebody",
                                                  "someone", "nobody", "everyone", "i", "you", "where", "why", "when", "how"):
        return {"command": {"kind": "note", "text": _as_he_said(text, fact_low)}, "say": None}
    # "I borrowed a ladder from Sam" (2026-10-08: to the planner) - his to
    # give back; money borrowed is the ledger's, above.
    m = re.fullmatch(r"i borrowed (?:a |an |the |some |his |her |their )?(?P<thing>[a-z][a-z' ]{1,30}?) from (?P<who>[a-z][a-z' ]{1,30})", fact_low) \
        or re.fullmatch(r"i (?:gave|brought|took|returned) (?:back )?(?:the |his |her |their |[a-z]+'s )(?P<thing>[a-z][a-z' ]{1,30}?)"
                        r" back(?: to [a-z][a-z' ]{1,30})?", fact_low)
    if m and not re.search(r"\d|\b(?:dollars?|bucks|money|cash)\b", m.group("thing")):
        return {"command": {"kind": "note", "text": _as_he_said(text, fact_low)}, "say": None}
    # "MIKE GAVE BACK MY DRILL" / "I GOT MY DRILL BACK" (2026-10-07: to the
    # planner, and "who has my drill" went on naming Mike). The return is a
    # note too; the newest note about the thing is the one `quick._lent` reads.
    m = (re.fullmatch(r"(?P<who>[a-z][a-z']{1,20}(?: [a-z][a-z']{1,20})?) (?:gave|brought|handed) (?:back )?(?:my|our|the) "
                      r"(?P<thing>[a-z][a-z' ]{1,25}?)(?: back)?", fact_low)
         or re.fullmatch(r"(?P<who>[a-z][a-z']{1,20}(?: [a-z][a-z']{1,20})?) returned (?:my|our|the) (?P<thing>[a-z][a-z' ]{1,25})", fact_low)
         or re.fullmatch(r"i got (?:my|our) (?P<thing>[a-z][a-z' ]{1,25}?) back(?: from (?P<who>[a-z][a-z' ]{1,25}))?", fact_low))
    if m and (m.group("who") or "mike") .split()[0] not in ("who", "what", "he", "she", "they", "it", "this", "that", "i", "you",
                                                          "where", "why", "when", "how", "nobody", "somebody", "someone") \
            and not re.search(r"\d|\b(?:money|dollars?|bucks|cash|call|hug|word|heart|life|job|time|confidence|attitude)\b",
                              m.group("thing")) \
            and (" back" in fact_low or "returned" in fact_low):
        return {"command": {"kind": "note", "text": _as_he_said(text, fact_low)}, "say": None}
    # "I LIKE MY COFFEE BLACK" (2026-10-07: to the planner) - how he takes
    # something he eats or drinks, read back by "how do I like my coffee".
    if re.fullmatch(r"i (?:like|take|have|drink|want|prefer) my (?:coffee|tea|steak|burgers?|eggs|toast|latte|martini|whiskey"
                    r"|bourbon|pizza|tacos|sandwich|smoothie|oatmeal) (?!a lot\b|so much\b|too\b|now\b|every\b|at\b|in the\b)"
                    r"[a-z][a-z ,'-]{1,40}", fact_low):
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
    # "Note to self buy stamps" kept "to self buy stamps" (2026-10-07).
    m = re.match(r"(?:(?:make a |take a |a )?note to (?:my)?self(?: that)?|make a note(?: that| of| to(?! (?:my)?self)|:)?|take a note(?: that|:)?|jot down(?: that)?|"
                 # "Write a note that the car needs oil" (2026-10-07: to the planner).
                 r"(?:write|leave|add|save|create|make) (?:me )?a (?:new )?note(?: that| saying| of| to(?! (?:my)?self)|:)?|"
                 # "Add to my notes that ...", "new note: ..." (2026-10-07: to the planner).
                 r"(?:add|put|save|write|stick) (?:this |that |it )?(?:to|in|into|on) my notes(?: that|:)?|new note(?: that|:)?|"
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

    # "I forgot to call mom" (2026-10-08: to the planner) is still to do.
    m = re.fullmatch(r"(?:oh |oops,? |dang,? |shoot,? )?i (?:totally |completely )?forgot to (?P<what>[a-z].{2,80}?)(?: today| yesterday| this morning| earlier)?", low)
    if m and _TASK_VERB.match(m.group("what")):
        got = _new_task(_as_he_said(text, m.group("what")))
        got["say"] = f"It's on your list now: {got['command']['description']}."
        return got
    # "I started the laundry", "I took the chicken out to thaw", "I forgot
    # my lunch" (2026-10-08: to the planner). Only these things: "I started
    # crying" is not a chore, and "I moved my car" has its own door.
    _chore = (r"(?:the |a |my |some )?(?:laundry|load of laundry|wash|washer|washing machine|dryer|dishwasher|dishes|oven|slow cooker|crock ?pot"
              r"|instant pot|roomba|sprinklers?|groceries|towels|sheets|clothes)")
    _meat = r"(?:the |some |a )?(?:chicken|meat|steak|steaks|roast|turkey|ground beef|beef|fish|salmon|pork|pork chops|shrimp|burgers?|ham|lasagna|chili|soup)"
    if re.fullmatch(r"i (?:just )?(?:started|ran|turned on|switched on|folded|put away|unloaded|loaded|emptied) " + _chore
                    + r"(?: (?:today|this morning|tonight|earlier))?", low) \
            or re.fullmatch(r"i (?:just )?(?:took|pulled|got) " + _meat + r" out(?: of the freezer)?(?: to (?:thaw|defrost))?(?: for (?:dinner|tonight|tomorrow))?", low) \
            or re.fullmatch(r"i (?:just )?(?:put|stuck) " + _meat + r" in the (?:oven|fridge|slow cooker|crock ?pot|instant pot)(?: to thaw)?", low) \
            or re.fullmatch(r"i (?:totally )?forgot my (?:lunch|wallet|phone|keys|laptop|charger|badge|id|glasses|bag|backpack|umbrella|water bottle|jacket|coat)"
                            r"(?: at (?:home|work|the office|school|the gym))?(?: today)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "My wife wears a size 8", "I wear a medium" (2026-10-08: to the planner).
    if re.fullmatch(r"(?:i|(?:my|our) [a-z]{2,12}|[a-z]{2,12}) (?:wear|wears|take|takes) (?:a |an )?(?:size )?"
                    r"(?:\d{1,2}(?:\.5)?(?: ?(?:w|wide|narrow|petite|tall))?|\d{2} ?x ?\d{2}|x{0,2}-?small|small|medium|x{0,3}-?large|large|xs|s|m|l|xl|xxl|xxxl|[0-9]{1,2}[a-d]{1,3})"
                    r"(?: (?:in |for )?(?:shoes?|sneakers|boots|pants|jeans|shirts?|t-?shirts|tops?|dress(?:es)?|jackets?|coats?|bras?|rings?|hats?|gloves|socks|shorts|underwear))?", low) \
            and not re.match(r"(?:who|what|which|it|he|she|they|you)\b", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I got a raise to 85000", "my commute took an hour today" (2026-10-08: to the planner).
    if re.fullmatch(r"i (?:just )?got a (?:raise|promotion|bump)(?: to| up to) \$?\d[\d,.]*k?(?: dollars| bucks)?(?: (?:a|per|an) (?:year|hour|month))?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": "Congratulations - that's well earned."}
    if re.fullmatch(r"(?:my|the) (?:commute|drive|drive home|drive in|drive to work|bus|train|ride)(?: home| in| to work)? (?:took|was|lasted) "
                    r"(?:about |almost |over |nearly )?(?:an hour(?: and a half)?|half an hour|\d{1,3} (?:minutes?|mins?|hours?))(?: today| this morning| tonight)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I have a deadline Friday for the budget report" (2026-10-08: to the planner).
    m = re.fullmatch(r"i (?:have|got|'ve got) a deadline (?:(?:on |this |next )?(?P<day>[a-z]+day|tomorrow|today|tonight) )?for (?P<what>(?:the |my |a )?[a-z][a-z0-9' ]{1,40}?)"
                     r"(?: (?:on |this |next )?(?P<day2>[a-z]+day|tomorrow|today|tonight))?", low)
    if m and (m.group("day") or m.group("day2")) and (m.group("day") or m.group("day2")) in WEEKDAYS + ("tomorrow", "today", "tonight"):
        return _interpret(f"i need to finish {m.group('what')} by {m.group('day') or m.group('day2')}")
    # "I'm going out with friends tonight", "I'll be home late" (2026-10-08:
    # "I can't think" and the planner). Kept, so "what time will I be home"
    # has his words to read.
    if re.fullmatch(r"(?:i'?m|i am|we'?re|we are) (?:going out|heading out|going out for drinks|going for drinks|going out to eat)"
                    r"(?: with (?:some |a few |my )?(?:friends|the guys|the girls|coworkers|work friends|the team|[a-z]{2,15}))?"
                    r"(?: (?:tonight|this evening|after work|later|tomorrow night|on (?:friday|saturday) night|friday night|saturday night))?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": "Have fun."}
    if re.fullmatch(r"(?:i'?ll|i will|i'?m going to|i'?m gonna) be (?:home|back) (?:late|early|around \d{1,2}(?::\d\d)?(?: ?[ap]m)?|by \d{1,2}(?::\d\d)?(?: ?[ap]m)?|after \d{1,2}(?::\d\d)?(?: ?[ap]m)?)"
                    r"(?: (?:tonight|today|tomorrow))?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I take my pill at 8 every morning" (2026-10-08: to the planner). Kept
    # as he said it, with the sentence that makes it a reminder.
    m = re.fullmatch(r"i (?:usually |always |normally )?take (?P<what>(?:my |a |an |the )?[a-z][a-z' ]{1,30}?) "
                     r"(?:(?P<at>at \d{1,2}(?::\d\d)?(?: ?[ap]m)?) (?P<every>every (?:morning|night|evening|day))"
                     r"|(?P<every2>every (?:morning|night|evening|day)) (?P<at2>at \d{1,2}(?::\d\d)?(?: ?[ap]m)?))", low)
    if m and re.search(r"\b(?:pills?|medicine|meds|medication|vitamins?|insulin|inhaler|dose|tablets?|capsules?|supplements?)\b|"
                       + _quick._DRUGS, m.group("what")):
        what = _as_he_said(text, m.group("what"))
        every, at = m.group("every") or m.group("every2"), m.group("at") or m.group("at2")
        return {"command": {"kind": "note", "text": _as_he_said(text, low)},
                "say": f"Noted. Want a reminder too? Say \"remind me to take {what} {every} {at}\"."}
    # "The internet is slow", "I switched to Verizon" (2026-10-08: to the planner).
    if re.fullmatch(r"(?:the |my |our )?(?:internet|wifi|wi-fi|connection|cable|tv|power|electricity|water|heat|ac|a/c|cell service|signal)"
                    r" (?:is|keeps|has been|was) (?:really |so |super |very )?(?:slow|spotty|out|dropping|cutting out|going out|acting up|flaky|weak|off|back on)"
                    r"(?: again| today| tonight| all day| this morning)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    if re.fullmatch(r"(?:i|we) (?:just )?(?:switched|changed|moved|went) (?:over )?(?:my |our )?(?:phone |cell |internet |insurance |electric |power |cable )?"
                    r"(?:carrier |provider |plan |company )?to [a-z][a-z&' -]{1,25}", low) \
            and not re.search(r"\bto (?:bed|sleep|work|school|the |a |my |decaf|tea)\b", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "My sister lands at 4 on Friday", "my sister left" (2026-10-08: to the
    # planner). Kept with the day it meant, for "when does my sister land".
    m = re.fullmatch(r"(?P<who>(?:my|our) (?:in[ -]laws|[a-z]{2,15}(?: in[ -]laws?)?)|[a-z]{2,15}) (?P<verb>lands?|arrives?|gets? in|flies in|fly in|gets? here|comes? in)"
                     r"(?P<at> at \d{1,2}(?::\d\d)?(?: ?[ap]m)?)?(?: (?:on |this )?(?P<day>today|tonight|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?"
                     r"(?P<at2> at \d{1,2}(?::\d\d)?(?: ?[ap]m)?)?", low)
    if m and (m.group("at") or m.group("at2") or m.group("day")) and m.group("who") not in ("it", "he", "she", "who", "what", "that", "this", "the", "everyone"):
        import datetime as _dtl
        day = ""
        if m.group("day") and _spoken_day(m.group("day")):
            on = _dtl.date.fromisoformat(_spoken_day(m.group("day"))[:10])
            day = f" on {on.strftime('%A')} {on.day} {on.strftime('%B')}"
        at = (m.group("at") or m.group("at2") or "")
        return {"command": {"kind": "note", "text": f"{_as_he_said(text, m.group('who'))} {m.group('verb')}{at}{day}"}, "say": None}
    if re.fullmatch(r"(?:my|our) (?:sister|brother|mom|mother|dad|father|parents|in laws|in-laws|mother in law|father in law|guests?|friends?|cousin|aunt|uncle|grandma|grandpa|grandparents|kids)"
                    r" (?:left|went home|headed home|flew home|took off)(?: today| this morning| tonight| yesterday)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I got a 50 dollar gift card to Target" (2026-10-08: to the planner).
    if re.fullmatch(r"(?:i (?:just )?(?:got|have|received|was given)|(?:[a-z]{2,15}|my [a-z]{2,15}) gave me) (?:a |an )?\$?\d[\d,]*(?: dollar| buck)? gift ?card"
                    r"(?: (?:to|for|from) [a-z][a-z&' -]{1,25})*", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I'm on season 3", a turn after "I'm watching Breaking Bad" (2026-10-08:
    # "I can't think"). The show is the one he said he is watching.
    m = re.fullmatch(r"(?:i'?m|i am) (?:now |up to |currently )?on (?P<where>(?:season|episode|chapter|page|book|part|level) \d{1,4}(?:,? (?:episode|chapter) \d{1,3})?)", low)
    if m:
        kind = "reading" if re.match(r"(?:chapter|page|book|part)\b", m.group("where")) else "watching"
        title = ""
        for row in _quick._notes()[:20]:
            said = " ".join(str(row.get("text") or "").split()).rstrip(".")
            got = re.fullmatch(rf"(?i:i'?m|i am|i'?ve been|i have been|i (?:just )?started) {kind} (?P<t>.{{2,60}})", said)
            if got:
                title = got.group("t")
                break
        return {"command": {"kind": "note", "text": f"I'm on {m.group('where')}" + (f" of {title}" if title else "")}, "say": None}
    # "I started a puzzle", "I'm learning Spanish on Duolingo", "my Duolingo
    # streak is 45 days" (2026-10-08: to the planner).
    if re.fullmatch(r"i (?:just )?started (?:a |an |my |a new )?(?:puzzle|jigsaw puzzle|lego set|painting|drawing|knitting project|sweater|scarf|quilt|garden|journal"
                    r"|diet|workout plan|program|course|class|podcast|series|game|video game|novel|blog)(?: today| tonight| this week)?", low) \
            or re.fullmatch(r"(?:i'?m|i am) (?:learning|studying|practicing) [a-z][a-z ]{1,20} (?:on|with|using|through) [a-z][a-z ]{1,20}", low) \
            or re.fullmatch(r"my [a-z][a-z ]{1,20} streak is (?:at |up to )?\d{1,4} (?:days?|weeks?)(?: now)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "The landlord is raising the rent", "I looked at an apartment on Elm
    # St", "the apartment on Elm St was 1600 a month" (2026-10-08: to the
    # planner). Kept, for "what apartments have I looked at".
    if re.fullmatch(r"(?:the |my |our )?landlord (?:is|'s) (?:raising|increasing|putting up) (?:the |my |our )?rent(?: (?:next|this) (?:month|year)| in [a-z]+)?", low) \
            or re.fullmatch(r"(?:i|we) (?:just )?(?:looked at|saw|toured|went to see|checked out|viewed) (?:an?|the|a nice|a new) (?:apartment|house|condo|place|townhouse|rental|unit|home)"
                            r"(?: (?:on|at|in|near|by) [a-z0-9][a-z0-9 .'-]{1,30})?(?: today| yesterday| this morning)?", low) \
            or re.fullmatch(r"the (?:apartment|house|condo|place|townhouse|rental|unit) (?:on|at|in|near|by) [a-z0-9][a-z0-9 .'-]{1,30}? (?:was|is|costs?|wants)"
                            r" \$?\d[\d,]*(?: dollars| bucks)?(?: (?:a|per) month)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I need to give 30 days notice" (2026-10-08: to the planner).
    m = re.fullmatch(r"i (?:need|have|gotta|got to|should)(?: to)? (?P<what>give (?:my |the |a )?(?:\d{1,3}|thirty|sixty|two weeks?'?) ?(?:days?'?|weeks?'?)? ?notice(?: to (?:my |the )?[a-z]+)?)", low)
    if m:
        return _new_task(_as_he_said(text, m.group("what")))
    # THE KIDS (2026-10-08: a field trip's money, a sick day, no school, the
    # team, goals, who picks them up and bedtime all went to the planner).
    _kd = r"(?:my|our) (?:son|daughter|kid|boy|girl|oldest|youngest|baby)|the kids|my kids|our kids"
    pron = "they"
    km = re.match(rf"(?P<kid>{_kd})\b", low)
    if km and re.search(r"\b(?:son|boy)\b", km.group("kid")):
        pron = "he"
    elif km and re.search(r"\b(?:daughter|girl)\b", km.group("kid")):
        pron = "she"
    if re.fullmatch(rf"(?:{_kd}) (?:needs?|has to bring|must bring) (?:\$?\d[\d.]* (?:dollars|bucks)|\$\d[\d.]*|(?:to bring|to wear) [a-z0-9][a-z0-9' ]{{0,30}}?) for (?:the |his |her |their |a )?[a-z][a-z ]{{1,25}}", low) \
            or re.fullmatch(rf"(?:{_kd}) (?:has|have) no school (?:on )?(?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|next week|this friday|this monday)", low) \
            or re.fullmatch(rf"(?:{_kd}) scored (?:\d{{1,3}}|a|an|one|two|three|four|five|six) (?:goals?|points?|baskets?|touchdowns?|runs?|home runs?)(?: today| tonight| this weekend| in (?:the|her|his|their) game)?", low) \
            or re.fullmatch(r"(?:my (?:wife|husband|mom|dad|partner|sister|brother)|grandma|grandpa|i|(?!(?:who|what|anyone|anybody|someone|somebody|nobody|everyone)\b)[a-z]{2,15}) (?:is|am|will be) (?:picking up the kids|picking the kids up|getting the kids|dropping off the kids|dropping the kids off)(?: today| tomorrow| tonight| this week)?", low) \
            or re.fullmatch(rf"(?:bedtime|lights out) for (?:{_kd}|the baby) is (?:at )?\d{{1,2}}(?::\d\d)?(?: ?[ap]m)?|(?:the kids'?|my (?:son|daughter)'s) bedtime is (?:at )?\d{{1,2}}(?::\d\d)?(?: ?[ap]m)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    if re.fullmatch(rf"(?:{_kd}) (?:is|are) (?:home )?sick(?: today| again)?|(?:{_kd}) (?:stayed|is staying|are staying) home(?: from school)?(?: sick)?(?: today)?|(?:{_kd}) missed school(?: today)?", low):
        sick = "sick" in low
        verb = "feel" if pron == "they" else "feels"
        return {"command": {"kind": "note", "text": _as_he_said(text, low)},
                "say": f"Oh no - I hope {pron} {verb} better soon." if sick else None}
    if re.fullmatch(rf"(?:{_kd}) (?:made|got (?:into|on)) (?:the |a )?(?:team|varsity|jv|play|musical|band|choir|honor roll|dean's list|travel team|all-stars|all stars)", low):
        obj = {"he": "him", "she": "her"}.get(pron, "them")
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": f"That's great - congratulations to {obj}!"}
    # "I got milk and eggs" with neither on his list (2026-10-08: to the
    # planner). Groceries he bought are kept, for "do I have milk".
    m = re.fullmatch(r"i (?:just )?(?:got|bought|picked up|grabbed) (?P<items>[a-z][a-z ,]{1,60}?)(?: (?:today|at the store|from the store))?", low)
    if m:
        from aletheia import quick as _qg
        parts = [re.sub(r"^(?:some |a |an |the |more )", "", p.strip()) for p in re.split(r",\s*(?:and\s+)?|\s+and\s+", m.group("items")) if p.strip()]
        grocery = (_qg._FOOD + r"|milk|butter|yogurt|cream|juice|coffee|tea|cereal|oatmeal|flour|sugar|oil|apples?|bananas?|oranges?|grapes"
                   r"|berries|strawberries|lettuce|avocados?|lemons?|limes?|garlic|celery|cucumbers?|corn|peas|soup|chips|crackers|snacks"
                   r"|water|soda|beer|wine|groceries|paper towels|toilet paper|dish soap|detergent|dog food|cat food|diapers|wipes")
        if parts and all(re.fullmatch(rf"(?:{grocery})", p) for p in parts):
            return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I have a wedding to go to on the 24th" (2026-10-08: to the planner) is
    # "I have a wedding on the 24th".
    m = re.fullmatch(r"(?P<head>i (?:have|'ve got|have got|got) (?:a|an) [a-z][a-z' ]{1,30}?) to (?:go to|attend|get to)(?P<rest> .{2,40})", low)
    if m:
        return _interpret(_as_he_said(text, m.group("head")) + " " + _as_he_said(text, m.group("rest").strip()))
    # "I'm the best man", "my speech is 3 minutes", "Jake registered at
    # Crate and Barrel" (2026-10-08: to the planner).
    m = re.fullmatch(r"(?:i'?m|i am) (?:the |a )?(?P<role>best man|maid of honor|matron of honor|groomsman|bridesmaid|officiant|ring bearer|usher|godfather|godmother|pallbearer|mc|emcee)(?: (?:at|in|for) [a-z][a-z' ]{1,30})?", low)
    if m:
        return {"command": {"kind": "note", "text": _as_he_said(text, low)},
                "say": "That's an honor - congratulations." if m.group("role") != "pallbearer" else "I'm sorry. That's a kind thing to be asked to do."}
    if re.fullmatch(r"my (?:speech|toast|talk|presentation|eulogy|reading) (?:is|has to be|should be|needs to be) (?:about |under |less than |no more than )?\d{1,2} minutes?(?: long)?", low) \
            or re.fullmatch(r"(?:[a-z]{2,15}|my [a-z]{2,15}|they|we) (?:(?:is|are) )?registered (?:at|on|with) [a-z][a-z&' -]{1,30}", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "We're getting a puppy", "the puppy is named Max" (2026-10-08: to the
    # planner).
    m = re.fullmatch(r"(?:we'?re|we are|i'?m|i am) (?:getting|adopting|bringing home) (?:a|an|another) (?P<pet>puppy|kitten|dog|cat|bunny|rabbit|hamster|guinea pig|parrot|bird|fish|turtle|lizard|horse)(?: (?:on |this |next |in )?[a-z0-9 ]{2,20})?", low)
    if m:
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": f"How exciting - a {m.group('pet')}!"}
    if re.fullmatch(r"(?:the|our|my|his|her) (?:new )?(?:puppy|kitten|dog|cat|bunny|rabbit|hamster|guinea pig|parrot|bird|fish|turtle|lizard|horse)(?:'s name)? (?:is named|is called|'s name is|is) (?!(?:sick|old|young|hungry|tired|due|on|at|in|out|home|here|gone|fine|okay|ok|missing|lost|scared|sleeping|outside|inside)\b)[a-z][a-z']{1,15}", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "The interviewer is Sarah Chen", "I think the interview went well",
    # "they said they would get back to me next week", "I turned down the
    # offer", "I'm negotiating the salary" (2026-10-08: to the planner).
    if re.fullmatch(r"(?:the|my) (?:interviewer|hiring manager|recruiter)(?:'s name)? (?:is|was) [a-z][a-z'. -]{1,30}", low) \
            or re.fullmatch(r"(?:i think |i feel like |honestly )?(?:the|my) (?:interview|presentation|meeting|date|game|test|exam|first day|call|pitch|audition|recital|surgery|appointment|trip|party)"
                            r"(?: [a-z]{2,15})? (?:went|go) (?:really |pretty |so |very |super )?(?:well|great|badly|bad|ok|okay|fine|terribly|awful|amazing|good|poorly|horribly|perfectly)", low) \
            or re.fullmatch(r"(?:they|she|he|the [a-z]{3,15}|[a-z]{2,15}) (?:said|told me|promised) (?:that )?(?:they|she|he|it) (?:would|will|'ll|should) (?:get back to me|call me back|let me know|be in touch|reach out|follow up)"
                            r"(?: (?:by |on |in |within |next |this )?[a-z0-9 ]{2,20})?", low) \
            or re.fullmatch(r"i (?:turned down|declined|accepted|took|got|signed|countered|rejected) (?:the|their|an?) (?:job )?(?:offer|counteroffer|counter offer)(?: from [a-z][a-z ]{1,20})?", low) \
            or re.fullmatch(r"(?:i'?m|i am|we'?re|we are) (?:negotiating|asking for more|countering)(?: (?:the|my) (?:salary|offer|raise|pay|rent|price))?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I need to get bloodwork done", "my prescription needs a refill"
    # (2026-10-08: to the planner) are jobs for his list.
    m = re.fullmatch(r"i (?:need|have|gotta|got to|should)(?: to)? get (?P<job>(?:my |the |some |a |an )?[a-z][a-z' ]{1,25}? (?:done|checked|tested|drawn|looked at))", low)
    if m:
        job = "get " + m.group("job")
        return _new_task(_as_he_said(text, job))
    m = re.fullmatch(r"(?P<whose>my|the|our) (?P<thing>prescription|meds|medication|inhaler|insulin|license|licence|passport|registration|membership|subscription|lease|car insurance|insurance)"
                     r" (?:needs|need|is due for) (?:a |an |to be )?(?P<act>refill|refilled|renewal|renewed)", low)
    if m:
        verb = "refill" if m.group("act").startswith("refill") else "renew"
        job = f"{verb} {'my' if m.group('whose') != 'our' else 'our'} {m.group('thing')}"
        return _new_task(job)
    # "I have a follow up in 2 weeks" (2026-10-08: to the planner) is kept
    # with the day it means, so "when is my follow up" can say it.
    m = re.fullmatch(r"(?P<head>i (?:have|'ve got|got) (?:a|an|my) [a-z][a-z' -]{1,30}?) in (?P<n>\d{1,2}|a|one|two|three|four|five|six) (?P<unit>days?|weeks?|months?)", low)
    if m:
        import datetime as _dtf
        from aletheia import localtime as _ltf
        n = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}.get(m.group("n")) or int(m.group("n"))
        today = _dtf.datetime.now(_ltf.operator_tz()).date()
        unit = m.group("unit")
        if unit.startswith("month"):
            mo = today.month - 1 + n
            day = today.replace(year=today.year + mo // 12, month=mo % 12 + 1, day=min(today.day, 28))
        else:
            day = today + _dtf.timedelta(days=n * (7 if unit.startswith("week") else 1))
        when = f"{day:%A} {day.day} {day:%B}"
        return {"command": {"kind": "note", "text": f"{_as_he_said(text, m.group('head'))} around {when}"},
                "say": f"Noted - that's around {when}."}
    # HOSTING (2026-10-08: "I'm hosting Thanksgiving this year", "12 people
    # are coming to Thanksgiving", "my sister is bringing the pie", "dinner is
    # at 4", "mom is allergic to nuts" - to the planner).
    if re.fullmatch(r"(?:i'?m|i am|we'?re|we are) (?:hosting|having|throwing|doing) (?:thanksgiving|christmas|easter|passover|hanukkah|friendsgiving|the [a-z]{3,15} party"
                    r"|(?:a |the )?(?:party|barbecue|bbq|cookout|potluck|dinner party|game night|birthday party|baby shower|bridal shower))"
                    r"(?: (?:this year|at (?:our|my) (?:house|place)|on [a-z0-9 ]{3,20}|this [a-z]{3,10}|next [a-z]{3,10}))?", low) \
            or re.fullmatch(r"(?:\d{1,3}|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty)(?: people| guests| of us| adults| kids)? (?:are|is) coming(?: to [a-z][a-z' ]{2,25})?", low) \
            or re.fullmatch(r"(?:my [a-z]{2,15}(?: in law)?|[a-z]{2,15}(?: and [a-z]{2,15})?|the [a-z]{2,15}) (?:is|are) bringing (?:the |a |an |some |her |his |their )?(?!up\b|it\b|that\b|this\b|them\b)[a-z][a-z' ]{1,30}", low) \
            or re.fullmatch(r"(?:thanksgiving |christmas |the |easter )?(?:dinner|lunch|brunch|the party|the barbecue|the bbq|the potluck) (?:is|starts) at \d{1,2}(?::\d\d)?(?: ?[ap]m)?(?: (?:on )?(?:thanksgiving|christmas|saturday|sunday|friday))?", low):
        say = None
        if re.match(r"(?:i'?m|i am|we'?re|we are) ", low):
            say = "Noted. Tell me who's coming and what they're bringing, and I'll keep it straight."
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": say}
    # CALLS AND NOTES HE OWES (2026-10-08: "I missed a call from my mom", "I
    # owe Sam a text", "I haven't talked to my brother in a while" - to the
    # planner).
    m = re.fullmatch(r"i (?:just )?missed (?:a |two |\d )?(?:calls?|facetime|video call) from (?P<who>my [a-z]{2,15}(?: in law)?|[a-z]{2,15}(?: [a-z]{2,15})?)", low)
    if m and m.group("who") not in ("you", "someone", "somebody", "work", "a number", "an unknown number"):
        return _new_task(_as_he_said(text, f"call {m.group('who')} back"))
    m = re.fullmatch(r"i (?:still )?owe (?P<who>my [a-z]{2,15}|[a-z]{2,15}) (?:a |an )?(?P<what>text|call|email|reply|text back|call back|thank you(?: note| card)?)", low)
    if m and m.group("who") not in ("you", "it", "them", "him", "her", "money"):
        what, who = m.group("what"), _as_he_said(text, m.group("who"))
        job = (f"write {who} a thank you {what.split()[-1] if what.endswith(('note', 'card')) else 'note'}" if what.startswith("thank")
               else f"reply to {who}" if what == "reply"
               else f"{what.split()[0]} {who}" + (" back" if what.endswith("back") else ""))
        return _new_task(job)
    m = re.fullmatch(r"i (?:have(?:n'?t| not)|haven't) (?:talked to|spoken to|called|seen|heard from|caught up with) (?P<who>my [a-z]{2,15}|[a-z]{2,15}) in (?:a while|ages|forever|a long time|weeks|months|a few weeks|a few months)", low)
    if m and m.group("who") not in ("you", "anyone", "anybody", "them"):
        who = _as_he_said(text, m.group("who"))
        return {"command": {"kind": "note", "text": _as_he_said(text, low)},
                "say": f"Noted. Say \"remind me to call {who} this weekend\" and I'll make sure you do."}
    # "I sent the birthday card" (2026-10-08: to the planner): ticks off
    # the task about it, or is kept.
    m = re.fullmatch(r"i (?:just |finally )?(?P<v>sent|mailed|posted|dropped off|returned|submitted|filed|signed|renewed|booked|scheduled|wrote|bought|picked up|paid)"
                     r" (?:the|my|a|an|our) (?P<thing>[a-z][a-z' ]{1,30}?)(?: (?:today|yesterday|this morning|already))?", low)
    # "I paid the water bill" (2026-10-08: kept, with "pay the water bill"
    # left on his list). Only a bill: "I paid the dentist" settles what he
    # owed, which the ledger reads from his words.
    if m and m.group("v") == "paid" and not re.search(r"\b(?:bill|invoice|tuition|taxes|tax bill|fine|ticket|tolls?|fee|premium|registration|deposit)$", m.group("thing")):
        m = None
    if m:
        try:
            from aletheia import intercom as _icm2
            found, _why = _icm2._one_task(m.group("thing"))
        except Exception:
            found = None
        if found is not None:
            return {"command": {"kind": "task_done", "which": m.group("thing")}, "say": None}
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # A TRIP (2026-10-08: "I'm going on a road trip next week", "we're driving
    # to Chicago", "the drive is 6 hours", "we're leaving at 7am", "we're
    # stopping in Indianapolis", "the kids want to go to the zoo", "we get
    # back Sunday" - all to the planner).
    if re.fullmatch(r"(?:i'?m|i am|we'?re|we are) (?:going on|taking|planning) (?:a |our )?(?:road trip|trip|vacation|cruise|camping trip|ski trip|beach trip|getaway)"
                    r"(?: to [a-z][a-z' ]{1,25})?(?: (?:next|this) [a-z]{3,10}| in [a-z]{3,10}| on [a-z0-9 ]{3,20}| tomorrow)?", low) \
            or re.fullmatch(r"(?:i'?m|i am|we'?re|we are) (?:driving|flying|heading|going|road tripping) (?:up |down |out )?to (?!(?:the )?(?:store|gym|work|bed|sleep|school|church|doctor|dentist)\b)[a-z][a-z' ]{1,25}"
                            r"(?: (?:next|this) [a-z]{3,10}| tomorrow| on [a-z]{3,10}| for (?:the )?(?:weekend|week|holidays?))?", low) \
            or re.fullmatch(r"(?:the |our )?(?:drive|flight|train ride|trip) (?:there |home |back )?(?:is|takes|will take) (?:about |around )?(?:\d{1,2}(?:\.\d)?|an?|one|two|three|four|five|six|seven|eight|nine|ten) (?:and a half )?(?:hours?|minutes?|days?)", low) \
            or re.fullmatch(r"(?:we'?re|we are|i'?m|i am) (?:leaving|heading out|taking off|hitting the road) (?:at \d{1,2}(?::\d\d)? ?(?:am|pm)?|early|first thing)(?: (?:tomorrow|on [a-z]+|in the morning))?", low) \
            or re.fullmatch(r"(?:we'?re|we are|i'?m|i am) (?:stopping|staying the night|staying overnight|spending the night) (?:in|at) [a-z][a-z' ]{1,25}(?: on the way(?: there| back)?)?", low) \
            or re.fullmatch(r"(?:the kids|my kids|my son|my daughter|my wife|my husband|[a-z]{2,15}) (?:wants?|would like) to (?:go to|visit|see|do) (?:the |a )?[a-z][a-z' ]{1,25}", low) \
            and not re.match(r"(?:i|you|he|she|it|they|who|what)\b", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    m = re.fullmatch(r"(?:we|i) (?:get|come|are|am|'re|'m) (?:back|home) (?:on |this |next )?(?P<day>monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow)", low)
    if m and _spoken_day(m.group("day")):
        import datetime as _dtb
        on = _dtb.date.fromisoformat(_spoken_day(m.group("day"))[:10])
        head = low[:m.start("day")].strip()
        head = re.sub(r" (?:on|this|next)$", "", head)
        return {"command": {"kind": "note", "text": f"{_as_he_said(text, head)} on {on:%A} {on.day} {on:%B}"}, "say": None}
    # "The plumber charged 250", "recycling is every other week" (2026-10-08:
    # to the planner). What somebody charged is a fact he was told, not
    # money she spends.
    from aletheia.quick import TRADES
    if re.fullmatch(r"(?:the|my|our) " + TRADES +
                    r" (?:charged(?: me| us)?|quoted(?: me| us)?|wants|said it(?:'s| is| would be| will be)|billed(?: me| us)?) (?:about |around )?\$?\d[\d,]*(?:\.\d\d)?(?: dollars| bucks)?(?: for [a-z][a-z' ]{1,25})?", low) \
            or re.fullmatch(r"(?:the )?(?:recycling|trash|garbage|yard waste|compost|bulk pickup|street sweeping|lawn service|cleaning lady|cleaner)"
                            r" (?:is|comes|goes out|gets picked up|pickup is) (?:every other|every|on|each|once a|twice a) [a-z ]{3,20}", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # THE KIDS AGAIN (2026-10-08: "the tooth fairy needs to come tonight",
    # "my son is grounded until Friday", "I'm coaching the soccer team" - to
    # the planner).
    if re.fullmatch(r"(?:the )?tooth fairy (?:needs to|has to|should|must) (?:come|visit|stop by)(?: tonight)?", low):
        return _new_task("tooth fairy tonight")
    m = re.fullmatch(r"(?P<who>my (?:son|daughter|kid|boy|girl)|[a-z]{2,15}) (?:is|'s) grounded (?:until|till|through) (?P<day>monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow)", low)
    if m and _spoken_day(m.group("day")):
        import datetime as _dtg
        on = _dtg.date.fromisoformat(_spoken_day(m.group("day"))[:10])
        return {"command": {"kind": "note", "text": f"{_as_he_said(text, m.group('who'))} is grounded until {on:%A} {on.day} {on:%B}"}, "say": None}
    if re.fullmatch(r"(?:i'?m|i am) (?:coaching|helping coach|assistant coaching|the coach of|volunteering (?:for|with|at)|leading|running) (?:the |my (?:son'?s|daughter'?s|kids'?) |a )?[a-z][a-z' ]{1,30}"
                    r"(?: (?:this|next) (?:season|year|fall|spring|summer|winter))?", low) \
            and re.search(r"\b(?:team|league|troop|club|class|group|pta|scouts|practice)\b", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # SAVING UP (2026-10-08: "we need 40000 for a down payment" was refused
    # as spending money; "we have saved 12000 so far", "my student loan
    # balance is 18000", "my car loan is paid off" went to the planner). A
    # sum he is saving toward is a fact he tells her; keeping it spends
    # nothing.
    if re.fullmatch(r"(?:we|i) (?:need|want|have to save|need to save|are saving|am saving|'re saving|'m saving) (?:about |around |roughly )?\$?\d[\d,]*(?:k| thousand)?(?: dollars| bucks)?"
                    r" (?:for|toward|towards|to cover) (?:a |the |our |my )?(?:down payment|house|home|wedding|new car|car|tuition|college|emergency fund|trip|vacation|honeymoon|baby|move|renovation|retirement)", low) \
            or re.fullmatch(r"(?:we|i) (?:have|'ve) (?:saved|put away|got saved) (?:about |around |roughly )?\$?\d[\d,]*(?:k| thousand)?(?: dollars| bucks)?(?: (?:so far|for (?:the |a |our )?[a-z ]{3,20}|already|total))*", low) \
            or re.fullmatch(r"my (?:student loan|car loan|mortgage|credit card|loan|personal loan|heloc)s? (?:balance )?(?:is|are) (?:at |down to |now )?\$?\d[\d,]*(?:k| thousand)?(?: dollars)?", low) \
            or re.fullmatch(r"(?:my|our) (?:car loan|student loans?|mortgage|credit card|loan|personal loan|truck|car|house) (?:is|are) (?:finally |all )?paid off", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # IN THE KITCHEN (2026-10-08: "I need 2 pounds of ground beef", "I doubled
    # the recipe", "the pizza will be here at 7", "I burned the toast" - to
    # the planner).
    m = re.fullmatch(r"(?:we|i) need (?P<item>(?:\d{1,3}(?:\.\d)?|a|an|one|two|three|four|five|six|a couple|half a) (?:pounds?|lbs?|cups?|dozen|gallons?|bags?|cans?|boxes|box|bottles?|loaves|loaf"
                     r"|packs?|packages?|pints?|quarts?|ounces?|oz|sticks?|heads?|bunch(?:es)?|jars?|cartons?|rolls?|bars?) (?:of )?[a-z][a-z '-]{1,30})", low)
    if m:
        return {"command": {"kind": "shopping_add", "item": _as_he_said(text, m.group("item"))}, "say": None}
    if re.fullmatch(r"i (?:doubled|tripled|halved|cut) (?:the|this|my) recipe(?: in half)?", low) \
            or re.fullmatch(r"(?:the |our )?(?:pizza|food|takeout|delivery|order|chinese|thai|groceries|grocery order|instacart|doordash|uber eats)"
                            r" (?:will be|should be|is going to be|'ll be|is) (?:here|arriving|coming|delivered) (?:at|by|around|in) [0-9a-z: ]{1,15}", low) \
            or re.fullmatch(r"i (?:just )?(?:burned|burnt|overcooked|undercooked|dropped|spilled) (?:the|my|our) [a-z][a-z' ]{1,20}", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "My anxiety is bad today" (2026-10-08: to the planner) goes in his
    # journal, with a kind word.
    m = re.fullmatch(r"my (?P<what>anxiety|depression|stress|back|back pain|knee|migraine|migraines|allergies|asthma|arthritis|pain|neck|shoulder|stomach|sciatica|ibs)"
                     r" (?:is|are|has been|have been) (?:really |so |pretty )?(?:bad|worse|terrible|awful|acting up|flaring up|killing me|through the roof|rough)(?: today| again| this week| lately)?", low)
    if m:
        calm = m.group("what") in ("anxiety", "stress", "depression")
        return {"command": {"kind": "note", "text": "Journal: " + _as_he_said(text, low)},
                "say": "I'm sorry. Try one slow breath - in for four, out for six. I've put it in your journal." if calm
                else "Sorry - go easy on yourself today. I've put it in your journal."}
    # BOOKS AND SHOWS (2026-10-08: "I'm halfway through it" got "I can't
    # think", "we are reading Circe for book club" and "I listened to a great
    # podcast about sleep" went to the planner).
    m = re.fullmatch(r"(?:i'?m|i am) (?P<ep>halfway|a third of the way|most of the way|almost done|nearly done|near the end) (?:through|into|with) (?P<t>it|the book|my book|this book|the show|this show|[a-z0-9][a-z0-9' :-]{1,40})", low)
    if m:
        title = m.group("t")
        if title in ("it", "the book", "my book", "this book", "the show", "this show"):
            title = ""
            for row in _quick._notes()[:20]:
                said = " ".join(str(row.get("text") or "").split()).rstrip(".")
                got = re.fullmatch(r"(?i:i'?m|i am|i'?ve been|i have been|i (?:just )?started) (?:reading|watching|listening to) (?P<t>.{2,60})", said) \
                    or re.fullmatch(r"(?i:i (?:just )?started (?:a new |the )?(?:book|show|series)(?: called)?) (?P<t>.{2,60})", said)
                if got:
                    title = got.group("t")
                    break
        else:
            title = _as_he_said(text, title)
        if title:
            return {"command": {"kind": "note", "text": f"I'm {m.group('ep')} through {title}"}, "say": None}
    if re.fullmatch(r"(?:we'?re|we are|i'?m|i am) reading [a-z0-9][a-z0-9' :-]{1,40} for (?:my |our |the )?book club", low) \
            or re.fullmatch(r"i (?:just )?(?:listened to|heard) (?:a |an |the )?(?:great |good |really good |interesting |fascinating )?podcast (?:about|on|called|with) [a-z0-9][a-z0-9' :-]{1,40}", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # US (2026-10-08: "we went to Olive Garden for date night", "my wife is
    # working late tonight", "my wife is mad at me", "I forgot our
    # anniversary" - to the planner).
    if re.fullmatch(r"we (?:went|had|did|got) (?:to |out to )?[a-z][a-z' &]{1,30} for (?:date night|our anniversary|my birthday|her birthday|his birthday|dinner|brunch|lunch)", low) \
            or re.fullmatch(r"(?:we had|we did) (?:a |our )?date night(?: at [a-z][a-z' &]{1,30})?(?: tonight| last night| on [a-z]+)?", low) \
            or re.fullmatch(r"my (?:wife|husband|partner|girlfriend|boyfriend|fiance|fiancee|roommate) (?:is|'s) (?:working late|staying late|out late|on a trip|traveling|travelling|away|out of town|at her mom'?s|at his mom'?s)"
                            r"(?: tonight| today| this week| until [a-z0-9 ]{3,15})?", low) \
            or re.fullmatch(r"(?:my|our) (?:wife|husband|partner|girlfriend|boyfriend|fiance|fiancee)'s favou?rite [a-z ]{2,15} (?:is|are) [a-z][a-z' ]{1,30}", low) \
            or re.fullmatch(r"(?:my|our) (?:wife|husband|partner|girlfriend|boyfriend|fiance|fiancee)'s (?:ring|shoe|dress|shirt|pants) size is [a-z0-9. ]{1,10}", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    m = re.fullmatch(r"my (?P<who>wife|husband|partner|girlfriend|boyfriend|fiance|fiancee) (?:is|'s) (?:mad|angry|upset|annoyed|pissed) (?:at|with) me", low)
    if m:
        return {"command": {"kind": "note", "text": "Journal: " + _as_he_said(text, low)},
                "say": "Sorry - that's hard. If there's something to make right, I can help you do it: a note, flowers on your list, or time on the calendar."}
    if re.fullmatch(r"i (?:forgot|missed) (?:our|my wife'?s|my husband'?s|her|his) (?:anniversary|birthday)", low):
        return {"command": {"kind": "note", "text": "Journal: " + _as_he_said(text, low)},
                "say": "Oof. It's not too late to make it right today - say \"add flowers to the list\" or \"remind me in an hour to call\" and I'll help. And tell me the date, and I'll make sure it never sneaks up again."}
    # AT WORK (2026-10-08: "I have a one on one with my manager at 3", "my new
    # title is senior engineer", "my PTO balance is 12 days", "my coworker Jen
    # is leaving" - to the planner).
    m = re.fullmatch(r"i (?:have|'ve got|got) (?:a |my )?(?P<what>one on one|1 on 1|one-on-one|1:1|check-in|check in|standup|stand-up|sync|catch-up|catch up|skip level)"
                     r"(?P<rest>(?: with [a-z][a-z' ]{1,25}?)?(?: (?:at|on|this|next|tomorrow|today) .{1,25}))", low)
    if m:
        again = _interpret(f"i have a meeting{m.group('rest')}")
        if ((again or {}).get("command") or {}).get("kind") == "calendar_hold":
            title = again["command"]["title"]
            again["command"]["title"] = re.sub(r"^meeting", "one on one" if re.match(r"(?:one|1)", m.group("what")) else m.group("what"), title)
            return again
    m = re.fullmatch(r"(?:my )?(?:pto|vacation|paid time off|leave) (?:balance )?is (?P<n>\d{1,3}(?:\.\d)?) (?:days|hours)", low) \
        or re.fullmatch(r"i have (?P<n>\d{1,3}(?:\.\d)?) days of (?:pto|vacation|paid time off)(?: left)?", low)
    if m:
        return _interpret(f"I have {m.group('n')} vacation days left")
    if re.fullmatch(r"my (?:new )?(?:job )?title is [a-z][a-z' -]{2,40}", low) \
            or re.fullmatch(r"(?:my (?:coworker|co-worker|colleague|teammate|boss|manager|supervisor|assistant) )?[a-z]{2,15}(?: from [a-z ]{2,15})? (?:is leaving|is quitting|quit|got fired|got let go|is retiring|retired|got promoted|is moving teams|is going on leave|put in (?:her|his|their) notice)"
                            r"(?: today| this week| next week| on [a-z]+| at the end of the (?:week|month))?", low) \
            and not re.match(r"(?:i|you|he|she|it|they|we|who|what|everyone|somebody|someone)\b", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # THE GYM (2026-10-08: "I did legs today" got "that wasn't on your task
    # list"; "I'm training for a half marathon", "I'm taking a rest day" and
    # "I have a session with my trainer Tuesday at 6" went to the planner).
    if re.fullmatch(r"i (?:just )?did (?:legs|arms|chest|back|abs|shoulders|upper body|lower body|leg day|arm day|chest day|chest and triceps|back and biceps|push|pull|full body"
                    r"|yoga|pilates|cardio|a workout|weights|crossfit|hiit)(?: day)?(?: (?:for )?\d{1,3} minutes)?(?: today| this morning| tonight| at the gym| after work)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": "Nice work. I've kept it."}
    if re.fullmatch(r"(?:i'?m|i am) (?:training for|signed up for|registered for|running) (?:a|an|the|my first) (?:half marathon|marathon|5k|10k|triathlon|race|ultra|tough mudder|spartan race|century ride|half ironman|ironman)(?: in [a-z]+| on [a-z0-9 ]+)?", low) \
            or re.fullmatch(r"(?:i'?m|i am) taking (?:a|today as a) rest day(?: today)?|today is (?:a|my) rest day", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    m = re.fullmatch(r"i (?:have|'ve got|got) (?:a |my )?(?:session|training session|appointment|class) with my (?P<who>trainer|coach|therapist|tutor|physical therapist|pt)(?P<rest> (?:on |this |next )?.{2,25})", low)
    if m:
        again = _interpret(f"i have a meeting{m.group('rest')}")
        if ((again or {}).get("command") or {}).get("kind") == "calendar_hold":
            again["command"]["title"] = f"session with my {m.group('who')}"
            return again
    # "Put a hold on Thursday at 4 for a call with the bank", "I have a
    # conference all day Wednesday" (2026-10-08: to the planner).
    m = re.fullmatch(r"(?:put|place|make) (?:a )?hold (?:on|for) (?P<when>.{3,30}?) for (?:a |an |the )?(?P<what>[a-z][a-z' ]{2,40})", low) \
        or re.fullmatch(r"(?:put|place|make) (?:a )?hold for (?:a |an |the )?(?P<what>[a-z][a-z' ]{2,40}?) (?:on |at )(?P<when>.{3,30})", low)
    if m:
        again = _interpret(f"i have a meeting {m.group('when')}")
        if ((again or {}).get("command") or {}).get("kind") == "calendar_hold":
            again["command"]["title"] = _as_he_said(text, m.group("what"))
            return again
    m = re.fullmatch(r"(?:i (?:have|'ve got|got)|there(?:'s| is)) (?:a |an |the )?(?P<what>[a-z][a-z' ]{2,30}?) all day (?:on |this |next )?(?P<day>monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow)", low) \
        or re.fullmatch(r"(?:i (?:have|'ve got|got)|there(?:'s| is)) (?:a |an |the )?(?P<what>[a-z][a-z' ]{2,30}?) (?:on |this |next )?(?P<day>monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow) all day", low)
    if m:
        held = _calendar_hold(text, _as_he_said(text, m.group("what")), m.group("day"), None, "9am")
        if held:
            held["command"]["minutes"] = 8 * 60
            return held
    # "Add chips to the list for Saturday" (2026-10-08: to the planner): the
    # thing goes on the list, and the day stays with it.
    m = re.fullmatch(r"(?:add|put) (?P<item>[a-z][a-z' -]{1,30}?) (?:to|on) (?:the|my) (?:shopping |grocery )?list (?P<for>for (?:saturday|sunday|monday|tuesday|wednesday|thursday|friday|the party|the weekend|tomorrow|tonight|the trip|thanksgiving|christmas))", low)
    if m:
        return {"command": {"kind": "shopping_add", "item": _as_he_said(text, m.group("item")) + " " + _as_he_said(text, m.group("for"))}, "say": None}
    # NEIGHBORS (2026-10-08: "my neighbor Tom has a snowblower", "Tom gave it
    # back", "the HOA fee is 200 a quarter", "Tom is out of town this week",
    # "I'm watching Tom house this week" - to the planner, or kept as a show).
    m = re.fullmatch(r"(?:i'?m|i am) (?:watching|looking after|house ?sitting|pet ?sitting|checking on|feeding) (?P<who>[a-z]{2,15}?)(?:'s|s)? (?P<what>house|place|apartment|dog|dogs|cat|cats|kids|pets|plants|baby|mail)"
                     r"(?P<when> (?:this|next) (?:week|weekend)| today| tonight| tomorrow| until [a-z]+| while (?:they'?re|he'?s|she'?s) (?:away|gone|out of town))?", low)
    if m and m.group("who") not in ("the", "my", "our", "a", "your"):
        who = _as_he_said(text, m.group("who"))
        return {"command": {"kind": "note", "text": f"I'm watching {who}'s {m.group('what')}{m.group('when') or ''}"}, "say": None}
    m = re.fullmatch(r"(?P<who>[a-z]{2,15}|my [a-z]{2,15}) (?:gave|brought|handed) (?:it|that|them|my [a-z ]{2,20}) back|(?P<who2>[a-z]{2,15}|my [a-z]{2,15}) returned (?:it|that|them|my [a-z ]{2,20})", low)
    if m:
        who = m.group("who") or m.group("who2")
        thing = re.search(r"\bmy ([a-z ]{2,20}?)(?: back)?$", low)
        thing = thing.group(1) if thing else ""
        if not thing:
            for row in _quick._notes()[:30]:
                said = " ".join(str(row.get("text") or "").split()).rstrip(".")
                got = re.search(rf"\b{re.escape(who)} (?:is borrowing|borrowed|has|took) (?:my|our|the) (?P<t>[a-z][a-z ]{{1,20}})$", said, re.I) \
                    or re.search(rf"\bi (?:lent|loaned|gave) (?:my|our|the) (?P<t>[a-z][a-z ]{{1,20}}) to {re.escape(who)}$", said, re.I)
                if got:
                    thing = got.group("t")
                    break
        if thing:
            return {"command": {"kind": "note", "text": f"{_as_he_said(text, who)} gave my {thing} back"}, "say": None}
    if re.fullmatch(r"(?:the|our|my) (?:hoa|condo|association|club|membership|parking|daycare|tuition|insurance|internet|cable|phone|gym|storage unit) (?:fee|fees|dues|premium|bill|rate|payment) (?:is|are) \$?\d[\d,]*(?:\.\d\d)?(?: dollars)? (?:a|per|every|each) (?:month|quarter|year|week)", low) \
            or re.fullmatch(r"(?:my (?:neighbou?r|friend|coworker|brother|sister|cousin|uncle|aunt) )?[a-z]{2,15} (?:has|owns|has got) (?:a|an) [a-z][a-z' -]{2,25}", low) \
            and not re.match(r"(?:i|he|she|it|they|we|you|who|what|everyone|everybody|someone|somebody|nobody|my (?:wife|husband|son|daughter|kid|baby|dog|cat))\b", low) \
            and not re.search(r"\b(?:appointment|meeting|game|practice|class|party|birthday|cold|fever|flu|cough|headache|question|point|problem|test|exam)\b", low) \
            or re.fullmatch(r"(?:my (?:neighbou?r|friend|coworker|brother|sister|cousin|parents|mom|dad) )?[a-z]{2,15} (?:is|are) (?:out of town|away|on vacation|traveling|travelling)(?: this week| this weekend| next week| until [a-z]+)?", low) \
            and not re.match(r"(?:i|he|she|it|they|we|you|who|what)\b", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "My phone is at 10 percent" (2026-10-08: to the planner).
    m = re.fullmatch(r"my (?P<what>phone|laptop|watch|tablet|ipad|headphones|earbuds|car) (?:is|'s) (?:at|down to|on) (?P<n>\d{1,2})(?: ?%| percent)(?: battery)?", low)
    if m:
        n = int(m.group("n"))
        return {"command": None, "say": f"Plug it in soon - {n} percent won't last long." if n <= 20 else "That'll hold for a while."}
    # "My coworker Jake is out sick", "I worked from home today" (2026-10-08:
    # to the planner). His day at work, kept; "who is out" and "how many days
    # did I work from home" read them.
    if re.fullmatch(r"(?:(?:my )?(?:coworker|co-worker|colleague|boss|manager|assistant|teammate) )?(?!(?:i|it|he|she|they|we|power|the|who|what|anyone|anybody|everyone|everybody|somebody|someone|nobody)\b)[a-z]{2,15}"
                    r" (?:is|was) out (?:sick|today|this week|on vacation|on leave|on pto|on maternity leave|on paternity leave|until [a-z0-9 ]+)"
                    r"(?: (?:today|this week|again))?", low) \
            or re.fullmatch(r"i (?:worked|am working|'m working|was working|will work|'ll work) (?:from home|remotely|remote|in the office|from the office)"
                            r"(?: (?:today|yesterday|this morning|this afternoon|tomorrow))?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I booked a hotel in Chicago for the 15th" (2026-10-08: to the planner).
    if re.fullmatch(r"(?:i|we) (?:booked|reserved|got) (?:a |an |the |our |my )?(?:hotel|room|hotel room|airbnb|air bnb|motel|cabin|rental|condo|campsite)"
                    r"(?: (?:in|at|near) [a-z0-9][a-z0-9 '&-]{1,40}?)?(?: (?:for|on|from) [a-z0-9][a-z0-9 ,'-]{1,40})?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I took the bus today" (2026-10-08: to the planner).
    if re.fullmatch(r"(?:i|we) (?:took|rode|caught|got) (?:the |a |an )?(?:bus|train|subway|metro|tram|ferry|uber|lyft|taxi|cab|bike|scooter)"
                    r"(?: (?:to|from) (?:work|school|the office|home|the airport|the city|downtown))?(?: (?:today|this morning|tonight|yesterday))?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "Add Olive Garden to places to try" (2026-10-08: to the planner) - a
    # list named without the word list.
    m = re.fullmatch(r"(?:add|put) (?P<x>[a-z0-9][a-z0-9 '&-]{1,40}?) (?:to|on) (?:my |the |our )?"
                     r"(?P<name>(?:places|restaurants|things|movies|shows|books|bars|spots|recipes) to (?:try|see|watch|read|visit|go|make|cook))", low)
    if m:
        again = _interpret(f"add {m.group('x')} to my {m.group('name')} list")
        if ((again or {}).get("command") or {}).get("kind") == "list_add":
            again["command"]["item"] = _as_he_said(text, m.group("x"))
            return again
    # "It is my anniversary next week" (2026-10-08: to the planner).
    if re.fullmatch(r"(?:it is|it's|its) (?:my|our) (?:wedding )?anniversary (?:next week|next month|this weekend|in \d{1,2} days|soon)", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)},
                "say": "Noted. Say \"our anniversary is\" and the date, and I'll remember it every year."}
    # "I have to work Saturday", "my shift is 7 to 3 tomorrow" (2026-10-08:
    # to the planner). His shifts, kept.
    if re.fullmatch(r"(?:i have to|i've got to|i gotta|i need to|i'?m|i am|i will be|i'?ll be) (?:work|working|going in|on shift)(?: (?:a |an )?(?:double|late|early|overnight|night) shift)? (?:today|tonight|tomorrow|(?:on |this |next )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|this weekend|next weekend)(?: (?:from )?\d{1,2}(?::\d\d)? ?(?:am|pm)? (?:to|until|till|-) ?\d{1,2}(?::\d\d)? ?(?:am|pm)?)?", low) \
            or re.fullmatch(r"my (?:shift|hours) (?:is|are) (?:from )?\d{1,2}(?::\d\d)? ?(?:am|pm)? (?:to|until|till|-) ?\d{1,2}(?::\d\d)? ?(?:am|pm)?(?: (?:today|tonight|tomorrow|(?:on |this |next )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|this weekend|next weekend))?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "It is my turn to cook", "Sam is doing the dishes tonight", "the trash
    # goes out tonight" (2026-10-08: to the planner). Whose turn, kept.
    if re.fullmatch(r"(?:it is|it's|its) (?:my|our|[a-z]{2,15}'s) turn to (?:cook|do the dishes|do dishes|do the laundry|take out the trash|walk the dog|drive|pick up the kids|clean|vacuum|mow)(?: tonight| today| this week)?", low) \
            or re.fullmatch(r"(?:my (?:wife|husband|son|daughter|partner)|(?!(?:who|what|nobody|everyone|anyone)\b)[a-z]{2,15}) (?:is|will be) (?:doing|cooking|making) (?:the dishes|dishes|dinner|the laundry|laundry)(?: tonight| today| this week)?", low) \
            or re.fullmatch(r"the (?:trash|garbage|recycling|bins?) (?:goes|go|go out|goes out|is picked up|gets picked up) (?:out )?(?:tonight|tomorrow|today|on [a-z]+days?|every [a-z]+day)", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "Mike just had a baby boy" (2026-10-08: to the planner) - a friend's
    # news, by name. The capital is what makes it a name.
    m = re.fullmatch(r"(?P<who>[A-Z][a-z]{1,15}(?: and [A-Z][a-z]{1,15})?) (?:just )?(?:had|welcomed) (?:a|their|her|his) (?:new )?baby(?: boy| girl)?(?: today| yesterday| last night| this week)?[.!]*",
                     " ".join(text.split()).strip())
    if m and m.group("who").split()[0] not in ("My", "The", "We", "I", "She", "He", "They", "Our"):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)},
                "say": f"That's wonderful - congratulations to {m.group('who')}. I've kept it."}
    # "I got a package today" (2026-10-08: to the planner).
    if re.fullmatch(r"(?:i|we) (?:just )?(?:got|received) (?:a |the |my |our )?(?:package|parcel|delivery|box|letter)(?: from [a-z0-9 ]{2,25})?(?: today| yesterday| this morning)?", low) \
            or re.fullmatch(r"(?:a|my|the|our) (?:[a-z]+ )?(?:package|parcel|delivery|order) (?:just )?(?:came|arrived|got here|was delivered|showed up)(?: today| yesterday| this morning)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # Shopping for a car (2026-10-08, each to the planner): "the civic is
    # 25000", "I test drove the camry", "my budget for a car is 30000".
    # Kept, which spends nothing; only a car by name is read as a price.
    from aletheia.quick import CAR_MODELS
    if re.fullmatch(rf"(?:the |that |a )?(?:used |new )?{CAR_MODELS} (?:is|was|costs?|is listed at|was listed at|is going for|is priced at) \$?\d[\d,]*k?(?: dollars)?", low) \
            or re.fullmatch(rf"(?:i|we) (?:just )?(?:test drove|test-drove|test drive|drove|looked at|checked out|went to see) (?:a |the |that )?(?:used |new )?{CAR_MODELS}(?: today| yesterday| this weekend)?", low) \
            or re.fullmatch(r"(?:my|our) (?:(?:new )?car budget|budget for (?:a|the|our|my) (?:new |used )?car) is (?:about |around |up to )?\$?\d[\d,]*k?(?: dollars)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # Around the house (2026-10-08, each to the planner): "the pest control
    # guy is coming friday", "the water heater is 10 years old", "we
    # painted the bedroom blue", "the furnace filter needs changing".
    if re.fullmatch(r"(?:the|my|our) " + TRADES + r" (?:is|are) (?:coming|coming out|coming by|scheduled|booked)(?: (?:on|this|next))? (?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
                    r"(?: (?:at|between) \d{1,2}(?::\d\d)? ?(?:am|pm)?(?: (?:and|to|-) \d{1,2}(?::\d\d)? ?(?:am|pm)?)?)?(?: (?:morning|afternoon))?", low) \
            or re.fullmatch(r"(?:the|my|our) (?:water heater|furnace|roof|ac|air conditioner|hvac|fridge|refrigerator|dishwasher|washer|dryer|washing machine|oven|stove|garage door opener|mattress|deck|fence|boiler)"
                            r" (?:is|was) (?:about |around |almost |over )?\d+ (?:years?|months?) old", low) \
            or re.fullmatch(r"(?:i|we) (?:just )?painted (?:the|my|our) (?:[a-z]{3,15}(?: room)?|living room|dining room|guest room) [a-z][a-z ]{2,25}", low) \
            or re.fullmatch(r"the paint colou?r (?:in|for) (?:the|my|our) [a-z ]{3,20} is [a-z][a-z ]{2,25}", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    m = re.fullmatch(r"(?:the|my|our) (?P<f>(?:air |furnace |hvac |ac |water |fridge |refrigerator )?filter) (?:needs|need) (?:changing|replacing|to be changed|to be replaced|changed|replaced)", low)
    if m:
        return _new_task(f"change the {m.group('f')}")
    # School (2026-10-08, each to the planner): "the kids have early release
    # wednesday", "report cards come out friday", "my son lost his lunchbox".
    _DAY = r"(?:today|tomorrow|(?:on |this |next )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|next week|this week|" + SPOKEN_DATE + r")"
    if re.fullmatch(r"(?:the kids|my kids|our kids|my son|my daughter|[a-z]{2,15}) (?:has|have|get|gets) (?:an? )?(?:early release|early dismissal|a half day|half day|no school|a day off|a snow day|late start)(?: (?:on|this|next))? " + _DAY, low) \
            or re.fullmatch(r"(?:report cards|progress reports|grades|school pictures|picture day|spirit week|book fair|field day|the field trip|the science fair|the school play|the school concert|open house|graduation|the spelling bee)"
                            r" (?:is|are|come out|comes out|go out|will be|are due)(?: (?:on|this|next))? " + _DAY, low) \
            or re.fullmatch(r"(?:my son|my daughter|my kid|[a-z]{2,15}) (?:lost|forgot|left) (?:his|her|their) (?:lunchbox|lunch box|lunch|backpack|jacket|coat|homework|water bottle|glasses|retainer|library book|permission slip|phone|shoes)(?: at school| at home| on the bus)?(?: again| today)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # Friends (2026-10-08, each to the planner): "I owe jake a beer",
    # "my friend sarah got engaged", "jake's wife is named amy".
    if re.fullmatch(r"i owe (?!(?:you|it|them|him|her|money)\b)[a-z]{2,15} (?:a|an|one|two) (?:beer|drink|coffee|lunch|dinner|favor|favour|round|pizza|call|apology|thank you|visit)(?: or two)?", low) \
            or re.fullmatch(r"(?!(?:who|what|when|where|how|did|has|is)\b)(?:my )?(?:friend |buddy |cousin |coworker |neighbor )?[a-z]{2,15}(?:'s)? (?:wife|husband|girlfriend|boyfriend|fiance|fiancee|son|daughter|baby|dog|cat|partner)(?:'s name)? is (?:named|called) [a-z]{2,15}", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    m = re.fullmatch(r"(?:my )?(?:friend |buddy |best friend |cousin |coworker |neighbor )?(?P<who>(?!(?:who|what|did|has|is|i|we|you)\b)[a-z]{2,15}(?: and [a-z]{2,15})?) (?:just )?(?:got|are|is) (?P<what>engaged|married|promoted|a new job|a dog|a puppy|into (?:college|grad school|law school|med school))", low)
    if m:
        return {"command": {"kind": "note", "text": _as_he_said(text, low)},
                "say": f"That's great news - congratulations to {_as_he_said(text, m.group('who')).title() if m.group('who').islower() else _as_he_said(text, m.group('who'))}. I've kept it."}
    # A race and a game (2026-10-08, each to the planner): "I signed up for
    # a 5k", "the 5k is on november 2", "I played basketball tonight".
    _RACE = r"(?:5k|10k|half marathon|marathon|half|race|fun run|color run|turkey trot|triathlon|tough mudder|spartan race|charity walk)"
    if re.fullmatch(r"(?:i|we) (?:just )?(?:signed up|registered|entered) for (?:a|an|the|my) " + _RACE + r"(?: (?:on|this|next) [a-z0-9 ]{2,20})?", low) \
            or re.fullmatch(r"(?:the|my|our) " + _RACE + r" is (?:on |this |next )?(?:" + SPOKEN_DATE + r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday|next month|next weekend|this weekend)", low) \
            or re.fullmatch(r"(?:i|we) (?:just )?(?:played|shot|went) (?:some )?(?:basketball|hoops|soccer|tennis|pickleball|golf|volleyball|softball|baseball|racquetball|squash|frisbee|ultimate|hockey|football|disc golf|bowling|a round of golf|9 holes|18 holes)"
                            r"(?: with [a-z ]{2,25})?(?: today| tonight| this morning| yesterday| last night)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # Debt and refunds (2026-10-08: "I have 3000 in credit card debt" was
    # refused as spending money; "I got a 50 dollar refund from amazon" went
    # to the planner). What he owes or got back is a fact; keeping it spends
    # nothing.
    if re.fullmatch(r"(?:i|we) (?:have|owe|still owe|have about|have around) (?:about |around )?\$?\d[\d,]*k?(?: dollars)? (?:in|of|on) (?:my |our )?(?:credit card|student loan|student|car|medical|personal)? ?(?:debt|loans?|card)", low) \
            or re.fullmatch(r"(?:my|our) (?:credit card|student loan|car loan|personal loan|medical) (?:debt|balance) is (?:about |around )?\$?\d[\d,]*k?(?: dollars)?", low) \
            or re.fullmatch(r"(?:i|we) (?:just )?(?:got|received) (?:a |an |my |our )?(?:\$?\d[\d,]*(?:\.\d\d)? (?:dollar )?)?(?:refund|rebate|reimbursement|credit)(?: of \$?\d[\d,]*(?:\.\d\d)?(?: dollars)?)?(?: (?:from|back from) [a-z0-9][a-z0-9 ]{1,25})?(?: today| yesterday)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # The car's running costs (2026-10-08, each to the planner): "gas was
    # 3.49 a gallon", "my car gets 30 miles a gallon".
    if re.fullmatch(r"(?:gas|diesel|premium|regular) (?:was|is|cost|costs) (?:about |around )?\$?\d(?:\.\d\d?)? ?(?:a|per|/) ?gallon(?: (?:today|at [a-z0-9 ]{2,25}))?", low) \
            or re.fullmatch(r"(?:i|we) paid \$?\d(?:\.\d\d?)? ?(?:a|per) gallon(?: for gas)?(?: today| at [a-z0-9 ]{2,25})?", low) \
            or re.fullmatch(r"(?:my|our|the) (?:car|truck|van|suv|[a-z]{3,12}) (?:gets|averages|does) (?:about |around )?\d{1,3} (?:miles (?:a|per|to the) gallon|mpg|miles to a gallon)(?: on the highway| in town| city| highway)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "The gate code at moms is 2580" (2026-10-08: to the planner).
    if re.fullmatch(r"the (?:gate|door|front door|garage|alarm|lock ?box|building|key ?pad|entry|wifi network|parking) (?:code|number|combo|combination) (?:at|for) (?:my |the )?[a-z][a-z' ]{1,25} is [0-9a-z#* ]{3,14}", low) \
            and not _ID_NUMBER.search(low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I have a fever of 101" (2026-10-08: to the planner).
    m = re.fullmatch(r"i (?:have|'ve got|got|am running|'m running) (?:a )?(?:fever|temperature|temp) of (?P<t>\d{2,3}(?:\.\d)?)(?: degrees)?(?: today| tonight| this morning)?", low)
    if m:
        t = float(m.group("t"))
        high = t >= 103 if t > 45 else t >= 39.4
        say = ("That's high. Call your doctor, and if there's a stiff neck, confusion or trouble breathing, call 911. I've put it in your journal."
               if high else "Rest and fluids. If it goes past 103, or lasts more than three days, call your doctor. I've put it in your journal.")
        return {"command": {"kind": "note", "text": "Journal: " + _as_he_said(text, low)}, "say": say}
    # "We need to get the guest room ready" (2026-10-08: the shopping list).
    m = re.fullmatch(r"(?:i|we) (?:need|have|got) to get (?P<what>(?:the|my|our) (?!(?:kids?|son|daughter|baby|wife|husband)\b)[a-z][a-z ]{1,25}? (?:ready|set up|organi[sz]ed|sorted|packed)(?: for [a-z ]{2,20})?)", low)
    if m:
        return _new_task("get " + _as_he_said(text, m.group("what")))
    # "She is staying until Sunday" (2026-10-08: to the planner, a turn after
    # "my sister is coming to visit"). Kept in his words; "how long is my
    # sister staying" reads it.
    if re.fullmatch(r"(?:she|he|they|my [a-z]{2,15}|[a-z]{2,15}) (?:is|are|'s|'re|will be) (?:staying|here|in town|visiting) (?:until|till|through|for) [a-z0-9][a-z0-9 ]{1,20}", low) \
            and not re.match(r"(?:who|what|how|when|where|it|that|this)\b", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I have orientation at 9" (2026-10-08: to the planner) - a hold with
    # no day, the way "I have a meeting at 3" already is.
    m = re.fullmatch(r"i (?:have|'ve got|got) (?:an? )?(?P<what>orientation|training|onboarding|new hire orientation|a class|class|practice|rehearsal|therapy|physical therapy|pt|counseling)"
                     r" at (?P<t>\d{1,2}(?::\d\d)?(?: ?(?:am|pm))?)", low)
    if m:
        again = _interpret(f"i have a meeting at {m.group('t')}")
        cmd = (again or {}).get("command") or {}
        if cmd.get("kind") == "calendar_hold":
            cmd["title"] = re.sub(r"^an? ", "", m.group("what"))
            return again
    # "I get 15 days of PTO", "I used 3 days of PTO" (2026-10-08: to the planner).
    if re.fullmatch(r"i (?:get|have|got|used|took) (?:\d{1,3}(?:\.5)?|a|one|two|three|four|five|six|seven|eight|nine|ten|half a) (?:days? of (?:pto|vacation|leave|sick time|sick leave)|(?:pto|vacation|sick|personal) days?)(?: a year| per year| each year| every year| this year| so far)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I quit smoking today", "I haven't had a drink in 30 days" (2026-10-08:
    # to the planner). Kept, with a word for it.
    if re.fullmatch(r"i (?:just |finally |officially )?(?:quit|stopped|gave up) (?:smoking|vaping|drinking|caffeine|coffee|soda|sugar|nicotine|dip|chewing tobacco|gambling)(?: today| yesterday| this week| for good)?", low) \
            or re.fullmatch(r"i (?:have not|haven't) (?:had a drink|had a cigarette|smoked|vaped|had alcohol) (?:in|for) \d{1,4} days", low) \
            or re.fullmatch(r"i(?:'m| am) (?:\d{1,4} days|one week|two weeks|a month|\d{1,2} months) (?:sober|clean|smoke free|smoke-free)", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": "That's a big one - good for you. I'll keep count."}
    # "I had a cheat day", "I skipped my workout" (2026-10-08: to the planner).
    if re.fullmatch(r"(?:i|we) (?:had|have|'m having|am having) (?:a |my )?cheat (?:day|meal)(?: today| yesterday| tonight)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": "Noted. Tomorrow's a fresh start."}
    # Planning a party (2026-10-08, each to the planner): "I'm planning a
    # party for my wife", "I invited Sam, Mike and Jess", "the theme is 80s".
    if re.fullmatch(r"(?:i'?m|i am|we'?re|we are) (?:planning|throwing|hosting|having|putting together|organi[sz]ing) (?:a |an )?(?:surprise |birthday |retirement |going away |going-away |graduation |dinner |holiday |christmas |halloween |housewarming |baby shower |bridal shower )?"
                    r"(?:party|shower|get together|get-together|barbecue|bbq|cookout|celebration)(?: for [a-z' ]{2,30})?(?: (?:on|this|next) [a-z0-9 ]{2,20})?", low) \
            or re.fullmatch(r"(?:i|we) (?:invited|have invited|'ve invited|asked) (?!(?:you|her|him|them|it)\b)[a-z][a-z ,'&]{1,80}?(?: (?:to|over for) (?:the |my |our )?[a-z ]{2,30})?", low) \
            or re.fullmatch(r"the (?:party |wedding |shower )?(?:theme|dress code|color scheme|colou?rs) (?:is|are|will be) [a-z0-9][a-z0-9 '&-]{1,30}", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "The dishwasher is running" (2026-10-08: to the planner).
    if re.fullmatch(r"(?:the |my )?(?:dishwasher|washer|washing machine|dryer|laundry|oven|slow cooker|crock ?pot|instant pot|roomba|sprinklers?)"
                    r" (?:is|are) (?:running|going|on|done|finished|preheating|preheated|in)", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # A THING HE DID, OR A DATE ON SOMETHING OF HIS (2026-10-07: "I changed
    # the oil today", "I gave the dog his medicine", "my license expires
    # June 2027" each went to the planner). Last before the planner, so
    # every verb with its own door keeps it: said as a fact, it is a note in
    # his words, and "when did I last change the oil" reads it back.
    out = re.fullmatch(r"i (?:just )?took (?P<what>(?:the |our |my )?(?:trash|garbage|recycling|rubbish|bins?|compost|dog|cat)) out"
                       r"(?P<when> (?:today|yesterday|this morning|tonight|last night|earlier))?", low)
    if out:
        return {"command": {"kind": "note", "text": f"I took out {out.group('what')}{out.group('when') or ''}"}, "say": None}
    if re.fullmatch(r"i (?:just )?(?:" + _DONE_VERBS + r") (?:the |my |our |his |her |a |an |some )?[a-z][a-z' ]{1,50}"
                    r"(?: (?:today|yesterday|this morning|this afternoon|this evening|tonight|last night|earlier))?", low) \
            or re.fullmatch(r"(?:my|our|the) [a-z][a-z' ]{1,30}? (?:expires?|runs? out|(?:is|are) due|renews?|ends?) (?:on |in )?"
                            r"(?:" + SPOKEN_DATE + r"|" + _MONTH + r"(?: \d{4})?|\d{4})(?:,? \d{4})?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I WENT FOR A RUN", "I went to the gym" (2026-10-07: to the planner,
    # and "when did I last go to the gym" had nothing to read). A note in
    # his words, read back and counted by `quick._went`.
    if re.fullmatch(r"i (?:just )?(?:" + _WENT + r")(?: (?:today|yesterday|this morning|this afternoon|this evening"
                    r"|tonight|last night|earlier|again))?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I did 50 pushups", "I walked 5000 steps" (2026-10-07): a count he
    # keeps, added up by "how many pushups have I done today".
    if re.fullmatch(r"i (?:did|just did|have done|walked|took|swam|rowed) (?:another )?\d[\d,]* [a-z][a-z -]{1,20}"
                    r"(?: (?:today|this morning|this afternoon|this evening|tonight|yesterday))?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I had a burrito for lunch", "I ate a salad" (2026-10-07: to the
    # planner). What he ate is a note; "what did I have for lunch
    # yesterday" reads it back by day and meal.
    if re.fullmatch(r"i (?:had|ate|just had|just ate|made|cooked|just made|just cooked|grabbed|ordered|got) (?!lunch\b|dinner\b|breakfast\b|a meeting\b|a call\b|an? (?:idea|question|dream)\b)"
                    r"[a-z0-9][a-z0-9' ,&-]{1,50}? for (?:breakfast|lunch|dinner|supper|a snack|dessert)"
                    r"(?: (?:today|yesterday|this morning|tonight|last night))?", low) \
            or re.fullmatch(r"(?:for (?:breakfast|lunch|dinner|supper|dessert)(?: today| yesterday| tonight)?,? )i (?:had|ate) "
                            r"[a-z0-9][a-z0-9' ,&-]{1,50}", low) \
            or re.fullmatch(r"i (?:ate|just ate) (?!it\b|that\b|this\b|nothing\b)[a-z0-9][a-z0-9' ,&-]{1,50}?"
                            r"(?: (?:today|yesterday|this morning|tonight|last night))?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I had coffee at 3", "I drank 2 beers" (2026-10-07: to the planner),
    # added up by "how many coffees have I had today".
    if re.fullmatch(r"i (?:just )?(?:had|drank|finished) (?:an? |another |my (?:first|second|third|fourth) |\d+ |one |two |three |four )?"
                    r"(?:coffee|tea|soda|beer|wine|juice|milk|latte|espresso)s?"
                    r"(?: (?:at \d{1,2}(?::\d\d)?(?: ?(?:am|pm))?|this morning|this afternoon|today|tonight|just now))?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I had pizza last night" (2026-10-07: to the planner) - a meal by
    # when, with the things that are not food left out.
    if re.fullmatch(r"i (?:had|ate) (?!(?:a|an|the|my) (?:bad|good|great|rough|long|hard|fun|weird|strange|crazy|busy)\b)"
                    r"(?!.*\b(?:fight|dream|nightmare|argument|date|call|meeting|party|fever|headache|time|blast|day|talk"
                    r"|chat|conversation|idea|thought|feeling|drink|drinks|accident|fall|crash|game|class|lesson|session|visitor"
                    r"|guests?|friends? over|breakdown|panic attack|migraine|cold|flu|baby)\b)"
                    r"[a-z][a-z' ,&-]{1,40}? (?:last night|tonight|this morning)", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    if re.fullmatch(r"i (?:just )?(?:took|had) a (?:quick |short |long |little |power )?nap(?: (?:for|of) (?:\d{1,3}|an?|one|two) (?:minutes?|mins?|hours?))?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I'm going to bed" with no time (2026-10-08: "what time did I go to
    # bed" a turn later said "You haven't told me"). Saying it IS the time,
    # in the evening or the small hours; at noon it is a nap, not a night.
    if re.fullmatch(r"(?:(?:i'?m|im|i am) )?(?:going to|off to|heading to|heading off to) (?:bed|sleep)(?: now)?(?:,? thea)?"
                    r"|(?:i'?m|im|i am) turning in(?: now)?|good ?night(?:,? thea)?", low):
        from aletheia import localtime
        import datetime as _dt
        now = _dt.datetime.now(localtime.operator_tz())
        if now.hour >= 19 or now.hour < 5:
            clock = now.strftime("%I:%M %p").lstrip("0").lower()
            return {"command": {"kind": "note", "text": f"I went to bed at {clock}"},
                    "say": "Goodnight. I'll keep going quietly."}
    if re.fullmatch(r"(?:i'?m|i am) going to (?:bed|sleep) (?:at |around )\d{1,2}(?::\d\d)?(?: ?(?:am|pm))?(?: tonight)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": "Noted. Goodnight when you get there."}
    # "My work hours are 9 to 5", "I work 9 to 5" (2026-10-08: to the
    # planner). Kept in his words; "what time do I get off" reads it.
    if re.fullmatch(r"(?:my (?:work |working )?hours are|i work(?: from)?) \d{1,2}(?::\d\d)?(?: ?(?:am|pm))? (?:to|till|until|-) "
                    r"\d{1,2}(?::\d\d)?(?: ?(?:am|pm))?(?: (?:on )?(?:weekdays|monday to friday|monday through friday|every day))?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I'm on a diet", "I'm on call this weekend", "I started keto"
    # (2026-10-08: to a model, which kept nothing). A state he is in is a
    # note in his words; "what did I tell you about my diet" reads it.
    if re.fullmatch(r"(?:i'?m|i am) (?:on|starting|going on|doing) (?:a |an |the )?(?:new )?(?:diet|keto(?: diet)?|cut|bulk|cleanse|fast"
                    r"|juice cleanse|low[- ]carb(?: diet)?|vegan diet|vegetarian diet|call|antibiotics|medication|meds|a break"
                    r"|break|vacation|leave|parental leave|maternity leave|paternity leave|sick leave|holiday)"
                    r"(?: (?:this|next) (?:week|weekend|month)| until [a-z0-9 ]{2,20}| now| again| today| tonight)?"
                    r"|i (?:started|began) (?:a |an |the )?(?:new )?(?:diet|keto|cleanse|fast|antibiotics|medication)(?: today| this week)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I have 3 vacation days left", "I took a sick day today", "I took
    # Friday off" (2026-10-08: to the planner). Kept in his words; "how
    # many vacation days do I have left" counts them down.
    if re.fullmatch(r"i (?:have|'ve got|have got|got|still have) (?:\d{1,3}(?:\.5)?|one|two|three|four|five|six|seven|eight|nine|ten)"
                    r" (?:more )?(?:vacation|pto|sick|personal|holiday|leave) days?(?: left| remaining)?(?: this year)?"
                    r"|i (?:just )?(?:took|used) (?:a|an|one|two|three|four|five|\d{1,2}(?:\.5)?|half a) (?:vacation|pto|sick|personal|holiday|leave)"
                    r" days?(?: today| yesterday| off| this week| on (?:monday|tuesday|wednesday|thursday|friday))?"
                    r"|i took (?:today|yesterday|monday|tuesday|wednesday|thursday|friday|the day) off", low):
        said = re.sub(r" (?:this year|today|yesterday|off|this week|on (?:monday|tuesday|wednesday|thursday|friday))$", "",
                      _as_he_said(text, low)) if not re.match(r"i took (?:today|yesterday|\w+day|the day) off", low) else _as_he_said(text, low)
        return {"command": {"kind": "note", "text": said}, "say": None}
    # "I woke up at 7", "I went to bed at 11" (2026-10-07: to the planner).
    # Kept in his words; "what time did I wake up" reads the newest back.
    if re.fullmatch(r"i (?:woke up|got up|went to bed|went to sleep|fell asleep) (?:at |around |about )?"
                    r"(?:midnight|\d{1,2}(?::\d{2})?(?: ?(?:am|pm|a\.m\.|p\.m\.))?)"
                    r"(?: (?:today|this morning|last night|yesterday))?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I weigh 180", "I spent 40 dollars on gas" (2026-10-07: to the planner).
    # Kept in his words; "what's my weight" reads the newest one back.
    if re.fullmatch(r"i(?: weigh| weighed| am|'m) \d{2,3}(?:\.\d)?(?: ?(?:pounds|lbs?|kg|kilos|kilograms))?"
                    # "I weighed 185 last week" (2026-10-08: to the planner)
                    r"(?: (?:today|now|this morning|yesterday|last week|last month|a week ago|a month ago|(?:two|three|2|3) weeks ago))?", low) and (low.startswith("i weigh") or re.search(r"pounds|lbs?|kg|kilo", low)) \
            or re.fullmatch(r"i (?:spent|paid) \$?\d[\d,.]*(?: dollars| bucks)? (?:on|for|at) [a-z][a-z' ]{1,40}"
                            r"(?: (?:today|yesterday|this week|last night))?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # HIS BODY, SAID (2026-10-07: "I'm 6 feet tall", "I want to lose 10
    # pounds" and "I slept badly" each went to the planner). Notes in his
    # words; "how tall am I", "what's my BMI" and "how much weight have I
    # lost" read them.
    if re.fullmatch(r"(?:i'?m|i am) (?:about |around )?(?:\d(?:'| foot| feet| ft)(?: ?\d{1,2}(?:\"|''| inches| in)?)?|\d{3} ?cm|1\.\d\d ?m)(?: tall)?"
                    r"|my height is (?:about |around )?(?:\d(?:'| foot| feet| ft)(?: ?\d{1,2}(?:\"|''| inches| in)?)?|\d{3} ?cm|1\.\d\d ?m)"
                    r"|i (?:want|need|'d like|would like|am trying|'m trying) to (?:lose|gain|drop|put on) \d{1,3} (?:pounds|lbs?|kg|kilos)"
                    r"(?: by [a-z0-9 ]{2,20}| this year| this month)?"
                    r"|i slept (?:badly|terribly|poorly|well|great|fine|ok|okay|awful|horribly|like a baby|like crap|like garbage)"
                    r"(?: last night)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I couldn't sleep last night", "I had a nightmare", "I napped for an
    # hour" (2026-10-08: to the planner). Kept, with a kind word where one fits.
    if re.fullmatch(r"i (?:could not|couldn'?t|can'?t|cannot|didn'?t|did not|barely|hardly) (?:get to )?sleep(?: (?:at all|much|well|a wink))?(?: last night| again)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": "Sorry - that's rough. Go easy on yourself today."}
    if re.fullmatch(r"i had (?:a |another |the worst |such a )?(?:nightmare|bad dream|horrible dream|awful dream|scary dream)(?: last night| again)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": "Sorry - that's no fun. It's over now."}
    if re.fullmatch(r"i (?:just )?(?:napped|dozed off|took a nap) for (?:about |around |like )?(?:an hour|half an hour|(?:\d{1,3}|twenty|thirty|forty|fifteen|ten|two|three) (?:minutes?|mins?|hours?))(?: today| this afternoon)?"
                    r"|i (?:just )?took a (?:\d{1,3}[- ](?:minute|min|hour) |short |long |quick |power )nap(?: today| this afternoon)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I STARTED READING THE HOBBIT" (2026-10-07: to the planner); "what am
    # I reading" reads it back until he finishes it.
    if re.fullmatch(r"i(?:'ve| have)? (?:just )?(?:started|begun|began) reading [a-z0-9][a-z0-9 ,:'&-]{1,60}", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # A PLACE HE WANTS TO GO, A RATING (2026-10-08: to the planner): "I'd
    # like to visit Japan someday", "rate Inception 5 stars". Kept in his
    # words; "where do I want to travel" and "what did I rate Inception" read them.
    if re.fullmatch(r"(?:i'?d|i would|i really want to|i want to|we'?d|we would) (?:love|like)? ?(?:to )?(?:visit|go to|see|travel to)"
                    r" (?:[a-z][a-z' ]{1,30}?)(?: someday| one day| sometime| before i die| eventually)", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    m = re.fullmatch(r"(?:rate|i(?:'d)? (?:rate|give)|i rated|i gave) (?P<what>[a-z0-9][a-z0-9' :-]{1,40}?) (?P<n>[0-5](?:\.5)?|one|two|three|four|five)"
                     r" (?:stars?|out of (?:5|five|10|ten))", low)
    if m and m.group("what") in ("it", "that", "this", "this one", "that one"):
        # "I gave it 4 stars" a turn after "I watched Oppenheimer last
        # night" (2026-10-08: kept as "I rated it 4 stars", which no
        # question about Oppenheimer could find) is the thing he just named.
        said_before, _ = _previous_turn()
        named = re.fullmatch(r"i (?:just )?(?:watched|finished(?: watching| reading)?|read|saw|played|beat|listened to)"
                             r" (?P<t>[a-z0-9].{1,50}?)(?: (?:last night|today|yesterday|this morning|again))?\.?", said_before.casefold())
        if named and named.group("t") not in ("it", "that", "this", "tv", "the news", "a movie", "a show"):
            title = _as_he_said(said_before, named.group("t"))
            stars = "stars" if "star" in low else low.split(m.group("n") + " ", 1)[1]
            return {"command": {"kind": "note", "text": f"I rated {title} {m.group('n')} {stars}"}, "say": None}
    if m:
        return {"command": {"kind": "note", "text": f"I rated {_as_he_said(text, m.group('what'))} {m.group('n')} "
                                                    f"{'stars' if 'star' in low else low.split(m.group('n') + ' ', 1)[1]}"},
                "say": None}
    # "Remind me on the last day of the month to pay rent" (2026-10-08: to
    # the planner): this month's last day, at 9 unless he says a time.
    m = re.fullmatch(r"remind me (?:on )?the last day of (?:the |this )?month(?: at (?P<t>\d{1,2}(?::\d\d)?(?: ?(?:am|pm))?|noon))?"
                     r" (?:to|about) (?P<what>.{2,80})", low)
    if m:
        import calendar as _cal
        import datetime as _dt
        from aletheia import localtime
        now = _dt.datetime.now(localtime.operator_tz())
        clock = _spoken_time(m.group("t")) if m.group("t") else "09:00"
        if clock:
            hh, mm = map(int, clock.split(":"))
            if m.group("t") and _is_bare_hour(m.group("t")) and hh < 7:
                hh += 12
            last = now.replace(day=_cal.monthrange(now.year, now.month)[1], hour=hh, minute=mm, second=0, microsecond=0)
            if last <= now:
                nxt = (now.replace(day=1) + _dt.timedelta(days=32)).replace(day=1)
                last = last.replace(year=nxt.year, month=nxt.month, day=_cal.monthrange(nxt.year, nxt.month)[1])
            return {"command": {"kind": "remind_at", "at": last.isoformat(), "text": _as_he_said(text, m.group("what"))}, "say": None}
    # HABITS HE KEEPS (2026-10-08: to the planner): "I want to work out 4
    # times a week", "I smoked a cigarette", "I didn't drink today". Kept in
    # his words; "am I on track with my workouts" and "how many cigarettes
    # this week" read them.
    if re.fullmatch(r"i (?:want|need|plan|am going|'m going|aim) to (?:work out|exercise|go to the gym|hit the gym|train|run|meditate|read)"
                    r" (?:\d|one|two|three|four|five|six|seven) (?:times|days) (?:a|per|each) week", low) \
            or re.fullmatch(r"i (?:just )?smoked (?:\d+|a|an|one|two|three|four|five|a couple(?: of)?|a few) (?:more )?(?:cigarettes?|smokes?)"
                            r"(?: today| tonight| this morning)?", low) \
            or re.fullmatch(r"i (?:didn'?t|did not) (?:drink|smoke|have (?:a|any) (?:drinks?|alcohol|cigarettes?))(?: any(?: alcohol)?)?"
                            r"(?: today| tonight| this week| yesterday)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # WHO SOMEBODY IS TO HIM, BY NAME (2026-10-08: "my wife is Anna" and
    # "my neighbor is Bob" went to the planner; "Bob's wife is Linda" too).
    # Only a name he said with a capital - "my wife is sick" is how she is.
    _people = (r"wife|husband|sister|brother|mom|mum|mother|dad|father|son|daughter|kids?|grandma|grandpa|girlfriend|boyfriend"
               r"|partner|fiancee?|roommate|neighbou?r|next door neighbou?r|cousin|aunt|uncle|niece|nephew|best friend|coworker"
               r"|co-worker|colleague|stepmom|stepdad|stepson|stepdaughter|in-laws|mother-in-law|father-in-law|plumber|electrician"
               r"|handyman|contractor|cleaner|housekeeper|gardener|landscaper|chiropractor|dermatologist|financial advisor|insurance agent")
    m = re.fullmatch(r"(?:(?:my|our) |(?P<whose>[a-z]{2,15})'s )(?:new |older |younger |little |big )?(?P<rel>" + _people + r") (?:is|'s) (?:called |named )?"
                     r"(?P<name>[a-z][a-z'-]{1,20}(?: [a-z][a-z'-]{1,20})?)", low)
    if m:
        name = _as_he_said(text, m.group("name"))
        whose = _as_he_said(text, m.group("whose") or "")
        if all(w[:1].isupper() for w in name.split()) and (not whose or whose[:1].isupper()) \
                and name.split()[0].casefold() not in ("in", "on", "at", "a", "an", "the", "not", "very", "so", "my", "i"):
            return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # A GIFT IDEA FOR SOMEBODY (2026-10-07: "add a gift idea for my sister:
    # a scarf" went to the planner). A line on his gift list naming who it
    # is for; "what gift ideas do I have for my sister" reads it back.
    m = re.fullmatch(r"(?:add (?:a )?|save (?:a )?|new )?gift idea for (?P<who>(?:my )?[a-z][a-z' ]{1,25}?)[:,-]? (?P<what>[a-z0-9].{1,60})"
                     r"|(?P<what2>[a-z0-9][a-z0-9 '-]{1,40}?) (?:would be|is|could be|might be) a (?:good|great|nice|perfect) "
                     r"(?:gift|present)(?: idea)? for (?P<who2>(?:my )?[a-z][a-z' ]{1,25}?)(?: for (?:(?:her|his|their) )?(?:birthday|christmas))?"
                     # "Add perfume to Anna's gift list" (2026-10-07: to the planner).
                     r"|(?:add|put) (?P<what3>[a-z0-9][a-z0-9 '-]{1,40}?) (?:to|on) (?:(?P<who3>(?:my )?[a-z][a-z ]{1,25}?)'s gift (?:list|ideas)"
                     r"|my gift (?:list|ideas) for (?P<who4>(?:my )?[a-z][a-z' ]{1,25}?)"
                     # "Add a scarf to gift ideas for my sister" (2026-10-08: to the planner).
                     r"|(?:the |my )?gift (?:list|ideas)(?: list)? for (?P<who5>(?:my )?[a-z][a-z' ]{1,25}?))", low)
    if m and not re.match(r"(?:it|that|this|what)\b", m.group("what") or m.group("what2") or m.group("what3")):
        what = _as_he_said(text, m.group("what") or m.group("what2") or m.group("what3"))
        who = _as_he_said(text, m.group("who") or m.group("who2") or m.group("who3") or m.group("who4") or m.group("who5"))
        return {"command": {"kind": "list_add", "list": "gift", "item": f"{what} for {who}"}, "say": None}
    # HIS MEAL PLAN (2026-10-07: "add chicken to my meal plan for monday"
    # went to the planner). A line "Monday: chicken" on the list called
    # meal plan; "what am I having for dinner monday" reads the day back.
    _wd = r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|tonight|tomorrow"
    m = re.fullmatch(r"(?:add|put) (?P<what>[a-z0-9][a-z0-9 ,'&-]{1,50}?) (?:to|on|in) (?:my |the |our )?meal plan"
                     r"(?: (?:for|on) (?P<day>" + _wd + r"))?(?: night)?"
                     r"|(?:for |on )?(?P<day2>" + _wd + r")(?: night)?(?:'s dinner is| dinner is| we'?re having| i'?m (?:having|making)) (?P<what2>[a-z0-9][a-z0-9 ,'&-]{1,50})"
                     # "I'm making tacos tonight" (2026-10-07: to a model) -
                     # the day said after the dish.
                     r"|(?:(?:i'?m|we'?re|i am|we are) (?:making|having|cooking)"
                     # "I want to make chili this weekend" (2026-10-08: to the planner).
                     r"|(?:i|we) (?:want to|wanna|would like to|'d like to|plan to|are going to|'re going to) (?:make|cook)"
                     r"|(?:i'?m|we'?re|i am|we are) (?:going to|gonna|planning to) (?:make|cook)) (?P<what3>(?!dinner\b|lunch\b|breakfast\b|plans\b|a call\b|time\b"
                     # "We're having people over Friday night" is company, not
                     # a dish (2026-10-07: it went on the meal plan).
                     r"|people\b|friends\b|guests\b|company\b|family\b|folks\b|the kids\b|a party\b|a baby\b|surgery\b"
                     r"|a meeting\b|a wedding\b|a test\b|an? [a-z]+ party\b|[a-z' ]+ over\b)[a-z][a-z0-9 ,'&-]{1,40}?)"
                     # "I'm making lasagna for dinner" is tonight (2026-10-08: to a model).
                     # "We're having chili on Saturday" read "chili on" (2026-10-08).
                     r"(?:(?: for dinner)? (?:on |this )?(?P<day3>" + _wd + r"|weekend)(?: night)?| for (?P<meal3>dinner|supper))", low)
    if m:
        import datetime as _dt
        from aletheia import localtime
        said = m.group("day") or m.group("day2") or m.group("day3") or ("today" if m.group("meal3") else "")
        if said in ("today", "tonight", "tomorrow"):
            day = _dt.datetime.now(localtime.operator_tz()).date() + _dt.timedelta(days=1 if said == "tomorrow" else 0)
            said = day.strftime("%A").lower()
        what = _as_he_said(text, m.group("what") or m.group("what2") or m.group("what3"))
        # "Added to your meal plan list: Wednesday: lasagna" (2026-10-08).
        tonight = (m.group("day") or m.group("day2") or m.group("day3") or ("today" if m.group("meal3") else "")) in ("today", "tonight")
        when = "tonight" if tonight else "this weekend" if said == "weekend" else f"on {said.capitalize()}" if said else ""
        return {"command": {"kind": "list_add", "list": "meal plan",
                            "item": f"{said.capitalize()}: {what}" if said else what},
                "say": f"{what[:1].upper() + what[1:]} {when} - it's on your meal plan." if when else None}
    # HIS PLANS WITH A WHEN (2026-10-07: "I'm moving next month", "I start
    # my new job on Monday", "my vacation is next week" each went to the
    # planner). A note in his words; `quick._life_when` reads it back with
    # the day he said it, because "next month" moves with the calendar.
    # "The electrician is coming tomorrow between 8 and 12" and "my Amazon
    # order is arriving tomorrow" (2026-10-08: both to the planner) too.
    _when = (r"(?:on |in |this |next |the )?(?:today|tomorrow|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday"
             r"|week|month|year|weekend|summer|winter|spring|fall|\d{1,2} (?:days|weeks|months)|the \d{1,2}(?:st|nd|rd|th)"
             r"|" + SPOKEN_DATE + r"|" + _MONTH + r"(?: \d{1,2}(?:st|nd|rd|th)?)?)(?: \d{4})?")
    # "I got the job at Google", then "I start on November 2" (2026-10-08:
    # to the planner). Only right after he told her about a new job.
    m = re.fullmatch(r"i (?:start|begin) (?P<when>" + _when + r")", low)
    if m:
        try:
            recent = [" ".join(str(r.get("text") or "").split()).casefold() for r in _quick._notes()[:3]]
        except Exception:  # noqa: BLE001
            recent = []
        if any(re.search(r"\b(?:got|start|starting|new|accepted|took) (?:a |the |my )?(?:new )?(?:job|offer|position|role)\b|\bgot hired\b", r)
               for r in recent):
            return {"command": {"kind": "note", "text": "I start my new job " + _as_he_said(text, m.group("when"))}, "say": None}
    if re.fullmatch(r"(?:i'?m|i am|we'?re|we are) (?:moving(?: out)?|going on (?:vacation|holiday|a trip|our trip|my trip|our honeymoon)"
                    r"|flying to [a-z][a-z ]{1,25}?|driving to [a-z][a-z ]{1,25}?|having surgery"
                    r"|starting (?:my |a )?(?:new job|school|college|classes|work)|retiring|graduating)(?: to [a-z][a-z ]{1,25}?)? " + _when, low) \
            or re.fullmatch(r"(?:i|we) (?:start|begin) (?:my |our |a )?(?:new job|school|college|classes|work|the new job) " + _when, low) \
            or re.fullmatch(r"(?:i'?m|i am|we'?re|we are|i'?ll be|i will be|i'?m going to be|i'?m gonna be) (?:on vacation|on holiday|off(?: work)?|out of (?:the )?office"
                            r"|working from home|wfh|working late|late|home late|out of town|away) " + _when, low) \
            or re.fullmatch(r"(?:i'?m|i am) taking (?:the day |a day |time |pto |a few days )?off " + _when, low) \
            or re.fullmatch(r"(?:i'?m|i am) taking (?:" + _when + r") off", low) \
            or re.fullmatch(r"i (?:have|got|'ve got|have got) (?:a |the )?(?:day off|days off|time off|pto) " + _when, low) \
            or re.fullmatch(r"i (?:have|got|'ve got|have got) (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow"
                            r"|next week|the day|the week) off", low) \
            or re.fullmatch(r"(?:my|our) (?:vacation|holiday|trip|move|moving day|surgery|first day|graduation|honeymoon|flight to [a-z ]{2,20}?)"
                            r" (?:is|starts|begins) " + _when, low) \
            or re.fullmatch(r"(?:" + _SOCIAL_PLAN + r")(?: (?:for|on|over) (?:" + _HOLIDAYS + r"))?(?: " + _when + r")?(?: night| morning| afternoon| evening)?"
                            r"(?: between \d{1,2}(?::\d\d)?(?: ?[ap]m)? and \d{1,2}(?::\d\d)?(?: ?[ap]m)?)?", low) \
            or re.fullmatch(r"(?:the|my|our) [a-z]+(?: [a-z]+)? (?:is|are) (?:coming|coming over|coming by|stopping by|showing up) "
                            + _when + r" (?:between \d{1,2}(?::\d\d)?(?: ?[ap]m)? and \d{1,2}(?::\d\d)?(?: ?[ap]m)?"
                            r"|in the (?:morning|afternoon|evening)|sometime (?:in the )?(?:morning|afternoon))", low) \
            or re.fullmatch(r"(?:my|our|the) (?:[a-z]+ )?(?:order|package|delivery|parcel|shipment|box)s? (?:is|are|should be|will be)"
                            r" (?:arriving|coming|delivered|here|getting here|showing up|out for delivery)(?: " + _when + r")?", low) \
            and re.search(r"\b(?:today|tomorrow|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|weekend|month"
                          r"|\d{1,2}(?:st|nd|rd|th)|" + _HOLIDAYS + r"|" + _MONTH + r")\b", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "We met in 2012", "we started dating in 2012", "we got engaged in
    # 2019" (2026-10-08: to the planner) - read by "how long have we been
    # together".
    if re.fullmatch(r"(?:we|(?:my|our) (?:wife|husband|partner|girlfriend|boyfriend|fiancee?) and i|i) (?:first )?(?:met|started dating|got together|got engaged"
                    r"|moved in together|started going out)(?: (?:my|our) (?:wife|husband|partner|girlfriend|boyfriend|fiancee?))?"
                    r" (?:in|on|back in) (?:" + _MONTH + r" )?(?:\d{1,2}(?:st|nd|rd|th)?,? )?(?:19|20)\d\d", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "My daughter needs new shoes" (2026-10-08: to the planner) is
    # something to get for her, on his list.
    # "My son needs a permission slip signed" (2026-10-08: "get my son a
    # permission slip signed") is his to sign.
    m = re.fullmatch(r"(?P<who>my (?:son|daughter|kid|kids)|the kids) (?:needs|need|has|have) (?:a |an |his |her |their )?(?P<what>[a-z][a-z' ]{1,25}?) (?:signed|to be signed|that needs signing)", low)
    if m:
        whose = {"my son": "my son's", "my daughter": "my daughter's", "my kid": "my kid's"}.get(m.group("who"), "the kids'")
        return _new_task(f"sign {whose} {m.group('what')}")
    m = re.fullmatch(r"(?P<who>my (?:son|daughter|kid|kids|wife|husband|mom|dad|baby|dog|cat|boy|girl)|the (?:kids|baby|dog|cat))"
                     r" (?:needs|need|could use) (?P<what>(?:a |an |some |new |more )+[a-z][a-z' ]{1,30}?)(?: for [a-z ]{2,20})?", low)
    if m and not re.search(r"\b(?:help|to|attention|sleep|rest|a nap|a bath|a walk|me|you|him|her|them|space|time)\b", m.group("what")):
        whom = m.group("who")
        return _new_task(f"get {whom} {m.group('what')}")
    # "I got my W2", "I made 85000 last year" (2026-10-08: to the planner).
    if re.fullmatch(r"i (?:just |finally )?(?:got|received) (?:my |the |a |our )?(?:w-?2|1099|tax forms?|tax documents?|tax return|refund|tax refund"
                    r"|passport|new passport|license|new license|id|new id|green card|diploma|results|test results|lab results|paycheck|bonus|raise"
                    r"|security deposit|deposit back)(?: (?:back|in the mail|today|yesterday))?(?: (?:today|yesterday|in the mail))?", low) \
            or re.fullmatch(r"i (?:made|earned|got paid) (?:about |around )?\$?[\d,.]+k?(?: dollars)? (?:last year|this year|in (?:19|20)\d\d)", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I started taking vitamin D", "my neighbor is watching the dog this
    # weekend" (2026-10-08: both to the planner) are kept, and read back by
    # "what vitamins do I take" and "who is watching the dog".
    if re.fullmatch(r"i (?:just |recently )?started (?:taking|on) (?:a |an |some |my )?[a-z0-9][a-z0-9' ]{1,40}", low) \
            or re.fullmatch(r"(?!(?:who|what|where|when|why|how|which|is|are|i)\b)(?:my |our |the )?[a-z][a-z']{1,20}(?: [a-z][a-z']{1,20})?"
                            r" (?:is|are|will be) (?:watching|feeding|walking|taking care of|looking after|babysitting|dog-?sitting|house-?sitting)"
                            r" (?:the|my|our) (?:dogs?|cats?|kids|baby|pets?|house|plants|fish|son|daughter|puppy|kitten)"
                            r"(?: (?:this|next) (?:weekend|week)| (?:on )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)| tonight| tomorrow| while [a-z ]{3,30})?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "My brother is getting married in June", "my sister had a baby girl
    # named Emma", "my grandma turns 90 next month", "I sent my mom flowers"
    # (2026-10-08: all to the planner).
    m = re.fullmatch(r"(?:my|our) (?:sister|brother|sister in law|brother in law|cousin|daughter|son)(?:'s wife| and her husband| and his wife)? (?:just )?had "
                     r"(?:a |her |his |their )?(?:new )?(?:baby )?(?:girl|boy|daughter|son|baby) (?:named|called) (?P<name>[a-z][a-z'-]{1,20})(?: today| yesterday| last night)?", low)
    if m:
        name = _as_he_said(text, m.group("name"))
        name = name[:1].upper() + name[1:]
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": f"Congratulations to them! Welcome, {name}."}
    # "My wife is pregnant" (2026-10-08: to the planner, and "my sister is
    # pregnant" was a plain "Noted."): kept, with the kind word it wants.
    happy = re.fullmatch(r"(?:my|our) (?P<who>mom|mother|dad|father|parents|brother|sister|son|daughter|cousin|aunt|uncle|niece|nephew|best friend|friend [a-z]+"
                         r"|wife|husband|partner|girlfriend|boyfriend|fiancee?|sister in law|brother in law|grandma|grandpa|grandmother|grandfather|boss|coworker [a-z]+)"
                         r" (?:is|are) (?:finally )?(?P<what>getting married|engaged|having a baby|expecting|pregnant|graduating|retiring)"
                         r"(?: (?:again|with (?:twins|a (?:girl|boy))))?(?: (?:in|on|this|next) [a-z0-9 ]{2,20})?", low)
    if happy:
        who = happy.group("who")
        whose = ("you both" if who in ("wife", "husband", "partner", "girlfriend", "boyfriend", "fiance", "fiancee")
                 else "her" if who in ("mom", "mother", "sister", "daughter", "aunt", "niece", "grandma", "grandmother", "sister in law")
                 else "him" if who in ("dad", "father", "brother", "son", "uncle", "nephew", "grandpa", "grandfather", "brother in law")
                 else "them")
        return {"command": {"kind": "note", "text": _as_he_said(text, low)},
                "say": f"That's wonderful news - congratulations to {whose}."}
    if re.fullmatch(r"(?:my|our) (?:mom|mother|dad|father|parents|brother|sister|son|daughter|cousin|aunt|uncle|niece|nephew|best friend|friend [a-z]+"
                    r"|grandma|grandpa|grandmother|grandfather|boss|coworker [a-z]+) (?:is|are) (?:getting married|getting divorced|moving|retiring|graduating"
                    r"|having a baby|expecting|pregnant|due)(?: to [a-z ]{2,25})?(?: (?:in|on|this|next) [a-z0-9 ]{2,20})?", low) \
            or re.fullmatch(r"(?:my|our) (?:mom|mother|dad|father|grandma|grandpa|grandmother|grandfather|aunt|uncle|son|daughter|brother|sister|niece|nephew|cousin|wife|husband)"
                            r" (?:turns|will be|is turning) \d{1,3}(?: (?:in|on|this|next) [a-z0-9 ]{2,20})?", low) \
            or re.fullmatch(r"i (?:just )?(?:sent|got|bought) (?:my |our )(?:mom|mother|dad|father|wife|husband|grandma|grandpa|sister|brother|son|daughter"
                            r"|aunt|uncle|boss|friend|girlfriend|boyfriend|neighbor) (?:some |a |an )?(?:flowers|a card|a gift|a present|a birthday card|a thank you card"
                            r"|a thank you note|chocolates|a cake|a care package|a gift card|a text|money)(?: today| yesterday| for (?:her|his|their) [a-z ]{2,20})?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "My new boss is named Rachel" (2026-10-08: to the planner) is who his
    # boss is, kept the way "who is my boss" reads it.
    m = re.fullmatch(r"my (?:new )?(?P<role>boss|manager|supervisor|coworker|doctor|dentist|landlord|neighbor|trainer|therapist)"
                     r"(?:'s name)? is (?:named|called) (?P<name>[a-z][a-z'-]{1,20}(?: [a-z][a-z'-]{1,20})?)", low)
    if m:
        return {"command": {"kind": "note", "text": f"my {m.group('role')} is {_as_he_said(text, m.group('name'))}"}, "say": None}
    # "My interview is with Sarah Jones", "the interview went well", "I work
    # from home on Fridays", "my coworker Sam is leaving the company", "I got
    # a bonus of 2000", "I have a performance review next week" (2026-10-08:
    # all to the planner).
    if re.fullmatch(r"(?:my|the) (?:job |phone |video |second |final )?interview (?:is|was|will be) with [a-z][a-z' .-]{1,40}", low) \
            or re.fullmatch(r"(?:my|the) (?:job |phone |video |second |final )?interview (?:went|was) (?:really |pretty |so |very |not )?(?:well|great|good|ok|okay|fine|badly|bad|terrible|awful|amazing|horrible|rough)(?: today| yesterday)?", low) \
            or re.fullmatch(r"i (?:think i )?(?:nailed|bombed|aced) (?:the|my) interview(?: today| yesterday)?", low) \
            or re.fullmatch(r"i (?:work from home|wfh|work remotely) (?:on |every )?(?:mondays?|tuesdays?|wednesdays?|thursdays?|fridays?)"
                            r"(?:(?:,| and|, and) (?:mondays?|tuesdays?|wednesdays?|thursdays?|fridays?))*", low) \
            or re.fullmatch(r"(?:my (?:coworker|boss|manager|friend at work) )?[a-z][a-z'-]{1,20} (?:is|are) leaving (?:the company|the team|work)(?: (?:next|this) (?:week|month)| on [a-z]+| soon)?", low) \
            or re.fullmatch(r"i got a (?:\$?\d[\d,]*k? )?(?:bonus|raise)(?: of \$?\d[\d,]*k?)?(?: today| this year| yesterday)?", low) \
            or re.fullmatch(r"i have (?:a |my )?(?:performance review|annual review|review|one on one|1 on 1|team meeting|all hands|training|work trip|conference)"
                            r" (?:next week|this week|next month|this month|soon)", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I have 30 days to return the jacket" (2026-10-08: to the planner) is
    # the return, due on the last day.
    m = re.fullmatch(r"i (?:have|got|only have) (?P<n>\d{1,3}) days to (?P<what>return|exchange|send back) (?P<thing>(?:the|my|this|that) [a-z][a-z' ]{1,30})", low)
    if m:
        import datetime as dt
        from aletheia import localtime
        last = dt.datetime.now(localtime.operator_tz()).date() + dt.timedelta(days=int(m.group("n")))
        task = _new_task(f"{m.group('what')} {_as_he_said(text, m.group('thing'))}")
        task["command"]["deadline"] = last.isoformat()
        return task
    # "I usually buy oat milk" (2026-10-08: refused at the money door as an
    # instruction to spend) is a habit he is telling her about - kept, and
    # nothing is bought. "The dog food we use is Purina", "I have 3 cans of
    # soup left", "I meal prepped chicken for the week" (2026-10-08: to the planner).
    if re.fullmatch(r"i (?:usually|always|normally|only|tend to) (?:buy|get|use|drink|eat) (?:the |a |an )?[a-z0-9][a-z0-9 %'-]{1,30}?(?: (?:from|at) [a-z][a-z' ]{1,20})?", low) \
            and not re.search(r"\b(?:for me|now|today|tonight|tomorrow|please|again)\b", low) \
            or re.fullmatch(r"(?:the |our |my )[a-z][a-z ]{1,20}? (?:we|i) (?:use|buy|get|like) is [a-z0-9][a-z0-9' -]{1,30}", low) \
            or re.fullmatch(r"(?:i|we) (?:have|only have|still have|'ve got) (?:\d{1,3}|one|two|three|four|five|six|a few|a couple of) (?:cans|bags|boxes|bottles|rolls|packs|jars|cartons|pods|tubs|loaves|dozen)"
                            r" (?:of )?[a-z][a-z ]{1,20}? left", low) \
            or re.fullmatch(r"i (?:just )?(?:meal ?prepped|prepped|batch cooked) [a-z][a-z ,]{1,40}?(?: for the week| for lunches| this week)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    if re.fullmatch(r"(?:groceries|gas|everything|food|eggs|rent|prices) (?:are|is) (?:so |really |crazy |too )?(?:expensive|pricey|high)(?: now| these days| lately| right now)?", low):
        return {"command": None, "say": "I know - it adds up. If you tell me what you spend, I'll keep the running total."}
    # "My neighbor Bob lent me his ladder" (2026-10-08: to the planner) is
    # a thing he borrowed, kept the way "what have I borrowed" reads it.
    m = re.fullmatch(r"(?P<who>(?:my |our )?(?:neighbou?r|friend|brother|sister|dad|mom|boss|coworker|cousin|uncle|aunt)(?: [a-z][a-z'-]{1,20})?|[a-z][a-z'-]{1,20})"
                     r" (?:lent|loaned|let) me (?:borrow )?(?:his |her |their |a |an |the |some )?(?P<thing>[a-z][a-z' ]{1,30}?)(?: for [a-z ]{2,20})?", low)
    if m and m.group("who") not in ("he", "she", "they", "it", "you", "someone", "somebody", "nobody", "the bank", "who"):
        who = m.group("who")
        named = re.sub(r"^(?:my |our )?(?:neighbou?r|friend|brother|sister|dad|mom|boss|coworker|cousin|uncle|aunt) ", "", who)
        if named != who and _said_as_a_title(text, named):
            who = named
        elif named != who:
            who = re.match(r"(?:my |our )?[a-z]+", who).group(0)
        if who == named and not who.startswith(("my ", "our ")) and not _said_as_a_title(text, who):
            m = None
        if m:
            thing = m.group("thing")
            art = "an" if thing[:1] in "aeiou" else "a"
            return {"command": {"kind": "note", "text": f"I borrowed {art} {thing} from {_as_he_said(text, who)}"}, "say": None}
    # "The power went out", "the internet is back", "my neighbor's dog
    # keeps barking" (2026-10-08: all to the planner).
    if re.fullmatch(r"(?:the |our |my )(?:power|electricity|internet|wifi|wi-fi|water|hot water|heat|heating|ac|a/c|air conditioning|cable|gas|phone service|cell service)"
                    r" (?:went out|is out|went down|is down|is off|got cut off|got shut off|was cut off|was shut off|is back(?: on| up)?|came back(?: on)?|is working again|is on again|is fixed)"
                    r"(?: again)?(?: today| tonight| this morning| last night)?", low) \
            or re.fullmatch(r"(?:my |the |our )(?:[a-z]+(?:'s|s'|s) )?[a-z][a-z]{1,15}(?: [a-z]{2,15})? (?:keeps|won't stop|wont stop|will not stop) (?!it\b)[a-z]{3,15}ing(?: [a-z ]{1,25})?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "My kids hate broccoli", "my son won't eat peas", "my mom's lasagna
    # recipe uses ricotta" (2026-10-08: all to the planner).
    if re.fullmatch(r"(?:my|our) (?:kids|son|daughter|children|boys|girls|husband|wife|partner|girlfriend|boyfriend|mom|dad|mother|father|[a-z]+ in law|baby|toddler)"
                    r" (?:hates?|don'?t like|doesn'?t like|won'?t eat|refuses? to eat|can'?t stand|dislikes?) (?!it\b|that\b|me\b|when\b|to\b|going\b)[a-z][a-z ,'-]{1,30}", low) \
            or re.fullmatch(r"(?:my |our |the )?(?:[a-z]+(?:'s|s) )?[a-z][a-z ]{1,25} recipe (?:uses|calls for|needs|has|takes|is) [a-z0-9][a-z0-9 ,'/-]{2,60}", low):
        # "my moms lasagna" is how the room hears "my mom's lasagna".
        said = re.sub(r"\b(my|our) (mom|dad|mother|father|grandma|grandpa|grandmother|grandfather|aunt|uncle|wife|husband|sister|brother|nana|papa)s\b",
                      r"\1 \2's", _as_he_said(text, low), flags=re.I)
        return {"command": {"kind": "note", "text": said}, "say": None}
    # "The chicken needs to cook for 45 minutes" (2026-10-08: to the
    # planner). Kept, and the timer is one sentence away.
    m = re.fullmatch(r"the (?P<f>[a-z][a-z ]{1,20}?) (?:needs|has|is supposed) to (?:cook|bake|roast|simmer|rest|boil|marinate|sit|rise|chill|soak|steep|smoke)"
                     r" (?:for )?(?:another |about |around )?(?P<n>\d+|an?|half an) (?P<u>minutes?|mins?|hours?|hrs?)", low)
    if m:
        n = {"a": "1", "an": "1", "half an": "30"}.get(m.group("n"), m.group("n"))
        unit = "minutes" if m.group("n") == "half an" or m.group("u").startswith("m") else ("hour" if n == "1" else "hours")
        return {"command": {"kind": "note", "text": _as_he_said(text, low)},
                "say": f"Noted. Want me to time it? Say \"set a timer for {n} {unit} for the {m.group('f')}\"."}
    # "I have a paper due Friday", "my chemistry class is in room 204", "I
    # dropped my history class" (2026-10-08: all to the planner).
    m = re.fullmatch(r"i (?:have|'ve got|have got|got) (?:a |an |my |some |the )?(?P<thing>(?:[a-z]+ )?(?:paper|essay|report|project|assignment|homework|lab|lab report|presentation"
                     r"|problem set|reading|book report|proposal|draft|thesis|article|worksheet|quiz corrections))(?: (?:for|in) [a-z][a-z ]{1,20}?)? due (?P<when>[a-z0-9][a-z0-9 :]{2,25})", low)
    if m:
        thing = m.group("thing")
        mine = "my " + thing
        done = _interpret(f"i need to finish {mine} by {m.group('when')}")
        cmd = (done or {}).get("command") or {}
        if cmd.get("kind") == "task_new" and cmd.get("deadline"):
            return done
    if re.fullmatch(r"my (?:[a-z]+ )?(?:class|lecture|lab|seminar|section|exam|final|midterm) is (?:in|at) (?:room |building |hall )?[a-z0-9][a-z0-9 .'-]{1,30}", low) \
            or re.fullmatch(r"i (?:just )?(?:dropped|added|withdrew from|signed up for|registered for|enrolled in|am taking|'m taking) (?:my |a |the )?[a-z][a-z ]{1,25} (?:class|course|lecture|seminar)", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I got a text from Sarah", "Sarah said she is running late", "my boss
    # emailed me about the report", "my new card is coming in 7 to 10 days",
    # "my card was declined", "my credit card limit is 5000" (2026-10-08:
    # all to the planner, and the limit refused at the money door as an
    # order to spend; a fact about his card is not an order).
    m = re.fullmatch(r"(?P<who>my [a-z]+(?: in law)?|[a-z][a-z'-]{1,20}) said (?:that )?(?P<x>(?:she|he|they|it|the|we|i)\b.{3,100})", low)
    if m and m.group("who") not in ("you", "she", "he", "they", "it", "someone", "somebody", "who", "everyone", "nobody", "thea", "i", "we") \
            and (m.group("who").startswith("my ") or _said_as_a_title(text, m.group("who"))):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    if re.fullmatch(r"i (?:just )?got (?:a |an )?(?:text|call|message|voicemail|email|letter|card|package|dm|phone call) from (?:my |the )?[a-z][a-z' &.-]{1,30}?(?: today| this morning| earlier)?", low) \
            or re.fullmatch(r"(?P<w>my [a-z]+(?: in law)?|[a-z][a-z'-]{1,20}) (?:emailed|texted|called|messaged|dm'?d|slacked) me(?: back)?(?: (?:about|regarding|re) [a-z0-9][a-z0-9 ,'-]{1,40})?(?: today| this morning| earlier)?", low) \
            and not re.match(r"(?:who|someone|somebody|nobody|you|it|they|he|she) ", low) \
            or re.fullmatch(r"my (?:new |replacement )?(?:credit |debit |bank )?card (?:is coming|will come|should come|comes|arrives|will arrive|should arrive|is arriving|will be here)"
                            r" in \d+(?: to \d+| or \d+)? (?:business )?days", low) \
            or re.fullmatch(r"my (?:credit |debit |bank )?card (?:was|got|is|has been) (?:declined|stolen|lost|frozen|locked|cancell?ed|replaced|compromised|hacked|expired|blocked)(?: today| again| yesterday)?", low) \
            or re.fullmatch(r"i (?:got|received|activated) (?:a |my )?new (?:credit |debit |bank )?card", low) \
            or re.fullmatch(r"i (?:reported|froze|locked|cancell?ed) my (?:credit |debit |bank )?card(?: (?:lost|stolen|as lost|as stolen))?", low) \
            or re.fullmatch(r"my (?:credit card |card )?(?:credit )?limit is \$?\d[\d,.]*k?(?: dollars)?|my credit card balance is \$?\d[\d,.]*k?(?: dollars)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "The baby is named Lily" a turn after "my sister had her baby", "my
    # dad got out of the hospital" (2026-10-08: both to the planner).
    m = re.fullmatch(r"(?:the |her |his |their )?baby(?:'s name)? is (?:named |called )?(?P<n>[a-z][a-z'-]{1,20}(?: [a-z][a-z'-]{1,20})?)"
                     r"|(?:they|she|he) named (?:the baby|her|him|it) (?P<n2>[a-z][a-z'-]{1,20}(?: [a-z][a-z'-]{1,20})?)", low)
    if m and _said_as_a_title(text, m.group("n") or m.group("n2")):
        name = _as_he_said(text, m.group("n") or m.group("n2"))
        before = _previous_turn()[0].casefold()
        whose = re.search(r"\b(my [a-z]+(?: in law)?)(?:'s wife)? (?:had|has had|just had) (?:her|his|their|a|the) baby\b", before)
        if m.group("n2") and "baby" not in before and not re.search(r"\bthe baby\b", low):
            # "They named her Lily" is a baby only right after one.
            return {"command": {"kind": "intent", "text": text}, "say": None}
        return {"command": {"kind": "note", "text": f"{whose.group(1)}'s baby is named {name}" if whose else f"the baby is named {name}"},
                "say": None}
    if re.fullmatch(r"(?:my |our )[a-z]+(?: in law)? (?:got out of|came home from|is out of|was discharged from|is home from|left|is back home from) the hospital(?: today| yesterday| this morning)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I started a new medication called lisinopril", "I stopped taking
    # lisinopril", "the doctor took me off lisinopril" (2026-10-08: to the
    # planner), kept the way "what medications am I on" reads them.
    m = re.fullmatch(r"i (?:just |recently )?(?:started|began|am starting|'m starting|got put on|was put on|was prescribed|got prescribed) (?:on )?(?:a |an |my )?(?:new )?"
                     r"(?:medication|medicine|med|prescription|pill|drug|blood pressure (?:med|medication|pill)|antibiotic)s? (?:called |named )?(?P<drug>[a-z][a-z0-9 -]{2,30})", low) \
        or re.fullmatch(r"(?:the |my )?doctor (?:put me on|started me on|prescribed(?: me)?) (?P<drug>[a-z][a-z0-9 -]{2,30})", low)
    if m and m.group("drug") not in ("it", "that", "this", "them", "something", "today", "yesterday"):
        return {"command": {"kind": "note", "text": f"I started taking {_as_he_said(text, re.sub(r' (?:today|yesterday|this week)$', '', m.group('drug')))}"}, "say": None}
    m = re.fullmatch(r"i (?:just )?(?:stopped|quit|am done|'m done|finished) (?:taking )?(?:my )?(?P<drug>[a-z][a-z0-9 -]{2,30})"
                     r"|(?:the |my )?doctor (?:took me off|stopped|discontinued) (?:my )?(?P<drug2>[a-z][a-z0-9 -]{2,30})"
                     r"|i(?:'m| am) (?:off|no longer on|not on) (?P<drug3>[a-z][a-z0-9 -]{2,30}?)(?: now| anymore| any more)?", low)
    if m:
        drug = re.sub(r" (?:today|yesterday|now|anymore|any more)$", "", m.group("drug") or m.group("drug2") or m.group("drug3"))
        if re.search(_quick._DRUGS + r"|\b(?:vitamin|supplement|pill|meds?|medication|antibiotics?|birth control)\b", drug) \
                or m.group("drug2") or re.search(r"\b(?:taking|doctor)\b", low):
            return {"command": {"kind": "note", "text": f"I stopped taking {_as_he_said(text, drug)}"}, "say": None}
    # Sports and the scores he keeps: "I have tickets to the Packers game on
    # Sunday", "our seats are section 112 row 8", "I bowled a 180 tonight",
    # "I shot an 89 at golf today", "I caught a 5 pound bass", "I ran a 5k in
    # 28 minutes", "my fantasy team is in first place", "I joined a softball
    # league", "softball is every Thursday at 6", "my tee time is 8am
    # Saturday" (2026-10-08: all to the planner).
    when_said = r"(?: (?:today|tonight|yesterday|last night|this morning|this afternoon|this weekend|on (?:mon|tues|wednes|thurs|fri|satur|sun)day))?"
    day = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?"
    if re.fullmatch(r"(?:i|we) (?:have|got|bought|have got|'ve got) (?:two |2 |four |4 |a pair of )?tickets (?:to|for) (?:the |a |an )?(?!it\b|that\b)[a-z0-9][a-z0-9 .'&-]{2,40}", low) \
            or re.fullmatch(r"(?:our|my) seats? (?:are|is) (?:in )?(?:section|sec|row|seat|box|the (?:upper|lower|club)) ?[a-z0-9][a-z0-9 ,]{0,40}", low) \
            or re.fullmatch(r"i (?:bowled|rolled) (?:a |an )?\d{2,3}(?: game| series)?" + when_said, low) \
            or re.fullmatch(r"i shot (?:a |an )?\d{2,3}(?: (?:at|in|playing) golf| on the course| at [a-z][a-z ]{2,25})?" + when_said, low) \
            or re.fullmatch(r"i caught (?:a |an |two |2 |three |3 )?(?:\d+(?:\.\d+)? ?(?:pound|lb|inch|in)s? )?(?:[a-z]+ )?(?:bass|trout|walleye|pike|salmon|catfish|perch|crappie|musky|muskie|fish|bluegill|tuna|redfish|snapper|carp|sunfish|halibut|marlin)"
                            r"(?: (?:at|on|in) (?:the )?[a-z][a-z ]{2,25}?)?" + when_said, low) \
            or re.fullmatch(r"i (?:ran|walked|swam|biked|rode|did|finished|completed) (?:a |the |my )?(?:5k|10k|15k|half marathon|half|marathon|mile|\d+(?:\.\d+)? ?(?:k|km|miles?))(?: race)?"
                            r" in (?:\d{1,2}:\d\d(?::\d\d)?|\d+(?:\.\d+)? ?(?:minutes|mins|min|hours|hrs))" + when_said, low) \
            or re.fullmatch(r"my fantasy (?:football |baseball |basketball |hockey )?(?:team|league) is (?:in |now in )?(?:\d|first|second|third|last|1st|2nd|3rd|[a-z]+th|undefeated|winning|losing|[0-9]+ and [0-9]+)[a-z0-9 -]{0,30}", low) \
            or re.fullmatch(r"i (?:just )?joined (?:a |the |our )?(?:[a-z]+ )?(?:softball|baseball|basketball|soccer|volleyball|hockey|bowling|golf|tennis|pickleball|kickball|dodgeball|darts|pool|flag football|rec|running|cycling|hiking)"
                            r" (?:league|team|club|group)", low) \
            or re.fullmatch(r"(?:my |our )?(?:[a-z]+ )?(?:softball|baseball|basketball|soccer|volleyball|hockey|bowling|golf|tennis|pickleball|kickball|poker|trivia|darts|book club|band practice|choir|yoga|pilates|spin class|league)"
                            r"(?: night| league| game| games| practice| class)? (?:is|are) (?:every|on) " + day + r"(?: and " + day + r")?(?: (?:at|from) [0-9: apm-]+(?: to [0-9: apm]+)?)?(?: nights?)?", low) \
            or re.fullmatch(r"my tee time is (?:at )?[0-9: apm.]+(?: (?:on )?(?:today|tomorrow|" + day + r"))?|my tee time is (?:on )?(?:today|tomorrow|" + day + r")(?: at [0-9: apm.]+)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # A wedding, a party, a funeral: "it is my cousin's wedding", "the
    # wedding starts at 4", "the wedding is at the Grand Hotel", "the dress
    # code is cocktail", "I RSVPd yes", "I am bringing Sarah as my plus
    # one", "the registry is on Amazon" (2026-10-08: all to the planner).
    m = re.fullmatch(r"(?:it is|it's|its|this is|that is|that's) (?P<whose>(?:my |our )?[a-z]+?)(?P<pos>'s|s'|s)? (?P<ev>" + _EVENT_WORDS + r")", low)
    if m and (m.group("pos") or m.group("whose").startswith(("my ", "our "))):
        whose = m.group("whose")
        if m.group("pos") == "s" and whose.split()[-1] in ("parent", "grandparent", "friend", "cousin", "neighbor", "kid"):
            plural = whose.split()[-1] in ("parent", "grandparent")
            whose += "s'" if plural else "'s"
        else:
            whose += "'s"
        return {"command": {"kind": "note", "text": f"the {m.group('ev')} is {_as_he_said(text, whose)}"}, "say": None}
    if re.fullmatch(r"(?:the|my|our) (?:" + _EVENT_WORDS + r") (?:starts|begins|is|kicks off|ends|finishes|is over) (?:at|by) \d{1,2}(?::\d\d)?(?: ?[ap]\.?m\.?)?(?: on [a-z]+)?", low) \
            or re.fullmatch(r"the (?:" + _EVENT_WORDS + r") is (?:at|in) (?!\d)(?!(?:the morning|the afternoon|the evening|noon)\b)[a-z][a-z0-9 .'&-]{1,40}", low) \
            or re.fullmatch(r"the dress code(?: for the (?:" + _EVENT_WORDS + r"))? is [a-z][a-z -]{1,30}", low) \
            or re.fullmatch(r"i (?:rsvpd|rsvp'd|rsvped|rsvp-ed|rsvp ?'d)(?: (?:yes|no))?(?: (?:to|for) (?:the |my |our )?[a-z][a-z' ]{1,30}?)?(?: (?:yes|no))?", low) \
            or re.fullmatch(r"(?:the|their|her|his|our) (?:wedding |baby |bridal )?registry is (?:on|at) [a-z][a-z0-9 .'&-]{1,25}"
                            r"|(?:they are|they're|she is|she's|he is|he's) registered (?:at|on) [a-z][a-z0-9 .'&-]{1,25}", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    m = re.fullmatch(r"(?:i am|i'm|im) (?:bringing|taking) (?P<who>[a-z][a-z'-]{1,20}) as my plus(?: |-)?one"
                     r"|my plus(?: |-)?one (?:is|will be) (?P<who2>[a-z][a-z'-]{1,20})", low)
    if m and _said_as_a_title(text, m.group("who") or m.group("who2")):
        return {"command": {"kind": "note", "text": f"my plus one is {_as_he_said(text, m.group('who') or m.group('who2'))}"}, "say": None}
    # "The realtor is Linda" (2026-10-08: to the planner) is who his
    # realtor is, kept the way "who is our realtor" reads it.
    m = re.fullmatch(r"the (?P<role>realtor|contractor|plumber|electrician|lawyer|attorney|accountant|mechanic|landlord|property manager|mover|babysitter|nanny|tutor|vet|dentist|doctor)"
                     r"(?:'s name)? is (?:named |called )?(?P<name>[a-z][a-z'-]{1,20}(?: [a-z][a-z'-]{1,20})?)", low)
    if m and _said_as_a_title(text, m.group("name")):
        return {"command": {"kind": "note", "text": f"my {m.group('role')} is {_as_he_said(text, m.group('name'))}"}, "say": None}
    # "We close on the house November 15", "we move on December 1", "we
    # offered 350000", "the moving truck costs 200" (2026-10-08: to the planner).
    if re.fullmatch(r"(?:we|i) (?:close|move|move in|move out|closed|moved|are closing|are moving|'re closing|'re moving) (?:on |into |out of )?(?:the |our |my |a )?(?:new )?(?:house|home|apartment|place|condo)?"
                    r" ?(?:on )?(?:" + _MONTH + r") \d{1,2}(?:st|nd|rd|th)?", low) \
            or re.fullmatch(r"(?:we|i) (?:offered|put in an offer of|made an offer of|bid|paid|sold (?:it|the house|our house) for|listed (?:it|the house) (?:at|for)) \$?\d[\d,.]*k?(?: dollars)?(?: on (?:the|a) (?:house|condo|place))?", low) \
            or re.fullmatch(r"(?:the |our |my )(?!(?:bill|rent|electric|water|gas|phone|internet|cable)\b)[a-z][a-z ]{1,20}? (?:costs|is) \$?\d[\d,.]*(?: dollars| bucks)(?: a day| a month)?"
                            r"|(?:the |our |my )(?:moving truck|movers|storage unit|uhaul|u-haul|inspection|appraisal|down payment|closing costs) (?:costs|is|was|were) \$?\d[\d,.]*(?: dollars| bucks)?(?: a day| a month)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I need to change my address with the bank" (2026-10-08: to the planner).
    m = re.fullmatch(r"i (?:need|have) to (?P<what>(?:change|update) my address (?:with|at|for) (?:the |my )?[a-z][a-z' ]{1,25})", low)
    if m:
        return _new_task(m.group("what"))
    # "My son has a fever", "my daughter got an A on her test", "my daughter
    # wants a bike for her birthday", "I paid the babysitter 60" (2026-10-08:
    # all to the planner).
    _kid = r"(?:my|our) (?:son|daughter|kid|kids|baby|boy|girl|wife|husband|mom|dad)|the (?:kids|baby)"
    m = re.fullmatch(rf"(?P<who>{_kid}) (?:has|have|has got|is running|woke up with|came home with) (?:a |an )?(?:bad |high |low |slight )?"
                     r"(?P<what>fever|cold|cough|flu|the flu|stomach bug|ear infection|sore throat|rash|headache|stomach ache|tummy ache|strep|covid|pink eye|lice|runny nose)"
                     r"(?: today| again| this morning)?", low)
    if m:
        return {"command": {"kind": "note", "text": _as_he_said(text, low)},
                "say": "Oh no - I hope they feel better soon."}
    _kid = r"(?:my|our) (?:son|daughter|kid|kids|boy|girl)|the kids"
    if re.fullmatch(rf"(?:{_kid}) (?:got|scored|made|earned) (?:an? |a perfect |a |)(?:[a-f][+-]?|\d{{1,3}}(?:%| percent)?|perfect score|honor roll|first place|second place|third place)"
                    r"(?: on (?:her|his|their|the|a) [a-z][a-z ]{1,25}| in [a-z][a-z ]{1,20})?", low) \
            or re.fullmatch(rf"(?:{_kid}) (?:wants|would like|is asking for|asked for) (?:a |an |some |the )?[a-z][a-z' ]{{1,30}}? for (?:her|his|their|christmas|hanukkah)(?: birthday)?", low) \
            or re.fullmatch(r"(?:my|our) (?:son|daughter|kids?|boy|girl|wife|husband|mom|mother|dad|father|sister|brother|grandma|grandpa|"
                            r"girlfriend|boyfriend|fiancee?|partner|niece|nephew|best friend) (?:really )?(?:wants|would like|is asking for|asked for|has been wanting)"
                            r" (?:a |an |some |new |the )[a-z][a-z' ]{1,30}?(?: for (?:her|his|their|christmas|hanukkah|mother's day|father's day|valentine'?s(?: day)?)(?: birthday)?)?", low) \
            or re.fullmatch(r"i paid (?:the )?(?:babysitter|sitter|nanny|dog walker|cleaner|cleaning lady|lawn guy|gardener|plumber|electrician|tutor|handyman|mechanic) \$?\d[\d,.]*(?: dollars| bucks)?(?: today| tonight)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "My glasses prescription is minus 2", "I have a dentist cleaning every
    # 6 months", "my last dentist visit was in April" (2026-10-08: all to
    # the planner).
    if re.fullmatch(r"my (?:glasses|eyeglass|contacts?|contact lens|eye) prescription is (?:minus |plus |-|\+)?\d[\d.]*(?: [a-z0-9 .+-]{1,30})?", low) \
            or re.fullmatch(r"i (?:have|get|go for|need) (?:a |my )?(?:dentist |dental |teeth )?(?:cleaning|checkup|check-up|physical|eye exam|mammogram|colonoscopy)s?"
                            r" every (?:\d{1,2}|six|three|twelve) (?:months|years)", low) \
            or re.fullmatch(r"my last (?:dentist|dental|doctor|eye|vet|haircut|oil change|physical|cleaning|checkup) (?:visit |appointment |exam )?(?:was|was on|was in)"
                            r" (?:january|february|march|april|may|june|july|august|september|october|november|december|last [a-z]+|\d{1,2}/\d{1,2}|[a-z]+ \d{1,2})", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I got home at 6", "I left work at 5", "I dropped the kids off at
    # school", "I am meeting Dana at the coffee shop at 3" (2026-10-08: all
    # to the planner).
    if re.fullmatch(r"i (?:got|came|made it) (?:home|back home|back) at \d{1,2}(?::\d\d)?(?: ?(?:am|pm))?", low) \
            or re.fullmatch(r"i (?:left|got off|finished|started|got to|got in to) work at \d{1,2}(?::\d\d)?(?: ?(?:am|pm))?(?: today)?", low) \
            or re.fullmatch(r"i (?:just )?(?:dropped|picked) (?:the |my )?(?:kids|son|daughter|baby|wife|husband|mom|dad|dog|[a-z]{2,15}) (?:off|up) at (?:the |my )?[a-z][a-z' ]{1,25}", low) \
            or re.fullmatch(r"(?:i'?m|i am) meeting [a-z][a-z' ]{1,20}? (?:at|for) (?:the |a )?[a-z][a-z' ]{1,25}? at \d{1,2}(?::\d\d)?(?: ?(?:am|pm))?(?: today| tomorrow)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I need to stop at the bank on the way home" (2026-10-08: to the planner).
    m = re.fullmatch(r"i (?:need|have|want) to (?P<what>(?:stop|swing by|go|run) (?:at|by|to) (?:the |a )?[a-z][a-z' ]{1,20}?|grab [a-z][a-z' ]{1,20}?|pick up [a-z][a-z' ]{1,20}?)"
                     r" on (?:the|my) way (?P<where>home|to work|back)", low)
    if m:
        return _new_task(f"{m.group('what')} on the way {m.group('where')}")
    # "Traffic is terrible" (2026-10-08: to the planner) wants a kind word.
    if re.fullmatch(r"(?:the )?traffic (?:is|was) (?:terrible|awful|horrible|bad|crazy|insane|the worst|so bad|a nightmare)(?: today| tonight| this morning)?", low):
        return {"command": None, "say": "Ugh, sorry. Drive safe - I'll be here."}
    # "I planted tomatoes today", "the sprinklers are set for 6am", "the
    # mulch was 40 dollars", "the tomatoes are ready to pick" (2026-10-08:
    # all to the planner).
    if re.fullmatch(r"i (?:just )?(?:planted|seeded|sowed|transplanted|pruned|fertilized|weeded|mulched|repotted|harvested|picked) (?:the |my |some |a few |our )?"
                    r"[a-z][a-z ]{1,25}?(?: today| yesterday| this morning| this weekend| last weekend)?", low) \
            and not re.search(r"\b(?:up|it|that|them|him|her|out|a fight)\b", low) \
            or re.fullmatch(r"(?:the |my |our )?(?:sprinklers?|irrigation|thermostat|timer|alarm system|porch lights?|lights) (?:is|are) set (?:for|to) "
                            r"\d{1,2}(?::\d\d)?(?: ?(?:am|pm))?(?: degrees)?(?: every (?:day|morning|night))?", low) \
            or re.fullmatch(r"(?:the |my |our )(?!(?:bill|rent|electric|water|gas|phone|internet|cable)\b)[a-z][a-z ]{1,20}? (?:was|were|cost|came to|ran me) (?:me )?(?:about |around )?\$?\d[\d,.]*(?: dollars| bucks)?", low) \
            or re.fullmatch(r"(?:the |my |our )(?:tomatoes|peppers|cucumbers|zucchini|squash|beans|strawberries|lettuce|apples|pumpkins|herbs) (?:are|is) (?:ready|ripe|ready to (?:pick|harvest))", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I need to fertilize the lawn in spring" (2026-10-08: to the planner).
    m = re.fullmatch(r"i (?:need|have|want|should) to (?P<what>[a-z][a-z ]{2,40}?) (?P<when>in (?:the )?(?:spring|summer|fall|autumn|winter))", low)
    if m and not re.match(r"(?:go|be|move|travel|visit|fly)\b", m.group("what")):
        return _new_task(f"{m.group('what')} {m.group('when')}")
    # "I have concert tickets for Saturday", "my book club meets on the
    # first Tuesday", "I started learning guitar", "I beat Zelda last
    # night" (2026-10-08: all to the planner).
    if re.fullmatch(r"i (?:have|got|bought) (?:two |2 |a pair of )?(?:concert|game|show|movie|theater|theatre|play|festival|comedy show|hockey|baseball|football|basketball)"
                    r" tickets? (?:for|on) (?:this |next )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tonight|tomorrow|the [0-9]{1,2}(?:st|nd|rd|th)?)", low) \
            or re.fullmatch(r"(?:my |our |the )?(?:book club|bowling league|poker night|game night|trivia night|bible study|small group|knitting group|running club|chess club)"
                            r" (?:meets|is) (?:on )?(?:every |the )?(?:first |second |third |fourth |last |other )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?"
                            r"(?: of (?:the|every|each) month)?(?: (?:at|around) \d{1,2}(?::\d\d)?(?: ?(?:am|pm))?)?", low) \
            or re.fullmatch(r"i (?:just )?started (?:learning|taking|playing|practicing) (?:the )?(?:guitar|piano|drums|violin|ukulele|bass|saxophone|spanish|french|german"
                            r"|italian|japanese|chinese|korean|sign language|to code|coding|chess|golf|tennis|pickleball|yoga|pilates|karate|boxing|jiu jitsu|swimming"
                            r"|dance|dancing|singing|painting|drawing|photography|knitting|cooking)(?: lessons| classes)?(?: today| this week| last week)?", low) \
            or re.fullmatch(r"i (?:just )?(?:beat|finished|completed) (?!the game\b|it\b|that\b)[a-z0-9][a-z0-9' :-]{1,30}(?: last night| today| yesterday)", low) \
            and _said_as_a_title(text, re.sub(r"^i (?:just )?(?:beat|finished|completed) | (?:last night|today|yesterday)$", "", low)):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I started a new workout program today", "I skipped the gym today"
    # (2026-10-08: to the planner) - read back by "when did I start my
    # workout program".
    if re.fullmatch(r"i (?:just |finally )?started (?:a |an |my |the |on a |on my )(?:new )?(?:workout|exercise|training|lifting|running|diet|meal|sleep|"
                    r"physical therapy|therapy|couch to 5k|weight loss|fitness|reading|study|savings|budget|keto|fasting)"
                    r"(?: [a-z]{3,12})?(?: today| yesterday| this week| last week| on (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))?", low) \
            or re.fullmatch(r"i (?:just )?started (?:physical therapy|therapy|keto|intermittent fasting|couch to 5k|counting calories)"
                            r"(?: today| yesterday| this week| last week)?", low) \
            or re.fullmatch(r"i skipped (?:the gym|my workout|leg day|my run|breakfast|lunch|dinner|my meds|my medicine|practice|class|church)"
                            r"(?: today| this morning| tonight| yesterday)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "My son's soccer practice is every Tuesday at 5", "my son goes to
    # Lincoln Elementary", "my kid lost a tooth" (2026-10-08: all to the
    # planner) are kept for "when is soccer practice" and "what school does
    # my son go to".
    kin = r"(?:my|our) (?:son|daughter|kid|kids|boy|girl|oldest|youngest|child|children)(?:'s|s'?)?"
    if re.fullmatch(kin + r" (?:[a-z]+ ){0,2}(?:practice|lessons?|class|classes|games?|rehearsal|tutoring|club|swim|dance|karate|piano|scouts)"
                    r" (?:is|are) (?:every|on) (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?"
                    r"(?: and (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?)?(?: (?:at|from) [0-9: apm-]+(?: to [0-9: apm]+)?)?", low) \
            or re.fullmatch(kin.replace("(?:'s|s'?)?", "") + r" (?:goes|go|go to school|goes to school) (?:to )?[a-z][a-z .'-]{2,40}?"
                            r"(?: elementary| middle(?: school)?| high(?: school)?| academy| school| prep| preschool| daycare| college| university)", low) \
            or re.fullmatch(kin.replace("(?:'s|s'?)?", "") + r" (?:just )?lost (?:a|his|her|their|another|a second|another) (?:first )?(?:baby )?tooth(?: today| tonight| yesterday)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I signed up for Spotify at 11 a month", "I cancelled Netflix"
    # (2026-10-08: both to the planner). Kept the way "what are my bills"
    # reads them: "my Spotify is 11 a month".
    svc = (r"netflix|spotify|hulu|disney plus|hbo max|youtube premium|youtube tv|amazon prime|apple music|apple tv|icloud|peacock"
           r"|paramount plus|audible|game pass|xbox game pass|playstation plus|chatgpt|the gym|a gym|planet fitness")
    m = re.fullmatch(rf"i (?:just )?(?:signed up for|subscribed to|started paying for|joined) (?P<svc>{svc})"
                     r"(?: (?:at|for) \$?(?P<n>\d[\d,.]*)(?: dollars| bucks)? (?:a|per|each) (?P<per>month|year|week))?", low)
    if m:
        name = _as_he_said(text, m.group("svc")).removeprefix("the ").removeprefix("a ")
        name = name[:1].upper() + name[1:]
        if m.group("n"):
            return {"command": {"kind": "note", "text": f"my {name} is {m.group('n')} a {m.group('per')}"}, "say": None}
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    m = re.fullmatch(rf"i (?:just |finally )?(?:cancell?ed|unsubscribed from|stopped paying for|got rid of) (?:my |our )?(?P<svc>{svc}|gym membership)"
                     r"(?: subscription| membership| account)?(?: today| yesterday)?", low)
    if m:
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "Take an advil at 2" (2026-10-08: to the planner) is said to her, so
    # it is a reminder to him.
    m = re.fullmatch(r"take (?P<what>(?:an? |my |some |two |2 |one |1 )?(?:advil|tylenol|ibuprofen|aspirin|motrin|aleve|pills?|meds|medicine|medication"
                     r"|vitamins?|antibiotics?|allergy (?:pill|medicine)|insulin|inhaler))(?P<at> (?:at|in) [0-9a-z: ]{1,15})", low)
    if m:
        again = _interpret(f"remind me to take {m.group('what')}{m.group('at')}")
        if again and (again.get("command") or {}).get("kind") in ("remind_at", "remind_in"):
            return again
    # "My wife works at the hospital" (2026-10-08: to the planner) is kept
    # for "where does my wife work". A name needs its capital.
    m = re.fullmatch(r"(?P<who>my (?:wife|husband|partner|mom|mum|dad|mother|father|sister|brother|son|daughter|girlfriend|boyfriend"
                     r"|fiance|fiancee|friend|neighbou?r|roommate|best friend|cousin|aunt|uncle)|[a-z]{2,15})"
                     r" (?:works|teaches|volunteers|goes to school|studies) (?:at|for|in|as) (?:an? |the )?[a-z][a-z0-9 &'.-]{2,40}", low)
    if m and (m.group("who").startswith("my ") or re.search(r"\b" + re.escape(m.group("who").capitalize()) + r"\b", text)) \
            and m.group("who") not in ("it", "this", "that", "he", "she", "who", "nobody", "everyone"):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I bought everything on the list" (2026-10-08: kept as a note, with
    # every line still on it) ticks the whole shopping list off.
    if re.fullmatch(r"i (?:just )?(?:got|bought|picked up|grabbed) everything on (?:the|my) (?:shopping |grocery )?list(?: today)?", low):
        return {"command": {"kind": "shopping_off", "item": "everything"}, "say": None}
    # "I made tacos tonight" (2026-10-08: to the planner) is dinner, kept
    # the way "I had tacos for dinner" is.
    m = re.fullmatch(r"i (?:just )?(?:made|cooked) (?P<what>(?:a |an |some |homemade )?[a-z][a-z' ]{2,30}?) (?:for dinner |for lunch )?(?:tonight|today|for dinner|for lunch|last night"
                     # "I made cookies for the bake sale" (2026-10-08: to the planner).
                     r"|for (?:the |a |my |our )?(?:bake sale|party|potluck|kids|family|neighbors?|office|team|church|school|picnic|game|class))", low)
    if m and not re.search(r"\b(?:mistake|reservation|appointment|call|decision|plan|it|that|money|progress|time|friends?)\b", m.group("what")):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "Sam and I are going fishing Saturday" (2026-10-08: to the planner) is
    # a plan with somebody, kept for "what am I doing Saturday".
    if re.fullmatch(r"(?:my [a-z]{2,15}|[a-z]{2,15}) and i (?:are|will be|'re) (?:going|heading|getting|having|doing|playing|meeting|grabbing)"
                    r" [a-z' ]{2,30}? (?:on |this |next )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|tonight|this weekend"
                    r"|next week)(?: (?:morning|afternoon|evening|night))?(?: at [0-9: apm]{1,8})?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I checked in for my flight" (2026-10-08: to the planner) is kept.
    if re.fullmatch(r"i (?:just |already )?checked in (?:for|to) (?:my |the |our )?(?:flight|hotel|appointment|room)(?: today| already| online)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I need to leave at 2:30" (2026-10-08: to the planner) is a reminder
    # to leave, and "Jake is picking me up from the airport" is kept.
    m = re.fullmatch(r"i (?:need|have|got|gotta|should|must)(?: to)? (?:leave|head out|go|get going) (?:at|by) (?P<t>\d{1,2}(?::\d\d)?(?: ?(?:am|pm))?)"
                     r"(?P<d> today| tonight| tomorrow)?", low)
    if m:
        again = _interpret(f"remind me to leave at {m.group('t')}{m.group('d') or ''}")
        if again and (again.get("command") or {}).get("kind") == "remind_at":
            return again
    if re.fullmatch(r"(?!(?:who|what|is|are)\b)(?:my |our )?[a-z][a-z']{1,20}(?: [a-z][a-z']{1,20})? (?:is|are|will be) (?:picking (?:me|us|the kids) up|getting (?:me|us)|driving (?:me|us)|giving (?:me|us) a (?:ride|lift))"
                    r"(?: (?:from|at) (?:the )?[a-z' ]{2,30}?)?(?: (?:at|around) [0-9: apm]{1,8})?(?: today| tonight| tomorrow)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I froze the leftover soup", "I made a double batch of chili"
    # (2026-10-08: to the planner). What is in the freezer is read back.
    if re.fullmatch(r"i (?:just )?froze (?:the |some |my |a |our )?[a-z][a-z' ]{1,40}?(?: today| yesterday| last night| for later)?", low) \
            or re.fullmatch(r"i (?:just )?(?:made|cooked|baked) (?:a |an )?(?:double |triple |big |huge |small )?(?:batch|pot|pan|tray|loaf|dozen|sheet)"
                            r" of [a-z][a-z' ]{1,30}?(?: today| yesterday| last night| for (?:the week|dinner|lunch|meal prep))?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I have a work trip to Chicago next week", "I have a deadline on the
    # report Friday", "I worked 45 hours this week", "my coworker Sam is out
    # sick", "my work email is ..." (2026-10-08: all to the planner).
    if re.fullmatch(r"i (?:have|'ve got|have got|got) (?:a |an |my |our )?(?:work |business |family |road |ski |camping |weekend |girls'? |guys'? )?"
                    r"(?:trip|conference|offsite|retreat|visit) to [a-z][a-z' ]{1,30}? " + _when, low) \
            and re.search(r"\b(?:today|tomorrow|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|weekend|month"
                          r"|\d{1,2}(?:st|nd|rd|th)|" + _MONTH + r")\b", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    m = re.fullmatch(r"i (?:have|'ve got|have got|got) (?:a |the )?deadline (?:on|for) (?P<w>(?:the|my|our) [a-z][a-z' ]{1,30}?) (?:on |by |this |next )?"
                     r"(?P<d>today|tomorrow|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday|(?:" + _MONTH + r") \d{1,2})", low)
    if m:
        again = _interpret(f"{m.group('w')} is due {m.group('d')}")
        if again and (again.get("command") or {}).get("kind") == "note":
            return again
    if re.fullmatch(r"i (?:worked|put in) \d{1,3}(?:\.\d+)? hours?(?: of work)? (?:today|yesterday|this week)", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    m = re.fullmatch(r"(?:my (?:coworker|co-worker|colleague|boss|manager|teammate|assistant) )?(?P<who>[a-z][a-z'-]{1,20}) (?:is|called in) "
                     r"(?:out sick|off sick|sick today|out today|off today|on vacation(?: this week)?|out of (?:the )?office(?: today)?|working from home(?: today)?)"
                     r"(?: today)?", low)
    if m and re.search(r"\b" + re.escape(m.group("who").capitalize()) + r"\b", text) and m.group("who") not in ("i", "he", "she", "it", "who"):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "My boss is out this week", "my coworker is out sick today" (2026-10-08:
    # to the planner) - the role is who.
    if re.fullmatch(r"my (?:coworker|co-worker|colleague|boss|manager|supervisor|teammate|assistant) (?:is|called in) "
                    r"(?:out sick|off sick|sick|out|off|on vacation|on leave|out of (?:the )?office|working from home)"
                    r"(?: today| this week| until [a-z]+| all week| tomorrow| next week| on [a-z]+)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    if re.fullmatch(r"my (?:work|personal|school|other|business) (?:email|e-mail|email address|phone|phone number|number|cell) is \S.{1,60}", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I'm going to Denver next weekend", "I'm visiting my parents next
    # week" (2026-10-07: both to the planner). A trip with a when is a note
    # in his words; "I'm going to call mom tomorrow" is something to DO and
    # is left alone, so the place may not start with a verb.
    m = re.fullmatch(r"(?:i'?m|i am|we'?re|we are) (?:going|heading|headed|driving|taking a trip|off) to (?P<place>[a-z][a-z' ]{1,30}?) " + _when, low) \
        or re.fullmatch(r"(?:i'?m|i am|we'?re|we are) visiting (?P<place>[a-z][a-z' ]{1,30}?) " + _when, low)
    if m and not re.match(r"(?:be|call|text|email|buy|get|do|make|have|need|try|work|start|finish|pay|clean|take|go|see|meet|watch"
                          r"|cook|read|write|fix|send|pick|drop|order|book|cancel|stop|check|ask|tell|leave|bring|study|run|play"
                          r"|want|miss|skip|sleep|eat|stay|help|move|apply|quit|sell|look|find|talk|join|wake|put|use|keep|let"
                          r"|give|show|change|bed|sleep|lunch|dinner|breakfast|work|school)\b", m.group("place")):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I ordered a new phone" (2026-10-07: to the planner). Something he
    # already bought is a note in his words - past tense, nothing for her
    # to buy - read back by "when is my phone arriving".
    if re.fullmatch(r"i (?:just |finally )?(?:ordered|bought|purchased) (?:a |an |some |the |my |new |a new |an extra )*[a-z][a-z0-9' -]{1,40}?"
                    r"(?: (?:from|on|off) [a-z][a-z0-9.' -]{1,25}?)?(?: today| yesterday| last night| this morning| online)?"
                    r"(?:,? (?:it'?s|and it'?s|it is) (?:arriving|coming|due|getting here) [a-z0-9 ]{2,25})?", low) \
            and not re.search(r"\b(?:you|thea)\b", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "My checking account has 2400" (2026-10-07: to the planner). A
    # balance he read off his bank, kept in his words with the time - there
    # is no bank connected, so this is the only balance she can hold.
    if re.fullmatch(r"(?:my |i have (?:about |around )?\$?[\d,.]+k?(?: dollars| bucks)? in (?:my )?)"
                    r"(?:checking|savings|bank|checking account|savings account|bank account|401k|ira|brokerage(?: account)?)"
                    r"(?: account)?(?: (?:has|is at|has got|balance is|is) (?:about |around )?\$?[\d,.]+k?(?: dollars| bucks)?(?: in it)?)?", low) \
            and re.search(r"\d", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I owe 12000 on my car" (2026-10-07: to the planner) - what is left
    # on a loan, kept in his words.
    if re.fullmatch(r"i (?:still )?owe (?:about |around )?\$?[\d,.]+k?(?: dollars| bucks)? on (?:my |the )?(?:car|truck|house|mortgage|student loans?|loan|credit card|card)"
                    r"|i (?:just )?got paid \$?[\d,.]+k?(?: dollars| bucks)?(?: today| yesterday| this week)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "The doctor said I have the flu" (2026-10-07: to the planner). What
    # someone he deals with told him, kept in his words; "what did the
    # doctor say" reads it. Only the roles, never a name: "what did Dana
    # say" is a question about his messages.
    if re.fullmatch(r"(?:the|my|our) (?:" + _quick._ROLES_WHO_TELL + r") (?:said|says|told me|told us|thinks|recommended|wants me to)"
                    r"(?: that)? [a-z0-9].{2,120}", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I take lisinopril every morning" (2026-10-07: to the planner) -
    # what he takes, in his words, read back by "what medications do I take".
    if re.fullmatch(r"i(?: take| am taking|'m taking|'m on| am on) (?:(?:\d+ ?mg|\d+|one|two|a|an) (?:of )?)?(?:" + _quick._DRUGS
                    + r"|[a-z]+ pills?|vitamins?|vitamin [a-z0-9]{1,3}|fish oil|[a-z]+ supplements?)(?: \d+ ?mg)?"
                    r"(?: (?:every|each|once a|twice a|three times a|a) (?:day|morning|night|evening|week)| daily| at night| in the morning"
                    r"| with (?:breakfast|dinner|food|meals)| for (?:my )?[a-z ]{2,25})*", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "It's my anniversary on May 5" (2026-10-07: to the planner) is "my
    # anniversary is May 5", the shape every date reader already reads.
    m = re.fullmatch(r"(?:it'?s|it is) (?P<whose>my|our|[a-z]+'s|my [a-z]+'s) (?P<what>anniversary|birthday|wedding anniversary)"
                     r" (?:on|is on|is) (?P<when>" + SPOKEN_DATE + r"|" + _MONTH + r" \d{1,2}(?:st|nd|rd|th)?)", low)
    if m:
        return {"command": {"kind": "note",
                            "text": _as_he_said(text, f"{m.group('whose')} {m.group('what')} is {m.group('when')}")}, "say": None}
    # "I'm going to the gym after work" (2026-10-07: to the planner). A plan
    # for later today is a note in his words, not a reminder he didn't ask for.
    if re.fullmatch(r"(?:i'?m|i am|i'?ll be|i will be) (?:going|heading|gonna go|going to go) (?:to )?(?:the )?"
                    r"(?:gym|store|grocery store|pool|park|library|post office|bank|doctor'?s?|dentist'?s?|office|mall|barber|salon|vet"
                    r"|for a (?:run|walk|swim|bike ride|drive)|on a (?:run|walk|bike ride)|running|walking|swimming|shopping)"
                    r" (?:after work|before work|after lunch|after dinner|after school|later(?: today| tonight)?|tonight|this afternoon"
                    r"|this evening|in the morning|tomorrow(?: morning| afternoon| evening| night)?)", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I have a flight to Denver on November 3 at 6am", "I'm staying at the
    # Hilton in Denver" (2026-10-08: both to the planner). Kept in the shape
    # the readers already know - "my flight ... is", "my hotel is" - so
    # "when is my flight" and "where am I staying" answer.
    m = re.fullmatch(r"i (?:have|'ve got|got) (?:a|my) flight(?P<to> (?:to|back to|home to|from) [a-z][a-z .'-]{1,30}?)? "
                     # a date that stays true when the note is read next week - not "tomorrow"
                     r"(?:on )?(?P<when>(?:" + _MONTH + r")\.? \d{1,2}(?:st|nd|rd|th)?(?:,? (?:at|@) [0-9: ]{1,5}(?: ?[ap]\.?m\.?)?)?)", low)
    if m:
        to = _as_he_said(text, m.group("to").strip()) if m.group("to") else ""
        return {"command": {"kind": "note",
                            "text": f"my flight{' ' + to if to else ''} is {_as_he_said(text, m.group('when'))}"},
                "say": None}
    m = re.fullmatch(r"(?:i'?m|i am|we'?re|we are) (?:staying|booked) (?:at|in) (?P<at>(?:the |an? )?[a-z0-9][a-z0-9 &'.-]{1,40}?"
                     r"(?:hotel|inn|suites|resort|lodge|motel|hostel|airbnb|hilton|marriott|hyatt|westin|sheraton|holiday inn|hampton|"
                     r"courtyard|ritz|four seasons|best western|motel 6)(?: [a-z][a-z .'-]{1,20}?)?)(?P<in> in [a-z][a-z .'-]{1,30})?"
                     r"(?: (?:tonight|this weekend|next week|while i'?m there))?", low)
    if m:
        where = _as_he_said(text, m.group("at")) + (" " + _as_he_said(text, m.group("in").strip()) if m.group("in") else "")
        return {"command": {"kind": "note", "text": f"my hotel is {where}"}, "say": None}
    # "My hotel in Paris is the Ritz" (2026-10-08: to the planner).
    m = re.fullmatch(r"(?:my|our) (?:hotel|airbnb|hostel|resort|place) (?P<in>in [a-z][a-z .'-]{1,30}? )?is (?:called )?(?P<at>(?:the |an? )?[a-z0-9][a-z0-9 &'.-]{1,40}?)", low)
    if m and not re.match(r"(?:nice|great|good|bad|awful|terrible|amazing|small|big|clean|dirty|close|far|booked|ready|expensive|cheap)\b", m.group("at")):
        where = _as_he_said(text, m.group("at")) + (" " + _as_he_said(text, m.group("in").strip()) if m.group("in") else "")
        return {"command": {"kind": "note", "text": f"my hotel is {where}"}, "say": None}
    # "I need to pack my charger" (2026-10-08: to the planner) goes on the
    # packing list "what do I need to pack" already reads.
    m = re.fullmatch(r"(?:i (?:need|have|got|gotta|should|must)(?: to)? |don'?t (?:let me )?forget to |remember to )pack (?:my |the |a |an |some |our )?"
                     r"(?P<what>[a-z][a-z0-9 '&-]{1,40}?)(?: for (?:the |my |our )?(?:trip|vacation|holiday|flight))?", low)
    # "I need to pack lunches tonight" (2026-10-08: on the packing list) is
    # a chore with a day on it, not something for a bag.
    # "I need to pack for my trip" (2026-10-08) put "for your trip" on the
    # packing list. Packing is the job; the trip is what it is for.
    if m and re.match(r"for |up for ", m.group("what")):
        return _new_task("pack " + _as_he_said(text, m.group("what")))
    if m and m.group("what") not in ("it", "that", "this", "everything", "up", "stuff", "things", "bags", "bag", "suitcase") \
            and not re.search(r"\blunch(?:es)?\b|\bsnacks? for (?:the )?(?:kids|school)\b|\b(?:tonight|tomorrow|today|this (?:morning|evening))$", m.group("what")):
        return {"command": {"kind": "list_add", "list": "packing", "item": _as_he_said(text, m.group("what"))}, "say": None}
    # "I benched 185 today" (2026-10-08: to the planner). A lift he logs;
    # "what's my max bench" reads the heaviest.
    if re.fullmatch(r"i (?:just )?(?:benched|bench pressed|squatted|deadlifted|overhead pressed|military pressed|curled|leg pressed|"
                    r"did (?:a )?(?:bench|squat|deadlift)(?: of)?) \d{2,4}(?: ?(?:pounds|lbs?|kilos|kgs?))?"
                    r"(?: (?:for|x|times) \d{1,2}(?: reps?)?)?(?: (?:today|this morning|tonight|yesterday|at the gym))?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "My gym opens at 5am" (2026-10-08: to the planner) - kept in his
    # words, read back by "what time does my gym open".
    if re.fullmatch(r"(?:my|the|our) (?:local )?[a-z][a-z' ]{1,25}? (?:opens|closes|is open|is closed)(?: (?:at|until|till|from))? "
                    r"\d{1,2}(?::\d\d)? ?(?:am|pm|a\.m\.|p\.m\.)?(?:(?: to| until| till|-) ?\d{1,2}(?::\d\d)? ?(?:am|pm)?)?"
                    r"(?: (?:on )?(?:weekdays|weekends|every day|daily|on sundays|on saturdays|on sunday|on saturday))?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I moved my car to the garage" (2026-10-08: to the planner, after
    # "where did I park" had been answered from the old spot) - a new spot.
    m = re.fullmatch(r"i (?:just )?(?:moved|re-?parked|left|put) (?:my|the) (?:car|truck|van) (?P<prep>to|in|into|at|on|by|outside|behind) (?P<where>(?!(?:drive|park|neutral|reverse|gear|sport mode)\b).{2,60})", low)
    if m:
        prep = {"to": "in", "into": "in"}.get(m.group("prep"), m.group("prep"))
        return {"command": {"kind": "note", "text": f"I parked {prep} {_as_he_said(text, m.group('where'))}"}, "say": None}
    # "I got gas today" (2026-10-08: to the planner) - kept, so "when did I
    # last get gas" has an answer.
    if re.fullmatch(r"i (?:just )?(?:got|bought|put in|filled up(?: on)?) gas(?: in (?:the|my) (?:car|truck))?"
                    r"(?: (?:today|this morning|yesterday|earlier|tonight|on the way home))?(?: for \$?\d[\d.,]*(?: dollars| bucks)?)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I GOT A HAIRCUT", "I need an oil change" (2026-10-07: both to the
    # planner). A service he had is a note "when did I last get a haircut"
    # reads; one he needs is a task to get it.
    # "...at 45,000 miles" (2026-10-08: to the planner) is kept with it.
    # "I need to see a dentist" (2026-10-08: to the planner) is an errand.
    m = re.fullmatch(r"i (?:need to|have to|should|gotta|got to|really need to|really should) (?P<what>(?:see|go to|visit) (?:a |an |the |my )?"
                     r"(?:doctor|dentist|eye doctor|optometrist|dermatologist|chiropractor|therapist|physical therapist|vet|doc|specialist|orthodontist)"
                     r"(?: about [a-z' ]{2,30})?)", low)
    if m:
        return _new_task(_as_he_said(text, m.group("what")))
    # "I need to get a passport" went on the shopping list (2026-10-08).
    # Paperwork is an errand.
    m = re.fullmatch(r"i (?:need|have to get|gotta get|got to get|should get|need to get|need to renew|have to renew|need to apply for|have to apply for) "
                     r"(?P<what>(?:a |an |my )?(?:new )?(?:passport|visa|driver'?s license|license|licence|real id|id card|permit|birth certificate"
                     r"|social security card|marriage license|insurance card)(?: renewed| replaced)?)", low)
    if m:
        verb = re.search(r"\b(renew|apply for)\b", low)
        return _new_task(f"{verb.group(1) if verb else 'get'} {_as_he_said(text, m.group('what'))}")
    # "I need a dog sitter" went on the shopping list (2026-10-08).
    m = re.fullmatch(r"i (?:need|have to find|gotta find|got to find|should find|should get|need to find|need to get) (?:a |an )?(?P<who>(?:dog|pet|cat|house|baby) ?sitter|babysitter|dog walker)(?: for (?:the |this |next )?(?:weekend|week|trip|[a-z]+day(?: night)?))?", low)
    if m:
        return _new_task("find a " + m.group("who"))
    m = re.fullmatch(r"i (?:just |finally )?(?:got|had|have had|'ve had|got done) (?P<svc>" + _quick._SERVICES + r")"
                     r"(?: done)?(?: today| yesterday| this morning| last week| earlier)?(?: at \d[\d,]* (?:miles|mi|km))?", low)
    if m:
        # "get a haircut" on his list is ticked off; the note is kept either way
        svc = re.sub(r"^(?:a|an|my|the) ", "", m.group("svc"))
        if _names_one_open_task("get " + svc):
            return {"command": {"kind": "task_done", "which": "get " + svc}, "say": None}
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    m = re.fullmatch(r"i(?: really)?(?: need| should get| have to get| need to get| gotta get| am due for|'m due for) (?P<svc>" + _quick._SERVICES + r")"
                     # "I need a haircut before the wedding" (2026-10-08: to the planner).
                     r"(?: soon| this week| sometime)?(?P<before> before (?:the|my|our) [a-z][a-z' ]{1,30})?", low)
    if m:
        svc = _as_he_said(text, m.group("svc"))
        if not re.match(r"(?:a|an|my|the) ", svc, re.I):
            svc = ("an " if svc[:1].lower() in "aeiou" else "a ") + svc
        return _new_task(f"get {svc}" + (m.group("before") or ""))
    # "I watched Oppenheimer" (2026-10-07: to the planner) - "what movies
    # have I watched" reads it back with his watch list.
    if re.fullmatch(r"i (?:just )?(?:watched|finished watching|binged) (?!(?:it|that|this|them|him|her|you|the kids|my)\b)"
                    r"[a-z0-9][a-z0-9 ,:'&-]{1,60}?(?: (?:last night|tonight|today|yesterday|again))?", low):
        # On his watch list, it comes off it (2026-10-08: "what should I
        # watch tonight" offered Dune a turn after "I watched Dune").
        title = re.sub(r"^i (?:just )?(?:watched|finished watching|binged) | (?:last night|tonight|today|yesterday|again)$", "", low).strip()
        try:
            from aletheia import lists
            listed = {str(t).casefold() for t in (lists.items("watch") or [])}
        except Exception:  # noqa: BLE001
            listed = set()
        if title.casefold() in listed:
            return {"command": {"kind": "list_off", "list": "watch", "item": _as_he_said(text, title)}, "say": None}
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I START WORK AT 9", "my commute is 30 minutes" (2026-10-07: to the
    # planner). Notes in his words; "what time do I start work" reads the
    # first, and "when should I leave for work" adds the two up when there
    # is no work address to time a drive to.
    if re.fullmatch(r"i (?:start|begin|get to|have to be at|need to be at|clock in at|clock in|go in)(?: work)?(?: at)? "
                    r"\d{1,2}(?::\d\d)?(?: ?(?:am|pm|a\.m\.|p\.m\.))?(?: (?:every day|on weekdays|most days|tomorrow|today))?"
                    r"|i (?:get off|finish|leave|clock out)(?: work)?(?: at)? \d{1,2}(?::\d\d)?(?: ?(?:am|pm|a\.m\.|p\.m\.))?"
                    r"|my (?:shift|work ?day) (?:starts|begins|ends|finishes) (?:at )?\d{1,2}(?::\d\d)?(?: ?(?:am|pm|a\.m\.|p\.m\.))?"
                    r"|(?:my commute is|it takes me|my drive to work is) (?:about |around )?\d{1,3} (?:minutes|mins|min|hours?)"
                    r"(?: to get to work| to work| each way)?", low):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "I work at Acme", "I go to school at UIC" (2026-10-07: to the planner).
    # Not "I work at 9 tomorrow" - that is a shift, not a place.
    m = re.fullmatch(r"i (?:work|am working|started working|go to school|study) (?:at|for) (?P<where>[a-z][a-z0-9&' .-]{1,40})", low)
    if m and not re.search(r"\b(?:today|tonight|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday"
                            r"|morning|afternoon|evening|night|noon|home|the moment|now|it|that|this)\b", m.group("where")):
        return {"command": {"kind": "note", "text": _as_he_said(text, low)}, "say": None}
    # "The rent is due Friday" (2026-10-07: to the planner). A weekday is
    # only true this week, so the note keeps the date it meant.
    m = re.fullmatch(r"(?P<thing>(?:my|our|the) [a-z][a-z' ]{1,30}?) (?P<verb>expires?|runs? out|(?:is|are) due|renews?|ends?) (?:on |by )?"
                     r"(?P<day>today|tomorrow|(?:this )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))", low)
    if m and _spoken_day(m.group("day")):
        import datetime as dt
        on = dt.date.fromisoformat(_spoken_day(m.group("day"))[:10])
        dated = f"{m.group('thing')} {m.group('verb')} {on.strftime('%A')} {on.day} {on.strftime('%B')}"
        return {"command": {"kind": "note", "text": _as_he_said(text, dated)}, "say": None}

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
    # "Which one - 6 am or 7 am?" -> "good night" (2026-10-07) was taken as
    # the choice: "None of your reminders is about good night." A choice
    # names something in the question; anything else is a new sentence.
    asked = re.sub(r"^.*?\bWhich one\b", "", str(last.get("she_answered") or "")).casefold()
    if not any(re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", asked)
               for w in re.findall(r"[a-z0-9:']+", answer) if w not in ("a", "an", "at", "on", "the", "my", "and", "or", "am", "pm")):
        return None
    if cmd.get("kind") in ("reminder_off", "reminder_on") and re.fullmatch(r"\d{1,2}", answer):
        # "The 7 one" asked again (2026-10-07): a bare hour is read the way
        # "turn off my 7 alarm" reads it.
        answer = f"{answer}:00"
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
    previous = _previous_ask().casefold().rstrip(".?!")
    # "Remind me tomorrow" -> "Remind you of what?" -> "to call Sam"
    # (2026-10-08: to the planner). The when came a turn ago.
    half = re.fullmatch(r"remind me (?P<when>tomorrow(?: morning| afternoon| evening| night)?|tonight|later today"
                        r"|this (?:morning|afternoon|evening)|next week|on (?:mon|tues|wednes|thurs|fri|satur|sun)day"
                        r"|(?:tomorrow )?(?:at|around) (?:\d{1,2}(?::\d\d)?(?: ?[ap]m)?|noon|midnight)(?: (?:today|tomorrow|tonight))?)",
                        previous)
    if half:
        # Only straight after she asked: "turn off the lights" an hour later
        # is not the reminder's missing half.
        try:
            from aletheia import converse
            asked = str(((converse.recent(limit=1) or [{}])[-1]).get("she_answered") or "")
        except Exception:  # noqa: BLE001
            asked = ""
        half = half if asked.startswith("Remind you of what") else None
    if half:
        said = re.sub(r"^(?:to|that) ", "", text.strip().rstrip("."), flags=re.IGNORECASE)
        how = "that" if re.match(r"(?i)that ", text.strip()) else "to"
        again = _interpret(f"remind me {half.group('when')} {how} {said}")
        if ((again or {}).get("command") or {}).get("kind") in ("remind_at", "remind_daily", "remind_weekly"):
            return again
    before = _BARE_ASK.fullmatch(previous)
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
