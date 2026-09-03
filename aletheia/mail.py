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

Inbox polling is also read-only. On the first poll, the current unread set is
baselined without emitting events; this prevents old unread mail from becoming
fake "new" notifications when the feature is first enabled. Later unseen
headers are fingerprinted locally and emitted once as `mail.received`. If
exactly one WAITING communication expectation resolves to the sender (and, when
necessary, the thread subject), that header is recorded as an inbound
communication and emits `mail.reply`. Ambiguity is surfaced as
`mail.reply_ambiguous`; Aletheia never guesses which conversation a message
belongs to.
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
POLL_MIN_INTERVAL_S = 300  # one IMAP login per 5 min is plenty; a login per
                           # Core beat got throttled by Gmail live 2026-08-26
NETWORK_TIMEOUT_S = 15     # a hung socket must never hang the runtime


SECRET_NAME = "mail.password"


def stored_password() -> str:
    """The app password out of the DPAPI vault, or "" if it is not there.

    Added 2026-09-03. It lived in `~/.aletheia/mail.json` as plain text,
    which a security review named correctly: gitignored is not encrypted.
    Any process running as him, any backup or sync that follows the folder,
    any archive of the home directory carried a working credential to his
    mailbox. `aletheia.secret_store` seals a secret with Windows DPAPI to
    this user on this machine, and has since the secrets slice landed — the
    mail path simply never used it.

    Reading is best-effort: a machine without DPAPI (or a vault that has
    not been written yet) falls through to the environment and then to the
    legacy file, so nothing breaks while he migrates.
    """
    try:
        from aletheia import secret_store
        return secret_store.get(SECRET_NAME)
    except Exception:
        return ""


def _config() -> dict:
    cfg = {}
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cfg = {}
    # env (an explicit override) -> sealed vault -> the legacy plaintext file
    password = (os.environ.get("ALETHEIA_MAIL_PASSWORD", "")
                or stored_password() or cfg.get("password", ""))
    return {
        "address": os.environ.get("ALETHEIA_MAIL_ADDRESS", cfg.get("address", "")),
        "password": password,
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


def migrate_password_to_vault() -> dict:
    """Move the app password from the plaintext file into the sealed vault.

    Idempotent, and it does not delete anything it has not first verified
    it can read back — losing his mail credential to a tidy-up would be a
    worse outcome than the plaintext it is fixing.
    """
    from aletheia import secret_store
    ok, why = secret_store.available()
    if not ok:
        return {"moved": False, "reason": why}
    if not CONFIG_FILE.exists():
        return {"moved": False, "reason": "no legacy mail.json to migrate"}
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"moved": False, "reason": f"mail.json is unreadable: {type(exc).__name__}"}
    secret = str(cfg.get("password", ""))
    if not secret:
        return {"moved": False, "reason": "mail.json holds no password"}
    secret_store.put(SECRET_NAME, secret, provider="mail", kind="app_password")
    if secret_store.get(SECRET_NAME) != secret:
        return {"moved": False, "reason": "the vault did not read back what was written"}
    cfg.pop("password", None)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    journal.append("event", "mail:secret",
                   "the mail app password moved from mail.json into the DPAPI vault",
                   actor=ACTOR)
    return {"moved": True, "vault_name": SECRET_NAME, "file": str(CONFIG_FILE)}


MAX_BODY_CHARS = 6_000


class MailError(RuntimeError):
    pass


class MailTransport(Protocol):
    def fetch_unread(self, limit: int) -> list[dict]: ...
    def fetch_body(self, message_id: str) -> dict: ...
    def send(self, msg: EmailMessage) -> None: ...


