"""What kind of page this is, in words that are true of every website.

The brief (docs/JARVIS_BRIEF.md §4): underneath the ATS adapters is a
general observe -> understand -> act -> verify loop with a SMALL page-state
vocabulary. The operator's direction on 2026-09-16 shapes the vocabulary:
*"jobs should be the current test case, not the architecture."* So nothing
in here knows what a job is. A job posting, a library-card form and a
dentist's appointment wizard are all CONTENT, FORM, MULTI_PAGE_WIZARD,
REVIEW and SUCCESS; "this content page is a job post" is an ANNOTATION a
skill adds on top (`job_skill`), never a state the loop has to know.

    CONTENT             something to read or a link to follow
    FORM                questions on one page
    MULTI_PAGE_WIZARD   a form that says it is one step of several
    ACCOUNT_LOGIN       wants credentials she does not keep
    ACCOUNT_SIGNUP      wants an account MADE - a durable thing, approval-gated
    EMAIL_VERIFICATION  wants a code that arrives by mail
    SMS_VERIFICATION    wants a code that arrives by text
    MFA_CHALLENGE       wants a second factor only he holds (an authenticator
                        app, a push to his phone, a security key)
    REVIEW              everything answered, a final button to press
    SUCCESS             the site says it went through
    CAPTCHA             wants a person; she never solves one
    ERROR               the site failed (a 5xx, a 404, "something went wrong")
    UNKNOWN             nothing readable yet

Classification works on the SEMANTIC observation (roles, accessible names,
visible text, the HTTP status) and never on a selector, so it is testable
without a browser and the same function reads a page for every goal.

Also here, because it is the same question asked of one control rather
than a page: `control_kind`. The loop only ever presses a control whose
kind is PROGRESS or NAVIGATE by itself. COMMIT and CREATE_ACCOUNT go to the
existing hash-bound approval; SPEND is refused outright (webtask's
MONEY_WORDS, the one permanent rule); SIGN_IN is a boundary.
"""
from __future__ import annotations

import re

CONTENT = "CONTENT"
FORM = "FORM"
ACCOUNT_LOGIN = "ACCOUNT_LOGIN"
ACCOUNT_SIGNUP = "ACCOUNT_SIGNUP"
EMAIL_VERIFICATION = "EMAIL_VERIFICATION"
SMS_VERIFICATION = "SMS_VERIFICATION"
MFA_CHALLENGE = "MFA_CHALLENGE"
MULTI_PAGE_WIZARD = "MULTI_PAGE_WIZARD"
REVIEW = "REVIEW"
SUCCESS = "SUCCESS"
CAPTCHA = "CAPTCHA"
ERROR = "ERROR"
UNKNOWN = "UNKNOWN"

STATES = (CONTENT, FORM, ACCOUNT_LOGIN, ACCOUNT_SIGNUP, EMAIL_VERIFICATION,
          SMS_VERIFICATION, MFA_CHALLENGE, MULTI_PAGE_WIZARD, REVIEW, SUCCESS, CAPTCHA,
          ERROR, UNKNOWN)

#: Roles a person answers (as opposed to presses or follows).
ANSWER_ROLES = frozenset({"textbox", "combobox", "checkbox", "radio", "file",
                          "password", "option", "switch"})
PRESS_ROLES = frozenset({"button", "link", "tab", "menuitem"})

# ---- controls ---------------------------------------------------------------

PROGRESS = "progress"          # next / continue: moves a wizard along
NAVIGATE = "navigate"          # a link to follow
COMMIT = "commit"              # submit / send / confirm: approval-gated
CREATE_ACCOUNT = "create_account"  # makes a durable account: approval-gated
SPEND = "spend"                # refused, never gated
SIGN_IN = "sign_in"            # needs credentials: a boundary
BACK = "back"                  # never pressed by the loop
OTHER = "other"                # a widget: a tab, a toggle, "add another"

_PROGRESS = re.compile(
    r"^\s*(?:next|continue|proceed|next step|next page|save (?:and|&) continue|"
    r"continue to (?:next|review|the next).*|go to (?:next|review).*|review"
    r"(?: (?:my|your) (?:answers|application|request|details))?|"
    r"get started|start|begin|start (?:my |your )?(?:application|request))\s*[>›→»]*\s*$",
    re.I)
