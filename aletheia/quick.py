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
    # `down` marks the alternatives that ask whether she is STOPPED, so
    # the answer can agree with the question. Without it "are you
    # running" and "you there" -- the two most natural ways to ask --
    # were answered "No, I'm running.", which is a contradiction in the
    # same breath.
    ("halted", re.compile(
        r"^(?:are|r) (?:you|u) (?P<down>halted|stopped|paused|off|frozen)$"
        r"|^(?:are|r) (?:you|u) (?:running|on|up|working|alive|awake)$"
        r"|^is the kill switch (?P<down2>on)$|^is the kill switch off$"
        r"|^(?:are|r) (?:you|u) ok$"
        # No verb at all is how a person actually checks. "you there" is
        # the single most natural way to ask this and it paid a planner
        # round trip to be told yes.
        r"|^(?:you|u) (?:there|awake|up|good|ok|alive|with me)$"
        r"|^(?:are|r) (?:you|u) (?:there|still there|still up)$"
        r"|^still (?:there|awake|up)$|^(?:you|u) still (?:there|up)$")),
    ("waiting", re.compile(
        r"^what(?:'s| is|s)? waiting(?: on| for)? me$"
        r"|^what(?:'s| is|s)? waiting$"
        r"|^(?:is there )?anything (?:waiting )?for me$"
        r"|^(?:do )?(?:you )?need anything(?: from me)?$"
        r"|^what needs me$|^anything i need to (?:do|see|look at)$"
        r"|^what(?:'s| is|s)? on my plate$"
        r"|^is there anything waiting(?: on me| for me)?$"
        r"|^anything i should know(?: about)?$"
        r"|^what am i blocking$|^am i blocking anything$")),
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
    # Eight seconds and a round trip for the clock she is holding.
    ("clock", re.compile(
        r"^what(?:'s| is|s)? the time( right now| now)?$"
        r"|^(?:do you know )?what time is it( right now| now)?$"
        r"|^(?:got|have) the time$|^time$")),
    ("date", re.compile(
        r"^what(?:'s| is|s)? (?:the |today'?s? )?date( today)?$"
        r"|^what day is it( today)?$|^what(?:'s| is|s)? today$"
        r"|^what day of the week is it$")),
    # NOT folded into "date": that sentence is "Monday the 7th of
    # September", which contains no year and buries the month. Answering
    # "what year is it" with it was a confident answer to a question he
    # did not ask.
    ("month", re.compile(
        r"^what month is it( now)?$|^what(?:'s| is|s)? the month$"
        r"|^what month are we in$")),
    ("year", re.compile(
        r"^what year is it( now)?$|^what(?:'s| is|s)? the year$"
        r"|^what year are we in$")),
    # Five stores she was already holding and answering from a model.
    ("tasks", re.compile(
        r"^what(?:'s| is|s)? on my task list$|^what are my tasks$"
        r"|^what tasks do i have$|^how many tasks do i have$"
        r"|^(?:my )?task list$|^my tasks$"
        r"|^what(?:'s| is|s)? my next task$|^what(?:'s| is|s)? next$")),
    ("approvals", re.compile(
        r"^how many approvals are pending$|^what needs approving$"
        r"|^what(?:'s| is|s)? pending(?: approval)?$"
        r"|^(?:are there |any )?approvals(?: pending| waiting)?$"
        r"|^what am i approving$")),
    # "What can you do" is the question this whole registry exists to
    # answer, and it was the one question that went to a model to be
    # answered ABOUT the registry.
    # The counts, for the question the old "what can you do" answer was
    # really answering. He almost never asks this; when he does, he wants
    # the number and not the list.
    ("how_many", re.compile(
        r"^how many (?:things|capabilities|capabilitys) (?:can|could) "
        r"(?:you|u) do$"
        r"|^how many (?:things|capabilities) (?:do|have) (?:you|u) "
        r"(?:do|have|got)$"
        r"|^how many capabilities (?:are there|do you have)$")),
    ("capabilities", re.compile(
        r"^what can (?:you|u) do(?: for me)?$"
        r"|^what are (?:you|u) able to do$|^what are your capabilities$"
        r"|^what do (?:you|u) do$")),
    ("alerts", re.compile(
        r"^(?:are there |is there )?any(?:thing)? (?:alerts|broken|wrong|failing)$"
        r"|^any alerts$|^is anything broken$|^anything broken$"
        r"|^how(?:'s| is) the fleet$|^is everything (?:ok|green|fine)$"
        r"|^fleet status$")),
    ("repos", re.compile(
        r"^how many repos (?:are )?(?:you|u) (?:watching|watch|track|tracking)$"
        r"|^how many repos do (?:you|u) watch$"
        r"|^what repos (?:are )?(?:you|u) watching$"
        r"|^how many repos$")),
    ("shopping", re.compile(
        r"^what(?:'s| is|s)? on my shopping list$|^what(?:'s| is|s)? on my list$"
        r"|^(?:my )?shopping list$|^what do i need (?:to buy|from the store)$"
        r"|^what(?:'s| is|s)? on the shopping list$")),
    # "What is running" was wired into `voice` and NOT here, so SAYING it
    # was instant and TYPING it paid a full planner round trip for the
    # same answer out of the same store. Every door should give the same
    # one — that is the whole point of there being one answer.
    ("running", re.compile(
        r"^what(?:'s| is|s)? running(?: right now)?$"
        r"|^which parts are running$|^what parts (?:of you )?are running$"
        r"|^is anything running$|^what(?:'s| is|s)? on right now$"
        r"|^are (?:you|u) all running$")),
    # His own details, out of his own profile. She read them off his resume;
    # asking a model to recite them is a round trip to the wrong store.
    # "What code are you running" had no answer, and that is the question
    # this whole session started from: the Core had been up three days on
    # code ninety commits old, every part reported healthy, and nothing
    # anywhere said so.
    # 55ms spoken against ~25 SECONDS typed, for the same sentence off the
    # same feed. `quick` declined this on the belief that the calendar was
    # not connected; it is — an ICS feed, reporting "1 feed(s)
    # configured" — it is simply EMPTY, and "free all day" from a feed
    # that really says nothing is a correct answer rather than a guess.
    #
    # Only the whole-day forms. "Am I free at 3", "am I free this
    # afternoon" and "am I free for an hour" all take arguments this
    # cannot parse, and the planner is better at them than a regex.
    ("free", re.compile(
        r"^am i free(?: (?P<free>today|tomorrow))?$"
        r"|^(?:do i|have i) (?:have|got) (?:anything|any plans|much) on"
        r"(?: (?P<free2>today|tomorrow))?$"
        r"|^is my (?P<free3>today|tomorrow) free$")),
    ("version", re.compile(
        r"^what version are (?:you|u) on$|^what version are (?:you|u) running$"
        r"|^what code are (?:you|u) running$|^what(?:'s| is|s)? your version$"
        r"|^which (?:branch|commit) are (?:you|u) on$"
        r"|^are (?:you|u) (?:up to date|current|stale)$"
        r"|^are (?:you|u) running the latest code$")),
    ("uptime", re.compile(
        r"^how long have (?:you|u) been (?:up|running|on|awake|going)$"
        r"|^how long have (?:you|u) been here$"
        r"|^what(?:'s| is|s)? your uptime$|^uptime$")),
    # A greeting is not small talk to something that can see his day. It
    # cost 25-80 seconds to be greeted back, and the answer to "hey" that
    # is worth saying is what is waiting on him.
    # THE WEATHER. In `quick` rather than the grammar because it is a
    # read she can do from a cache in a hundredth of a second, which is
    # what this lane is for — and it means the most ordinary question
    # anybody asks never touches a model.
    ("weather", re.compile(
        r"^(?:what(?:'s| is|s)? (?:the )?weather"
        r"|how(?:'s| is) the weather|what(?:'s| is|s)? it like outside)"
        r"(?: (?P<weather>today|tonight|tomorrow|this (?:morning|afternoon|evening)"
        r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?$"
        r"|^(?:is|will) it (?:going to )?(?:rain|snow) (?P<weather2>today|tonight|tomorrow)$"
        r"|^weather(?: (?P<weather3>today|tonight|tomorrow))?$")),
    ("greeting", re.compile(
        r"^(?:hi|hello|hey|yo|hiya|howdy|hey there|hi there)$"
        r"|^good (?:morning|afternoon|evening)$"
        r"|^how (?:are|r) (?:you|u)(?: doing| today)?$"
        r"|^how (?:you|u) doing$|^how goes it$")),
    ("mine", re.compile(
        r"^what(?:'s| is|s)? my (?P<mine>email(?: address)?|phone(?: number)?"
        r"|number|city|town|name|first name|last name|full name)$"
        r"|^who am i$")),
    ("home", re.compile(
        r"^where do i live$|^what city do i live in$"
        r"|^what town do i live in$|^where(?:'s| is) home$")),
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
        rest = next((captured[k] for k in ("what", "what2", "what3", "mine",
                                           "free", "free2", "free3",
                                           "down", "down2", "weather",
                                           "weather2", "weather3")
                     if captured.get(k)), "")
        return name, rest
    return None


