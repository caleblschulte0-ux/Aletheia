"""A conversation with somebody, carried: draft, send, wait, understand, follow up.

Continuity brief IV.15 (and rules 2, 3, 5, 8): *"do not make every mundane
message require rebuilding context by hand."* A message she sends is not a
one-off: it is a THREAD with a recipient, a history, questions still open, a
reply to wait for, a next action, and a date to follow up on. This module is
that thread, for any purpose (a landlord, a recruiter, a clinic, a plumber) -
nothing here knows what the conversation is about.

    draft -> identify the recipient (a contact, a prior thread, or a public
             contact found on the web WITH its provenance)
          -> load what was said before (her own records of the thread)
          -> send under the right rule (`conversation_authority`)
          -> wait for the reply (`wait_adapter`, backed by the expectation store
             `mail.poll_events` already resolves)
          -> understand it (`reply_understanding`: untrusted data, routine class)
          -> decide the next action (answer, ask Caleb, propose or accept a time,
             pencil in a hold, confirm an event, close)
          -> follow up when the questions stay unanswered

THE STATES (`STATES`), each with a reason and a next action (rule 3), and each
mapped onto the shared work vocabulary by `work_view` so the work engine and
mission control read conversations like every other queue:

    DRAFTED            a draft exists but cannot go yet (no address: ask Caleb)
    AWAITING_APPROVAL  a message waits for his yes (or for a grant check)
    SENT               delivered this beat (transient)
    AWAITING_REPLY     waiting on the other person; a follow-up date is set
    REPLIED            they answered and the next action needs Caleb
    FOLLOW_UP_DUE      nobody answered in time; a follow-up is being drafted
    CLOSED             answered, declined, or given up on - and why

SENDING, ONCE. A message is hash-bound (sha256 of thread, recipient, subject,
body and kind) to its approval; the record is claimed (SENDING) on disk before
the transport is called, so a second beat or a restart cannot send it twice - a
SENDING record found with nobody sending it becomes SEND_UNCERTAIN and is never
retried. A REHEARSAL (`ALETHEIA_REHEARSAL`, `talk --sandbox`) sends nothing
through any transport that is not explicitly rehearsal-safe.

His words and their replies are private state (`state/private/conversations`).
The journal gets the recipient's display name and the subject, never a body.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import secrets
import sys
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr
from typing import Any, Callable

from aletheia import (calendar_reasoning, conversation_authority, journal, policy,
                      reply_understanding as ru, stateio, wait_adapter)

ACTOR = "aletheia-conversations"

DRAFTED = "DRAFTED"
AWAITING_APPROVAL = "AWAITING_APPROVAL"
SENT = "SENT"
AWAITING_REPLY = "AWAITING_REPLY"
REPLIED = "REPLIED"
FOLLOW_UP_DUE = "FOLLOW_UP_DUE"
CLOSED = "CLOSED"
STATES = (DRAFTED, AWAITING_APPROVAL, SENT, AWAITING_REPLY, REPLIED, FOLLOW_UP_DUE, CLOSED)

# message states
M_AWAITING = "AWAITING_APPROVAL"
M_SENDING = "SENDING"
M_SENT = "SENT"
M_UNCERTAIN = "SEND_UNCERTAIN"
M_REFUSED = "REFUSED"
M_FAILED = "FAILED"

FOLLOW_UP_AFTER_DAYS = 3
MAX_FOLLOW_UPS = 2
MAX_SEND_ATTEMPTS = 3
MAX_BODY_CHARS = 4_000
REPLY_TEXT_KEPT = 1_500
HER_OWN = ("aletheia", "agent")

_IN_FLIGHT: set[str] = set()


class ConversationError(ValueError):
    """Said in a sentence he can act on."""


# ---- the store ---------------------------------------------------------------------

def store_dir():
    return stateio.private_dir("conversations")


def _path(thread_id: str):
    return store_dir() / f"{stateio.safe_id(thread_id, name='conversation id')}.json"


def load(thread_id: str) -> dict:
    return stateio.read_json(_path(thread_id))


def all_threads(state: str | None = None) -> list[dict]:
    directory = store_dir()
    if not directory.is_dir():
        return []
    out = []
    for path in sorted(directory.glob("conv-*.json")):
        try:
            value = stateio.read_json(path)
        except ValueError:
            continue
        if state is None or value.get("state") == state:
            out.append(value)
    return out


def _now(now: dt.datetime | None) -> dt.datetime:
    value = now or dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(dt.timezone.utc)


def _stamp(when: dt.datetime) -> str:
    return when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp: object) -> dt.datetime | None:
    try:
        value = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def save(thread: dict, *, now: dt.datetime | None = None) -> dict:
    thread["updated_at"] = _stamp(_now(now))
    stateio.write_json_atomic(_path(thread["id"]), thread)
    return thread


def _transition(thread: dict, state: str, reason: str, next_action: str, *, now: dt.datetime | None = None,
                quiet: bool = False) -> dict:
    if state not in STATES:
        raise ValueError(f"state {state!r} not in {STATES}")
    before = thread.get("state")
    thread.update({"state": state, "reason": str(reason)[:300], "next": str(next_action)[:300]})
    thread.setdefault("history", []).append({"at": _stamp(_now(now)), "from": before, "to": state,
                                             "why": str(reason)[:200]})
    thread["history"] = thread["history"][-60:]
    save(thread, now=now)
    if not quiet and before != state:
        journal.append("event", f"conversation:{thread['id']}",
                       f"{_name(thread)}: {before or 'new'} -> {state}: {str(reason)[:160]}", actor=ACTOR)
    return thread


def _name(thread: dict) -> str:
    recipient = thread.get("recipient") or {}
    return str(recipient.get("name") or recipient.get("address") or thread.get("who") or "someone")


# ---- recipients and history ---------------------------------------------------------

_ADDRESS = re.compile(r"^[^@\s<>()]+@[^@\s<>()]+\.[A-Za-z]{2,}$")


def identify_recipient(who: str, *, public_contact: dict | None = None) -> dict:
    """Who a message goes to, and HOW she knows. Never a guess.

    Sources, in order: an address he said; a saved contact; a prior conversation
    with that name; memory; a public contact found on the web - accepted only
    with its provenance (the page URL and the words on it that show the
    address). Raises LookupError with the question to ask him."""
    said = " ".join(str(who or "").split())
    if public_contact:
        address = str(public_contact.get("address") or "").strip()
        url = str(public_contact.get("url") or "").strip()
        quote = str(public_contact.get("quote") or "")
        if not _ADDRESS.match(address) or not url.lower().startswith(("http://", "https://")) \
                or address.casefold() not in quote.casefold():
            raise LookupError("a contact found on the web needs its page and the words on it that show the "
                              "address, or I can't say where it came from")
        return {"address": address, "name": str(public_contact.get("name") or said or address),
                "source": "public_web", "provenance": {"url": url, "quote": quote[:300],
                                                       "found_at": stateio.utcnow()}}
    if not said:
        raise LookupError("who should I write to?")
    spoken = re.sub(r"\s+at\s+", "@", said, flags=re.I)
    spoken = re.sub(r"\s+dot\s+", ".", spoken, flags=re.I).replace(" ", "")
    if _ADDRESS.match(spoken):
        return {"address": spoken, "name": said if "@" in said else spoken.split("@")[0],
                "source": "given", "provenance": {}}
    try:
        from aletheia import contacts
        contact = contacts.resolve(said)
        return {"address": contacts.primary_email(contact), "name": contact["display_name"],
                "source": "contact", "provenance": {"contact_id": contact["id"]}}
    except KeyError:
        pass
    except LookupError as exc:
        raise LookupError(str(exc)) from None
    matches = {}
    for thread in all_threads():
        recipient = thread.get("recipient") or {}
        if recipient.get("address") and _mentions(thread, said):
            matches[recipient["address"].casefold()] = recipient
    if len(matches) == 1:
        found = dict(next(iter(matches.values())))
        return {**found, "source": "prior_thread", "provenance": {"from_thread": True}}
    if len(matches) > 1:
        raise LookupError(f"I've written to more than one {said}; which address?")
    try:
        from aletheia import mail
        address, name = mail.resolve_address(said)
        if address:
            return {"address": address, "name": name, "source": "memory", "provenance": {}}
    except Exception:  # noqa: BLE001
        pass
    raise LookupError(f"I don't have an email address for {said}. Tell me what it is, or where it's listed.")


def _mentions(thread: dict, words: str) -> bool:
    needle = " ".join(str(words or "").casefold().replace("the ", "").split())
    if not needle:
        return False
    recipient = thread.get("recipient") or {}
    hay = " ".join(str(x) for x in (recipient.get("name"), recipient.get("address"), thread.get("who"),
                                    thread.get("subject"), thread.get("purpose"))).casefold()
    return needle in hay


def history(address: str, *, exclude: str = "", limit: int = 10) -> list[dict]:
    """What was said with this person before, across her threads: the context a
    follow-up or a reply is written against, without anyone rebuilding it."""
    rows = []
    for thread in all_threads():
        if thread["id"] == exclude or str((thread.get("recipient") or {}).get("address", "")).casefold() \
                != str(address or "").casefold():
            continue
        for message in thread.get("messages") or []:
            if message.get("state") == M_SENT:
                rows.append({"thread": thread["id"], "at": message.get("sent_at"), "direction": "OUT",
                             "subject": message.get("subject"), "summary": message.get("body", "")[:200]})
        for reply in thread.get("replies") or []:
            rows.append({"thread": thread["id"], "at": reply.get("received_at"), "direction": "IN",
                         "subject": reply.get("subject"), "summary": reply.get("category")})
    return sorted(rows, key=lambda r: str(r.get("at") or ""))[-limit:]


def resolve_thread(who: str) -> dict:
    """The ONE open conversation he means ("the property manager", "they")."""
    words = " ".join(str(who or "").split())
    open_threads = [t for t in all_threads() if t.get("state") != CLOSED]
    if words.lower() in ("", "they", "them", "him", "her", "it", "that", "that one"):
        ranked = sorted(open_threads, key=lambda t: str(t.get("updated_at") or ""), reverse=True)
        if not ranked:
            raise LookupError("there's no conversation open right now")
        return ranked[0]
    try:
        return load(words)
    except (ValueError, OSError):
        pass
    hits = [t for t in open_threads if _mentions(t, words)]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise LookupError(f"I don't have an open conversation with {words}")
    from aletheia import speech
    raise LookupError("which one: " + speech.or_list([f"{_name(t)} about {t.get('subject')}" for t in hits[:4]]))


# ---- drafting ---------------------------------------------------------------------

def content_sha(thread_id: str, to: str, subject: str, body: str, kind: str) -> str:
    raw = json.dumps({"thread": thread_id, "to": str(to).casefold(), "subject": subject, "body": body,
                      "kind": kind}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def action_for(sha: str) -> str:
    return f"conversation.send:{sha}"


def _first(name: str) -> str:
    word = str(name or "").split()[0] if str(name or "").split() else ""
    return word if word and "@" not in word and word.lower() not in ("the", "a") else "there"


def compose_body(about: str, *, name: str, asks: list[str] | None = None, sign: str = "Caleb") -> str:
    """A plain first message from what he asked for. Deterministic on purpose:
    what he approves is what she wrote, not a model's paraphrase of it."""
    lines = [f"Hi {_first(name)},", "", f"I'm reaching out about {about.strip().rstrip('.')}."]
    for ask in asks or []:
        text = ask.strip()
        lines.append(text if text.endswith("?") else text.rstrip(".") + "?")
    lines += ["", "Thanks,", sign]
    return "\n".join(lines)


