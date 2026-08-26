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

    if re.fullmatch(r"(status|what's going on|what is going on|what's up|"
                    r"how are things|anything happening|report)", low):
        return {"command": None, "say": _status_say()}

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

    # unrecognized: journal it honestly, never guess an action (§104)
    return {"command": {"kind": "note", "text": f"(voice, unmatched) {text}"},
            "say": "I don't have a command for that yet, so I journaled it. "
                   "I can: status, halt, resume, read a site, screenshot, "
                   "approve or deny, add a task, or take a note."}


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