def _halted(asks_if_down: bool = True) -> str:
    """Yes or no, agreeing with the direction the question was asked in.

    "Are you halted?" and "You there?" want opposite words for the same
    state. Answering both with the sentence written for the first is how
    "are you running" came back "No, I'm running." — the state was right
    and the first word contradicted it.
    """
    from aletheia import policy
    halt = policy.halted()
    if not halt:
        return "No, I'm running." if asks_if_down else "Yes, I'm running."
    reason = str(halt.get("reason") or "").strip()
    lead = "Yes, I'm halted" if asks_if_down else "No, I'm halted"
    return lead + (f" — {reason}." if reason else ".")


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
        parts.append(f"{len(waiting)} waiting on you — the first is "
                     + speech.shorten(what, 90))
    if notices:
        # SAY WHAT THEY ARE. A reminder fired correctly, on time, and the
        # answer to "what's waiting on me" was "1 thing I wanted to tell
        # you about" — the answer to "how many", when he asked what.
        # Titles rather than bodies, cut at a word boundary. A body is a
        # paragraph with commas in it, and `and_list` joins with commas —
        # three of those ran together into one unbreathable sentence
        # ending "...is worth right now?: I don't ha,".
        said = speech.and_list([speech.notice_line(n) for n in notices[:3]])
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