def _asks_from(body: str) -> list[str]:
    return ru.questions_in(body)


def start(to: str, *, about: str, body: str | None = None, subject: str | None = None,
          asks: list[str] | None = None, public_contact: dict | None = None, via: str = "",
          work_item: str = "", meeting: dict | None = None, now: dt.datetime | None = None) -> dict:
    """Open a conversation and draft its first message. Sends nothing.

    The draft's send approval is filed at once (email.send, always his) unless
    the recipient is unknown, in which case the thread waits in DRAFTED with the
    question to ask him."""
    now = _now(now)
    about = " ".join(str(about or "").split())
    if not about and not body:
        raise ConversationError("say what the message is about")
    thread_id = f"conv-{secrets.token_hex(5)}"
    thread = {"version": 1, "id": thread_id, "channel": "email", "who": " ".join(str(to or "").split()),
              "purpose": about or (subject or "")[:120], "subject": (subject or about or "")[:140].strip(),
              "state": DRAFTED, "reason": "", "next": "", "created_at": _stamp(now), "updated_at": _stamp(now),
              "work_item": work_item or f"conversation:{thread_id}", "via": str(via)[:120],
              "recipient": None, "messages": [], "replies": [], "open_asks": [], "waits": [],
              "follow_up": {"due": None, "sent": 0, "max": MAX_FOLLOW_UPS, "after_days": FOLLOW_UP_AFTER_DAYS},
              "scheduling": {"state": None}, "meeting": dict(meeting or {}), "grants": [], "history": []}
    try:
        thread["recipient"] = identify_recipient(to, public_contact=public_contact)
    except LookupError as exc:
        thread["pending_draft"] = {"about": about, "body": body, "subject": subject, "asks": asks}
        save(thread, now=now)
        return _transition(thread, DRAFTED, str(exc), "ask Caleb for the address", now=now)
    name = thread["recipient"]["name"]
    text = body if body else compose_body(about, name=name, asks=asks)
    thread["subject"] = (subject or about[:1].upper() + about[1:]).strip()[:140]
    save(thread, now=now)
    return draft_message(thread, text, kind="first", now=now)


