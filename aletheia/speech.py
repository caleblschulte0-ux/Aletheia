"""How she says things (Playbook §§144–148).

A receipt is not a sentence. Aletheia's spoken replies were the receipts
her own subsystems return, read out verbatim, so the room heard:

    "reminder remind-3f9ab2c1 set for 2026-09-04T09:00:00+00:00 — 'Call
     the dentist'"
    "task water-the-plants queued"
    "Approval mail-a1e1957d0f is pending; approving it sends the email."

Every one of those is accurate and none of them is speech. §145 is
explicit: never expose implementation details unless they are useful —
"Fix Shorts", not "give me the repo slug and workflow filename". A hex id
read aloud is the worst case of it, because he cannot act on a string he
cannot hold in his head, and the reply that follows tells him to say it
back.

So this module is one job: turn a receipt into the sentence a person
would have said. It is deliberately deterministic — no model, no latency,
no chance of inventing an outcome that did not happen. It only ever
rephrases what the receipt already says, and anything it does not
recognise passes through untouched rather than being mangled into
confident nonsense.

Two rules it holds:

**Never invent, only re-say.** If a receipt does not contain a fact, the
sentence does not either. `spoken_receipt` cannot make a reminder later
than it is or an email sent that is not.

**Identifiers are for machines.** Ids are dropped from speech, not
shortened — the operator approves by saying "approve", and the Command
Center is where things have names. The one exception is when an id is
genuinely the only handle he has, and then it is said as a short tail
("...ending 663") rather than the whole hash.
"""
from __future__ import annotations

import datetime as dt
import re

# state/private ids: mail-a1e1957d0f, intent-0a06bbb663, errand-…, remind-…
ID_TOKEN = re.compile(
    r"\b([a-z][a-z0-9]*-[0-9a-f]{6,})\b"
    # `browser.interact:193cc7235619…` — a content-bound approval names
    # itself with a sha256, and this only knew about the HYPHENATED shape,
    # so the wall's headline read "4 decisions waiting:
    # browser.interact:193cc723561941c0…". Found 2026-09-05 while making
    # the same sentence answerable without a model call.
    r"|\b([a-z][a-z0-9_.]*:[0-9a-f]{8,})\b"
    # and a bare digest on its own
    r"|\b([0-9a-f]{16,})\b")
# slugs used as task/plan ids: water-the-plants, light-up-the-wall-s2
SLUG_TOKEN = re.compile(r"\b([a-z0-9]+(?:-[a-z0-9]+){1,6})\b")
ISO_TIME = re.compile(
    r"\b(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::\d{2})?"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b")

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
            "Saturday", "Sunday")


def _operator_zone():
    """His timezone, or None to leave the instant where it is.

    Deliberately soft: this module is the last step before something is
    SPOKEN, and a missing tzdata entry must degrade to a slightly odd
    hour, never to an exception in the middle of a sentence.
    """
    try:
        from aletheia import localtime
        return localtime.operator_tz()
    except Exception:
        return None


def short_id(value: str) -> str:
    """The last few characters of an id, for when he truly needs one."""
    tail = str(value or "").rstrip()[-4:]
    return f"ending {tail}" if tail else ""


def humanize_time(stamp: str, now: dt.datetime | None = None) -> str:
    """An ISO timestamp as a person would say it.

    Relative where that is what a person means ("tomorrow at nine"),
    absolute where it is not. Timezone-aware input is rendered in local
    time, because "fifteen hundred UTC" is not an answer to "when?".
    """
    try:
        parsed = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return str(stamp)
    if parsed.tzinfo is not None:
        # HIS zone, not this process's. `astimezone()` with no argument
        # uses whatever the machine is set to, and the two are the same
        # only by luck. A reminder set for 03:00 America/Chicago was read
        # back as "tomorrow at 8 am" — correct arithmetic, useless
        # sentence, and it MASKED a separate bug that saying the real time
        # would have exposed in one syllable. The confirmation exists so
        # he can catch a mistake; rendered in the wrong zone it cannot do
        # that job.
        parsed = parsed.astimezone(_operator_zone() or None)
    now = now or dt.datetime.now(parsed.tzinfo) if parsed.tzinfo else (
        now or dt.datetime.now())
    if now.tzinfo is not None and parsed.tzinfo is None:
        now = now.replace(tzinfo=None)
    if parsed.tzinfo is not None and now.tzinfo is not None:
        # "today"/"tomorrow" is a comparison of CALENDAR DAYS, and two
        # dates in different zones are not comparable.
        now = now.astimezone(parsed.tzinfo)

    clock = parsed.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ")
    clock = clock.replace(" AM", " am").replace(" PM", " pm")
    days = (parsed.date() - now.date()).days
    if days == 0:
        return f"today at {clock}"
    if days == 1:
        return f"tomorrow at {clock}"
    if 2 <= days <= 6:
        return f"{WEEKDAYS[parsed.weekday()]} at {clock}"
    if days == -1:
        return f"yesterday at {clock}"
    return f"{parsed.strftime('%d %B').lstrip('0')} at {clock}"