def _clock() -> str:
    """"What time is it" — from the machine's own clock, in HIS zone.

    A model round trip for this is eight seconds to read a clock she is
    already holding, and it answered in the process's timezone once
    already (CLAUDE.md, the 03:00 reminder).
    """
    import datetime as dt
    from aletheia import localtime
    now = dt.datetime.now(localtime.operator_tz())
    clock = now.strftime("%I:%M %p").lstrip("0").replace(" AM", " am").replace(" PM", " pm")
    return f"{clock}, {now.strftime('%A')} the {_ordinal(now.day)} of {now.strftime('%B')}."


def _date() -> str:
    """"What day is it" — the day first, because that is what he asked."""
    import datetime as dt
    from aletheia import localtime
    now = dt.datetime.now(localtime.operator_tz())
    return f"{now.strftime('%A')} the {_ordinal(now.day)} of {now.strftime('%B')}."


def _month() -> str:
    import datetime as dt
    from aletheia import localtime
    now = dt.datetime.now(localtime.operator_tz())
    return f"{now.strftime('%B')} — the {_ordinal(now.day)}."


def _year() -> str:
    import datetime as dt
    from aletheia import localtime
    return f"{dt.datetime.now(localtime.operator_tz()).year}."


def _ordinal(day: int) -> str:
    if 10 <= day % 100 <= 20:
        return f"{day}th"
    return f"{day}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th') }"


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