def draft_message(thread: dict, body: str, *, kind: str = "reply", subject: str | None = None,
                  now: dt.datetime | None = None) -> dict:
    """One outbound message on a thread, with its authority decided and its
    approval filed (or spent from a grant he created). Sends nothing."""
    now = _now(now)
    body = str(body or "").strip()
    if not body:
        raise ConversationError("the message is empty")
    if len(body) > MAX_BODY_CHARS:
        raise ConversationError(f"the message is longer than {MAX_BODY_CHARS} characters")
    recipient = thread.get("recipient") or {}
    address = recipient.get("address")
    if not address:
        raise ConversationError(f"I don't have an address for {_name(thread)} yet")
    for pending in thread.get("messages") or []:
        if pending.get("state") == M_AWAITING:
            raise ConversationError("a message on this conversation is already waiting to go; "
                                    "approve or deny that one first")
    subject = subject or (thread["subject"] if kind == "first" else f"Re: {thread['subject']}")
    sha = content_sha(thread["id"], address, subject, body, kind)
    message_id = f"{thread['id']}-m{len(thread.get('messages') or []) + 1}"
    prior = any(m.get("state") == M_SENT for m in thread.get("messages") or [])
    decision = conversation_authority.decide(kind=kind, thread_id=thread["id"], recipient=address, body=body,
                                             subject=subject, prior_approved_to_recipient=prior)
    approval = policy.request(
        message_id, action_for(sha),
        reason=f"send {'a follow-up' if kind == 'followup' else 'an email'} to {recipient.get('name')}: "
               f"{subject}",
        consequence="the email is sent in Caleb's name and cannot be recalled",
        reversible=False, capability=decision["capability"], scope=decision["scope"])
    message = {"id": message_id, "kind": kind, "to": address, "subject": subject, "body": body, "sha256": sha,
               "approval": message_id, "capability": decision["capability"], "authority_why": decision["why"],
               "screen": decision["screen"], "state": M_AWAITING, "created_at": _stamp(now), "attempts": 0}
    decided = str(approval.get("decided_via") or "")
    if approval.get("state") == "APPROVED" and decided.startswith("grant:"):
        message["granted_by"] = decided.split(":", 1)[1]
    thread.setdefault("messages", []).append(message)
    if kind in ("first", "reply", "answer"):
        for ask in _asks_from(body):
            thread.setdefault("open_asks", []).append({"text": ask, "asked_in": message_id, "answered_in": None})
    journal.append("action", f"conversation:{thread['id']}",
                   f"drafted {kind} to {recipient.get('name')} - {subject[:80]!r}; "
                   + (f"covered by his standing grant {message['granted_by']}" if message.get("granted_by")
                      else "waiting for his approval"), actor=ACTOR)
    if message.get("granted_by"):
        return _transition(thread, FOLLOW_UP_DUE if kind == "followup" else AWAITING_APPROVAL,
                           f"a {kind} is covered by the permission he gave", "send it on the next beat", now=now)
    return _transition(thread, AWAITING_APPROVAL, f"a {kind} to {recipient.get('name')} waits for his yes "
                       f"({decision['why']})", "Caleb approves or denies the message", now=now)


def provide_address(thread_id: str, address: str, *, name: str = "", now: dt.datetime | None = None) -> dict:
    """He told her the address a DRAFTED conversation was missing."""
    thread = load(thread_id)
    if thread.get("state") != DRAFTED:
        raise ConversationError("that conversation is not waiting for an address")
    thread["recipient"] = identify_recipient(address)
    if name:
        thread["recipient"]["name"] = name
    pending = thread.pop("pending_draft", {}) or {}
    about = pending.get("about") or thread.get("purpose")
    body = pending.get("body") or compose_body(about, name=thread["recipient"]["name"], asks=pending.get("asks"))
    thread["subject"] = (pending.get("subject") or about[:1].upper() + about[1:])[:140]
    save(thread, now=now)
    return draft_message(thread, body, kind="first", now=now)


def note_grant(thread_id: str, grant: dict) -> None:
    thread = load(thread_id)
    thread.setdefault("grants", []).append(grant["id"])
    thread.setdefault("history", []).append({"at": stateio.utcnow(), "from": thread.get("state"),
                                             "to": thread.get("state"),
                                             "why": f"he gave standing permission for follow-ups ({grant['id']})"})
    save(thread)


# ---- sending --------------------------------------------------------------------------

class FakeMailTransport:
    """Hermetic mail for tests and rehearsals; never evidence of a live account.
    `rehearsal_safe` is what lets a rehearsal use it: nothing leaves the process."""
    rehearsal_safe = True

    def __init__(self, address: str = "caleb@example.test"):
        self.address = address
        self.outbox: list[EmailMessage] = []
        self.inbox: list[dict] = []
        self._bodies: dict[str, dict] = {}

    def send(self, msg: EmailMessage) -> None:
        self.outbox.append(msg)

    def deliver(self, *, sender: str, subject: str, text: str, when: dt.datetime,
                in_reply_to: str = "", headers: dict | None = None) -> dict:
        message_id = make_msgid(domain="counterpart.test")
        header = {"from": sender, "subject": subject, "date": when.strftime("%a, %d %b %Y %H:%M:%S %z"),
                  "message_id": message_id}
        self.inbox.append(header)
        self._bodies[message_id] = {**header, "text": text, "in_reply_to": in_reply_to,
                                    "headers": dict(headers or {})}
        return header

    def fetch_unread(self, limit: int) -> list[dict]:
        return list(reversed(self.inbox))[:limit]

    def fetch_body(self, message_id: str) -> dict:
        if message_id not in self._bodies:
            raise LookupError("that message is no longer in the inbox")
        return dict(self._bodies[message_id])


def _her_own(via: str) -> bool:
    return str(via or "").strip().lower().startswith(HER_OWN)


def _rehearsing() -> bool:
    from aletheia import intercom
    return intercom.rehearsing()


def _approved_by_handoff(message: dict, thread_id: str) -> str | None:
    """His yes to a session's `thread.send` handoff for EXACTLY this message
    (the handoff's hash covers the message sha) counts as his yes to the message.
    Verified against both stores; returns the handoff id or None."""
    try:
        from aletheia import handoffs
    except Exception:  # noqa: BLE001
        return None
    args = {"thread": thread_id, "message": message["id"], "sha256": message["sha256"]}
    digest = handoffs.request_digest("thread.send", args)
    for record in handoffs.all_handoffs():
        if record.get("tool") != "thread.send" or record.get("request_sha256") != digest:
            continue
        if record.get("state") not in (handoffs.RUNNING, handoffs.AWAITING):
            continue
        try:
            approval = policy.load(record.get("approval") or record["id"])
        except Exception:  # noqa: BLE001
            continue
        if approval.get("requested_action") != handoffs.action_for("thread.send", digest):
            continue
        ok, _ = policy.usable(approval["id"])
        if ok and not _her_own(approval.get("decided_via", "")) \
                and not str(approval.get("decided_via", "")).startswith("grant:"):
            return record["id"]
    return None


def _verify_grant(message: dict, thread: dict, grant_id: str) -> bool:
    """Defense in depth: a grant-decided approval must name a live, scoped,
    machine-signed follow-up grant about THIS thread, for a follow-up."""
    from aletheia import authority
    try:
        grant = authority.load(grant_id)
    except (ValueError, OSError):
        return False
    scope = grant.get("scope") or {}
    return (message.get("kind") == "followup" and message.get("capability") == conversation_authority.FOLLOWUP
            and conversation_authority.FOLLOWUP in grant.get("capability_ids", [])
            and scope.get("thread_id") == thread["id"]
            and scope.get("recipient", "") in ("", str(message.get("to", "")).casefold())
            and bool(grant.get("machine_binding")))