def deslug(value: str) -> str:
    """'water-the-plants' -> 'water the plants'."""
    return str(value or "").replace("-", " ").strip()


def strip_ids(text: str) -> str:
    """Remove machine identifiers from something about to be spoken."""
    return ID_TOKEN.sub("", str(text or ""))


def tidy(text: str) -> str:
    """Collapse the punctuation left behind by removing things."""
    # Parens left holding nothing but the punctuation that separated the
    # ids that were just removed: "(intent-1b32, intent-a3d2)" -> "(, )".
    out = re.sub(r"\s*\([\s,;:.&/·—–-]*\)", "", str(text or ""))
    # Only a single trailing mark. "Domain :: excerpt" is a separator,
    # not a comma, and squeezing it reads as a typo.
    out = re.sub(r"\s+([,.;!?])(?!\1)", r"\1", out)
    # An id removed from between two commas leaves ",,": "there's a
    # pending approval,, but I can't tell if that's what you mean". Not
    # full stops — "..." is a real thing a person writes.
    out = re.sub(r"([,;])\s*(?:\1\s*)+", r"\1 ", out)
    out = re.sub(r"([(\[])\s+", r"\1", out)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"(?:\s*[—–-]\s*)+$", "", out.strip())
    return out.strip(" ,;:")


# ----------------------------------------------------------------- markdown
# A model writes for a screen unless something stops it. "What I *can* do
# right now is look at your desktop live (computer.observe/control)" was a
# real answer, spoken in a room: an asterisk pair read as nothing at all,
# and an identifier with a slash in it read as gibberish. Both are §145 —
# implementation details never reach speech unless they are useful to him.
MD_FENCE = re.compile(r"```[a-zA-Z0-9_+-]*\n?")
MD_LINK = re.compile(r"\[([^\]\n]+)\]\([^)\s]+\)")
MD_BOLD = re.compile(r"(?<!\w)\*\*(\S(?:[^*]*?\S)?)\*\*(?!\w)")
MD_EM = re.compile(r"(?<!\w)\*(\S(?:[^*\n]*?\S)?)\*(?!\w)")
MD_CODE = re.compile(r"`([^`\n]+)`")
MD_HEADING = re.compile(r"(?m)^\s{0,3}#{1,6}\s+")
MD_BULLET = re.compile(r"(?m)^\s{0,3}[-*+]\s+")


def unmarkdown(text: str) -> str:
    """Markdown emphasis is invisible out loud, so remove the marks.

    Deliberately does NOT touch underscores: `_this_` is emphasis and
    `file_path` is a name, and getting that wrong renames things he asked
    about. A bullet becomes nothing rather than a dash, because a hyphen
    at the start of a line is either silence or the word "minus".
    """
    out = MD_FENCE.sub("", str(text or ""))
    out = MD_LINK.sub(r"\1", out)
    out = MD_BOLD.sub(r"\1", out)
    out = MD_EM.sub(r"\1", out)
    out = MD_CODE.sub(r"\1", out)
    out = MD_HEADING.sub("", out)
    return MD_BULLET.sub("", out)


# `computer.observe/control`, `room.scene`, `email.send` — a capability id
# is a correct, unsayable name for a thing the registry already describes
# in English. Only ids the registry really knows are replaced; anything
# else (example.com, converse.py) is left exactly as written.
CAP_ID = re.compile(
    r"\b([a-z][a-z0-9_]{2,}\.[a-z][a-z0-9_]{2,}(?:/[a-z][a-z0-9_]{2,})?)\b")


