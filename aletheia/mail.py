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
enters git — drafts and receipts live in `state/mail/` which is
GITIGNORED; the approval and the journal carry only the subject, a
display name, and the draft's sha256. Credentials are never in the repo:
environment variables or `~/.aletheia/mail.json` on the PC, nothing else.

Authority binds to the CONTENT, not the session (same design the review
ratified for computer control): the approval stores a sha256 of the
exact draft; a draft edited after approval no longer matches and is
refused. One approval, one send — a .sent receipt makes redelivery
impossible.

Config (NEEDS_CONFIGURATION until the operator provides it, on the PC):
  ALETHEIA_MAIL_ADDRESS   the account (e.g. Gmail address)
  ALETHEIA_MAIL_PASSWORD  an app password — never the real password
  ALETHEIA_IMAP_HOST / ALETHEIA_SMTP_HOST  (default: Gmail's)
or the same keys, lowercase, in ~/.aletheia/mail.json.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import uuid
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
from typing import Protocol

from aletheia import journal, memory, policy
from aletheia.fleet import REPO_ROOT

MAIL_DIR = REPO_ROOT / "state" / "mail"          # gitignored — see module doc
CONFIG_FILE = Path.home() / ".aletheia" / "mail.json"
ACTOR = "aletheia-mail"
MAX_BODY_CHARS = 20_000
CHECK_LIMIT = 5


def _config() -> dict:
    cfg = {}
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cfg = {}
    out = {
        "address": os.environ.get("ALETHEIA_MAIL_ADDRESS", cfg.get("address", "")),
        "password": os.environ.get("ALETHEIA_MAIL_PASSWORD", cfg.get("password", "")),
        "imap_host": os.environ.get("ALETHEIA_IMAP_HOST",
                                    cfg.get("imap_host", "imap.gmail.com")),
        "smtp_host": os.environ.get("ALETHEIA_SMTP_HOST",
                                    cfg.get("smtp_host", "smtp.gmail.com")),
    }
    return out


def available() -> tuple[bool, str]:
    c = _config()
    if not c["address"] or not c["password"]:
        return False, ("mail is not configured: set ALETHEIA_MAIL_ADDRESS and "
                       "ALETHEIA_MAIL_PASSWORD (an app password), or write "
                       f"{CONFIG_FILE} — see aletheia/mail.py")
    return True, f"configured for {c['address']}"


class MailTransport(Protocol):
    """Seam so policy is testable without a mail server (like ComputerBackend)."""

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
                })
        return out

    def send(self, msg: EmailMessage) -> None:
        import smtplib
        with smtplib.SMTP(self.cfg["smtp_host"], 587) as smtp:
            smtp.starttls()
            smtp.login(self.cfg["address"], self.cfg["password"])
            smtp.send_message(msg)


def resolve_address(who: str) -> tuple[str | None, str]:
    """A spoken name or address -> (email, display_name). Names come from
    memory (domain "people"); an unknown name is an honest miss, never a
    guess — email to a wrong address is an unrecallable disclosure."""
    text = who.strip()
    spoken = re.sub(r"\s+at\s+", "@", text, flags=re.I)
    spoken = re.sub(r"\s+dot\s+", ".", spoken, flags=re.I).replace(" ", "")
    if "@" in spoken and "." in spoken.split("@")[-1]:
        addr = parseaddr(spoken)[1] or spoken
        return addr, addr.split("@")[0]
    key = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
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
    """Write a local draft and file its operator_always approval."""
    addr, name = resolve_address(to)
    if addr is None:
        raise ValueError(
            f"no address known for {name!r} — say: "
            f'"Thea, remember person {name} <their address>" first')
    if not body.strip():
        raise ValueError("the message body is empty")
    if len(body) > MAX_BODY_CHARS:
        raise ValueError(f"body exceeds {MAX_BODY_CHARS} characters")
    subject = subject.strip() or "Message from Caleb"
    d = {
        "id": f"mail-{uuid.uuid4().hex[:10]}",
        "to": addr,
        "to_name": name,
        "subject": subject,
        "body": body.strip(),
        "created": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "via": requested_via,
    }
    MAIL_DIR.mkdir(parents=True, exist_ok=True)
    (MAIL_DIR / f"{d['id']}.json").write_text(
        json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    policy.request(
        d["id"], f"email.send:{_draft_sha(d)}",
        reason=f"send email {subject!r} to {name}",
        consequence="the message is sent in Caleb's name and cannot be recalled",
        reversible=False)
    journal.append("action", "mail:draft",
                   f"draft {d['id']} to {name} — {subject!r}; approval pending",
                   actor=ACTOR)
    return d


def send_approved(transport: MailTransport | None = None) -> list[dict]:
    """Deliver every APPROVED, unsent draft; refuse anything that drifted.

    Called each Core tick, best-effort. A .sent receipt per draft makes
    delivery idempotent; a DENIED approval retires the draft.
    """
    if not MAIL_DIR.is_dir():
        return []
    results = []
    for path in sorted(MAIL_DIR.glob("mail-*.json")):
        if path.name.endswith((".sent.json", ".refused.json")):
            continue
        if path.with_suffix(".sent.json").exists() or \
           path.with_suffix(".refused.json").exists():
            continue
        d = json.loads(path.read_text(encoding="utf-8"))
        try:
            ap = policy.load(d["id"])
        except Exception:
            continue
        if ap.get("state") == "PENDING":
            continue
        result = {"id": d["id"], "to_name": d.get("to_name", "?"),
                  "subject": d["subject"]}
        if ap.get("state") != "APPROVED":
            result["outcome"] = "refused"
            result["detail"] = f"approval is {ap.get('state')}"
        elif ap.get("requested_action") != f"email.send:{_draft_sha(d)}":
            result["outcome"] = "refused"
            result["detail"] = "draft changed after approval — content no longer matches"
        else:
            try:
                driver = transport or SmtpImapTransport()
                msg = EmailMessage()
                msg["From"] = _config()["address"] or "aletheia"
                msg["To"] = d["to"]
                msg["Subject"] = d["subject"]
                msg.set_content(d["body"])
                driver.send(msg)
                result["outcome"] = "sent"
                result["detail"] = f"sent {d['subject']!r} to {d['to_name']}"
            except Exception as exc:
                # config/network trouble: leave the draft, retry next tick
                journal.append("event", "mail:send",
                               f"{d['id']} not sent yet: {type(exc).__name__}: {exc}",
                               actor=ACTOR)
                continue
        marker = ".sent.json" if result["outcome"] == "sent" else ".refused.json"
        path.with_suffix(marker).write_text(
            json.dumps({**result,
                        "at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
                       indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        journal.append("action", "mail:send",
                       f"{result['outcome']} — {result['detail']}", actor=ACTOR)
        results.append(result)
    return results


def check_unread(limit: int = CHECK_LIMIT,
                 transport: MailTransport | None = None) -> str:
    """A speakable one-liner about the inbox. Read-only, marks nothing."""
    driver = transport or SmtpImapTransport()
    unread = driver.fetch_unread(limit)
    if not unread:
        return "No unread email."
    parts = [f"{m['subject']} — from {parseaddr(m['from'])[0] or m['from']}"
             for m in unread]
    journal.append("action", "mail:check",
                   f"{len(unread)} unread reported", actor=ACTOR)
    head = f"{len(unread)} unread. " if len(unread) > 1 else "One unread: "
    return head + ". ".join(parts)