# Statuses that mean a task is off his list. FAILED stays ON it: something
# that broke is exactly what he wants named when he asks what is open.
_TASK_CLOSED = ("COMPLETED", "CANCELLED", "ABANDONED")


def _tasks() -> str:
    """His task list, counted and with the next one named."""
    from aletheia import speech, tasks
    rows = tasks.all_tasks()
    live = [t for t in rows
            if str(t.get("status") or "").upper() not in _TASK_CLOSED]
    if not live:
        return "Nothing open on your task list."
    index = {t.get("id"): t for t in rows}
    ready = [t for t in live if tasks.is_ready(t, index)]
    first = (ready or live)[0]
    what = str(first.get("description") or first.get("id") or "").strip()
    lead = f"{speech.count_phrase(len(live), 'task')} open"
    if ready and len(ready) != len(live):
        lead += f", {len(ready)} ready to start"
    return lead + (f". Next: {what[:130].rstrip('.')}." if what else ".")


def _approvals() -> str:
    """What is sitting on HIS yes. The count is the answer; the first one
    is what makes the count mean something."""
    from aletheia import policy, speech
    try:
        rows = policy.all_approvals()
    except Exception:
        return None
    pending = [a for a in rows
               if str(a.get("state") or "").upper() == "PENDING"]
    if not pending:
        return "Nothing is waiting on your approval."
    first = str(pending[0].get("reason") or pending[0].get("action") or "").strip()
    return (f"{speech.count_phrase(len(pending), 'approval')} pending"
            + (f". The first: {first[:130].rstrip('.')}." if first else "."))


# What he can ASK FOR, in his words. Keyed by intercom kind, because a
# kind is exactly a thing he can say — the registry's `core.*`,
# `policy.*` and `journal.*` are machinery he can neither reach nor care
# about, and two thirds of "104 things are live" was that.
#
# Hand-kept, the same reasoning `test_every_writer_has_a_reader` gives:
# a mechanical grouping would have to guess, and a wrong guess reads
# fluently while being wrong. A test asserts every kind is either here or
# deliberately marked internal, so a new verb cannot go unmentioned.
# How many groups she names out loud. A list of everything is a list of
# nothing: he stops listening at the fourth item.
SPOKEN_GROUPS = 6

_HE_CAN_ASK_FOR = {
    "your tasks and reminders": ("task_new", "tasks", "task_done",
                                 "task_status", "remind_at", "remind_daily",
                                 "remind_weekly", "reminders", "reminder_off",
                                 "do_task"),
    "your lists": ("shopping_add", "shopping_list", "shopping_off"),
    # Third on purpose: dict order is spoken order, only the first six
    # are said, and "can you make me a spreadsheet" is a question he
    # actually asked. A capability nobody hears about is one he will
    # never use.
    "making Word, Excel and PowerPoint files": ("doc_make",),
    "email": ("email_check", "email_read", "email_draft"),
    "texting people": ("message_send",),
    "your calendar and the weather": ("free_time", "meet"),
    "people you know": ("contacts", "contact_add", "watch_email_from",
                        "watches"),
    "remembering things": ("remember", "recall", "note"),
    "music": ("music",),
    "your files": ("file_list", "file_read", "file_write", "file_edit",
                   "file_move", "file_delete", "compose"),
    "looking things up on the web": ("browse_read", "browse_shot", "research",
                                     "web_task", "web_task_answer",
                                     "web_task_retry"),
    "driving your computer": ("computer_do", "computer_observe", "screen_ask",
                              "screenshot"),
    "your projects and repos": ("projects", "plan_new", "plan_add_step",
                                "plan_step", "plan_set", "issue", "dispatch"),
    "job applications": ("jobs", "apply_prepare", "apply_campaign",
                         "applications"),
    "money you spend": ("money", "subscriptions", "subscription_cancel"),
    "your car and journeys": ("car", "travel_time"),
    "media files": ("media_probe", "media_trim", "media_join", "media_audio",
                    "media_captions", "media_convert"),
    "putting workers on something": ("agents", "agent_new", "agent_stop",
                                         "agents_pause"),
}