def _recover(thread: dict, now: dt.datetime) -> bool:
    changed = False
    for message in thread.get("messages") or []:
        if message.get("state") == M_SENDING and message["id"] not in _IN_FLIGHT:
            message["state"] = M_UNCERTAIN
            message["uncertain_at"] = _stamp(now)
            changed = True
            journal.append("alert", f"conversation:{thread['id']}",
                           f"a message to {_name(thread)} stopped mid-send; it is NOT sent again", actor=ACTOR)
    if changed:
        _transition(thread, REPLIED, "a message may or may not have gone out (it stopped mid-send)",
                    "Caleb checks his sent mail; I will not send it twice", now=now)
    return changed


def send_approved(*, transport=None, now: dt.datetime | None = None, only_thread: str | None = None) -> list[dict]:
    """Deliver every message he approved (or a grant of his covers), exactly once."""
    now = _now(now)
    results: list[dict] = []
    if policy.halted() is not None:
        return [{"outcome": "halted", "detail": "Aletheia is halted; nothing is sent"}]
    for thread in all_threads():
        if only_thread and thread["id"] != only_thread:
            continue
        if thread.get("state") == CLOSED:
            continue
        _recover(thread, now)
        for message in thread.get("messages") or []:
            if message.get("state") != M_AWAITING:
                continue
            outcome = _send_one(thread, message, transport=transport, now=now)
            if outcome:
                results.append(outcome)
    return results


def _send_one(thread: dict, message: dict, *, transport, now: dt.datetime) -> dict | None:
    try:
        approval = policy.load(message["approval"])
    except (OSError, ValueError, KeyError):
        return None
    state = approval.get("state")
    base = {"thread": thread["id"], "message": message["id"], "to": _name(thread)}
    if state in ("DENIED", "EXPIRED"):
        message["state"] = M_REFUSED
        message["refused_because"] = "he said no" if state == "DENIED" else "the approval went stale"
        if message.get("kind") == "first":
            _transition(thread, CLOSED, f"he did not want the first message sent ({state.lower()})", "nothing",
                        now=now)
        else:
            thread["follow_up"]["due"] = None
            _transition(thread, AWAITING_REPLY if any(m.get("state") == M_SENT for m in thread["messages"])
                        else CLOSED, f"he did not want that {message.get('kind')} sent",
                        "wait for their reply; no more follow-ups unless he asks", now=now)
        return {**base, "outcome": "refused", "detail": message["refused_because"]}
    handoff = None
    if state != "APPROVED":
        handoff = _approved_by_handoff(message, thread["id"])
        if not handoff:
            return None
        policy.decide(message["approval"], "APPROVED", via=f"handoff:{handoff}",
                      because="he approved the session's request to send exactly this message")
        approval = policy.load(message["approval"])
    ok, why = policy.usable(message["approval"])
    if not ok:
        return {**base, "outcome": "waiting", "detail": why}
    decided = str(approval.get("decided_via") or "")
    sha = content_sha(thread["id"], message["to"], message["subject"], message["body"], message["kind"])
    if sha != message.get("sha256") or approval.get("requested_action") != action_for(sha):
        message["state"] = M_REFUSED
        message["refused_because"] = "the message changed after it was approved"
        _transition(thread, REPLIED, "a message changed after he approved it, so it was not sent",
                    "Caleb approves the message as it is now", now=now)
        return {**base, "outcome": "refused", "detail": message["refused_because"]}
    if _her_own(decided):
        message["state"] = M_REFUSED
        message["refused_because"] = "the approval was decided by one of her own processes"
        save(thread, now=now)
        return {**base, "outcome": "refused", "detail": message["refused_because"]}
    if decided.startswith("grant:") and not _verify_grant(message, thread, decided.split(":", 1)[1]):
        message["state"] = M_REFUSED
        message["refused_because"] = "the grant named on the approval does not cover this message"
        save(thread, now=now)
        return {**base, "outcome": "refused", "detail": message["refused_because"]}
    if _rehearsing() and not getattr(transport, "rehearsal_safe", False):
        return {**base, "outcome": "rehearsal", "detail": "a rehearsal: approved, and deliberately not sent"}
    if transport is None:
        from aletheia import mail
        available, reason = mail.available()
        if not available:
            return {**base, "outcome": "waiting", "detail": reason}
        transport = mail.SmtpImapTransport()
    # CLAIMED BEFORE THE TRANSPORT IS CALLED: nothing after this can send it twice.
    message["state"] = M_SENDING
    message["attempts"] = int(message.get("attempts") or 0) + 1
    save(thread, now=now)
    _IN_FLIGHT.add(message["id"])
    try:
        email = EmailMessage()
        email["From"] = getattr(transport, "address", None) or _from_address()
        email["To"] = message["to"]
        email["Subject"] = message["subject"]
        email["Message-ID"] = make_msgid(domain="aletheia.local")
        last_in = next((r for r in reversed(thread.get("replies") or []) if r.get("message_id")), None)
        if last_in:
            email["In-Reply-To"] = last_in["message_id"]
            email["References"] = last_in["message_id"]
        email.set_content(message["body"])
        transport.send(email)
    except Exception as exc:  # noqa: BLE001
        _IN_FLIGHT.discard(message["id"])
        message["state"] = M_AWAITING if message["attempts"] < MAX_SEND_ATTEMPTS else M_FAILED
        message["last_error"] = f"{type(exc).__name__}"
        save(thread, now=now)
        journal.append("event", f"conversation:{thread['id']}",
                       f"a message to {_name(thread)} did not send yet ({type(exc).__name__})", actor=ACTOR)
        return {**base, "outcome": "failed" if message["state"] == M_FAILED else "retry",
                "detail": type(exc).__name__}
    _IN_FLIGHT.discard(message["id"])
    message.update({"state": M_SENT, "sent_at": _stamp(now), "external_id": email["Message-ID"],
                    "approved_via": decided if not handoff else f"handoff:{handoff}"})
    _record_outbound(thread, message, now)
    if message.get("kind") == "followup":
        thread["follow_up"]["sent"] = int(thread["follow_up"].get("sent") or 0) + 1
    sched = thread.get("scheduling") or {}
    if sched.get("state") == "WE_ACCEPTED" and sched.get("message") == message["id"]:
        sched["state"] = "AWAITING_CONFIRMATION"
    elif sched.get("state") == "AGREED" and sched.get("message") == message["id"]:
        _confirm_scheduled(thread, now=now)
    elif sched.get("state") == "WE_PROPOSING" and sched.get("message") == message["id"]:
        sched["state"] = "WE_PROPOSED"
    open_asks = [a for a in thread.get("open_asks") or [] if not a.get("answered_in")]
    due = now + dt.timedelta(days=int(thread["follow_up"].get("after_days") or FOLLOW_UP_AFTER_DAYS))
    thread["follow_up"]["due"] = _stamp(due) if open_asks or sched.get("state") in (
        "AWAITING_CONFIRMATION", "WE_PROPOSED") else None
    journal.append("action", f"conversation:{thread['id']}",
                   f"sent {message['kind']} to {_name(thread)} - {message['subject'][:80]!r}"
                   + (f" under his standing grant {decided.split(':', 1)[1]}" if decided.startswith("grant:") else ""),
                   actor=ACTOR)
    when = calendar_reasoning.human(_stamp(due), now=now) if thread["follow_up"]["due"] else ""
    _transition(thread, AWAITING_REPLY, f"sent; waiting for {_name(thread)} to answer",
                f"read their reply; follow up {when} if they have not answered" if when
                else "read their reply when it comes", now=now)
    return {**base, "outcome": "sent", "kind": message["kind"],
            "via": "grant" if decided.startswith("grant:") else ("handoff" if handoff else "approval")}


