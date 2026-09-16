"""Verification codes and links, read out of his mailbox as EVENTS for a browser mission.

The brief (docs/JARVIS_BRIEF.md §4): "verification codes as events". The
general browser loop already stops at EMAIL_VERIFICATION and takes a code
from `browser_mission.post_event` or from a `code_source`. This module is
the code source that reads his inbox, so a mission waiting on a site's
email does not have to wait on him too.

What it will do, and nothing else:

- READ ONLY. The mailbox is opened readonly and bodies are peeked
  (`mail.SmtpImapTransport.fetch_recent`): nothing is marked seen, moved,
  replied to or deleted. There is no send path in this module.
- ONLY MAIL FROM THAT SITE. The sender's domain must be the site's own
  domain (or a parent/child of it), or a sender domain the REVIEWED seed
  names for that site's family (Greenhouse mails from greenhouse-mail.io).
  A learned skill cannot widen that list.
- ONLY MAIL THAT ARRIVED AFTER THE MISSION STARTED. A code older than the
  mission is some other attempt's code: live 2026-09-12 a stale code was
  typed into Reddit's form because the lookup ran nineteen seconds before
  the right one arrived (`apply_run._emailed_code`, same lesson).
- A LINK ONLY ONTO THE SAME SITE. A verification link that points anywhere
  else is not followed; the loop's own `_same_site` check refuses it again.

When mail is not configured it says so plainly, and the mission's stop
carries that sentence - "I can't read your mail, so give me the code".
"""
from __future__ import annotations

import datetime as dt
import re
import time
from email.utils import parseaddr, parsedate_to_datetime
from urllib.parse import urlparse

#: How long a waiting mission polls, by default: codes usually land within a
#: minute; a site that takes longer is a stop he can finish.
POLL_TRIES = 8
POLL_WAIT_S = 15.0
#: Clock skew allowed between a sender's Date header and the mission start.
SKEW_S = 30.0
MAX_MESSAGES = 25

#: Greenhouse: "Copy and paste this code into the security code field on your
#: application: ApHIj2MW" (proved on his real mail 2026-09-12; mixed case).
_CODE_FIELD = re.compile(r"(?:code|codes?)\s*(?:field[^:]{0,30})?[:\s]\s*([A-Za-z0-9]{6,10})\b")
#: "Your verification code is 482913", "code: 4829-13", "482913 is your code".
_CODE_IS = re.compile(r"\b(?:code|passcode|pin|otp)\b(?:\s+is)?\s*[:\-]?\s*([A-Za-z0-9]{4,10}(?:-[A-Za-z0-9]{2,6})?)\b",
                      re.I)
_CODE_BEFORE = re.compile(r"\b([A-Za-z0-9]{4,10})\b(?=\s+is\s+your\s+(?:\w+\s+){0,2}(?:code|passcode|pin))", re.I)
_NOT_A_CODE = frozenset({"security", "greenhouse", "application", "resubmit", "verification", "password",
                         "continue", "below", "above", "expires", "please", "enter", "field", "which",
                         "will", "your", "this", "that", "from", "here", "sent", "code", "valid"})
_VERIFY_LINK = re.compile(r"verif|confirm|activat|validat|magic|token|signin|sign-in|login", re.I)


class MailUnavailable(RuntimeError):
    pass


def _domain(value: str) -> str:
    text = str(value or "").strip().casefold()
    host = urlparse(text).hostname if "://" in text else text.rsplit("@", 1)[-1].split("/")[0]
    return re.sub(r"^www\.", "", str(host or "")).strip(".")


def _related(a: str, b: str) -> bool:
    return bool(a and b) and (a == b or a.endswith("." + b) or b.endswith("." + a))


def _base(host: str) -> str:
    """The last two labels: jobs.acme.com and mail.acme.com are one sender."""
    parts = [p for p in str(host or "").split(".") if p]
    if len(parts) >= 3 and len(parts[-1]) == 2 and len(parts[-2]) <= 3:
        return ".".join(parts[-3:])          # acme.co.uk, not every .co.uk sender
    return ".".join(parts[-2:]) if len(parts) >= 2 else str(host or "")


def sender_allowed(sender: str, site_url: str, mail_domains=()) -> bool:
    """Is this From address the site itself (or a sender its reviewed family names)?"""
    who = _domain(parseaddr(str(sender or ""))[1] or str(sender or ""))
    if not who:
        return False
    site = _domain(site_url)
    if _related(who, site) or (site and _base(who) == _base(site)):
        return True
    return any(_related(who, str(d).casefold()) for d in mail_domains or ())


