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
    from aletheia import localtime
    tz = localtime.operator_tz()
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
    low = text.lower().strip().rstrip(".?!")
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
    if re.fullmatch(r"(resume|resume everything|start again|back on|carry on|"
                    r"un-?halt|you can (resume|start again|carry on)|"
                    r"(go ahead and )?resume now)", low):
        return {"command": {"kind": "resume"}, "say": None}

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


ORDINALS = {"first": 0, "second": 1, "third": 2, "last": -1}


def approval_label(approval: dict) -> str:
    """What this approval is, in words he would recognise."""
    from aletheia import speech
    action = str(approval.get("requested_action", ""))
    capability = str(approval.get("capability", ""))
    if capability == "email.send" or action.startswith("email.send"):
        reason = str(approval.get("reason", ""))
        who = re.search(r"\bto ([A-Za-z][^.]*?)\s*(?:$|\.)", reason)
        return f"the email{' to ' + who.group(1) if who else ''}"
    if capability == "calendar.write" or action.startswith("calendar.write"):
        return "the calendar booking"
    if capability == "intent.execute":
        return "the plan"
    if capability == "errand.run":
        return speech.tidy(speech.strip_ids(action)) or "the errand"
    if capability == "agent.delegate" or action.startswith("delegate"):
        return "the work order"
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


def _offer_choice(pending: list[dict]) -> str:
    from aletheia import speech
    labels = [approval_label(a) for a in pending[:4]]
    more = "" if len(pending) <= 4 else f", and {len(pending) - 4} more"
    return (f"{speech.count_phrase(len(pending), 'thing')} waiting: "
            + speech.and_list(labels) + more
            + ". Which one — say approve the first, or name it.")


def spoken_reply(kind: str, outcome: str, detail: str) -> str:
    """Turn a run_command result into one speakable sentence.

    The receipts these come from are written for a log, not a room. See
    aletheia/speech.py for why a hex id read aloud is the worst version of
    §145 — he cannot hold it in his head, and the sentence after it asks
    him to say it back.
    """
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
    from aletheia import speech
    return speech.spoken_receipt(kind, detail)
