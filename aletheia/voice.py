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

from aletheia import policy, tasks

WAKE_WORDS = ("thea", "theia", "tia", "althea", "aletheia")


def strip_wake_word(text: str) -> str:
    t = text.strip()
    for w in WAKE_WORDS:
        if t.lower().startswith(w):
            rest = t[len(w):].lstrip(" ,.!?:;")
            return rest
    return t


def _spoken_url(tail: str) -> str | None:
    """'example dot com' -> https://example.com; 'github.com' passes through."""
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
    return "https://" + t


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


def _spoken_day(text: str) -> str | None:
    """'today' / 'tomorrow' / '2026-08-27' -> ISO date, else None."""
    import datetime as dt
    t = text.strip().lower().rstrip(".?!")
    today = dt.date.today()
    if t in ("today", ""):
        return today.isoformat()
    if t == "tomorrow":
        return (today + dt.timedelta(days=1)).isoformat()
    try:
        return dt.date.fromisoformat(t).isoformat()
    except ValueError:
        return None


def _next_occurrence_iso(hhmm: str) -> str:
    """The next future moment today/tomorrow at HH:MM, operator-local."""
    import datetime as dt
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/Chicago")
    now = dt.datetime.now(tz)
    hour, minute = map(int, hhmm.split(":"))
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += dt.timedelta(days=1)
    return candidate.isoformat()


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


def interpret(transcript: str) -> dict:
    """One spoken sentence -> a command to gate-check, or words to say."""
    text = strip_wake_word(transcript)
    low = text.lower().strip().rstrip(".?!")
    if not low:
        return {"command": None, "say": "I'm listening."}

    if re.fullmatch(r"(halt|stop|stop everything|kill switch|emergency stop|"
                    r"halt everything|shut it down)", low):
        return {"command": {"kind": "halt", "reason": f"by voice: {transcript!r}"},
                "say": None}
    if re.fullmatch(r"(resume|start again|back on|carry on|un-?halt)", low):
        return {"command": {"kind": "resume"}, "say": None}

    # Apostrophes optional: speech-to-text drops them far more often than it
    # keeps them, and "whats going on" was falling past the instant local
    # answer into the planner — twenty seconds for a question worth 50ms.
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
            at = _next_occurrence_iso(hhmm)
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

    # notifications
    if re.fullmatch(r"(?:check (?:my )?notifications?|any notifications?|"
                    r"what's new|anything new|notifications?)", low):
        return {"command": {"kind": "notify_check"}, "say": None}
    if re.fullmatch(r"(?:clear|dismiss|acknowledge) (?:my |the )?notifications?", low):
        return {"command": {"kind": "notify_clear"}, "say": None}

    # free time
    m = re.fullmatch(r"(?:when am i free|what's my availability|any free time)"
                     r"(?:\s+(?:on\s+)?(.+))?", low)
    if m:
        day = _spoken_day(m.group(1) or "today")
        if day:
            return {"command": {"kind": "free_time", "day": day}, "say": None}
        return {"command": None,
                "say": f"I couldn't parse the day {m.group(1)!r} — say today, tomorrow, or a date."}

    # private contact: "remember person bob smith bob at gmail dot com"
    m = re.match(r"remember (?:person|contact)\s+(.+?)\s+((?:\S+\s+at\s+\S.*|\S+@\S+))$", low)
    if m:
        return {"command": {"kind": "contact_add", "name": m.group(1).strip(),
                            "email": m.group(2).strip()}, "say": None}

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

    m = re.match(r"(?:read|open|check|look at|go to|browse)\s+(.+)", low)
    if m:
        url = _spoken_url(m.group(1))
        if url:
            return {"command": {"kind": "browse_read", "url": url}, "say": None}
        return {"command": None,
                "say": f"I need a web address to read — I heard {m.group(1)!r}."}

    m = re.match(r"screenshot\s+(.+)", low)
    if m and _spoken_url(m.group(1)):
        return {"command": {"kind": "browse_shot", "url": _spoken_url(m.group(1))},
                "say": None}

    m = re.match(r"(?:approve|approved|yes to)(?:\s+(?:that|it|the pending one))?$", low)
    if m:
        pending = [a for a in policy.all_approvals() if a["state"] == "PENDING"]
        if len(pending) == 1:
            return {"command": {"kind": "approve", "id": pending[0]["id"]}, "say": None}
        if not pending:
            return {"command": None, "say": "Nothing is waiting for approval."}
        return {"command": None,
                "say": f"{len(pending)} approvals are pending — I won't guess "
                       "which one. Use the Command Center to pick."}
    m = re.match(r"(?:deny|denied|no to)(?:\s+(?:that|it|the pending one))?$", low)
    if m:
        pending = [a for a in policy.all_approvals() if a["state"] == "PENDING"]
        if len(pending) == 1:
            return {"command": {"kind": "deny", "id": pending[0]["id"],
                                "because": "denied by voice"}, "say": None}
        if not pending:
            return {"command": None, "say": "Nothing is waiting for approval."}
        return {"command": None,
                "say": f"{len(pending)} approvals are pending — I won't guess. "
                       "Use the Command Center to pick."}

    m = re.match(r"(?:add a task|new task|task)\s*(?:to|:)?\s+(.+)", low)
    if m:
        desc = m.group(1).strip()
        slug = re.sub(r"[^a-z0-9]+", "-", desc.lower()).strip("-")[:40] or "voice-task"
        if any(t["id"] == slug for t in tasks.all_tasks()):
            slug = f"{slug}-2"
        return {"command": {"kind": "task_new", "id": slug, "description": desc},
                "say": None}

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


def spoken_reply(kind: str, outcome: str, detail: str) -> str:
    """Turn a run_command result into one speakable sentence."""
    if outcome == "halted":
        return "I'm halted — only resume works."
    if outcome in ("refused", "invalid"):
        return f"I can't do that: {detail}"
    if outcome == "error":
        return f"That failed: {detail}"
    if kind == "halt":
        return "Halted. Nothing acts until you say resume."
    if kind == "resume":
        return "Resumed."
    if kind == "browse_read":
        # detail is "read <url> — <title> :: <excerpt>" — speak title + excerpt
        return detail.split("read ", 1)[-1].replace(" :: ", ". ", 1)
    return detail