# Reachable, but not things a person asks FOR: switches, plumbing and the
# machinery of asking. Named so the test can tell "deliberately unlisted"
# from "somebody added a verb and forgot".
_NOT_A_THING_HE_ASKS_FOR = frozenset({
    "halt", "resume", "close", "open", "approve", "deny", "intent", "handle",
    "running", "brief", "setup_status", "notify_check", "notify_clear",
    "notify_snooze", "notify_operator", "announce_set", "rule",
    "authority_status", "mic", "mic_on", "mic_off",
    # Switches over her own workings, like the microphone: he turns
    # them on and off, he does not ask her to DO them.
    "chatgpt", "chatgpt_on", "chatgpt_off",
    # And looking at the actual picture of his screen. Asking about the
    # screen is `screen_ask`, which is listed; these three are the switch
    # behind it, which he flips rather than asks for.
    "eyes", "eyes_on", "eyes_off",
})


def _capabilities() -> str | None:
    """The things he can ask for, named — not counted.

    "104 things are live, 17 experimental..." was every number true and
    nobody's question. This says what they ARE, from the grammar, and
    only mentions what is live: a capability waiting on setup is not
    something he can ask for today.
    """
    from aletheia import capabilities, intercom, speech
    try:
        reg = capabilities.load_registry()
    except Exception:
        return None                 # unreadable registry — let the planner try
    live_ids = {c["id"] for c in reg.get("capabilities", [])
                if c.get("status") == "AVAILABLE"}
    if not live_ids:
        return None

    # A group is worth naming when the grammar can still reach it.
    named = [name for name, kinds in _HE_CAN_ASK_FOR.items()
             if any(k in intercom.KIND_ARGS for k in kinds)]
    if not named:
        return None
    # SIX, NOT SIXTEEN. Read out loud, a list of everything is a list of
    # nothing — he stops listening at the fourth item and has learned
    # less than from three. The dict is in the order a person meets them.
    head, rest = named[:SPOKEN_GROUPS], named[SPOKEN_GROUPS:]
    said = "I can help with " + speech.and_list(head)
    if rest:
        said += f", and {len(rest)} other kinds of thing"
    return said + ". Ask me for anything and I'll tell you straight if I can't."


def _how_many() -> str | None:
    """The counts, for the question the old answer was really answering."""
    from aletheia import self_knowledge, speech
    by = dict((self_knowledge.overview() or {}).get("by_status") or {})
    live = int(by.get("AVAILABLE") or 0)
    if not live:
        return None
    parts = [f"{live} things are live"]
    for key, label in (("EXPERIMENTAL", "experimental"),
                       ("NEEDS_CONFIGURATION", "waiting on setup"),
                       ("NOT_BUILT", "not built yet")):
        count = int(by.get(key) or 0)
        if count:
            parts.append(f"{count} {label}")
    return (speech.and_list(parts)
            + ". Ask about a specific one and I'll tell you straight.")


def _alerts() -> str | None:
    """The fleet's own red lights, from the pulse she already writes."""
    import json
    from aletheia import pulse, speech
    try:
        latest = json.loads((pulse.PULSE_DIR / "latest.json")
                            .read_text(encoding="utf-8"))
    except Exception:
        return None                 # no pulse written yet is not "all green"
    alerts = [a for a in (latest.get("alerts") or []) if isinstance(a, dict)]
    if not alerts:
        return "Nothing red. The fleet is green."
    named = []
    for row in alerts[:3]:
        repo = str(row.get("repo") or row.get("github") or "something")
        failing = [str(f) for f in (row.get("failing") or [])]
        named.append(repo + (f" ({', '.join(failing[:2])})" if failing else ""))
    if len(alerts) > 3:
        named.append(f"{len(alerts) - 3} more")
    return (f"{speech.count_phrase(len(alerts), 'repo')} red: "
            + speech.and_list(named) + ".")


