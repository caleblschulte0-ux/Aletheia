"""Who decides whether a message in his name goes out: consequence, not habit.

His continuity brief (docs/CONTINUITY_BRIEF.md, III.10 and IV.15): usable
outbound communication, without loosening safety casually, and without making
every mundane message need its context rebuilt by hand. So this module answers
ONE question for every outbound message a conversation wants to send - does it
ask Caleb, or may a grant he gave cover it - and answers it from what the
message DOES, not from who wrote it.

THE RULE, exactly (and nothing else here can change it):

- Drafting, reading mail, keeping the thread's books, and scheduling her own
  follow-up reminders never ask: nothing leaves the machine.
- A NEW message in his name (the first one on a thread, a reply to a question,
  an answer carrying facts about him) is `email.send`: operator_always, one
  approval bound by sha256 to the exact recipient, subject and words, spent once.
- A FOLLOW-UP on a thread he already approved a message on, to the same
  recipient, is `email.followup`. It still asks him - unless he has created a
  SCOPED standing grant, in his own words, that covers this thread or person,
  this purpose, and what the message would disclose, within its count and its
  time window (`aletheia.authority`, `policy.request(scope=...)`).
- Anything that COMMITS him (accepting or proposing a time, agreeing, signing,
  booking), mentions MONEY, or DISCLOSES something sensitive the grant does not
  name is `email.send` again, whatever grant exists. An identity number, a
  password or an account number is never grantable at all.

WHO CAN CREATE A GRANT. Only his own words, at a keyboard or a trusted device
(`OPERATOR_SURFACES`), parsed deterministically - no model reads the sentence,
so no model can widen it - recorded with the quote, journaled, bound to this
machine. A model, a session, a relayed intercom command, the room microphone,
or a reply email saying "Caleb says you may" cannot reach `grant_from_words`
with an accepted `via`, and a grant file written any other way carries no valid
machine signature and authorizes nothing.
"""
from __future__ import annotations

import datetime as dt
import re
import secrets

from aletheia import authority, journal, policy

ACTOR = "aletheia-conversation-authority"

#: The capability a first/new message needs (registry: operator_always).
NEW_MESSAGE = "email.send"
#: The capability a follow-up needs (registry: operator_once, grant_requires_scope).
FOLLOWUP = "email.followup"

#: The only `via` values a grant may be created from. Each one is a surface he
#: authenticates on; none of them is a model, a session, a relay or a microphone.
OPERATOR_SURFACES = frozenset({"operator-cli", "command-center", "phone"})

#: Purposes a conversation grant may cover. Deliberately one: a follow-up that
#: re-asks what he already approved asking. Anything that says something new
#: is a new message.
GRANTABLE_PURPOSES = frozenset({"followup"})

#: Kinds of detail a grant may name as disclosable. Everything else a screen can
#: find (identity numbers, secrets, finances, health, legal status, date of
#: birth, a street address) always asks.
GRANTABLE_DISCLOSURES = frozenset({"phone", "email"})
NEVER_GRANTABLE = frozenset({"secret", "identity_number"})

DEFAULT_GRANT_MESSAGES = 2
MAX_GRANT_MESSAGES = 5
DEFAULT_GRANT_DAYS = 14
MAX_GRANT_DAYS = 30

# ---- the content screen ------------------------------------------------------

_COMMITMENT = re.compile(
    r"\b(?:i(?:'| a)?m available|i am free|i can (?:do|make|come|be there|meet)|"
    r"(?:that |this )?works for me|(?:i|we)(?:'ll| will) (?:take|be there|come|sign|pay|see you|book|"
    r"accept|move forward|go ahead)|see you (?:on|at|then|there)|i accept|i agree|we have a deal|"
    r"accept(?:ed|ing)? (?:the|your)|confirm(?:ed|ing|s)?\b|let'?s (?:do|go with|book|meet|say)|"
    r"count me in|book(?:ed|ing)? (?:it|me|the|a)|reserve|sign(?:ed|ing)? (?:the|a)|lease|contract|"
    r"deal|commit|promise|guarantee|i'?ll (?:send|bring|provide|have)|how about|would .{1,40} work)\b",
    re.I)