def _from_address() -> str:
    try:
        from aletheia import mail
        return mail._config().get("address") or "aletheia"
    except Exception:  # noqa: BLE001
        return "aletheia"


def _record_outbound(thread: dict, message: dict, now: dt.datetime) -> None:
    """Mirror onto the channel-neutral store, so `mail.poll_events` can match a
    reply to this thread, and wait for it through the one wait seam."""
    from aletheia import communications
    address = message["to"].casefold()
    comms_id = thread.get("comms_thread") or thread["id"]
    try:
        communications.create_thread(comms_id, participants=[address], subject=thread.get("subject", ""))
    except FileExistsError:
        pass
    thread["comms_thread"] = comms_id
    try:
        communications.record_message(message["id"], thread_id=comms_id, direction="OUTBOUND", channel="email",
                                      participant=address, summary=message["subject"][:200],
                                      external_id=message.get("external_id"), occurred_at=_stamp(now))
    except FileExistsError:
        pass
    wait = wait_adapter.reply_from(comms_id, address, after_message_id=message["id"],
                                   reason=f"waiting for {_name(thread)} to reply about {thread.get('subject')}")
    thread.setdefault("waits", []).append(wait)
    thread["waits"] = thread["waits"][-10:]


# ---- replies ------------------------------------------------------------------------

def _inbound_unseen(thread: dict) -> list[dict]:
    from aletheia import communications
    comms_id = thread.get("comms_thread")
    if not comms_id:
        return []
    try:
        rows = communications.messages(comms_id)
    except (ValueError, OSError):
        return []
    seen = set(thread.get("seen_inbound") or [])
    return [m for m in rows if m.get("direction") == "INBOUND" and m["id"] not in seen]


Facts = Callable[[str], "str | None"]


def known_fact(question: str) -> str | None:
    """An answer to their question from what he has TOLD her (memory), or None.
    Only a remembered fact whose key names the question's words counts."""
    try:
        from aletheia import memory
        words = ru._content_words(question)
        for domain in ("preferences", "identity"):
            data = memory._load(domain)
            for key, entry in (data.get("facts") or data).items():
                key_words = set(str(key).replace("-", " ").replace("_", " ").lower().split())
                if key_words and key_words <= words:
                    value = entry.get("value") if isinstance(entry, dict) else entry
                    if isinstance(value, (str, int, float)) and str(value).strip():
                        return str(value)
    except Exception:  # noqa: BLE001
        return None
    return None


def check_replies(*, transport=None, now: dt.datetime | None = None, think=None, use_model: bool = True,
                  facts: Facts | None = None, provider=None, estimator=None) -> list[dict]:
    """Read each new reply on her open conversations, understand it, act on it."""
    now = _now(now)
    actions = []
    for thread in all_threads():
        if thread.get("state") in (CLOSED, DRAFTED):
            continue
        for inbound in _inbound_unseen(thread):
            outcome = _handle_reply(thread, inbound, transport=transport, now=now, think=think,
                                    use_model=use_model, facts=facts or known_fact, provider=provider,
                                    estimator=estimator)
            if outcome:
                actions.append(outcome)
            thread = load(thread["id"])
            if thread.get("state") == CLOSED:
                break
    return actions


def _handle_reply(thread: dict, inbound: dict, *, transport, now, think, use_model, facts, provider,
                  estimator) -> dict | None:
    external = inbound.get("external_id") or ""
    body = None
    if transport is not None and external:
        try:
            body = transport.fetch_body(external)
        except Exception as exc:  # noqa: BLE001
            if "no longer" not in str(exc):
                return {"thread": thread["id"], "outcome": "retry", "detail": f"could not read the reply ({type(exc).__name__})"}
    if body is None:
        if transport is None:
            try:
                from aletheia import mail
                if mail.available()[0]:
                    body = mail.SmtpImapTransport().fetch_body(external)
            except Exception:  # noqa: BLE001
                body = None
    if body is None:
        body = {"from": _name(thread), "subject": inbound.get("summary", ""), "text": "", "message_id": external}
    asks = thread.get("open_asks") or []
    open_texts = [a["text"] for a in asks if not a.get("answered_in")]
    open_index = [i for i, a in enumerate(asks) if not a.get("answered_in")]
    reading = ru.understand({**body, "received_at": inbound.get("occurred_at")}, our_questions=open_texts,
                            think=think, use_model=use_model and bool(body.get("text")))
    # indexes into the OPEN questions -> indexes into all of them
    answered = [open_index[i] for i in reading.get("answered") or [] if i < len(open_index)]
    reply_id = inbound["id"]
    for index in answered:
        asks[index]["answered_in"] = reply_id
    record = {"id": reply_id, "message_id": external, "received_at": inbound.get("occurred_at"),
              "from": body.get("from"), "subject": body.get("subject"),
              "text": str(body.get("text") or "")[:REPLY_TEXT_KEPT], "untrusted": True,
              "category": reading["category"], "confidence": reading["confidence"],
              "understood_by": reading["understood_by"], "model_error": reading.get("model_error", ""),
              "model_seconds": reading.get("model_seconds"),
              "times": reading.get("times") or [], "their_questions": reading.get("their_questions") or [],
              "answered": answered}
    thread.setdefault("replies", []).append(record)
    thread.setdefault("seen_inbound", []).append(reply_id)
    thread["follow_up"]["due"] = None
    decision = ru.route({**reading, "answered": [open_texts.index(asks[i]["text"]) for i in answered
                                                 if asks[i]["text"] in open_texts]},
                        open_asks=[{"text": t} for t in open_texts], scheduling=thread.get("scheduling"),
                        facts=facts)
    record["next_action"] = decision["action"]
    record["why"] = decision["why"]
    save(thread, now=now)
    journal.append("event", f"conversation:{thread['id']}",
                   f"{_name(thread)} replied: {reading['category'].replace('_', ' ')} "
                   f"(read by {reading['understood_by']}); next: {decision['action'].replace('_', ' ')}",
                   actor=ACTOR)
    _apply(thread, decision, reading, now=now, provider=provider, estimator=estimator)
    return {"thread": thread["id"], "outcome": "reply", "category": reading["category"],
            "understood_by": reading["understood_by"], "action": decision["action"],
            "model_seconds": reading.get("model_seconds")}


def _still_open(thread: dict) -> list[dict]:
    return [a for a in thread.get("open_asks") or [] if not a.get("answered_in")]


def _tell(title: str, body: str, key: str) -> None:
    try:
        from aletheia import notifications
        notifications.publish(title, body, priority="IMPORTANT", source="conversations", dedupe_key=key)
    except Exception:  # noqa: BLE001
        pass