def _capability_english(name: str) -> str:
    from aletheia import capabilities
    entry = capabilities.get(name)
    said = str((entry or {}).get("description") or "").strip()
    if not said:
        return ""
    # The registry writes "a sentence: the qualification" and "a sentence
    # - the qualification"; only the first half is the answer. The colon
    # has no space in front of it, which an earlier version of this split
    # required — so "operate the Windows PC: observe, open apps, click,
    # type" came out whole, inside a parenthesis, out loud.
    first = re.split(r"\s+[-—(]\s*|\s*:\s+|\.\s", said)[0].strip(" .")
    return (first[0].lower() + first[1:]) if first else ""


def say_capabilities(text: str) -> str:
    """Capability ids -> what the registry says they are.

    "(computer.observe/control)" becomes "(look at the desktop or operate
    the Windows PC)". The slash form is the model's own shorthand for two
    ids sharing a prefix, so it is expanded rather than mangled.
    """
    def one(match: re.Match) -> str:
        token = match.group(1)
        head, _, tail = token.partition("/")
        try:
            said = _capability_english(head)
            if tail:
                sibling = _capability_english(head.split(".")[0] + "." + tail)
                if said and sibling:
                    return f"{said} or {sibling}"
                if not said:
                    return token
            return said or token
        except Exception:
            return token
    try:
        return CAP_ID.sub(one, str(text or ""))
    except Exception:
        return str(text or "")


#: A line that ends like this already tells the voice to stop.
_ENDS_A_SENTENCE = ".!?:;,"


def sentences_not_lines(text: str) -> str:
    """Turn a written-down list into something sayable.

    A newline is punctuation on a page and nothing at all in a room. Four
    capabilities on four lines came out as one breath, ending
    "...never act on its own And 17 more are experimental" - no pause, no
    full stop, two sentences run together.

    Each line becomes its own sentence. Not `and_list`: four items in one
    comma-spliced breath is worse, and seventeen would be unlistenable.
    """
    lines = [line.strip() for line in str(text or "").splitlines()]
    kept = [line for line in lines if line]
    if len(kept) < 2:
        return " ".join(kept)
    finished = []
    for line in kept:
        if line[-1] not in _ENDS_A_SENTENCE:
            line += "."
        finished.append(line)
    return " ".join(finished)


def spoken_prose(text: str) -> str:
    """Model prose, made safe to read out: no markup, no identifiers.

    Everything she says that a model wrote goes through here. The pieces
    existed separately and each caller picked its own subset, which is how
    "What I *can* do right now is (computer.observe/control)" reached a
    room that had already had ids stripped from every other sentence.

    Line breaks are handled here for the same reason markdown is: they
    are page formatting, and this door exists because everything through
    it is going to be read out.
    """
    return tidy(strip_ids(say_capabilities(
        sentences_not_lines(unmarkdown(text)))))


def _times_to_words(text: str, now: dt.datetime | None = None) -> str:
    return ISO_TIME.sub(lambda m: humanize_time(m.group(0), now), text)


#: His first person, said back to him. Whole words only: "my" -> "your",
#: never "myopic" -> "yourpic". "our" is left alone deliberately - "our
#: repos" means both of them and "your repos" would be a small lie.
_HIS_PRONOUNS = (
    (r"\bmy\b", "your"), (r"\bmine\b", "yours"),
    (r"\bmyself\b", "yourself"), (r"\bI\b", "you"),
    (r"\bi\b", "you"), (r"\bme\b", "you"),
)


def as_she_says_it(phrase: str) -> str:
    """Turn HIS phrase into one SHE can say about him.

    "my resume" -> "your resume". Used where she describes back what he
    asked for; not for reproducing his exact words, which `_quoted`
    handles and which must stay literal.
    """
    said = str(phrase or "")
    for pattern, replacement in _HIS_PRONOUNS:
        said = re.sub(pattern, replacement, said)
    return said


#: Words that should not start a file name: they describe whose it is,
#: not what it is. "my resume" is `resume.docx`.
_LEADING_FILLER = re.compile(
    r"^(?:my|your|our|the|a|an|this|that|some)\s+", re.IGNORECASE)