def _repos() -> str | None:
    """How many repos the pulse actually covers — counted, not recalled."""
    import json
    from aletheia import pulse, speech
    try:
        latest = json.loads((pulse.PULSE_DIR / "latest.json")
                            .read_text(encoding="utf-8"))
    except Exception:
        return None
    repos = latest.get("repos")
    names = sorted(repos) if isinstance(repos, dict) else list(repos or [])
    if not names:
        return None                 # an empty pulse is not "zero repos"
    shown = [str(n) for n in names[:4]]
    if len(names) > 4:
        shown.append(f"{len(names) - 4} more")
    return (f"{speech.count_phrase(len(names), 'repo')}: "
            + speech.and_list(shown) + ".")


def _shopping() -> str | None:
    """The same sentence the `shopping_list` command gives, written once."""
    from aletheia import intercom
    return intercom.shopping_answer()


def _free(when: str = "") -> str | None:
    """Whether he is free, from the same code the `free_time` kind uses."""
    import datetime as dt
    from aletheia import intercom, localtime
    day = dt.datetime.now(localtime.operator_tz()).date()
    if str(when or "").strip().casefold() == "tomorrow":
        day += dt.timedelta(days=1)
    try:
        return intercom.free_time_answer({"kind": "free_time",
                                          "day": day.isoformat()})
    except Exception:
        return None             # no feed, or it could not be read


def _version() -> str | None:
    """Which code she is running, and whether the tree has moved past it."""
    from aletheia import running
    try:
        return running.version_words(running.version())
    except Exception:
        return None


def _uptime() -> str | None:
    """How long she has been on, from her own heartbeat."""
    from aletheia import liveness
    seconds = liveness.uptime_seconds()
    if seconds is None:
        return None                 # she does not know; do not invent one
    return f"Up {liveness.spoken_duration(seconds)}."


# What he calls it -> what the profile calls it.
# More than one field can answer one question: he says "my name" and the
# store has a preferred name, a legal name and a first name, any of which
# is a true answer. First one she has, in the order a person would say it.
_MINE = {"email": ("email",), "email address": ("email",),
         "phone": ("phone",), "phone number": ("phone",),
         "number": ("phone",),
         "city": ("city",), "town": ("city",),
         "name": ("preferred_name", "first_name", "legal_name"),
         "first name": ("first_name", "preferred_name"),
         "last name": ("last_name",),
         "full name": ("legal_name", "full_name")}

# "Who am I" has no captured word to look up, so it names its own.
_WHO_AM_I = "name"


def _running() -> str | None:
    """Which parts are up, out of her own process list.

    `include_tasks=False`: the scheduled-task query is the slow half
    (0.6 s against ~20 ms for the rest) and the headline never uses it.
    The full picture, logon tasks included, is `python -m aletheia.running`.
    """
    from aletheia import running
    try:
        return running.headline(running.snapshot(include_tasks=False))
    except Exception:
        return None             # she does not know; the planner may look


def _mine(what: str) -> str | None:
    """One fact about him, from his profile. Never guessed: an invented
    phone number is the exact failure `profile` exists to prevent.

    `profile.answer` reads her memory of him as well as the profile
    itself, so a fact she holds in one store is not denied from the
    other — which is how "where do I live" answered "I don't have your
    city on file" while "Hartford, SD 57033" sat on the same disk.
    """
    from aletheia import profile
    asked = " ".join(str(what or "").split()).casefold() or _WHO_AM_I
    fields = _MINE.get(asked)
    if not fields:
        return None
    try:
        for field in fields:
            value = profile.answer(field)
            if value:
                return str(value)
    except Exception:
        return None
    return (f"I don't have your {asked} on file. "
            "Tell me and I'll remember it.")