def _apply(thread: dict, decision: dict, reading: dict, *, now: dt.datetime, provider=None, estimator=None) -> dict:
    action = decision["action"]
    name = _name(thread)
    if action == "close":
        if decision.get("tell_caleb"):
            _tell(f"{name} said no", f"About {thread.get('subject')}: {decision['why']}.", f"conv-closed:{thread['id']}")
        return _transition(thread, CLOSED, decision["why"], "nothing", now=now)
    if action == "find_new_address":
        _tell(f"My email to {name} bounced", "Tell me another address and I'll resend it.",
              f"conv-bounce:{thread['id']}")
        return _transition(thread, REPLIED, decision["why"], "Caleb gives another address", now=now)
    if action == "ask_caleb":
        questions = decision.get("questions") or []
        said = "; ".join(questions)[:300] if questions else "I couldn't tell what their reply means"
        _tell(f"{name} asked you something", said, f"conv-ask:{thread['id']}:{len(thread.get('replies') or [])}")
        return _transition(thread, REPLIED, f"they asked: {said}" if questions else decision["why"],
                           "Caleb answers, and I draft the reply", now=now)
    if action == "answer_from_facts":
        lines = [f"Hi {_first(name)},", ""]
        for question, answer in decision["answers"].items():
            lines.append(f"To your question - {question.rstrip('?')}: {answer}.")
        lines += ["", "Thanks,", _signature(thread)]
        return draft_message(thread, "\n".join(lines), kind="answer", now=now)
    if action == "accept_time":
        return _accept_time(thread, reading, now=now, estimator=estimator)
    if action == "confirm_event":
        sched = thread.get("scheduling") or {}
        if sched.get("state") in ("AWAITING_CONFIRMATION",):
            _confirm_scheduled(thread, now=now, provider=provider)
        elif sched.get("state") == "WE_PROPOSED":
            return _accept_time(thread, reading, now=now, estimator=estimator)
        thread = load(thread["id"])
        return _after_answer(thread, now=now, why="they confirmed the time")
    if action == "keep_waiting":
        due = now + dt.timedelta(days=int(thread["follow_up"].get("after_days") or FOLLOW_UP_AFTER_DAYS))
        back = decision.get("not_before_date")
        if back:
            try:
                zone = calendar_reasoning._zone()
                local = dt.datetime.combine(dt.date.fromisoformat(back), dt.time(10, 0), tzinfo=zone)
                due = max(due, local.astimezone(dt.timezone.utc))
            except ValueError:
                pass
        return _after_answer(thread, now=now, why=decision["why"], due=due)
    return thread


def _after_answer(thread: dict, *, now: dt.datetime, why: str, due: dt.datetime | None = None) -> dict:
    still = _still_open(thread)
    sched = thread.get("scheduling") or {}
    waiting_on_time = sched.get("state") in ("WE_PROPOSED", "AWAITING_CONFIRMATION")
    if not still and not waiting_on_time:
        return _transition(thread, CLOSED, "everything I asked has an answer"
                           + ("; the time is confirmed" if sched.get("state") == "CONFIRMED" else ""), "nothing",
                           now=now)
    due = due or now + dt.timedelta(days=int(thread["follow_up"].get("after_days") or FOLLOW_UP_AFTER_DAYS))
    thread["follow_up"]["due"] = _stamp(due)
    left = f"{len(still)} question{'s' if len(still) != 1 else ''} still unanswered" if still else "waiting on the time"
    return _transition(thread, AWAITING_REPLY, f"{why}; {left}",
                       f"follow up {calendar_reasoning.human(_stamp(due), now=now)} if they have not answered",
                       now=now)


def _signature(thread: dict) -> str:
    first = next((m for m in thread.get("messages") or [] if m.get("kind") == "first"), None)
    if first:
        lines = [ln.strip() for ln in str(first.get("body") or "").splitlines() if ln.strip()]
        if lines and len(lines[-1]) <= 40:
            return lines[-1]
    return "Caleb"


def _accept_time(thread: dict, reading: dict, *, now: dt.datetime, estimator=None) -> dict:
    meeting = thread.get("meeting") or {}
    minutes = int(meeting.get("minutes") or 60)
    location = meeting.get("location")
    sched = thread.setdefault("scheduling", {"state": None})
    ours = {s["start"] for s in sched.get("slots") or []}
    checked = calendar_reasoning.evaluate(reading.get("times") or [], minutes=minutes, location=location,
                                          estimator=estimator, now=now)
    sched["checked"] = [{"human": c["human"], "free": c["free"], "past": c["past"],
                         "conflicts": [x["why"] for x in c["conflicts"]], "start": c["start"]} for c in checked]
    free = [c for c in checked if c["free"]]
    if ours:
        agreed = [c for c in free if c["start"] in ours]
        free = agreed or free
    title = meeting.get("title") or thread.get("subject") or f"Meeting with {_name(thread)}"
    if free:
        slot = free[0]
        held = calendar_reasoning.hold(title, slot["start"], slot["end"], location=location, thread_id=thread["id"],
                                       purpose=thread.get("purpose", ""), estimator=estimator, now=now)
        clashes = [c for c in checked if not c["free"] and not c["past"]]
        note = ""
        if clashes:
            note = " (" + "; ".join(f"{c['human']} clashes: {', '.join(x['why'] for x in c['conflicts'])}"
                                    for c in clashes) + ")"
        sched.update({"state": "AGREED" if slot["start"] in ours else "WE_ACCEPTED",
                      "slot": {"start": slot["start"], "end": slot["end"], "human": slot["human"]},
                      "hold": (held.get("event") or {}).get("id"), "note": note.strip(" ()")})
        save(thread, now=now)
        lines = [f"Hi {_first(_name(thread))},", "",
                 (f"{slot['human'][:1].upper()}{slot['human'][1:]} works for me - see you then."
                  if slot["start"] in ours else
                  f"Thanks! {slot['human'][:1].upper()}{slot['human'][1:]} works for me. Please confirm."),
                 "", "Thanks,", _signature(thread)]
        drafted = draft_message(thread, "\n".join(lines), kind="reply", now=now)
        drafted = load(thread["id"])
        drafted["scheduling"]["message"] = drafted["messages"][-1]["id"]
        save(drafted, now=now)
        return _transition(drafted, AWAITING_APPROVAL,
                           f"they offered times; {slot['human']} is free and pencilled in{note}",
                           "Caleb approves the reply accepting it", now=now)
    first, last = calendar_reasoning.window("next week", now=now)
    today = now.astimezone(calendar_reasoning._zone()).date()
    options = calendar_reasoning.spread(calendar_reasoning.find_free(
        today + dt.timedelta(days=1), last, minutes=minutes, location=location, estimator=estimator, now=now), 3)
    if not options:
        return _transition(thread, REPLIED, "none of their times are free and I found no free time to offer",
                           "Caleb picks a time", now=now)
    sched.update({"state": "WE_PROPOSING", "slots": options})
    save(thread, now=now)
    offered = "\n".join(f"- {o['human'][:1].upper()}{o['human'][1:]}" for o in options)
    body = (f"Hi {_first(_name(thread))},\n\nThanks - unfortunately those times don't work for me. "
            f"Would any of these work instead?\n{offered}\n\nThanks,\n{_signature(thread)}")
    drafted = draft_message(thread, body, kind="reply", now=now)
    drafted = load(thread["id"])
    drafted["scheduling"]["message"] = drafted["messages"][-1]["id"]
    return save(drafted, now=now)


def _confirm_scheduled(thread: dict, *, now: dt.datetime, provider=None) -> dict:
    sched = thread.get("scheduling") or {}
    if sched.get("hold"):
        confirmed = calendar_reasoning.confirm_hold(sched["hold"], provider=provider)
        sched["write_approval"] = (confirmed.get("record") or {}).get("write_approval")
    sched["state"] = "CONFIRMED"
    sched["confirmed_at"] = _stamp(now)
    save(thread, now=now)
    journal.append("action", f"conversation:{thread['id']}",
                   f"the time with {_name(thread)} is confirmed: {(sched.get('slot') or {}).get('human')}",
                   actor=ACTOR)
    return thread