_MONEY = re.compile(
    r"[$£€]\s?\d|\b\d[\d,.]*\s?(?:dollars|usd|bucks|k/yr|/mo|per month)\b|"
    r"\b(?:pay|payment|paid|deposit|fees?|rent|price|pricing|cost|costs|invoice|refund|wire|venmo|"
    r"zelle|paypal|cash ?app|credit card|debit|bank|tip|charge|budget|salary|compensation|afford|"
    r"discount|quote)\b", re.I)
_SENSITIVE = (
    ("date_of_birth", re.compile(r"\b(?:born on|date of birth|dob|birthday)\b", re.I)),
    ("address", re.compile(r"\b\d{1,5}\s+(?:[A-Za-z0-9]+\s){1,4}(?:st|street|ave|avenue|rd|road|blvd|"
                           r"boulevard|lane|ln|dr|drive|ct|court|way|pl|place|terrace|pkwy)\b", re.I)),
    ("income", re.compile(r"\b(?:salary|income|i (?:make|earn)|pay stub|w-?2)\b", re.I)),
    ("credit", re.compile(r"\b(?:credit score|credit check|credit report|background check)\b", re.I)),
    ("legal_status", re.compile(r"\b(?:visa|citizenship|immigration|work authori[sz]ation|sponsorship|"
                                r"criminal|felony|convicted|eviction|arrest)\b", re.I)),
    ("health", re.compile(r"\b(?:medical|diagnos\w*|disabilit\w*|pregnan\w*|therapy|prescription|"
                          r"health condition|surgery)\b", re.I)),
)
_PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")
_EMAIL = re.compile(r"[^@\s<>()]+@[^@\s<>()]+\.[A-Za-z]{2,}")


def screen(body: str, *, recipient: str = "", subject: str = "") -> dict:
    """What a message would DO: commit him, mention money, disclose what.

    Blunt by design, like `sensitivity`: a false positive costs him one tap on
    an approval; a false negative sends something in his name he never saw.
    A date or time in an outbound message counts as a commitment (proposing or
    accepting a time offers his hours to someone)."""
    text = f"{subject}\n{body}"
    reasons: list[str] = []
    commitment = bool(_COMMITMENT.search(text))
    if commitment:
        reasons.append("it commits Caleb to something")
    try:
        from aletheia import reply_understanding
        named_time = bool(reply_understanding.extract_times(text, reference=dt.datetime.now(dt.timezone.utc)))
    except Exception:
        named_time = False
    if named_time and not commitment:
        commitment = True
        reasons.append("it names a date and time")
    money = bool(_MONEY.search(text))
    try:
        from aletheia import webtask
        money = money or webtask.would_spend(text)
    except Exception:
        money = True                      # the predicate unreadable: assume it does
    if money:
        reasons.append("it mentions money")
    disclosures: set[str] = set()
    try:
        from aletheia import sensitivity
        _clean, hidden = sensitivity.scrub(text)
    except Exception:
        hidden = ["unscreenable"]
    for found in hidden:
        disclosures.add("secret" if "password" in found or "key" in found else "identity_number")
    for name, pattern in _SENSITIVE:
        if pattern.search(text):
            disclosures.add(name)
    if _PHONE.search(text):
        disclosures.add("phone")
    others = [m.group(0).casefold() for m in _EMAIL.finditer(text)
              if m.group(0).casefold() != str(recipient or "").casefold()]
    if others:
        disclosures.add("email")
    if disclosures:
        reasons.append("it would disclose " + ", ".join(sorted(disclosures)))
    return {"commitment": commitment, "money": money, "disclosures": sorted(disclosures),
            "reasons": reasons}