def _home() -> str | None:
    """Where he lives — the city AND the state, which is how it is said.

    `_mine("city")` alone answers "Hartford", and the store holds the
    state next to it.
    """
    from aletheia import profile
    try:
        city, state = profile.answer("city"), profile.answer("state")
    except Exception:
        return None
    if not city:
        return ("I don't have your city on file. "
                "Tell me and I'll remember it.")
    # Bare, no full stop: `_mine` returns the value and not a sentence,
    # and "Hartford, SD" already reads as an answer.
    return f"{city}, {state}" if state else str(city)


def _weather(when: str = "") -> str | None:
    """What it is doing outside, from the free national service.

    No key anywhere, and his postcode is already on file — so the most
    ordinary question anybody asks needs nothing from him and no model.
    """
    try:
        from aletheia import weather
        return weather.spoken(when)
    except Exception:
        return None                 # she does not know; the planner may try


def _greeting() -> str | None:
    """Greeted back, plus the one thing he would have asked next.

    Everything here comes from `presence` and the kill switch: whether
    she is running, and what is waiting on him. A greeting is the moment
    that is most worth saying, and it was costing a planner round trip to
    say nothing.
    """
    from aletheia import policy
    try:
        halt = policy.halted()
        if halt:
            reason = str(halt.get("reason") or "").strip()
            return ("I'm here, but halted"
                    + (f" — {reason}." if reason else ".")
                    + " Nothing runs until you resume me.")
        from aletheia import presence, speech
        now = presence.snapshot()
        waiting = len(list(now.get("waiting_on_you") or []))
        notices = len(list(now.get("notifications") or []))
        if not waiting and not notices:
            return "I'm here. Nothing is waiting on you."
        bits = []
        if waiting:
            bits.append(f"{waiting} waiting on you")
        if notices:
            bits.append(f"{notices} I wanted to tell you about")
        # The list itself is one sentence away, and reading it out is what
        # "what's waiting on me" is for.
        return f"I'm here. {speech.and_list(bits)}."
    except Exception:
        return None


ANSWERS = {"halted": lambda rest: _halted(asks_if_down=bool(rest)),
           "waiting": lambda rest: _waiting(),
           "doing": lambda rest: _doing(),
           "today": lambda rest: _today(),
           "yesterday": lambda rest: _yesterday(),
           "clock": lambda rest: _clock(),
           "date": lambda rest: _date(),
           "month": lambda rest: _month(),
           "year": lambda rest: _year(),
           "can_you": _can_you,
           "tasks": lambda rest: _tasks(),
           "approvals": lambda rest: _approvals(),
           "capabilities": lambda rest: _capabilities(),
           "how_many": lambda rest: _how_many(),
           "alerts": lambda rest: _alerts(),
           "repos": lambda rest: _repos(),
           "shopping": lambda rest: _shopping(),
           "uptime": lambda rest: _uptime(),
           "version": lambda rest: _version(),
           "free": _free,
           "running": lambda rest: _running(),
           "mine": _mine,
           "weather": lambda rest: _weather(rest),
           "greeting": lambda rest: _greeting(),
           "home": lambda rest: _home()}


# The sentences whose stores cost the most to reach the first time.
# Between them they pull `localtime` (and the tz database behind it),
# `speech`, `presence` and `self_knowledge` — which is nearly all of it.
_WARM = ("what time is it", "what are you doing", "what can you do",
         # psutil's first import is ~840ms of the ~860ms this costs
         # cold, and "is any of this on" is a very likely first ask.
         "what is running")


def warm() -> None:
    """Load what the fast lane needs BEFORE he asks for it.

    Measured on the operator's PC, 2026-09-07: the first `answer()` costs
    ~420 ms and every one after it under 1 ms. Almost none of that is
    work — it is lazy imports, and `zoneinfo` reading the timezone
    database is 160 ms on its own. That cost lands on whichever question
    he happens to ask first, which is precisely the moment this module
    exists to make fast.

    Every answer here is a read, so warming has no side effect: nothing is
    journaled, nothing is written, and a store that is empty or missing
    simply returns None. Never raises — a warm-up that can take down the
    Core would be worse than a slow first answer.
    """
    for sentence in _WARM:
        try:
            answer(sentence)
        except Exception:
            pass


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