def propose_times(thread_id: str, *, when: str = "next week", minutes: int | None = None,
                  location: str | None = None, count: int = 3, now: dt.datetime | None = None,
                  estimator=None) -> dict:
    """Offer the other side a few times he is free (travel buffers included), as a
    drafted reply. Proposing his hours is a commitment, so the message asks him."""
    now = _now(now)
    thread = load(thread_id)
    if thread.get("state") == CLOSED:
        raise ConversationError("that conversation is closed")
    meeting = thread.setdefault("meeting", {})
    if minutes:
        meeting["minutes"] = int(minutes)
    if location:
        meeting["location"] = location
    first, last = calendar_reasoning.window(when, now=now)
    options = calendar_reasoning.spread(calendar_reasoning.find_free(
        first, last, minutes=int(meeting.get("minutes") or 60), location=meeting.get("location"),
        estimator=estimator, now=now), count)
    if not options:
        raise ConversationError(f"I found no free time {when} to offer")
    thread["scheduling"] = {"state": "WE_PROPOSING", "slots": options}
    save(thread, now=now)
    offered = "\n".join(f"- {o['human'][:1].upper()}{o['human'][1:]}" for o in options)
    body = (f"Hi {_first(_name(thread))},\n\nWould any of these times work?\n{offered}\n\n"
            f"Thanks,\n{_signature(thread)}")
    drafted = draft_message(thread, body, kind="reply", now=now)
    drafted = load(thread_id)
    drafted["scheduling"]["message"] = drafted["messages"][-1]["id"]
    return save(drafted, now=now)


# ---- follow-ups -------------------------------------------------------------------------

def followup_body(thread: dict) -> str:
    """A follow-up that re-asks ONLY what he already approved asking. Nothing new
    is said, which is what keeps it inside a grant's purpose."""
    still = _still_open(thread)
    name = _first(_name(thread))
    if still:
        asked = " ".join(a["text"] for a in still[:3])
        middle = f"Just following up on my earlier question: {asked}" if len(still) == 1 else \
            f"Just following up on my earlier questions: {asked}"
    else:
        middle = f"Just following up on my earlier email about {thread.get('purpose') or thread.get('subject')}."
    return f"Hi {name},\n\n{middle}\n\nThanks,\n{_signature(thread)}"


def followup(thread_id: str, *, now: dt.datetime | None = None) -> dict:
    """Draft the follow-up now; `conversation_authority` decides whether his
    standing grant covers it or it asks."""
    now = _now(now)
    thread = load(thread_id)
    if thread.get("state") == CLOSED:
        raise ConversationError("that conversation is closed")
    if not any(m.get("state") == M_SENT for m in thread.get("messages") or []):
        raise ConversationError("nothing has been sent on that conversation yet, so there is nothing to follow up on")
    if int(thread["follow_up"].get("sent") or 0) >= int(thread["follow_up"].get("max") or MAX_FOLLOW_UPS):
        raise ConversationError(f"I've already followed up {thread['follow_up']['sent']} times")
    _transition(thread, FOLLOW_UP_DUE, "no answer yet to what I asked", "draft and send the follow-up", now=now)
    return draft_message(load(thread_id), followup_body(thread), kind="followup", now=now)


def followups_due(*, now: dt.datetime | None = None) -> list[dict]:
    now = _now(now)
    out = []
    for thread in all_threads(AWAITING_REPLY):
        due = _parse((thread.get("follow_up") or {}).get("due"))
        if due and due <= now and not any(m.get("state") == M_AWAITING for m in thread.get("messages") or []):
            out.append(thread)
    return out


# ---- the beat -------------------------------------------------------------------------

def reconcile(*, now: dt.datetime | None = None, transport=None, think=None, use_model: bool = True,
              provider=None, estimator=None, facts: Facts | None = None) -> dict:
    """One beat: send what is approved, read replies, act on them, follow up
    what is due, give up what is spent, write approved calendar holds. Never
    raises out of one conversation into the next."""
    now = _now(now)
    summary: dict[str, Any] = {"sent": [], "replies": [], "followups": [], "closed": [], "calendar": [],
                               "errors": []}
    try:
        from aletheia import communications
        communications.evaluate_all(now=now)
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(f"expectations: {type(exc).__name__}")
    for name, step in (("sent", lambda: send_approved(transport=transport, now=now)),
                       ("replies", lambda: check_replies(transport=transport, now=now, think=think,
                                                         use_model=use_model, facts=facts, provider=provider,
                                                         estimator=estimator))):
        try:
            summary[name] = step()
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"{name}: {type(exc).__name__}: {str(exc)[:120]}")
    if policy.halted() is None:
        for thread in followups_due(now=now):
            try:
                if int(thread["follow_up"].get("sent") or 0) >= int(thread["follow_up"].get("max") or MAX_FOLLOW_UPS):
                    _tell(f"No answer from {_name(thread)}",
                          f"I followed up {thread['follow_up']['sent']} times about {thread.get('subject')} "
                          "and heard nothing, so I've stopped.", f"conv-gaveup:{thread['id']}")
                    _transition(thread, CLOSED, f"no answer after {thread['follow_up']['sent']} follow-ups", "nothing",
                                now=now)
                    summary["closed"].append(thread["id"])
                    continue
                after = followup(thread["id"], now=now)
                last = after["messages"][-1]
                summary["followups"].append({"thread": thread["id"], "covered_by_grant": bool(last.get("granted_by")),
                                             "state": after["state"]})
            except Exception as exc:  # noqa: BLE001
                summary["errors"].append(f"followup {thread['id']}: {type(exc).__name__}: {str(exc)[:120]}")
        if summary["followups"]:
            try:
                summary["sent"] += send_approved(transport=transport, now=now)
            except Exception as exc:  # noqa: BLE001
                summary["errors"].append(f"sent: {type(exc).__name__}")
    try:
        summary["calendar"] = calendar_reasoning.execute_approved_writes(provider=provider)
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(f"calendar: {type(exc).__name__}")
    return summary


# ---- reading back -----------------------------------------------------------------------

def work_view(thread: dict) -> dict:
    """This conversation in the shared work vocabulary (`work_states`)."""
    from aletheia import work_states as ws
    state = thread.get("state")
    pending = next((m for m in thread.get("messages") or [] if m.get("state") == M_AWAITING), None)
    common = {"reason": thread.get("reason") or "", "next": thread.get("next") or "", "not_before": None,
              "requires": ["email"], "evidence": {}}
    if state == CLOSED:
        return {**common, "state": ws.DONE}
    if state == AWAITING_APPROVAL and pending:
        return {**common, "state": ws.BLOCKED_USER, "requires": ["email", "user_approval"],
                "evidence": {"approval": pending["approval"]}}
    if state == AWAITING_APPROVAL or state == FOLLOW_UP_DUE:
        return {**common, "state": ws.READY}
    if state in (DRAFTED, REPLIED):
        return {**common, "state": ws.BLOCKED_USER, "requires": ["email", "user_decision"]}
    if state in (AWAITING_REPLY, SENT):
        due = (thread.get("follow_up") or {}).get("due")
        return {**common, "state": ws.BLOCKED_EXTERNAL, "requires": ["email", "external_reply"], "not_before": due}
    return {**common, "state": ws.READY}