def file_stem(topic: str, limit: int = 40) -> str:
    """A file name from a spoken topic. "my resume" -> "resume"."""
    said = str(topic or "").strip()
    while True:
        shorter = _LEADING_FILLER.sub("", said)
        if shorter == said:
            break
        said = shorter
    return re.sub(r"[^a-z0-9]+", "-", said.lower()).strip("-")[:limit]


#: How he points at one item in a list she just read out. Lives here
#: because `voice` resolves approvals with it and `intercom` resolves
#: tasks with it, and two copies of a table like this drift.
ORDINALS = {"first": 0, "second": 1, "third": 2, "fourth": 3, "last": -1}

#: Words around an ordinal that carry no meaning of their own, so
#: "the first one" is the same reference as "first".
_ORDINAL_FILLER = re.compile(r"^(?:the\s+)?(?P<word>\w+)(?:\s+one)?$",
                             re.IGNORECASE)


def ordinal_index(phrase: str):
    """`"the first one"` -> 0. None when he is not counting.

    Only a phrase that is essentially JUST an ordinal resolves. "The
    first bank one" describes a task rather than counting to it, and
    belongs to whatever matches on words.
    """
    m = _ORDINAL_FILLER.match(" ".join(str(phrase or "").split()))
    if not m:
        return None
    return ORDINALS.get(m.group("word").casefold())


def _quoted(text: str) -> str:
    """Present his own words after a colon, so their capitals stay right.

    The obvious move is to lowercase the first letter for mid-sentence use
    — and it cannot be done safely, because "Call the dentist" and "Dana
    needs an answer" are the same shape and only one of them may be
    lowered. A colon sidesteps the guess entirely: whatever he said is
    reproduced exactly as he said it.
    """
    return str(text or "").strip().rstrip(".")


def clock_words(hhmm: str) -> str:
    """"09:00" -> "9 am". A 24-hour clock is a display, not a sentence."""
    try:
        hour, minute = (int(part) for part in str(hhmm).split(":", 1))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return str(hhmm)
    except (TypeError, ValueError):
        return str(hhmm)
    suffix = "am" if hour < 12 else "pm"
    twelve = hour % 12 or 12
    return f"{twelve} {suffix}" if minute == 0 else f"{twelve}:{minute:02d} {suffix}"