_BACK = re.compile(r"^\s*(?:[<‹←«]\s*)?(?:back|previous|go back|prev)\b", re.I)
_SIGN_IN = re.compile(r"\b(?:sign|log)\s*-?\s*in\b", re.I)
#: Signing in somewhere ELSE to bring something back: "Apply With LinkedIn",
#: "Dropbox", "Indeed Resume" (live 2026-09-17, Avature). Each opens another
#: company's sign-in, so it is a sign-in boundary, never a button to approve.
_THIRD_PARTY = re.compile(
    r"^\s*(?:(?:apply|sign up|continue|connect|import|log in|sign in)\s+(?:with|using|via|from)\s+)?"
    r"(?:linkedin|google(?: drive)?|facebook|indeed(?: resume)?|dropbox|one ?drive|apple|microsoft|github|"
    r"seek|glassdoor|ziprecruiter)(?: profile| account| resume)?\s*$", re.I)
_CREATE_ACCOUNT = re.compile(
    r"\b(?:create (?:an |my |your |a )?(?:new )?account|sign\s*-?\s*up|register|"
    r"open (?:an |my )?account|create (?:my |a )?profile|join now)\b", re.I)
#: Buttons on a form that are known NOT to send it. Everything else on a
#: page with questions is treated as a commit: "Join the list", "Let's go",
#: "Count me in" say none of the committing words and every one of them is
#: a submit button. Bias toward calling it a commit - a false positive costs
#: one approval, a false negative sends something without asking.
_FORM_HARMLESS = re.compile(
    r"^\s*(?:\+\s*)?(?:add(?: another| more| an?)?(?: \w+)?|upload(?: (?:a|an|your|my|new))?(?: \w+)?|attach(?: (?:a|your|my))?(?: \w+)?|browse|"
    r"choose(?: a)? file|select file|show(?: \w+)?|hide(?: \w+)?|more|less|see more|read more|"
    r"search|clear|edit|expand|collapse|close|dismiss|help|accept all(?: cookies)?|"
    r"(?:decline|reject)(?: all)?(?: cookies)?|cookie settings|manage cookies|got it|"
    r"skip to (?:content|main)|menu|x|×|share(?: this(?: job| page)?)?|print(?: this)?(?: job| page)?|copy link|save (?:job|for later)|follow|like|tweet|allow)\s*$", re.I)


#: An ORDER is spending even when no money word is on the button: "Submit
#: order", "Complete my order", "Confirm order" (httpbin's pizza form, the
#: one live observe). MONEY_WORDS only knew "place order".
_ORDER = re.compile(r"\b(?:submit|confirm|complete|finish|send|review|finali[sz]e)\s+(?:my\s+|your\s+|the\s+)?"
                    r"(?:order|booking|reservation)\b|\border\s+now\b", re.I)
#: A price the page is about to charge: a total, an amount due, beside money.
_CHARGE = re.compile(r"\b(?:order total|total due|amount due|grand total|total price|you(?:'|’)ll pay|"
                     r"total)\b[^\n]{0,40}?[$€£]\s?\d|[$€£]\s?\d[\d,.]*\s*(?:due|total)\b", re.I)


def shows_a_charge(text: str) -> bool:
    """Does the page show a total it is about to charge?"""
    return bool(_CHARGE.search(str(text or "")[:6000]))


def control_kind(label: str, *, role: str = "button", on_form: bool = False) -> str:
    """What pressing this control would DO, from its accessible name.

    Order is the safety argument: money first (refused whatever else the
    label says), then the account-making and committing words, then the
    harmless ones. A link whose words commit is still a commit - "Cancel my
    membership" is often an <a>.
    """
    from aletheia import computer, webtask
    text = " ".join(str(label or "").split())
    if webtask.MONEY_WORDS.search(text) or _ORDER.search(text):
        return SPEND
    if _CREATE_ACCOUNT.search(text):
        return CREATE_ACCOUNT
    if _SIGN_IN.search(text) or _THIRD_PARTY.search(text):
        return SIGN_IN
    if computer.committing_label(text):
        return COMMIT
    if _BACK.search(text):
        return BACK
    if _PROGRESS.search(text):
        return PROGRESS
    if role == "link":
        return NAVIGATE
    if on_form and role == "button" and not _FORM_HARMLESS.search(text):
        return COMMIT
    return OTHER


# ---- pages -------------------------------------------------------------------

_SERVER_ERROR = re.compile(
    r"internal server error|service (?:temporarily )?unavailable|bad gateway|"
    r"gateway time-?out|something went wrong on our end|an unexpected error occurred|"
    r"we(?:'|’)re having trouble|site is (?:temporarily )?down|"
    r"\b50[0-4]\b.{0,40}\berror\b|\berror\b.{0,20}\b50[0-4]\b", re.I)
