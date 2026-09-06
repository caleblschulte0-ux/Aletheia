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

from aletheia import capabilities, policy, tasks

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
    """Did he give an hour with no am/pm — "at 3" rather than "at 3 pm"?"""
    return re.fullmatch(r"\s*\d{1,2}\s*",
                        str(text or "").lower().replace(".", "")) is not None


def _spoken_time(text: str) -> str | None:
    """'8 am' / '8:30 pm' / '20:15' -> 'HH:MM', else None."""
    t = text.strip().lower().replace(".", "")
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
                     "waiting on you — say approve to grant the first one.")
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


def interpret(transcript: str) -> dict:
    """One spoken sentence -> a command to gate-check, or words to say."""
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
    if (re.fullmatch(r"(halt|stop|kill switch|emergency stop|shut it down|"
                     r"stand down)", low)
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
    m = re.match(r"^(resume|un-?halt|halt)\s+"
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

    # reminders — before email so "remind me to email bob" stays a reminder
    m = re.match(r"remind me (?:every day|daily) at ([\w: ]+?) (?:to|that) (.+)", low)
    if m:
        hhmm = _spoken_time(m.group(1))
        if hhmm:
            return {"command": {"kind": "remind_daily", "time": hhmm,
                                "text": m.group(2).strip()}, "say": None}
        return {"command": None,
                "say": f"I couldn't parse the time {m.group(1)!r} — say it like '8 am' or '14:30'."}
    m = re.match(r"remind me (?:at ([\w: ]+?)|in (\d+) (minutes?|hours?)) (?:to|that) (.+)", low)
    if m:
        if m.group(1):
            hhmm = _spoken_time(m.group(1))
            if not hhmm:
                return {"command": None,
                        "say": f"I couldn't parse the time {m.group(1)!r} — say it like '8 am' or '14:30'."}
            at = _next_occurrence_iso(hhmm, bare_hour=_is_bare_hour(m.group(1)))
        else:
            import datetime as dt
            amount = int(m.group(2))
            delta = dt.timedelta(minutes=amount) if m.group(3).startswith("minute") \
                else dt.timedelta(hours=amount)
            at = (dt.datetime.now(dt.timezone.utc) + delta).isoformat()
        return {"command": {"kind": "remind_at", "at": at, "text": m.group(4).strip()},
                "say": None}

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

    # "what files do you have" reached the planner, which sometimes
    # compiled `file_list` and sometimes let `converse` answer — and
    # `converse` does not know she can list a directory, so it replied
    # "no FILE HE NAMED was passed with this question".
    if re.fullmatch(r"(?:what|which) files (?:do you have|are there|"
                    r"have you got)|list (?:my |your )?files|"
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
        return {"command": None,
                "say": f"I couldn't parse {m.group(1)!r} — say today, tomorrow, "
                       "a date, or something like 'tomorrow afternoon'."}

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
                    r"catch me up|what did i miss", low):
        return {"command": {"kind": "brief"}, "say": None}

    m = re.match(r"handle (?:it|this|that)[,: ]*(.*)$", low)
    if m and m.group(1).strip():
        return {"command": {"kind": "handle", "text": m.group(1).strip()},
                "say": None}

    m = re.match(r"how long (?:does it take |to get )?(?:to )?(?:get to )?(.+)", low)
    if m:
        return {"command": {"kind": "travel_time", "place": m.group(1).strip()},
                "say": None}

    m = re.match(r"(?:add )?(.+?) to (?:the |my )?(?:shopping |grocery )?list$", low)
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
                    r"does the car need anything|check the car)", low):
        return {"command": {"kind": "car"}, "say": None}

    if re.fullmatch(r"(?:my projects?|what projects are (?:open|active)|"
                    r"what am i working on)", low):
        return {"command": {"kind": "projects"}, "say": None}

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
    m = (re.match(r"(?:deny|denied|no to|cancel|scrap|drop)"
                  r"(?:\s+(?:that|it|the pending one))?$", low)
         or re.match(r"(?:never ?mind|forget (?:it|that)|call it off|"
                     r"don'?t do (?:it|that))$", low))
    if m:
        pending = [a for a in policy.all_approvals() if a["state"] == "PENDING"]
        if len(pending) == 1:
            return {"command": {"kind": "deny", "id": pending[0]["id"],
                                "because": "denied by voice"}, "say": None}
        if not pending:
            return {"command": None, "say": "Nothing is waiting for approval."}
        # Read them out, the way `approve` does. "Use the Command Center"
        # is an instruction to go somewhere else, said to someone who is
        # standing in a room talking.
        return {"command": None, "say": _offer_choice(pending, verb="deny")}

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

    m = re.match(r"(?:note|note that|write down|log)\s+(.+)", low)
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


ORDINALS = {"first": 0, "second": 1, "third": 2, "last": -1}


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