def _sent_at(message: dict) -> float:
    try:
        return parsedate_to_datetime(str(message.get("date", ""))).timestamp()
    except Exception:
        return 0.0


def _started(record: dict) -> float:
    try:
        return dt.datetime.fromisoformat(str(record.get("created") or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()


def code_in(text: str) -> str:
    """The code out of one email's text, or "". The words are never it, and a
    candidate must carry a digit unless it is Greenhouse's mixed-case shape."""
    body = str(text or "")
    for pattern in (_CODE_FIELD, _CODE_IS, _CODE_BEFORE):
        for hit in pattern.finditer(body):
            found = (hit.group(1) or "").strip()
            if not found or found.casefold() in _NOT_A_CODE:
                continue
            mixed = re.search(r"[a-z]", found) and re.search(r"[A-Z]", found)
            if re.search(r"\d", found) or (pattern is _CODE_FIELD and mixed):
                return found
    return ""


def link_in(links, site_url: str) -> str:
    """The first verification-looking link onto the same site, or ""."""
    site = _domain(site_url)
    for link in links or []:
        host = _domain(link)
        if not (_related(host, site) or (site and _base(host) == _base(site))):
            continue
        if _VERIFY_LINK.search(str(link)):
            return str(link)
    return ""


class MailCodes:
    """A `code_source` for `browser_loop.pursue`: `source(record, via)`.

    `via` is "email" or "text" for a code and "link" for a verification
    link. Texts are not read here (no SMS store is wired to missions), so a
    text code is a stop he finishes. `why(record)` is the plain sentence for
    the stop when nothing was found."""

    def __init__(self, transport=None, *, tries: int = POLL_TRIES, wait_s: float = POLL_WAIT_S,
                 sleep=time.sleep, configured=None):
        self._transport = transport
        self.tries = max(1, int(tries))
        self.wait_s = float(wait_s)
        self.sleep = sleep
        self._configured = configured
        self.last_why = ""

    def _ready(self) -> tuple[bool, str]:
        if self._configured is not None:
            return self._configured()
        if self._transport is not None:
            return True, ""
        from aletheia import mail
        return mail.available()

    def transport(self):
        if self._transport is None:
            from aletheia import mail
            self._transport = mail.SmtpImapTransport()
        return self._transport

    def why(self, record: dict | None = None) -> str:
        return self.last_why

    def __call__(self, record: dict, via: str) -> str:
        if via == "text":
            self.last_why = "Codes sent by text are not something I can read, so that one is yours."
            return ""
        ok, reason = self._ready()
        if not ok:
            self.last_why = ("I can't read your mail to fetch it myself: " + str(reason).rstrip(".") + ".")
            return ""
        from aletheia import site_skills
        site_url = str(record.get("start_url") or "")
        here = str((record.get("boundary") or {}).get("url") or record.get("current_url") or "")
        mail_domains = site_skills.for_domain(site_url).get("mail_domains") or []
        since = _started(record) - SKEW_S
        seen_ids = set(record.get("mail_used") or [])
        for attempt in range(self.tries):
            try:
                messages = list(self.transport().fetch_recent(since, MAX_MESSAGES) or [])
            except Exception as exc:                          # noqa: BLE001
                self.last_why = f"I tried to read your mail and could not ({type(exc).__name__})."
                return ""
            mine = [m for m in messages
                    if _sent_at(m) >= since and str(m.get("message_id") or "") not in seen_ids
                    and sender_allowed(m.get("from", ""), site_url, mail_domains)]
            mine.sort(key=_sent_at, reverse=True)           # newest first, by its Date
            for message in mine:
                if via == "link":
                    found = link_in(message.get("links") or [], here or site_url) \
                        or link_in(message.get("links") or [], site_url)
                else:
                    found = code_in(f"{message.get('subject', '')}\n{message.get('text', '')}")
                if found:
                    record.setdefault("mail_used", []).append(str(message.get("message_id") or ""))
                    self.last_why = ""
                    return found
            if attempt + 1 < self.tries:
                self.sleep(self.wait_s)
        what = "link" if via == "link" else "code"
        self.last_why = (f"I watched your inbox for the {what} from {site_skills.domain_of(site_url)} "
                         f"for about {int(self.tries * self.wait_s)} seconds and it has not arrived.")
        return ""


def source(**kwargs) -> MailCodes:
    return MailCodes(**kwargs)