def summary(now: dt.datetime | None = None) -> dict:
    """The compact block for current_state and mission control. Never raises."""
    try:
        now = _now(now)
        threads = all_threads()
        live = [t for t in threads if t.get("state") != CLOSED]
        def brief(t):
            return {"id": t["id"], "with": _name(t), "subject": t.get("subject"), "state": t.get("state"),
                    "reason": t.get("reason"), "next": t.get("next"),
                    "follow_up_due": (t.get("follow_up") or {}).get("due"),
                    "approval": next((m["approval"] for m in t.get("messages") or [] if m.get("state") == M_AWAITING), None)}
        due = {t["id"] for t in followups_due(now=now)}
        holds = calendar_reasoning.upcoming_holds(now=now)
        conflicts = calendar_reasoning.conflicts_now(now=now)
        value = {
            "readable": True, "open": len(live),
            "needs_approval": [brief(t) for t in live if t.get("state") == AWAITING_APPROVAL],
            "awaiting_reply": [brief(t) for t in live if t.get("state") == AWAITING_REPLY and t["id"] not in due],
            "follow_up_due": [brief(t) for t in live if t["id"] in due or t.get("state") == FOLLOW_UP_DUE],
            "needs_caleb": [brief(t) for t in live if t.get("state") in (REPLIED, DRAFTED)],
            "recently_closed": [brief(t) for t in threads if t.get("state") == CLOSED
                                and (_parse(t.get("updated_at")) or now) >= now - dt.timedelta(days=1)],
            "holds": [{"id": h["id"], "title": h.get("title"), "start": h["start"], "status": h.get("status"),
                       "human": calendar_reasoning.human(h["start"], now=now)} for h in holds],
            "conflicts": conflicts,
        }
        value["said"] = spoken_summary(value)
        return value
    except Exception as exc:  # noqa: BLE001
        return {"readable": False, "note": f"the conversations could not be read ({type(exc).__name__})"}


def spoken_summary(value: dict) -> str:
    from aletheia import speech
    parts = []
    if value.get("needs_approval"):
        parts.append(f"{speech.count_phrase(len(value['needs_approval']), 'message')} waiting for your okay")
    if value.get("needs_caleb"):
        parts.append(f"{speech.count_phrase(len(value['needs_caleb']), 'conversation')} needing your answer")
    if value.get("awaiting_reply"):
        parts.append(f"waiting to hear back from {speech.and_list([t['with'] for t in value['awaiting_reply'][:3]])}")
    if value.get("follow_up_due"):
        parts.append(f"{speech.count_phrase(len(value['follow_up_due']), 'follow-up')} due")
    if not parts:
        return "No conversations are waiting on anything."
    return speech.and_list(parts)[:1].upper() + speech.and_list(parts)[1:] + "."


def status_words(which: str = "", *, now: dt.datetime | None = None) -> str:
    """"Did they reply?" answered from the thread, in a sentence."""
    now = _now(now)
    try:
        thread = resolve_thread(which)
    except LookupError as exc:
        text = str(exc)
        return text[:1].upper() + text[1:] + ("." if not text.endswith((".", "?")) else "")
    name = _name(thread)
    replies = thread.get("replies") or []
    state = thread.get("state")
    if replies:
        last = replies[-1]
        when = calendar_reasoning.human(str(last.get("received_at") or _stamp(now)), now=now)
        what = {"scheduling_proposal": "they offered times", "answered": "they answered",
                "question_back": "they asked you something", "rejection": "they said no",
                "auto_reply": "it was an automatic reply", "bounce": "the email bounced",
                "unrelated": "it was about something else"}.get(last.get("category"), "they wrote back")
        head = f"Yes, {name} replied {when}: {what}."
    elif state in (AWAITING_REPLY, FOLLOW_UP_DUE):
        head = f"No reply from {name} yet."
    else:
        head = f"Nothing has gone to {name} yet."
    return f"{head} {_next_words(thread, now)}".strip()


def _next_words(thread: dict, now: dt.datetime) -> str:
    state = thread.get("state")
    if state == AWAITING_APPROVAL:
        return f"A message is waiting for your okay: {thread.get('reason') or ''}".rstrip(" :") + "."
    if state == AWAITING_REPLY:
        due = (thread.get("follow_up") or {}).get("due")
        return (f"I'll follow up {calendar_reasoning.human(due, now=now)} if they haven't answered." if due
                else "I'm waiting on them.")
    if state == REPLIED:
        return f"{str(thread.get('reason') or '')[:1].upper()}{str(thread.get('reason') or '')[1:]}; that needs you."
    if state == CLOSED:
        return f"It's closed: {thread.get('reason')}."
    if state == DRAFTED:
        return f"It's waiting: {thread.get('reason')}"
    return ""


def spoken(thread: dict) -> str:
    name = _name(thread)
    state = thread.get("state")
    if state == AWAITING_APPROVAL:
        message = next((m for m in thread.get("messages") or [] if m.get("state") == M_AWAITING), {})
        return (f"I drafted an email to {name} about {thread.get('subject')}. It's waiting for your okay "
                "before it goes.") if message.get("kind") == "first" else \
            f"I drafted a reply to {name}; it's waiting for your okay."
    if state == DRAFTED:
        return f"I started the email about {thread.get('purpose')}, but {thread.get('reason')}"
    if state == FOLLOW_UP_DUE:
        return f"The follow-up to {name} is covered by the permission you gave, so it goes out next."
    return status_words(thread["id"])


# ---- CLI --------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Conversations she carries: draft, send, wait, follow up.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p_show = sub.add_parser("show"); p_show.add_argument("which")
    p_status = sub.add_parser("status"); p_status.add_argument("which", nargs="?", default="")
    p_new = sub.add_parser("new"); p_new.add_argument("to"); p_new.add_argument("about")
    p_new.add_argument("--body", default=None); p_new.add_argument("--ask", action="append", default=[])
    p_grant = sub.add_parser("grant", help="HIS words giving standing permission for follow-ups")
    p_grant.add_argument("words")
    p_off = sub.add_parser("grant-off"); p_off.add_argument("which")
    sub.add_parser("reconcile")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "list":
            for thread in all_threads():
                print(f"{thread['id']:18} {thread['state']:18} {_name(thread)} - {thread.get('subject')}")
        elif args.cmd == "show":
            print(json.dumps(resolve_thread(args.which), indent=2, ensure_ascii=False))
        elif args.cmd == "status":
            print(status_words(args.which))
        elif args.cmd == "new":
            print(spoken(start(args.to, about=args.about, body=args.body, asks=args.ask, via="operator-cli")))
        elif args.cmd == "grant":
            grant = conversation_authority.grant_from_words(args.words, via="operator-cli")
            print(f"Granted {grant['id']}: up to {grant['max_uses']} follow-up(s) until {grant['expires']}.")
        elif args.cmd == "grant-off":
            gone = conversation_authority.revoke_for(resolve_thread(args.which)["id"], via="operator-cli")
            print(f"Revoked {len(gone)} permission(s).")
        else:
            print(json.dumps(reconcile(), indent=2, default=str))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