def spoken_receipt(kind: str, detail: str, *,
                   now: dt.datetime | None = None) -> str:
    """One subsystem receipt, as a sentence.

    Unrecognised kinds fall through to a generic tidy: ids removed,
    timestamps humanised, punctuation repaired. That is always an
    improvement and never a fabrication.
    """
    text = str(detail or "").strip()
    if kind == "remind_at":
        when = ISO_TIME.search(text)
        what = re.search(r"[—-]\s*'(.+?)'\s*$", text) or re.search(r"'(.+?)'", text)
        if when and what:
            return (f"I'll remind you {humanize_time(when.group(0), now)}: "
                    f"{_quoted(what.group(1))}.")
    if kind == "remind_daily":
        when = re.search(r"\b(\d{1,2}:\d{2})\b", text)
        what = re.search(r"[—-]\s*'(.+?)'\s*$", text) or re.search(r"'(.+?)'", text)
        if when and what:
            return (f"Every day at {clock_words(when.group(1))} I'll remind "
                    f"you: {_quoted(what.group(1))}.")
    if kind == "remind_weekly":
        # "weekly reminder remind-weekly-9f2 set for Monday at 09:00 —
        # 'take out the trash'"
        when = re.search(r"set for (.+?) at (\d{1,2}:\d{2})\b", text)
        what = re.search(r"[—-]\s*'(.+?)'\s*$", text) or re.search(r"'(.+?)'", text)
        if when and what:
            days = when.group(1)
            lead = days if days in ("weekdays", "weekends", "every day") else f"every {days}"
            return (f"{lead[0].upper()}{lead[1:]} at "
                    f"{clock_words(when.group(2))} I'll remind you: "
                    f"{_quoted(what.group(1))}.")
    if kind == "notify_snooze":
        # "snoozed snooze-9f2 until 2026-09-07T21:00:00+00:00 — 'the boiler'"
        when = ISO_TIME.search(text)
        what = re.search(r"[—-]\s*'(.+?)'\s*$", text) or re.search(r"'(.+?)'", text)
        if when and what:
            return (f"Put away until {humanize_time(when.group(0), now)}: "
                    f"{_quoted(what.group(1))}.")
    if kind == "reminder_off":
        # "reminder remind-weekly-9f2 off — take out the trash — every
        # Monday at 9 am"
        body = re.search(r"off\s*[—-]\s*(.+)$", text)
        if body:
            return f"Stopped reminding you: {_quoted(body.group(1))}."
    if kind == "shopping_off":
        body = re.search(r"off\s*[—-]\s*(.+)$", text)
        if body:
            return f"Took it off your shopping list: {_quoted(body.group(1))}."
    if kind == "task_new":
        # "task renew-my-passport queued — renew my passport due Friday"
        named = re.search(r"task [a-z0-9-]+ queued\s*[—-]\s*(.+)", text)
        if named:
            return f"Added a task: {named.group(1).strip()}."
        slug = re.search(r"task ([a-z0-9-]+) queued", text)
        if slug:
            return f"Added a task: {deslug(slug.group(1))}."
        # The journal writes it differently from the receipt: "created —
        # call the plumber". Same event, and it is the one `recollection`
        # reads back when he asks what she did.
        made = re.match(r"created\s*[—-]\s*(.+)", text)
        if made:
            return f"Added a task: {made.group(1).strip()}."
    if kind == "remember":
        # 'set people.landlord = "Mr Okafor" (explicit)'
        noted = re.match(r"set\s+\S*?([\w-]+)\s*=\s*\"?(.+?)\"?\s*(?:\(.*\))?$",
                         text)
        if noted:
            return (f"Noted: {deslug(noted.group(1))} is "
                    f"{noted.group(2).strip()}.")
    if kind == "task_done":
        marked = re.match(r"marked done\s*[—-]\s*(.+)", text)
        if marked:
            return f"Done: {marked.group(1).strip()}."
    if kind == "task_status":
        moved = re.search(r"task ([a-z0-9-]+) -> ([A-Z_]+)", text)
        if moved:
            return (f"{deslug(moved.group(1)).capitalize()} is now "
                    f"{moved.group(2).replace('_', ' ').lower()}.")
    if kind == "email_draft":
        who = re.search(r"draft to ([^—]+?) ready", text)
        subject = re.search(r"'(.+?)'", text)
        if who:
            said = f"I've drafted it to {who.group(1).strip()}"
            if subject:
                said += f", subject {subject.group(1)}"
            return said + ". Say approve and it goes."
    if kind in ("approve", "deny"):
        decided = re.match(r"(approved|denied)\s*[—-]\s*(.+)", text)
        if decided:
            return f"{decided.group(1).capitalize()}: {decided.group(2).strip()}."
    if kind == "note":
        return "Noted."
    if kind == "notify_clear":
        cleared = re.search(r"cleared (\d+)", text)
        if cleared:
            count = int(cleared.group(1))
            return ("Nothing was waiting." if count == 0
                    else f"Cleared {count} notification{'s' if count != 1 else ''}.")
    return tidy(_times_to_words(strip_ids(text), now)) or text


# One CamelCase word, no spaces, then a colon: the shape of an exception
# class, whatever it is called. `KeyError`, `WorkspaceError`,
# `ReasonerUnavailable`, a bare `Refused` — all of them reached the room.
_CLASS_PREFIX = re.compile(r"^[A-Z][A-Za-z0-9_]{2,}:\s+")


def plainly(detail: str) -> str:
    """A failure as a reason rather than a traceback.

    The messages underneath are usually good — "resume is not a file", "no
    place matches 'the airport'" — and were simply arriving with a class
    name bolted to the front. Only the class is dropped, and only when
    what is left can stand without it: a bare KeyError says nothing but
    the key, and "I couldn't: 'generated_at'" is worse than the traceback.

    One implementation, because `intents.spoken` and `voice.spoken_reply`
    both say these out loud and had drifted into stripping differently.
    """
    text = " ".join(unmarkdown(str(detail or "")).split())
    stripped = _CLASS_PREFIX.sub("", text)
    if stripped != text and len(stripped.split()) < 2:
        stripped = text
    return tidy(strip_ids(stripped))


