"""Text a person — and never press Send herself.

The most-asked-for thing she could not do. `python -m aletheia.demand`
has exactly one entry, and it is this one, thirteen times in his own
words: *"send a text"*. Registered NOT_BUILT on 2026-09-02 after the
planner, asked to text somebody, named `intercom.relay` as the closest
gap and then compiled a sandboxed program for it — a program with no
network cannot text anyone.

**Sending reaches another person, so it is `operator_always` (§56 L4,
§72–73) and there is no flag that turns that off.** He decides once, per
message, on the exact words and the exact number.

THE DESIGN, and the second half is the important one.

**One approval, and it binds the words AND the plan.** The approval's
action is `computer.approval_action(plan)` — a sha256 over the steps —
and the steps literally contain the number and the message text. So the
thing he approves and the thing that runs cannot drift apart: edit
either and the digest no longer matches an approval, which is refused.
Two approvals (one for content, one for the plan) would have meant her
raising the second one herself, and she may not approve her own work.

**She cannot press Send even with the approval in hand.**
`computer.act` — the unattended hands — refuses any control whose label
matches `COMMITTING_PATTERN`, and "Send" is the first word in it. That
refusal is not something this module works around; it is the mechanism
it relies on. The press runs through `computer.execute`, which demands
the plan-bound approval and re-reads the label off the LIVE control
before it commits.

**The launch is aimed, not generic.** `sms:` is a protocol three
packaged apps claim on this machine, so `start sms:...` opens a chooser
or the wrong app — the same trap `phone_windows._launch_tel` documents
for `tel:`. It is addressed to Phone Link's own AUMID, and this module
reuses that constant rather than writing a second copy of a fact that
was expensive to learn.

**An unknown recipient is refused and never guessed.** The same rule as
`mail.draft`: a text to the wrong number is not recoverable, and the
number for "Brant" is either on file or it is a question.

His words live in private state, gitignored, and never enter the repo.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import uuid
from pathlib import Path
from urllib.parse import quote

from aletheia import contacts, journal, policy, stateio

ACTOR = "messages"

# SMS segments at 160 characters and Phone Link will carry far more, but a
# body long enough to be a document is a sign the sentence went somewhere
# it should not have. Long enough for anything he would say out loud.
MAX_BODY_CHARS = 900

# The window Phone Link opens under. Matched loosely on purpose: the app
# has been renamed twice ("Your Phone", "Phone Link") and a title that
# has to be exact is a capability that breaks on a Windows update.
PHONE_LINK_WINDOW = r"(?i).*(phone link|your phone).*"


def message_dir() -> Path:
    return stateio.private_dir("messages")


def primary_number(contact: dict) -> str:
    """The one number for this person, or a question. Never a choice she makes."""
    contacts.validate(contact)
    phones = [p for p in (contact.get("phones") or []) if str(p).strip()]
    if not phones:
        raise LookupError(f"contact {contact['id']!r} has no phone number")
    if len(phones) > 1:
        raise LookupError(
            f"contact {contact['id']!r} has {len(phones)} numbers; say which")
    return phones[0]


def normalize_number(raw: str) -> str:
    """Digits and one optional leading +, which is what a dialler takes."""
    text = str(raw or "").strip()
    plus = text.startswith("+")
    digits = re.sub(r"\D", "", text)
    return ("+" if plus else "") + digits


def looks_like_a_number(text: str) -> bool:
    """Ten digits or more is a phone number; "Brant" is not.

    Deliberately strict. A short string of digits is a house number, a
    time, or a mis-transcription, and texting one of those reaches
    somebody who is not expecting it.
    """
    digits = re.sub(r"\D", "", str(text or ""))
    return 10 <= len(digits) <= 15


def resolve_number(who: str) -> tuple[str | None, str]:
    """A spoken name or a spoken number -> (number, display name).

    Unknown is a MISS, never a guess: `(None, name)` and the caller
    turns that into a question. Same rule as `mail.resolve_address`.
    """
    text = str(who or "").strip()
    if not text:
        return None, text
    if looks_like_a_number(text):
        return normalize_number(text), normalize_number(text)
    try:
        contact = contacts.resolve(text)
    except Exception:
        return None, text
    try:
        return normalize_number(primary_number(contact)), \
            contact.get("display_name") or text
    except LookupError:
        return None, contact.get("display_name") or text


def plan(number: str, body: str) -> list[dict]:
    """The three steps, with his words inside them so the digest covers them.

    Step 3 is the one `computer.act` refuses. That is the point: the
    compose is unattended hands, the Send is his decision.
    """
    target = f"sms:{number}?body={quote(body, safe='')}"
    return [
        {"action": "open_app",
         # Addressed to Phone Link itself. `start sms:` uses whatever holds
         # the protocol association, and on this machine that is not it.
         "app": f"shell:AppsFolder\\{_phone_link_aumid()}",
         "arguments": [target]},
        {"action": "wait_window", "window": {"title_re": PHONE_LINK_WINDOW}},
        {"action": "invoke", "window": {"title_re": PHONE_LINK_WINDOW},
         "control": {"title": "Send"}},
    ]


def _phone_link_aumid() -> str:
    """Phone Link's AUMID, from the module that proved it on this PC."""
    try:
        from aletheia import phone_windows
        return phone_windows.PHONE_LINK_AUMID
    except Exception:
        return "Microsoft.YourPhone_8wekyb3d8bbwe!App"


