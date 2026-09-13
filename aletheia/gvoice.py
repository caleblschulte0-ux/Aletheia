"""Reading his Google Voice texts, so an SMS code is not a dead end.

The signup number is a Google Voice line (`profile.signup_phone`). Half of
what she will sign up for sends its verification code by TEXT rather than
email, and until now she could read the inbox and not the texts — so an
account got as far as "we sent you a code" and stopped, with the code
sitting in a tab he would have to go and read himself. That is the exact
shape of the thing this system exists to avoid: she does 90% of a job and
hands him the last 10% at the moment it is least convenient.

**A CODE THAT IS OLD IS WRONG, AND WRONG QUIETLY.** Learned the hard way on
2026-09-12, in the mail path: she typed an hour-old code into the box and
the form said no, and the failure read like a broken form rather than a
stale code. `latest_code` therefore takes a `since` and refuses anything
older — a code she cannot date is not a code she may use.

**IT READS. IT NEVER REPLIES.** Nothing here sends a text. Reading his
messages is already a large thing to be able to do; sending as him is a
different capability with a different risk, and it is not this one. A test
holds that.

Why the browser rather than an API: Google Voice has no public API for a
personal account, and the rule is no API keys anywhere (§6). She already
has an authorized Chrome profile — the same one `browse` uses to read a
page he is logged into — so this is the same door, pointed at his own
messages.

**UNPROVEN.** This has never run against the real voice.google.com. The
parsing below is written from the page's visible text, and Google changes
that layout without notice. `check()` says honestly whether she is even
logged in, and the registry entry says EXPERIMENTAL until a real code has
been read from a real signup.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys

from aletheia import journal

ACTOR = "aletheia-gvoice"

MESSAGES_URL = "https://voice.google.com/u/0/messages"

#: How old a verification code may be. Most expire in 5–10 minutes, and a
#: code she cannot date is refused outright rather than guessed at.
MAX_CODE_AGE_S = 10 * 60

OK = "ok"
NOT_SIGNED_IN = "not_signed_in"
NO_BROWSER = "no_browser"

#: The signed-out page, by what it says. If she is not signed in, the
#: messages page is a Google login screen and every "message" she would
#: read is furniture.
_SIGNED_OUT = re.compile(
    r"sign in to continue|use your google account|forgot email\?"
    r"|to continue to google voice|choose an account",
    re.I)

#: The shapes a real verification text takes. These are NOT the shapes an
#: email takes — measured against `apply_run.code_in`, which catches one of
#: six real SMS phrasings, because an email says "Copy and paste this code
#: into the security code field: ApHIj2MW" and a text says "284913 is your
#: code". Different grammar, so a different pattern; `code_in_text` still
#: asks the email extractor first so anything both can read reads the same.
_SMS_CODE = (
    # "G-839201 is your Google verification code"
    re.compile(r"\b[A-Z]-(\d{4,8})\b"),
    # "284913 is your Workday verification code"
    re.compile(r"\b(\d{4,8})\b(?=[^.\n]{0,40}\b(?:is your|is the)\b"
               r"[^.\n]{0,40}\bcode\b)", re.I),
    # "Your verification code is 284913" / "your code is 5821"
    re.compile(r"\bcode\s+(?:is|:)\s*(\d{4,8})\b", re.I),
    # "Use code 44821 to verify"
    re.compile(r"\b(?:use|enter)\s+(?:the\s+)?code\s+(\d{4,8})\b", re.I),
    # "Your one-time passcode: 913022"
    re.compile(r"\b(?:passcode|pin|otp)\b\D{0,20}(\d{4,8})\b", re.I),
)

#: A number in a text that is never a verification code.
_NOT_A_CODE = re.compile(
    r"\b(?:19|20)\d{2}\b"          # a year
    r"|\$\s?\d+"                   # money
    r"|\b\d{1,2}:\d{2}\b",         # a time
)


def code_in_text(text: str) -> str:
    """The verification code in one message, or "".

    Asks `apply_run.code_in` first, so a message both extractors can read
    is read the same way by both and they cannot drift apart on the
    overlap. Falls through to the SMS shapes, which the email pattern was
    never built for.
    """
    body = str(text or "")
    if not body.strip():
        return ""
    try:
        from aletheia import apply_run
        found = apply_run.code_in(body)
        if found:
            return found
    except Exception:
        pass
    for pattern in _SMS_CODE:
        for hit in pattern.finditer(body):
            got = (hit.group(1) or "").strip()
            if not got:
                continue
            # The surrounding words decide: a year or a price that happens
            # to be six digits is not what the site just sent.
            window = body[max(0, hit.start() - 20):hit.end() + 20]
            if _NOT_A_CODE.search(window) and not re.search(
                    r"\bcode\b|\bpasscode\b|\botp\b|\bverif", window, re.I):
                continue
            return got
    return ""


def _age_seconds(stamp: str, *, now: dt.datetime | None = None) -> float | None:
    """How long ago a Google Voice timestamp was. None when unreadable.

    Google Voice writes "10:42 AM" for today, "Yesterday", and a date for
    anything older. Only the first can be a live code; the other two are
    old by definition and are reported as such rather than guessed.
    """
    text = " ".join(str(stamp or "").split())
    if not text:
        return None
    now = now or dt.datetime.now()
    if re.match(r"^(?:yesterday|[A-Z][a-z]{2}\b|\d{1,2}/\d{1,2})", text, re.I):
        return float(MAX_CODE_AGE_S * 100)  # certainly too old
    m = re.match(r"^(\d{1,2}):(\d{2})\s*([AaPp])\.?[Mm]\.?$", text)
    if not m:
        return None
    hour, minute, half = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    hour = (hour % 12) + (12 if half == "P" else 0)
    when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if when > now:                      # a time later than now was yesterday
        when -= dt.timedelta(days=1)
    return (now - when).total_seconds()


#: One row of the messages list, as the page renders it in plain text:
#: a sender line, then the message, then a timestamp.
_ROW = re.compile(
    r"^(?P<who>[^\n]{1,60}?)\n(?P<body>[^\n]{1,300}?)\n"
    r"(?P<when>\d{1,2}:\d{2}\s*[AaPp]\.?[Mm]\.?|Yesterday|[A-Z][a-z]{2} \d{1,2}"
    r"|\d{1,2}/\d{1,2}/\d{2,4})\s*$",
    re.M)


def messages_in(page_text: str) -> list[dict]:
    """Every message the messages page is showing, as rows.

    Parsed from the page's VISIBLE TEXT, which is what `browse.read_page`
    returns. Google changes this layout without notice, so a run that finds
    nothing is reported as "nothing readable", never as "no messages" —
    the two are different and only one of them is his problem.
    """
    rows = []
    for m in _ROW.finditer(str(page_text or "")):
        body = m.group("body").strip()
        rows.append({"from": m.group("who").strip(), "text": body,
                     "when": m.group("when").strip(),
                     "code": code_in_text(body)})
    return rows


def check(reader=None) -> tuple[str, str]:
    """Can she read his texts at all? Reads a page; sends nothing.

    INSTALLED is not WORKING: having a browser says nothing about being
    signed in to Google Voice, and a reader that quietly returns an empty
    list because it is looking at a login screen would report "no code"
    forever while the code sat on his screen.
    """
    if reader is None:
        from aletheia import browse
        ok, why = browse.available()
        if not ok:
            return NO_BROWSER, why
        reader = browse.read_page
    try:
        page = reader(MESSAGES_URL)
    except Exception as exc:
        return NO_BROWSER, f"could not open Google Voice: {exc}"
    text = str((page or {}).get("text") or "")
    if _SIGNED_OUT.search(text):
        return NOT_SIGNED_IN, ("not signed in to Google Voice in her browser "
                               "profile — sign in once with "
                               "`python -m aletheia.browse login "
                               "https://voice.google.com` and she keeps it")
    return OK, "she can read the messages page"


def recent(*, reader=None) -> list[dict]:
    """His recent texts. Reads only."""
    state, why = check(reader=reader)
    if state != OK:
        raise RuntimeError(why)
    if reader is None:
        from aletheia import browse
        reader = browse.read_page
    page = reader(MESSAGES_URL)
    rows = messages_in(str((page or {}).get("text") or ""))
    journal.append("action", f"{ACTOR}:read",
                   f"read the Google Voice messages page — "
                   f"{len(rows)} message(s) visible", actor=ACTOR)
    return rows


def latest_code(*, reader=None, max_age_s: float = MAX_CODE_AGE_S,
                now: dt.datetime | None = None) -> dict | None:
    """The newest verification code that is still fresh, or None.

    A code she cannot date is refused. An hour-old code typed into a box
    fails in a way that reads like a broken form, and that cost a session
    once already on the mail path.
    """
    best = None
    for row in recent(reader=reader):
        if not row.get("code"):
            continue
        age = _age_seconds(row.get("when", ""), now=now)
        if age is None or age > max_age_s:
            continue
        if best is None or age < best["age_s"]:
            best = {**row, "age_s": age}
    return best


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read his Google Voice texts")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="can she read them? sends nothing")
    sub.add_parser("recent", help="the messages showing now")
    sub.add_parser("code", help="the newest fresh verification code")
    args = ap.parse_args(argv)

    if args.cmd == "check":
        state, why = check()
        print(f"{state}: {why}")
        return 0 if state == OK else 1

    try:
        if args.cmd == "recent":
            rows = recent()
            if not rows:
                print("Nothing readable on the messages page. "
                      "(That is not the same as no messages — the layout "
                      "may have changed.)")
            for row in rows:
                mark = f"  [code {row['code']}]" if row["code"] else ""
                print(f"  {row['when']:>10}  {row['from'][:24]:24} "
                      f"{row['text'][:60]}{mark}")
            return 0
        found = latest_code()
        if not found:
            print("No fresh verification code in his texts.")
            return 1
        print(f"{found['code']} (from {found['from']}, "
              f"{int(found['age_s'] // 60)} minutes ago)")
        return 0
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