_NOT_FOUND = re.compile(r"\b404\b|page (?:was )?not found|no longer (?:available|exists)", re.I)
_CODE_WALL = re.compile(
    r"verification code|security code|one[- ]time (?:pass)?code|confirmation code|"
    r"enter the (?:\d+[- ](?:digit|character) )?code|we (?:just )?(?:sent|texted|e-?mailed) "
    r"(?:you )?(?:a|the|an?) (?:\d+[- ](?:digit|character) )?code|code we (?:just )?(?:sent|texted|e-?mailed)|"
    r"enter the code|check your (?:e-?mail|inbox|phone) for a code", re.I)
_LINK_WALL = re.compile(
    r"verification link|verify your (?:e-?mail|account)(?: address)?|confirm your e-?mail(?: address)?|"
    r"check your (?:e-?mail|inbox) (?:to|for a link)|activate your account", re.I)
#: A code that came BY TEXT. Not the bare words "phone" or "mobile": nearly
#: every application form has a Phone box, and a Greenhouse page asking for the
#: security code it EMAILED read as a text-message code because of it.
_BY_TEXT = re.compile(
    r"\btext message\b|\bsms\b|\btexted\b|\bvia text\b|\bby text\b|"
    r"(?:sent|send|sending)\b[^.]{0,40}\bto (?:your |the )?(?:phone|mobile|cell)|"
    r"(?:phone|mobile|cell)(?: number)? ending in|code (?:to|on) your (?:phone|mobile|cell)", re.I)
#: A second factor she cannot fetch from anywhere: his authenticator app, a
#: push prompt on his phone, a hardware key. A named boundary, never a wait on mail.
_MFA = re.compile(
    r"authenticator app|authentication app|code from your (?:authenticator|authentication)|"
    r"security key|passkey|approve (?:the |this )?(?:sign-?in|login|request)|"
    r"(?:check|open) (?:the \w+ app on )?your (?:phone|device) to (?:approve|continue|confirm)|"
    r"push notification|tap (?:yes|approve) on your", re.I)
_STEP_OF = re.compile(r"\bstep\s+\d+\s*(?:of|/)\s*\d+\b|\bpage\s+\d+\s+of\s+\d+\b|"
                      r"\b\d+\s+of\s+\d+\s+steps?\b", re.I)
_REVIEW = re.compile(
    r"review (?:your|the|my) (?:application|request|details|information|answers|order|"
    r"submission|registration)|please review|confirm your (?:details|information|answers)|"
    r"summary of your|check your answers|before you submit", re.I)
_SUCCESS = re.compile(
    r"thank you|thanks for|has been (?:received|submitted|sent|scheduled|created|confirmed)|"
    r"we(?:'|’)ve received|we have received|successfully (?:submitted|sent|created|registered)|"
    r"confirmation number|reference number|you(?:'|’)re all set|request (?:was )?received|"
    r"application (?:was )?(?:received|submitted)", re.I)
_SIGN_IN_WALL = re.compile(
    r"(?:please |you must |you need to )?(?:sign|log) in to (?:continue|apply|proceed|view)|"
    r"sign in to your account|welcome back", re.I)
_SIGNUP_WORDS = re.compile(
    r"create (?:an |your |a )?(?:new )?account|sign up|register(?:ing)? for|"
    r"create (?:a |your )?(?:candidate )?profile|set (?:up|a) password|new (?:user|member)", re.I)
_CONFIRM_PASSWORD = re.compile(r"confirm|re-?enter|repeat|verify|again|retype", re.I)
_HUMAN = re.compile(
    r"i'?m not a robot|verify (?:that )?you(?:'re| are) (?:a )?human|are you a human|"
    r"complete the (?:captcha|security challenge)|press and hold|unusual traffic", re.I)


def _targets(observation: dict) -> list[dict]:
    return [t for t in observation.get("targets") or [] if isinstance(t, dict)]


def answerable(observation: dict) -> list[dict]:
    return [t for t in _targets(observation) if t.get("role") in ANSWER_ROLES]