def content_sha(number: str, body: str) -> str:
    """What he is agreeing to, in one line: this text, to this number."""
    canonical = json.dumps({"to": number, "body": body},
                           sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def draft(to: str, body: str, requested_via: str = "voice") -> dict:
    """Write it down, bind an approval to it, and stop.

    Nothing is sent here and nothing is opened here. The draft is a file
    and an approval; the world is touched only by `send_approved`, and
    only after he has said yes to this exact pair of things.
    """
    from aletheia import computer

    number, name = resolve_number(to)
    if number is None:
        raise ValueError(
            f"no phone number on file for {name!r} — add it privately first: "
            f"python -m aletheia.contacts new <id> {name!r} --phone <number>")
    body = str(body or "").strip()
    if not body:
        raise ValueError("the message is empty")
    if len(body) > MAX_BODY_CHARS:
        raise ValueError(f"the message is longer than {MAX_BODY_CHARS} characters")

    steps = plan(number, body)
    record = {
        "id": f"msg-{uuid.uuid4().hex[:10]}",
        "to": number, "to_name": name, "body": body,
        "content_sha": content_sha(number, body),
        "created": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "via": requested_via,
    }
    message_dir().mkdir(parents=True, exist_ok=True)
    stateio.write_json_atomic(message_dir() / f"{record['id']}.json", record)

    # ONE approval over the plan, and the plan carries the words. He is
    # deciding on the message, and the digest makes the message and the
    # keystrokes the same object.
    policy.request(
        record["id"], computer.approval_action(steps),
        reason=f"text {name}: {body[:120]}",
        consequence="the message is sent from his phone, in his name, "
                    "and cannot be recalled",
        reversible=False, capability="message.send")
    # The BODY is his and does not travel to a public log; that it exists does.
    journal.append("action", "messages:draft",
                   f"draft {record['id']} to {name}; approval pending",
                   actor=ACTOR)
    return record


def pending() -> list[dict]:
    """Drafts that have neither been sent nor refused."""
    directory = message_dir()
    if not directory.is_dir():
        return []
    out = []
    for path in sorted(directory.glob("msg-*.json")):
        if path.name.endswith((".sent.json", ".refused.json")):
            continue
        if (path.with_suffix(".sent.json").exists()
                or path.with_suffix(".refused.json").exists()):
            continue
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def send_approved(hands=None) -> list[dict]:
    """Send every draft he has approved, and nothing else.

    `hands` is the injection point the tests drive; live it is
    `computer.execute`, which re-reads the Send control's label off the
    screen before it presses anything.
    """
    from aletheia import computer

    results = []
    for record in pending():
        try:
            approval = policy.load(record["id"])
        except Exception:
            continue
        state = str(approval.get("state") or "")
        if state == "DENIED":
            _retire(record, "refused", "denied by operator")
            results.append({"id": record["id"], "state": "REFUSED"})
            continue
        if state != "APPROVED":
            continue

        steps = plan(record["to"], record["body"])
        # If either the number or the words changed since he agreed, the
        # digest no longer matches and execute() refuses. Checked here too
        # so the refusal is a sentence rather than a stack trace.
        if computer.approval_action(steps) != str(approval.get("requested_action")):
            _retire(record, "refused", "the message changed after it was approved")
            results.append({"id": record["id"], "state": "REFUSED",
                            "why": "edited after approval"})
            continue

        run = hands or computer.execute
        try:
            outcome = run(steps, approval=record["id"])
        except Exception as exc:
            journal.append("action", "messages:send",
                           f"{record['id']} to {record['to_name']} did not send: "
                           f"{type(exc).__name__}", actor=ACTOR)
            results.append({"id": record["id"], "state": "FAILED",
                            "why": str(exc)[:200]})
            continue
        _retire(record, "sent", "sent")
        journal.append("action", "messages:send",
                       f"texted {record['to_name']}", actor=ACTOR)
        results.append({"id": record["id"], "state": "SENT", "result": outcome})
    return results


def _retire(record: dict, suffix: str, why: str) -> None:
    path = message_dir() / f"{record['id']}.{suffix}.json"
    stateio.write_json_atomic(path, dict(record, outcome=why,
                                         at=stateio.utcnow()))
    original = message_dir() / f"{record['id']}.json"
    try:
        original.unlink()
    except OSError:
        pass
