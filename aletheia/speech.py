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
ID_TOKEN = re.compile(r"\b([a-z][a-z0-9]*-[0-9a-f]{6,})\b")
# slugs used as task/plan ids: water-the-plants, light-up-the-wall-s2
SLUG_TOKEN = re.compile(r"\b([a-z0-9]+(?:-[a-z0-9]+){1,6})\b")
ISO_TIME = re.compile(
    r"\b(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::\d{2})?"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b")

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
            "Saturday", "Sunday")


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
        parsed = parsed.astimezone()
    now = now or dt.datetime.now(parsed.tzinfo) if parsed.tzinfo else (
        now or dt.datetime.now())
    if now.tzinfo is not None and parsed.tzinfo is None:
        now = now.replace(tzinfo=None)

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
    out = re.sub(r"\s*\(\s*\)", "", str(text or ""))
    # Only a single trailing mark. "Domain :: excerpt" is a separator,
    # not a comma, and squeezing it reads as a typo.
    out = re.sub(r"\s+([,.;!?])(?!\1)", r"\1", out)
    out = re.sub(r"([(\[])\s+", r"\1", out)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"(?:\s*[—–-]\s*)+$", "", out.strip())
    return out.strip(" ,;:")


def _times_to_words(text: str, now: dt.datetime | None = None) -> str:
    return ISO_TIME.sub(lambda m: humanize_time(m.group(0), now), text)


def _quoted(text: str) -> str:
    """Present his own words after a colon, so their capitals stay right.

    The obvious move is to lowercase the first letter for mid-sentence use
    — and it cannot be done safely, because "Call the dentist" and "Dana
    needs an answer" are the same shape and only one of them may be
    lowered. A colon sidesteps the guess entirely: whatever he said is
    reproduced exactly as he said it.
    """
    return str(text or "").strip().rstrip(".")


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
            return (f"Every day at {when.group(1)} I'll remind you: "
                    f"{_quoted(what.group(1))}.")
    if kind == "task_new":
        slug = re.search(r"task ([a-z0-9-]+) queued", text)
        if slug:
            return f"Added a task: {deslug(slug.group(1))}."
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
    if kind == "note":
        return "Noted."
    if kind == "notify_clear":
        cleared = re.search(r"cleared (\d+)", text)
        if cleared:
            count = int(cleared.group(1))
            return ("Nothing was waiting." if count == 0
                    else f"Cleared {count} notification{'s' if count != 1 else ''}.")
    return tidy(_times_to_words(strip_ids(text), now)) or text


def and_list(items: list[str]) -> str:
    """['a','b','c'] -> 'a, b and c'. Speech, not a bullet list."""
    items = [str(i).strip() for i in items if str(i).strip()]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def count_phrase(count: int, singular: str, plural: str | None = None) -> str:
    plural = plural or singular + "s"
    return f"{count} {singular if count == 1 else plural}"