def classify(observation: dict) -> dict:
    """{"state": one of STATES, "evidence": [why], "controls": {kind: [labels]}}.

    Never raises and never guesses a state it has no evidence for: a page
    that fits nothing is UNKNOWN, which the loop treats as "look again".
    """
    text = " ".join(str(observation.get("text") or "").split())
    title = str(observation.get("title") or "")
    url = str(observation.get("url") or "")
    status = observation.get("status")
    targets = _targets(observation)
    answers = answerable(observation)
    typed = [t for t in answers if t.get("role") != "option"]
    on_form = bool(typed)
    controls: dict[str, list[str]] = {}
    for t in targets:
        if t.get("role") in PRESS_ROLES:
            kind = control_kind(t.get("label", ""), role=t.get("role", "button"), on_form=on_form)
            controls.setdefault(kind, []).append(str(t.get("label") or ""))
    evidence: list[str] = []

    def out(state: str, *why: str) -> dict:
        return {"state": state, "evidence": [w for w in (*evidence, *why) if w],
                "controls": controls}

    if observation.get("captcha") or _HUMAN.search(text[:6000]):
        return out(CAPTCHA, f"a human check is on the page ({observation.get('captcha') or 'its words'})")
    if isinstance(status, int) and status >= 500:
        return out(ERROR, f"the server answered {status}")
    if not typed and _SERVER_ERROR.search(f"{title} {text[:1500]}"):
        return out(ERROR, "the page says the site failed")
    if isinstance(status, int) and status == 404 or (not typed and _NOT_FOUND.search(title)):
        return out(ERROR, "the page is not there (404)")

    passwords = [t for t in typed if t.get("role") == "password"]
    if not typed and _LINK_WALL.search(f"{title} {text[:3000]}"):
        return out(EMAIL_VERIFICATION, "the page wants a link from email opened")
    if not typed and (_SUCCESS.search(text[:3000]) or _SUCCESS.search(title)):
        return out(SUCCESS, "the page says it went through and no questions remain")

    if _MFA.search(f"{title} {text[:3000]}") and not passwords and len(typed) <= 2:
        return out(MFA_CHALLENGE, "the page wants a second factor only he holds")
    if _CODE_WALL.search(text[:4000]) and any(t.get("role") == "textbox" for t in typed) \
            and not passwords:
        if _BY_TEXT.search(text[:4000]):
            return out(SMS_VERIFICATION, "the page wants a code sent by text")
        return out(EMAIL_VERIFICATION, "the page wants a code sent by email")

    if passwords:
        confirm = [p for p in passwords if _CONFIRM_PASSWORD.search(str(p.get("label") or ""))]
        resume = any(t.get("role") == "file" for t in typed)
        if (confirm or controls.get(CREATE_ACCOUNT) or _SIGNUP_WORDS.search(f"{title} {text[:2000]}")) \
                and not resume and not _SIGN_IN_WALL.search(title):
            return out(ACCOUNT_SIGNUP, "the page wants an account made (a new password box)")
        return out(ACCOUNT_LOGIN, "the page wants a password she does not keep")
    if not typed and controls.get(SIGN_IN) and _SIGN_IN_WALL.search(f"{title} {text[:1500]}"):
        return out(ACCOUNT_LOGIN, "the page says to sign in first")

    committing = controls.get(COMMIT, []) + controls.get(CREATE_ACCOUNT, [])
    if _REVIEW.search(f"{title} {text[:3000]}") and committing and len(typed) <= 2:
        return out(REVIEW, "the page asks to review before the final button")
    if typed and (_STEP_OF.search(f"{title} {text[:3000]}") or observation.get("progressbar")):
        return out(MULTI_PAGE_WIZARD, "the page says it is one step of several")
    if typed and controls.get(PROGRESS) and not committing:
        return out(MULTI_PAGE_WIZARD, "questions with a Next and no final button")
    if typed:
        return out(FORM, f"{len(typed)} question(s) on the page")
    if text.strip() or controls:
        return out(CONTENT, "something to read or follow, no questions")
    return out(UNKNOWN, "nothing readable on the page yet")


def say(state: str) -> str:
    """The state in words, for a sentence he hears."""
    return {
        CONTENT: "a page to read", FORM: "a form", ACCOUNT_LOGIN: "a sign-in page",
        ACCOUNT_SIGNUP: "a page to create an account", EMAIL_VERIFICATION:
        "a page wanting a code from email", SMS_VERIFICATION: "a page wanting a code by text",
        MFA_CHALLENGE: "a page wanting a second sign-in factor",
        MULTI_PAGE_WIZARD: "one step of a multi-page form", REVIEW: "a review page",
        SUCCESS: "a confirmation page", CAPTCHA: "a human check", ERROR: "an error page",
        UNKNOWN: "a page I cannot read yet"}.get(state, "a page")
