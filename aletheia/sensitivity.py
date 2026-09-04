"""What must never end up somewhere it can be read.

`docs/ROADMAP.md` names this as the review's best idea and the correct
answer to "I don't want it blackmailing me": *"Information-flow labels do
not exist. Nothing marks a bank balance or a private message as
SENSITIVE, so nothing structurally prevents such a value reaching an
outbound channel."* This is the first slice of it, aimed at the outbound
channel nobody thinks of.

**The journal is committed to a public GitHub repository.** So is the
pulse, and so is anything under `state/`. `CLAUDE.md` says "no secrets in
committed files" and nothing enforced it — every enforcement was a person
remembering. Meanwhile the journal records his own words: a web task
journals its goal, and "log into my bank, the password is hunter2" is a
sentence he might reasonably say out loud to an assistant.

So this is a scrubber, and it sits at the one place everything committed
passes through. It is deliberately BLUNT:

- It redacts by shape, not by understanding. A sixteen-digit number that
  is really an order id gets redacted too. In a prose journal that costs
  nothing; the alternative costs a card number in a public repo.
- It never throws. A scrubber that can fail is a scrubber that gets
  wrapped in a try/except and quietly skipped.
- It says WHAT it found, not what it hid, so a receipt can honestly read
  "one password redacted" without repeating the password to say so.

What it is NOT: a boundary on what she may DO with a value. Typing his
own password into his own bank's login box is the whole point of
`secret.fill`, and that is governed by its own host binding. This is
about what gets written down where other people can read it.
"""
from __future__ import annotations

import re

# Each rule is (name, pattern, how many groups to keep). The pattern must
# match the SECRET, not the sentence around it, because what replaces it
# is a marker and everything else stays readable.
RULES: tuple[tuple[str, re.Pattern, str], ...] = (
    # "password: hunter2", "api key = sk-abc123", "token is xyz"
    # TO THE END OF THE LINE. "passphrase: correct horse battery staple"
    # is four words and the first version took one of them, leaving three
    # quarters of it sitting in a public repository.
    ("a password", re.compile(
        r"\b(pass(?:word|phrase|code)|pwd)\b\s*(?:is|=|:)\s*\S.*", re.I),
     r"\1 [redacted]"),
    # "log in with password hunter2 and click submit" — no colon, no
    # "is", which is how a person actually says it. Only when the next
    # word LOOKS like a secret (six or more characters with a digit or a
    # symbol in it), so "the password field was empty" is left alone: a
    # scrubber that mangles ordinary sentences is one somebody turns off.
    ("a password", re.compile(
        r"\b(pass(?:word|phrase|code)|pwd)\s+(?=\S*[\d\W])\S{6,}", re.I),
     r"\1 [redacted]"),
    ("a key", re.compile(
        r"\b(api[ _-]?key|access[ _-]?token|client[ _-]?secret|secret[ _-]?key|"
        r"bearer|auth[ _-]?token)\b\s*(?:is|=|:)?\s*[A-Za-z0-9_\-\.]{12,}",
        re.I), r"\1 [redacted]"),
    # Provider-shaped keys with no label at all.
    ("a key", re.compile(r"\b(?:sk|pk|rk|ghp|gho|ghs|github_pat)[_-][A-Za-z0-9_]{16,}"),
     "[key redacted]"),
    ("a private key", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.S), "[private key redacted]"),
    # A social security number, written the way people write it.
    ("a social security number", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
     "[ssn redacted]"),
    # A card or account number: 13-19 digits, optionally spaced or dashed.
    # Deliberately blunt — an order id caught here costs nothing.
    ("an account number", re.compile(
        r"(?<![\w.-])(?:\d[ -]?){13,19}(?![\w.-])"), "[number redacted]"),
    # A CVV next to the word.
    ("a card code", re.compile(r"\b(cvv|cvc|security code)\b\s*(?:is|=|:)?\s*\d{3,4}",
                               re.I), r"\1 [redacted]"),
)

MARKER = "[redacted]"


def scrub(text: str) -> tuple[str, list[str]]:
    """The text with secret-shaped things replaced, and what kinds were found.

    Returns the KINDS, never the values: a receipt that says what it hid
    by quoting it has hidden nothing.
    """
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else "", []
    found: list[str] = []
    out = text
    for name, pattern, replacement in RULES:
        try:
            out, hits = pattern.subn(replacement, out)
        except Exception:                       # noqa: BLE001
            continue        # a broken rule must never take the writer down
        if hits and name not in found:
            found.append(name)
    return out, found


def clean(text: str) -> str:
    """`scrub` when only the text is wanted."""
    return scrub(text)[0]


def carries_secret(text: str) -> bool:
    return bool(scrub(text)[1])