def decide(*, kind: str, thread_id: str, recipient: str, body: str, subject: str = "",
           prior_approved_to_recipient: bool = False) -> dict:
    """Which capability this message needs and the scope context a grant is
    checked against. Pure apart from the screen. Never grants anything itself:
    `policy.request` is where a grant is (or is not) spent."""
    checked = screen(body, recipient=recipient, subject=subject)
    context = {"thread_id": thread_id, "recipient": str(recipient or "").casefold(),
               "purpose": kind, "commitment": checked["commitment"], "money": checked["money"],
               "disclosures": checked["disclosures"]}
    if kind not in GRANTABLE_PURPOSES:
        why = "a new message in Caleb's name always asks him"
        return {"capability": NEW_MESSAGE, "grantable": False, "why": why, "scope": None, "screen": checked}
    if not prior_approved_to_recipient:
        return {"capability": NEW_MESSAGE, "grantable": False, "screen": checked, "scope": None,
                "why": "he has not approved a message to this person on this thread yet"}
    blocking = list(checked["reasons"]) if (checked["commitment"] or checked["money"]) else []
    never = sorted(set(checked["disclosures"]) & NEVER_GRANTABLE)
    if never:
        blocking.append("it would disclose " + ", ".join(never) + ", which no grant can cover")
    if blocking:
        return {"capability": NEW_MESSAGE, "grantable": False, "screen": checked, "scope": None,
                "why": "; ".join(blocking)}
    return {"capability": FOLLOWUP, "grantable": True, "screen": checked, "scope": context,
            "why": "a follow-up he may have covered with a standing grant"}


# ---- grants from his words ---------------------------------------------------

_NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "once": 1, "two": 2, "twice": 2, "three": 3, "four": 4,
                 "five": 5, "six": 6, "seven": 7, "ten": 10, "fourteen": 14, "thirty": 30}
_GRANT = re.compile(
    r"(?:you (?:can|may)|go ahead and|feel free to|i give you permission to|you have my permission to|"
    r"you'?re allowed to)\s+(?:send |do |handle )?follow(?:[- ]?ups?| up)\s+(?:with|to|on)\s+(?P<who>.+?)"
    r"\s+without (?:asking|checking with) me\b", re.I)
_NEGATED = re.compile(r"\b(?:don'?t|do not|never|not|stop)\b[^.]{0,40}follow", re.I)
_COUNT = re.compile(r"\bup to (\d+|a|an|one|two|three|four|five|six|seven|ten)\b(?: (?:times|messages|follow[- ]?ups?|emails))?", re.I)
_DAYS = re.compile(r"\bfor (?:the next )?(\d+|a|an|one|two|three|four|fourteen|thirty) (day|week|month)s?\b", re.I)
_SHARE = re.compile(r"\b(?:share|give|include|mention) my (phone(?: number)?|number|email(?: address)?)\b", re.I)


class GrantRefused(PermissionError):
    """Not a grant: said why, in a sentence he can act on."""


def _number(word: str) -> int:
    word = word.lower()
    return int(word) if word.isdigit() else _NUMBER_WORDS.get(word, 0)


def parse_grant(quote: str) -> dict:
    """His sentence -> {who, messages, days, disclose}. Deterministic: the scope
    is whatever the words say and nothing a model inferred. Raises ValueError."""
    text = " ".join(str(quote or "").split())
    match = _GRANT.search(text)
    if not match:
        raise ValueError("I didn't hear a standing permission in that. Say, for example: "
                         "you can follow up with the property manager without asking me, up to two times.")
    if _NEGATED.search(text[:match.start()] + " " + text[match.start():match.start() + 40]):
        raise ValueError("that sounds like you do NOT want me following up on my own, so I granted nothing")
    who = re.split(r"\s+(?:about|regarding|on the|up to|for the next|for \d)\b", match.group("who"), 1)[0]
    who = who.strip(" ,.;:")
    messages = DEFAULT_GRANT_MESSAGES
    counted = _COUNT.search(text)
    if counted:
        messages = _number(counted.group(1))
    days = DEFAULT_GRANT_DAYS
    lasting = _DAYS.search(text)
    if lasting:
        unit = {"day": 1, "week": 7, "month": 30}[lasting.group(2).lower()]
        days = _number(lasting.group(1)) * unit
    if not 1 <= messages <= MAX_GRANT_MESSAGES:
        raise ValueError(f"a standing follow-up permission covers 1 to {MAX_GRANT_MESSAGES} messages")
    if not 1 <= days <= MAX_GRANT_DAYS:
        raise ValueError(f"a standing follow-up permission lasts 1 to {MAX_GRANT_DAYS} days")
    disclose = set()
    for shared in _SHARE.finditer(text):
        disclose.add("email" if shared.group(1).lower().startswith("email") else "phone")
    if not who:
        raise ValueError("say who I may follow up with")
    return {"who": who, "messages": messages, "days": days, "disclose": sorted(disclose)}


