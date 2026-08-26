"""Email — Phase 13, the first capability that touches the real world.

The vertical slice the playbook orders (§137): read -> draft -> approve ->
send -> verify, with sending behind `operator_always` (§56 L4: a message
in Caleb's name is a binding disclosure; no grant short-circuits it).

The flow, end to end by voice:
  "Thea, email <name> <message>"  -> draft written locally + approval filed
  the wall shows the pending approval (reason carries subject + name)
  "Thea, approve"                 -> approval APPROVED
  next Core tick                  -> send_approved() delivers it, journals,
                                     writes a .sent receipt (verify, §30)

Privacy: this repo is PUBLIC. Nothing that could identify a correspondent
enters git — drafts, receipts and mail-poll fingerprints live in `state/mail/`
which is GITIGNORED; bus events live in `state/private/`. The approval and the
journal carry only the subject, a display name, and the draft's sha256.
Credentials are never in the repo: environment variables or
`~/.aletheia/mail.json` on the PC, nothing else.

Authority binds to the CONTENT, not the session (same design the review
ratified for computer control): the approval stores a sha256 of the
exact draft; a draft edited after approval no longer matches and is
refused. One approval, one send — a .sent receipt makes redelivery
impossible.

Inbox polling is also read-only. New unread headers are fingerprinted locally
and emitted once as `mail.received`. If exactly one WAITING communication
expectation resolves to the sender (and, when necessary, the thread subject),
that header is recorded as an inbound communication and emits `mail.reply`.
Ambiguity is surfaced as `mail.reply_ambiguous`; Aletheia never guesses which
conversation a message belongs to.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import uuid
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Protocol

from aletheia import communications, events, journal, memory, policy
from aletheia.fleet import REPO_ROOT
from aletheia.stateio import utcnow, write_json_atomic

MAIL_DIR = REPO_ROOT / "state" / "mail"          # gitignored — see module doc
CONFIG_FILE = Path.home() / ".aletheia" / "mail.json"
ACTOR = "aletheia-mail"
MAX_BODY_CHARS = 20_000
CHECK_LIMIT = 5
POLL_SEEN_LIMIT = 2_000


def _config() -> dict:
    cfg = {}
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cfg = {}
    return {
        "address": os.environ.get("ALETHEIA_MAIL_ADDRESS", cfg.get("address", "")),
        "password": os.environ.get("ALETHEIA_MAIL_PASSWORD", cfg.get("password", "")),
        "imap_host": os.environ.get("ALETHEIA_IMAP_HOST", cfg.get("imap_host", "imap.gmail.com")),
        "smtp_host": os.environ.get("ALETHEIA_SMTP_HOST", cfg.get("smtp_host", "smtp.gmail.com")),
    }


def available() -> tuple[bool, str]:
    c = _config()
    if not c["address"] or not c["password"]:
        return False, ("mail is not configured: set ALETHEIA_MAIL_ADDRESS and "
                       "ALETHEIA_MAIL_PASSWORD (an app password), or write "
                       f"{CONFIG_FILE} — see aletheia/mail.py")
    return True, f"configured for {c['address']}"


class MailTransport(Protocol):
    def fetch_unread(self, limit: int) -> list[dict]: ...
    def send(self, msg: EmailMessage) -> None: ...


class SmtpImapTransport:
    """The real thing: IMAP4_SSL to read, SMTP+STARTTLS to send. Stdlib only."""
    def __init__(self) -> None:
        ok, reason = available()
        if not ok:
            raise RuntimeError(reason)
        self.cfg = _config()

    def fetch_unread(self, limit: int) -> list[dict]:
        import imaplib
        from email import message_from_bytes
        from email.header import decode_header, make_header
        out: list[dict] = []
        with imaplib.IMAP4_SSL(self.cfg["imap_host"]) as imap:
            imap.login(self.cfg["address"], self.cfg["password"])
            imap.select("INBOX", readonly=True)  # readonly: checking never marks read
            _, data = imap.search(None, "UNSEEN")
            ids = data[0].split()
            for mid in reversed(ids[-limit:]):
                _, msg_data = imap.fetch(mid, "(BODY.PEEK[HEADER])")
                msg = message_from_bytes(msg_data[0][1])
                out.append({
                    "from": str(make_header(decode_header(msg.get("From", "?")))),
                    "subject": str(make_header(decode_header(msg.get("Subject", "(no subject)")))),
                    "date": msg.get("Date", ""),
                    "message_id": msg.get("Message-ID", ""),
                })
        return out

    def send(self, msg: EmailMessage) -> None:
        import smtplib
        with smtplib.SMTP(self.cfg["smtp_host"], 587) as smtp:
            smtp.starttls()
            smtp.login(self.cfg["address"], self.cfg["password"])
            smtp.send_message(msg)


def resolve_address(who: str) -> tuple[str | None, str]:
    """A spoken name or address -> (email, display_name). Unknown is a miss."""
    text = who.strip()
    spoken = re.sub(r"\s+at\s+", "@", text, flags=re.I)
    spoken = re.sub(r"\s+dot\s+", ".", spoken, flags=re.I).replace(" ", "")
    if "@" in spoken and "." in spoken.split("@")[-1]:
        addr = parseaddr(spoken)[1] or spoken
        return addr, addr.split("@")[0]
    key = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    try:
        from aletheia import contacts
        return contacts.primary_email(contacts.resolve(text)), text
    except Exception:
        pass
    value = memory.recall("people", key)
    if isinstance(value, str) and "@" in value:
        return value, text
    if isinstance(value, dict) and "@" in str(value.get("email", "")):
        return value["email"], text
    return None, text


def _draft_sha(d: dict) -> str:
    canonical = json.dumps({k: d[k] for k in ("to", "subject", "body")},
                           sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def draft(to: str, subject: str, body: str, requested_via: str = "voice") -> dict:
    addr, name = resolve_address(to)
    if addr is None:
        raise ValueError(
            f"no address known for {name!r} — add them privately first: "
            f"python -m aletheia.contacts new <id> {name!r} --email <address>")
    if not body.strip():
        raise ValueError("the message body is empty")
    if len(body) > MAX_BODY_CHARS:
        raise ValueError(f"body exceeds {MAX_BODY_CHARS} characters")
    subject = subject.strip() or "Message from Caleb"
    d = {
        "id": f"mail-{uuid.uuid4().hex[:10]}", "to": addr, "to_name": name,
        "subject": subject, "body": body.strip(),
        "created": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "via": requested_via,
    }
    MAIL_DIR.mkdir(parents=True, exist_ok=True)
    (MAIL_DIR / f"{d['id']}.json").write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    policy.request(d["id"], f"email.send:{_draft_sha(d)}",
                   reason=f"send email {subject!r} to {name}",
                   consequence="the message is sent in Caleb's name and cannot be recalled",
                   reversible=False)
    journal.append("action", "mail:draft",
                   f"draft {d['id']} to {name} — {subject!r}; approval pending", actor=ACTOR)
    return d


def send_approved(transport: MailTransport | None = None) -> list[dict]:
    if not MAIL_DIR.is_dir():
        return []
    results = []
    for path in sorted(MAIL_DIR.glob("mail-*.json")):
        if path.name.endswith((".sent.json", ".refused.json")):
            continue
        if path.with_suffix(".sent.json").exists() or path.with_suffix(".refused.json").exists():
            continue
        d = json.loads(path.read_text(encoding="utf-8"))
        try:
            ap = policy.load(d["id"])
        except Exception:
            continue
        if ap.get("state") == "PENDING":
            continue
        result = {"id": d["id"], "to_name": d.get("to_name", "?"), "subject": d["subject"]}
        if ap.get("state") != "APPROVED":
            result["outcome"] = "refused"; result["detail"] = f"approval is {ap.get('state')}"
        elif ap.get("requested_action") != f"email.send:{_draft_sha(d)}":
            result["outcome"] = "refused"; result["detail"] = "draft changed after approval — content no longer matches"
        else:
            try:
                driver = transport or SmtpImapTransport()
                msg = EmailMessage(); msg["From"] = _config()["address"] or "aletheia"; msg["To"] = d["to"]; msg["Subject"] = d["subject"]
                msg.set_content(d["body"]); driver.send(msg)
                result["outcome"] = "sent"; result["detail"] = f"sent {d['subject']!r} to {d['to_name']}"
            except Exception as exc:
                journal.append("event", "mail:send", f"{d['id']} not sent yet: {type(exc).__name__}: {exc}", actor=ACTOR)
                continue
        marker = ".sent.json" if result["outcome"] == "sent" else ".refused.json"
        path.with_suffix(marker).write_text(json.dumps({**result, "at": utcnow()}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        journal.append("action", "mail:send", f"{result['outcome']} — {result['detail']}", actor=ACTOR)
        results.append(result)
    return results


def check_unread(limit: int = CHECK_LIMIT, transport: MailTransport | None = None) -> str:
    driver = transport or SmtpImapTransport()
    unread = driver.fetch_unread(limit)
    if not unread:
        return "No unread email."
    parts = [f"{m['subject']} — from {parseaddr(m['from'])[0] or m['from']}" for m in unread]
    journal.append("action", "mail:check", f"{len(unread)} unread reported", actor=ACTOR)
    return (f"{len(unread)} unread. " if len(unread) > 1 else "One unread: ") + ". ".join(parts)


def _fingerprint(message: dict) -> str:
    message_id = str(message.get("message_id", "")).strip().lower()
    if message_id:
        material = {"message_id": message_id}
    else:
        material = {k: str(message.get(k, "")).strip() for k in ("from", "subject", "date")}
    raw = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _subject_key(value: str) -> str:
    text = value.strip().casefold()
    while True:
        reduced = re.sub(r"^(re|fwd?|aw)\s*:\s*", "", text, flags=re.I)
        if reduced == text:
            break
        text = reduced
    return " ".join(text.split())


def _occurred_at(message: dict) -> str:
    try:
        parsed = parsedate_to_datetime(str(message.get("date", "")))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OverflowError):
        return utcnow()


def _reply_candidates(sender: str, subject: str) -> list[dict]:
    candidates = []
    for expectation in communications.all_expectations():
        if expectation.get("status") != "WAITING":
            continue
        expected, _ = resolve_address(expectation["from_participant"])
        if not expected or expected.casefold() != sender.casefold():
            continue
        candidates.append(expectation)
    if len(candidates) <= 1:
        return candidates
    subject_key = _subject_key(subject)
    narrowed = []
    for expectation in candidates:
        try:
            thread = communications.load_thread(expectation["thread_id"])
        except Exception:
            continue
        thread_subject = _subject_key(thread.get("subject", ""))
        if thread_subject and thread_subject == subject_key:
            narrowed.append(expectation)
    return narrowed if narrowed else candidates


def poll_events(limit: int = 50, transport: MailTransport | None = None) -> list[dict]:
    """Emit each newly observed unread header once and correlate exact replies.

    This does not mark mail read. The seen set stores sha256 fingerprints only.
    """
    if limit < 1 or limit > 500:
        raise ValueError("mail poll limit must be between 1 and 500")
    driver = transport or SmtpImapTransport()
    unread = driver.fetch_unread(limit)
    MAIL_DIR.mkdir(parents=True, exist_ok=True)
    state_path = MAIL_DIR / "poll-state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {"version": 1, "seen": []}
    seen_order = [str(x) for x in state.get("seen", []) if isinstance(x, str)]
    seen = set(seen_order)
    actions = []
    # fetch_unread is newest-first; process oldest unseen first for sane chronology.
    for message in reversed(unread):
        fp = _fingerprint(message)
        if fp in seen:
            continue
        display, sender = parseaddr(str(message.get("from", "")))
        sender = sender.strip().casefold()
        subject = str(message.get("subject", "(no subject)"))[:500]
        label = display or sender or "unknown sender"
        occurred = _occurred_at(message)
        emitted = events.emit(
            "mail.received", f"email:{sender or 'unknown'}", f"{subject} — from {label}",
            source="mail", occurred_at=occurred,
            attributes={"sender": sender, "fingerprint": fp[:24]},
        )
        actions.append({"action": "received", "event": emitted["event"]["id"], "fingerprint": fp})
        if sender:
            candidates = _reply_candidates(sender, subject)
            if len(candidates) == 1:
                expectation = candidates[0]
                message_id = f"mail-{fp[:24]}"
                try:
                    communications.record_message(
                        message_id, thread_id=expectation["thread_id"], direction="INBOUND",
                        channel="email", participant=expectation["from_participant"],
                        summary=subject, external_id=str(message.get("message_id") or fp),
                        occurred_at=occurred,
                    )
                except FileExistsError:
                    pass
                reply = events.emit(
                    "mail.reply", f"thread:{expectation['thread_id']}",
                    f"Reply from {expectation['from_participant']}: {subject}", source="mail",
                    occurred_at=occurred,
                    attributes={"thread_id": expectation["thread_id"],
                                "expectation_id": expectation["id"], "fingerprint": fp[:24]},
                )
                actions.append({"action": "reply", "event": reply["event"]["id"],
                                "expectation": expectation["id"]})
            elif len(candidates) > 1:
                ambiguous = events.emit(
                    "mail.reply_ambiguous", f"email:{sender}",
                    f"New mail from {label} matches {len(candidates)} waiting conversations; no thread chosen.",
                    source="mail", occurred_at=occurred,
                    attributes={"match_count": len(candidates), "fingerprint": fp[:24]},
                )
                actions.append({"action": "ambiguous", "event": ambiguous["event"]["id"],
                                "matches": len(candidates)})
        seen.add(fp); seen_order.append(fp)
    if actions:
        write_json_atomic(state_path, {"version": 1, "seen": seen_order[-POLL_SEEN_LIMIT:], "updated_at": utcnow()})
    return actions