def _body_text(msg) -> str:
    """The readable text of a parsed message: text/plain first, else the
    HTML with its tags stripped. Attachments are never opened."""
    from html.parser import HTMLParser

    class _Strip(HTMLParser):
        def __init__(self):
            super().__init__(); self.out = []; self.skip = 0

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style"):
                self.skip += 1
            elif tag in ("p", "br", "div", "li", "tr", "h1", "h2", "h3"):
                self.out.append("\n")

        def handle_endtag(self, tag):
            if tag in ("script", "style") and self.skip:
                self.skip -= 1

        def handle_data(self, data):
            if not self.skip:
                self.out.append(data)

    plain, html_parts = [], []
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.get_content_maintype() != "text" or part.get_filename():
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            text = payload.decode(part.get_content_charset() or "utf-8", "replace")
        except (LookupError, ValueError):
            continue
        (plain if part.get_content_subtype() == "plain" else html_parts).append(text)
    if plain:
        text = "\n".join(plain)
    elif html_parts:
        stripper = _Strip(); stripper.feed("\n".join(html_parts)); text = "".join(stripper.out)
    else:
        text = ""
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:MAX_BODY_CHARS]


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
        with imaplib.IMAP4_SSL(self.cfg["imap_host"], timeout=NETWORK_TIMEOUT_S) as imap:
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

    def fetch_body(self, message_id: str) -> dict:
        """One message's text, found by its Message-ID. Read-only: the
        mailbox is opened readonly, so reading never marks anything seen."""
        import imaplib
        from email import message_from_bytes
        from email.header import decode_header, make_header
        mid = str(message_id or "").strip()
        if not mid:
            raise MailError("a Message-ID is required")
        with imaplib.IMAP4_SSL(self.cfg["imap_host"], timeout=NETWORK_TIMEOUT_S) as imap:
            imap.login(self.cfg["address"], self.cfg["password"])
            imap.select("INBOX", readonly=True)
            _, data = imap.search(None, "HEADER", "Message-ID", mid)
            ids = data[0].split()
            if not ids:
                raise MailError("that message is no longer in the inbox")
            _, msg_data = imap.fetch(ids[-1], "(BODY.PEEK[])")
            msg = message_from_bytes(msg_data[0][1])
        return {
            "from": str(make_header(decode_header(msg.get("From", "?")))),
            "subject": str(make_header(decode_header(msg.get("Subject", "(no subject)")))),
            "date": msg.get("Date", ""),
            "message_id": mid,
            "text": _body_text(msg),
        }

    def send(self, msg: EmailMessage) -> None:
        import smtplib
        with smtplib.SMTP(self.cfg["smtp_host"], 587, timeout=NETWORK_TIMEOUT_S) as smtp:
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
                   reversible=False, capability="email.send")
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


def read_body(which: str, limit: int = CHECK_LIMIT,
              transport: MailTransport | None = None) -> dict:
    """The text of ONE unread message, named by sender or subject.

    "What did the dentist say?" needs the body, and until 2026-09-02 she
    could read only headers. The match must be exactly one message: zero is
    an honest "nothing from them", more than one is a question back with
    the candidates — never a guess at which one he meant. The mailbox is
    read readonly, and the journal records the subject, never the text.
    """
    needle = str(which or "").strip().casefold()
    if not needle:
        raise MailError("say whose email, or what it is about")
    driver = transport or SmtpImapTransport()
    unread = driver.fetch_unread(limit)
    hits = [m for m in unread
            if needle in str(m.get("from", "")).casefold()
            or needle in str(m.get("subject", "")).casefold()]
    if not hits:
        raise MailError(f"no unread email matches {which!r}")
    if len(hits) > 1:
        listed = "; ".join(f"{m['subject']} (from {parseaddr(m['from'])[0] or m['from']})"
                           for m in hits[:5])
        raise MailError(f"{len(hits)} unread emails match {which!r} — which one: {listed}")
    message = driver.fetch_body(hits[0].get("message_id", ""))
    journal.append("action", "mail:read_body",
                   f"read body of {message['subject'][:80]!r} from "
                   f"{parseaddr(message['from'])[0] or message['from']}", actor=ACTOR)
    return message


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
    """Emit newly observed unread headers once and correlate exact replies.

    The first poll baselines the current unread set rather than claiming old
    messages are newly received. This does not mark mail read. The seen set
    stores sha256 fingerprints only.
    """
    if limit < 1 or limit > 500:
        raise ValueError("mail poll limit must be between 1 and 500")
    MAIL_DIR.mkdir(parents=True, exist_ok=True)
    state_path = MAIL_DIR / "poll-state.json"
    state_exists = state_path.is_file()
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {"version": 1, "seen": []}
    if transport is None and state_exists and state.get("updated_at"):
        # rate-limit REAL polls only; an injected transport is a test/tool
        try:
            last = dt.datetime.fromisoformat(str(state["updated_at"]).replace("Z", "+00:00"))
            age = (dt.datetime.now(dt.timezone.utc) - last).total_seconds()
            if 0 <= age < POLL_MIN_INTERVAL_S:
                return []
        except ValueError:
            pass
    driver = transport or SmtpImapTransport()
    unread = driver.fetch_unread(limit)
    seen_order = [str(x) for x in state.get("seen", []) if isinstance(x, str)]
    if not state_exists:
        baseline = [_fingerprint(message) for message in unread]
        write_json_atomic(state_path, {"version": 1, "seen": baseline[-POLL_SEEN_LIMIT:],
                                       "updated_at": utcnow()})
        return [{"action": "baseline", "count": len(unread)}]
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
    write_json_atomic(state_path, {"version": 1, "seen": seen_order[-POLL_SEEN_LIMIT:],
                                   "updated_at": utcnow()})
    return actions