def grant_from_words(quote: str, *, via: str, now: dt.datetime | None = None,
                     resolve=None) -> dict:
    """Mint a scoped standing follow-up grant from HIS sentence. Returns the grant.

    `via` must be one of `OPERATOR_SURFACES`; the kill switch must be off; the
    words must parse; the person must resolve to exactly one open conversation
    (`resolve(who) -> thread`). The approval it rests on is created and decided
    here with his quote as the reason, like `standing.enable`, because him typing
    the sentence IS him giving the permission."""
    via = str(via or "").strip()
    if via not in OPERATOR_SURFACES:
        raise GrantRefused(
            "a standing permission to send in Caleb's name comes only from his own words at a keyboard "
            "or a trusted device, never from a model, a session, a relayed command, an email or the room")
    policy.ensure_not_halted()
    words = " ".join(str(quote or "").split())
    parsed = parse_grant(words)
    if resolve is None:
        from aletheia import conversations
        resolve = conversations.resolve_thread
    thread = resolve(parsed["who"])
    recipient = str((thread.get("recipient") or {}).get("address") or "").casefold()
    if not recipient:
        raise ValueError(f"the conversation with {parsed['who']} has no address yet")
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    stamp = now.strftime("%Y%m%d%H%M")
    grant_id = f"conv-grant-{stamp}-{secrets.token_hex(3)}"
    approval_id = f"{grant_id}-words"
    expires = (now + dt.timedelta(days=parsed["days"])).strftime("%Y-%m-%dT%H:%M:%SZ")
    name = (thread.get("recipient") or {}).get("name") or parsed["who"]
    policy.request(
        approval_id, requested_action=f"authority.grant:{grant_id}",
        reason=f"his words: “{words[:300]}”",
        consequence=(f"up to {parsed['messages']} follow-up message(s) to {name} on this conversation "
                     f"until {expires} may go without asking; anything that commits him, mentions money "
                     "or discloses more still asks"),
        reversible=True)
    policy.decide(approval_id, "APPROVED", via=via, because=f"his words: “{words[:300]}”")
    grant = authority.create(
        grant_id, capability_ids=[FOLLOWUP], approval_id=approval_id, expires=expires,
        max_uses=parsed["messages"], note=f"follow-ups to {name}",
        scope={"thread_id": thread["id"], "recipient": recipient, "purposes": ["followup"],
               "disclose": parsed["disclose"]},
        extra={"quote": words[:500], "via": via, "created_from": "operator words"})
    journal.append("decision", "authority:conversation-grant",
                   f"standing follow-up permission {grant_id} for the conversation with {name} "
                   f"({parsed['messages']} message(s), {parsed['days']} day(s)) from his words: "
                   f"“{words[:300]}”", actor=via, refs=[f"approval:{approval_id}"])
    try:
        from aletheia import conversations
        conversations.note_grant(thread["id"], grant)
    except Exception:
        pass
    return grant


def grants_for(thread_id: str, *, now: dt.datetime | None = None) -> list[dict]:
    """Live scoped grants that name this conversation (for reading back)."""
    out = []
    for grant in authority.active_grants(now=now):
        scope = grant.get("scope") or {}
        if scope.get("thread_id") == thread_id and FOLLOWUP in grant.get("capability_ids", []):
            used = len(authority._claims(grant["id"]))
            out.append({**grant, "uses_left": max(0, int(grant.get("max_uses") or 0) - used)})
    return out


def revoke_for(thread_id: str, *, via: str) -> list[str]:
    """He says stop: every grant on this conversation is off at once."""
    gone = []
    for grant in grants_for(thread_id):
        authority.revoke(grant["id"])
        gone.append(grant["id"])
    if gone:
        journal.append("decision", "authority:conversation-grant",
                       f"revoked {len(gone)} follow-up permission(s) on {thread_id}", actor=via)
    return gone