def shorten(text: str, limit: int = 70) -> str:
    """Cut to `limit` characters at a WORD boundary, never mid-word.

    "I don't have" truncated to "I don't ha" is noise where a fact
    should be, and read out loud it sounds like she broke off. Anything
    that has to be cut for speech comes through here.
    """
    words = " ".join(str(text or "").split())
    if len(words) <= limit:
        return words
    cut = words[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    # A single word longer than the limit has no boundary to cut at;
    # better a slightly long word than a mangled one.
    return cut or words.split(" ")[0]


# A title that names a CATEGORY tells him nothing: every reminder is
# titled "Reminder", and the thing he wants is the body.
#: One list. `presence` kept a second one that had already drifted - it
#: had "update" and "aletheia", this had "aletheia finished thinking",
#: and neither had the other's - so the wall and the room disagreed about
#: which titles were worth reading out.
CATEGORY_TITLES = frozenset({"reminder", "reminders", "notification",
                             "notifications", "notice", "alert", "alerts",
                             "update", "aletheia",
                             "aletheia finished thinking"})

#: Kept for the callers that already spell it privately.
_CATEGORY_TITLES = CATEGORY_TITLES


def notice_line(notice: dict, limit: int = 70) -> str:
    """One notification, in a phrase that can be said in one breath.

    Prefers the title, because a body is a paragraph — unless the title
    is a category, which names the kind and not the thing.
    """
    title = " ".join(str(notice.get("title") or "").split())
    body = " ".join(str(notice.get("says") or notice.get("body") or "").split())
    if title and title.casefold() not in _CATEGORY_TITLES:
        return shorten(title, limit)
    return shorten(body or title, limit)


def and_list(items: list[str]) -> str:
    """['a','b','c'] -> 'a, b and c'. Speech, not a bullet list."""
    items = [str(i).strip() for i in items if str(i).strip()]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def or_list(items: list[str]) -> str:
    """['a','b','c'] -> 'a, b or c'. For a CHOICE, where "and" is wrong.

    "Which one — call the dentist and call the plumber?" reads as one
    thing made of two; the question is asking him to pick.
    """
    items = [str(i).strip() for i in items if str(i).strip()]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " or " + items[-1]


def count_phrase(count: int, singular: str, plural: str | None = None) -> str:
    """"3 boards", "1 match", "2 matches".

    The default used to be `singular + "s"`, so a caller who did not think
    about it got "3 matchs" — which is how "3002 match(es)" ended up in a
    journal line she then read out loud, half of the same sentence having
    been written through this function. An explicit plural still wins;
    this only stops the naive default from being wrong.
    """
    if plural is None:
        word = singular.rsplit(" ", 1)[-1]
        head = singular[:len(singular) - len(word)]
        if word.endswith(("s", "x", "z", "ch", "sh")):
            word += "es"
        elif len(word) > 1 and word.endswith("y") and word[-2] not in "aeiou":
            word = word[:-1] + "ies"
        else:
            word += "s"
        plural = head + word
    return f"{count} {singular if count == 1 else plural}"


# ---------------------------------------------------------------- acknowledging
# A person who is thinking says so. Aletheia did not: an ordinary ask went
# quiet for the whole round trip — measured 2026-09-05 at ~3.6s minimum for
# a `claude -p` call, and much longer for anything with real steps in it —
# and silence from something that is supposed to be listening is
# indistinguishable from silence from something that is broken. He said it
# exactly: "even if it's just telling me that you have to think a little
# harder."
#
# `quick` removed the wait for the sentences she can answer from a file.
# This is the other half: for everything else, say something true while she
# works. Both lines are true no matter how the request ends — she IS
# looking, she IS working on it — which matters, because the answer that
# follows may well be "that needs your approval" or "I can't".
LOOKING_UP = re.compile(
    r"^(?:what|who|when|where|why|how|which|is|are|was|were|do|does|did|"
    r"can|could|should|will|would|have|has|any|tell me|show me|remind me "
    r"what)\b")
ACK_QUESTION = "Let me look."
ACK_ACTION = "Working on it."
ACK_STILL = "Still on it — I'll tell you when it's done."


def ack_line(command: str) -> str:
    """What to say while she thinks. Deterministic, no model, no latency."""
    text = " ".join(str(command or "").split()).casefold()
    if not text:
        return ACK_ACTION
    return ACK_QUESTION if LOOKING_UP.match(text) else ACK_ACTION
