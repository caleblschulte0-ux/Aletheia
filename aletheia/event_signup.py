"""Signing him up for things, on his ruling.

His words, 2026-10-09: *"Okay, until I actually start getting into this, I
need uh, her to just start throwing shit on my calendar and signing me up
for stuff."* "This" is Project Reboot - the job, the move, the house - and
until he is driving it himself she does the joining: a hiring webinar an
employer emails about, a career fair, an info session, a networking event.

Until this module, nothing could. The interview path books a scheduling
link (`calendly`), and a free event's registration page was a web task,
which is operator_always - one tap per event, on a day he has said he will
not be the one tapping. So `event.register` is its own capability, a
registry_grant one, spent under the sign-ups grant his ruling creates
(`config/rulings.json`, `runtime._apply_rulings`), and it does ONE kind of
thing: fill a FREE registration form with his ordinary contact details and
press Register.

What it will not do, by construction rather than by remembering to:

- **Money.** A price on the page, a card field, a checkout: she leaves it
  and says so. No grant reaches spending (§56 L4), and "free" is read off
  the page, not assumed from the host.
- **An account, a CAPTCHA, an agreement.** A password box is an account
  (`account.create` has its own rules), a CAPTCHA is a wall she does not
  climb, and a required "I agree" box is a binding term: each stops her
  BEFORE anything is pressed, with the reason.
- **A question she cannot answer from his facts.** A required field that
  is not a name, an email, a phone, a place, a title or an employer stops
  her; she does not guess at a form.
- **A clash.** When the page names one time and it overlaps something
  already on his calendar - an interview, above all - she does not sign
  him up for it.
- **His hours.** A weekday event that starts before 5:30 pm Central is left:
  he works days. Evenings and weekends only.
- **Volume.** At most `MAX_PER_WEEK` sign-ups a week, and one per page
  ever. "Signing me up for stuff" is not "fill my inbox with webinars".

Every sign-up is journaled, recorded in the unattended ledger as OUTWARD,
and said to him after the fact in one notice; when the page names its
time it goes on his calendar (her own, and the live one under the same
grant's `calendar.write`).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from aletheia import journal, stateio

ACTOR = "aletheia-sign-ups"
CAPABILITY = "event.register"
#: Pages whose job is to register people for an event. A plain meeting link
#: is not a sign-up, so Zoom and GoToWebinar count only on their register
#: paths.
EVENT_HOSTS = ("eventbrite.com", "lu.ma", "luma.com", "meetup.com", "on24.com", "bigmarker.com",
               "livestorm.co", "crowdcast.io", "airmeet.com", "hopin.com", "goldcast.io",
               "joinhandshake.com", "app.joinhandshake.com", "splashthat.com", "cvent.com",
               "events.zoom.us", "attendee.gotowebinar.com", "webinar.ringcentral.com")
_REGISTER_PATHS = (("zoom.us", "/webinar/register"), ("zoom.us", "/meeting/register"),
                   ("zoom.com", "/webinar/register"), ("gotowebinar.com", "/register"))
#: His sign-ups in one week, at most. His Project Reboot answers, 2026-10-09:
#: at most three a week, evenings after 5:30 pm Central and weekends only.
MAX_PER_WEEK = 3
EVENINGS_FROM = dt.time(17, 30)
HIS_ZONE = "America/Chicago"
DEFAULT_MINUTES = 60

_LINK = re.compile(r"https?://[^\s<>\"'\)\]]+", re.I)
#: A line that prices the thing: an amount above zero next to the words a
#: price sits beside. A salary in a fair's blurb ("roles paying $90K") is
#: not on such a line; a ticket is.
_PRICE_WORDS = re.compile(r"ticket|price|fee|cost|admission|pay\b|payment|donat|checkout|order total|"
                          r"subtotal|per person|general admission|early bird", re.I)
_AMOUNT = re.compile(r"(?:[$£€]\s?(\d[\d,]*(?:\.\d{1,2})?))|(?:(\d[\d,]*(?:\.\d{1,2})?)\s?(?:usd|dollars))", re.I)
_CAPTCHA = re.compile(r"recaptcha|hcaptcha|turnstile|verify (?:that )?you(?:'re| are) (?:a )?human|"
                      r"i'?m not a robot", re.I)
_CONFIRMED = re.compile(
    r"you(?:'|’| a)?re (?:all )?(?:registered|signed up|going|in\b|on the (?:guest ?)?list)|"
    r"registration (?:is )?(?:confirmed|complete|successful)|thanks? (?:you )?for (?:registering|signing up)|"
    r"see you there|check your (?:email|inbox)|confirmation (?:email )?(?:has been |was )?sent|"
    r"order (?:is )?complete|you(?:'|’| a)?re attending", re.I)
_REFUSED = re.compile(r"is required|invalid|please (?:enter|fill|complete|correct)|something went wrong|"
                      r"try again|sold out|registration (?:is )?closed|event (?:is )?full|no longer available", re.I)
_REGISTER_BUTTON = re.compile(r"^\s*(?:register(?: now| for free| for this event)?|sign ?up|rsvp|"
                              r"reserve(?: a| my)? (?:spot|seat|place)|save my (?:spot|seat)|count me in|"
                              r"submit|complete registration|join (?:the )?(?:waitlist|event)|"
                              r"get (?:a )?(?:free )?ticket)\s*$", re.I)
_AGREES = re.compile(r"agree|terms|consent|privacy|acknowledge|accept", re.I)

#: What an event form may ask that his facts answer, in the words forms use.
#: Longest phrase wins, so "company name" is the employer and not his name.
ASKS: dict[str, tuple[str, ...]] = {
    "first_name": ("first name", "given name", "forename", "fname"),
    "last_name": ("last name", "surname", "family name", "lname"),
    "legal_name": ("full name", "your name", "name"),
    "email": ("email", "e-mail", "email address"),
    "phone": ("phone", "mobile", "telephone", "cell"),
    "city": ("city", "town"),
    "state": ("state", "province", "region"),
    "postal_code": ("zip", "postal", "postcode"),
    "country": ("country",),
    "linkedin": ("linkedin",),
    "current_title": ("job title", "current title", "your title", "position", "role", "title"),
    "current_employer": ("company name", "company", "organization", "organisation", "employer"),
}
_AUTOCOMPLETE = {"given-name": "first_name", "family-name": "last_name", "name": "legal_name",
                 "email": "email", "tel": "phone", "address-level2": "city", "address-level1": "state",
                 "postal-code": "postal_code", "country": "country", "country-name": "country",
                 "organization": "current_employer", "organization-title": "current_title"}

_ZONES = (
    (re.compile(r"\b(?:EDT|EST|ET|Eastern(?: Time)?)\b"), "America/New_York"),
    (re.compile(r"\b(?:CDT|CST|CT|Central(?: Time)?)\b"), "America/Chicago"),
    (re.compile(r"\b(?:MDT|MST|MT|Mountain(?: Time)?)\b"), "America/Denver"),
    (re.compile(r"\b(?:PDT|PST|PT|Pacific(?: Time)?)\b"), "America/Los_Angeles"),
    (re.compile(r"\b(?:UTC|GMT)\b(?![+-]\d)"), "UTC"),
)

_FIELDS_JS = """() => Array.from(document.querySelectorAll('input, select, textarea')).map((el, i) => {
  const st = window.getComputedStyle(el);
  const type = (el.type || '').toLowerCase();
  const visible = type !== 'hidden' && st.display !== 'none' && st.visibility !== 'hidden'
                  && (el.offsetParent !== null || st.position === 'fixed');
  let label = '';
  if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) label = l.innerText; }
  if (!label) { const l = el.closest('label'); if (l) label = l.innerText; }
  label = (label || '').trim();
  return {index: i, tag: el.tagName.toLowerCase(), type: type, name: el.name || '', id: el.id || '',
          placeholder: el.placeholder || '', aria: el.getAttribute('aria-label') || '',
          autocomplete: (el.getAttribute('autocomplete') || '').toLowerCase(), label: label.slice(0, 200),
          required: !!(el.required || el.getAttribute('aria-required') === 'true' || /\\*\\s*$/.test(label)),
          visible: visible,
          options: el.tagName === 'SELECT' ? Array.from(el.options).map(o => o.text.trim()).slice(0, 300) : []};
})"""
_CAPTCHA_JS = """() => !!document.querySelector('.g-recaptcha, .h-captcha, .cf-turnstile, iframe[src*="recaptcha"], '
  + 'iframe[src*="hcaptcha"], iframe[src*="turnstile"], iframe[src*="challenges.cloudflare"]')"""
_BUTTONS_JS = """() => Array.from(document.querySelectorAll('button, input[type=submit], a[role=button], a'))
  .map((el, i) => ({index: i, text: ((el.innerText || el.value || el.getAttribute('aria-label') || '') + '').trim().slice(0, 80),
                    submit: (el.type || '').toLowerCase() === 'submit',
                    visible: el.offsetParent !== null}))"""


def _rehearsal() -> bool:
    """A rehearsal (`talk --sandbox`) never presses anything on a real site."""
    import os
    return bool(os.environ.get("ALETHEIA_REHEARSAL"))


# ---- what a link is ----------------------------------------------------------

def is_event_page(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or "").casefold().removeprefix("www.")
    path = parts.path.casefold()
    for h, prefix in _REGISTER_PATHS:
        if (host == h or host.endswith("." + h)) and prefix in path:
            return True
    return any(host == h or host.endswith("." + h) for h in EVENT_HOSTS)


def find_event_links(text: str) -> list[str]:
    """Every event-registration link in the text, first seen first, once each."""
    out: list[str] = []
    for raw in _LINK.findall(str(text or "")):
        url = raw.rstrip(".,;:!?")
        if is_event_page(url) and url not in out:
            out.append(url)
    return out


# ---- what the page says ------------------------------------------------------

def costs_money(body: str, fields: list[dict]) -> str:
    """Why this page would take his money, or "" when it would not. Fails
    toward refusing: a false alarm costs him one tap, a miss spends."""
    for f in fields:
        hay = " ".join(str(f.get(k) or "") for k in ("name", "id", "label", "placeholder", "aria", "autocomplete"))
        if re.search(r"\bcc-|card ?number|cardnumber|\bcvc\b|\bcvv\b|security code|expir", hay, re.I):
            return "it asks for a card"
    for line in str(body or "").splitlines():
        if not _PRICE_WORDS.search(line):
            continue
        for m in _AMOUNT.finditer(line):
            raw = (m.group(1) or m.group(2) or "0").replace(",", "")
            try:
                if float(raw) > 0:
                    return f"it costs money ({' '.join(line.split())[:80]})"
            except ValueError:
                return "it may cost money"
    return ""


def _descriptor(f: dict) -> str:
    return " ".join(str(f.get(k) or "") for k in ("label", "aria", "placeholder", "name", "id")).casefold() \
        .replace("_", " ").replace("-", " ")


def field_for(f: dict) -> str:
    """Which of his facts this box asks for, or "" when none does."""
    auto = str(f.get("autocomplete") or "").split()[-1:] or [""]
    if auto[0] in _AUTOCOMPLETE:
        return _AUTOCOMPLETE[auto[0]]
    if str(f.get("type") or "") == "email":
        return "email"
    if str(f.get("type") or "") == "tel":
        return "phone"
    hay = " " + re.sub(r"[^a-z0-9 ]+", " ", _descriptor(f)) + " "
    best, length = "", 0
    for field, phrases in ASKS.items():
        for phrase in phrases:
            if f" {phrase} " in hay and len(phrase) > length:
                best, length = field, len(phrase)
    return best


def plan_fields(fields: list[dict], facts: dict) -> tuple[list[dict], list[str]]:
    """(what to fill, what stops her). Only visible boxes; a required box she
    cannot answer from his facts stops her, and so does a required agreement."""
    fills: list[dict] = []
    stops: list[str] = []
    for f in fields:
        if not f.get("visible") or str(f.get("type") or "") in ("hidden", "submit", "button", "image", "reset"):
            continue
        kind = str(f.get("type") or "")
        words = " ".join(str(f.get("label") or f.get("aria") or f.get("placeholder") or f.get("name") or "").split())
        if kind == "password":
            stops.append("it wants an account and a password")
            continue
        if kind in ("checkbox", "radio"):
            if f.get("required"):
                stops.append(("it asks you to agree to " if _AGREES.search(words) else "it asks ")
                             + (words[:80] or "a box only you can tick"))
            continue
        field = field_for(f)
        value = str(facts.get(field) or "") if field else ""
        if field == "legal_name" and not value:
            value = " ".join(x for x in (facts.get("first_name"), facts.get("last_name")) if x)
        if field and value:
            if f.get("tag") == "select":
                options = [o for o in f.get("options") or [] if o]
                pick = next((o for o in options if o.casefold() == value.casefold()), "")
                if not pick and field == "country" and value.casefold() in ("us", "usa", "united states"):
                    pick = next((o for o in options if o.casefold() in
                                 ("united states", "united states of america", "usa", "us")), "")
                if not pick:
                    if f.get("required"):
                        stops.append(f"it asks {words[:80] or field} with no answer of yours on its list")
                    continue
                value = pick
            fills.append({"index": int(f.get("index", -1)), "field": field, "value": value,
                          "select": f.get("tag") == "select"})
        elif f.get("required"):
            stops.append(f"it asks {words[:80] or 'something'}"
                         + (", and I don't know your answer" if field else ""))
    return fills, stops


def _zone_of(text: str) -> str:
    found = {zone for pattern, zone in _ZONES if pattern.search(text)}
    return found.pop() if len(found) == 1 else ("" if found else HIS_ZONE)


def when(body: str, *, now: dt.datetime) -> dict | None:
    """The one time this page is for, in HIS zone: {"start", "end"}, or None.

    None when the page names no time, several days (a series), more than one
    zone, or a time already past - a wrong entry on his calendar is worse
    than none, and the site's confirmation email carries the time anyway. A
    time with no zone is read in his: the browser on his PC renders in it."""
    from aletheia import reply_understanding as ru
    text = str(body or "")[:6000]
    zone = _zone_of(text)
    if not zone:
        return None
    times = ru.extract_times(text, reference=now, timezone=zone, minutes=DEFAULT_MINUTES)
    starts = sorted({t["start"] for t in times})
    if not starts:
        return None
    parsed = [dt.datetime.fromisoformat(s) for s in starts]
    if len({p.date() for p in parsed}) != 1 or len(parsed) > 2:
        return None
    start = parsed[0]
    end = parsed[1] if len(parsed) == 2 and parsed[1] > start else start + dt.timedelta(minutes=DEFAULT_MINUTES)
    if end - start > dt.timedelta(hours=12) or start <= now:
        return None
    his = ZoneInfo(HIS_ZONE)
    return {"start": start.astimezone(his).isoformat(), "end": end.astimezone(his).isoformat()}


def said_when(start: str) -> str:
    moment = dt.datetime.fromisoformat(start).astimezone(ZoneInfo(HIS_ZONE))
    hour = moment.strftime("%I").lstrip("0")
    clock = hour + (moment.strftime(":%M") if moment.minute else "") + (" am" if moment.hour < 12 else " pm")
    return f"{moment.strftime('%A, %B')} {moment.day} at {clock} Central"


# ---- what she has done -------------------------------------------------------

def _ledger_path():
    return stateio.private_dir("sign_ups") / "registered.json"


def registered() -> dict:
    try:
        raw = stateio.read_json(_ledger_path())
    except (OSError, ValueError):
        return {}
    rows = raw.get("pages") if isinstance(raw, dict) else None
    return {str(k): v for k, v in (rows or {}).items() if isinstance(v, dict)}


def _remember(url: str, row: dict) -> None:
    rows = registered()
    rows[_key(url)] = row
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    stateio.write_json_atomic(path, {"version": 1, "pages": rows})


def _key(url: str) -> str:
    parts = urlsplit(str(url or ""))
    return f"{(parts.hostname or '').casefold().removeprefix('www.')}{parts.path.rstrip('/')}"


def this_week(now: dt.datetime) -> int:
    floor = now - dt.timedelta(days=7)
    count = 0
    for row in registered().values():
        if row.get("state") != "registered":
            continue
        try:
            if dt.datetime.fromisoformat(str(row.get("at"))) >= floor:
                count += 1
        except ValueError:
            continue
    return count


def _facts() -> dict:
    from aletheia import profile
    known = profile.known()
    facts = {k: str(v) for k, v in known.items() if isinstance(v, (str, int)) and str(v).strip()}
    # The number he makes accounts with, never his real one (`signup`'s rule):
    # an event list is a mailing list, and his real number is for employers.
    # With no sign-up number a required phone box stops her.
    facts.pop("phone", None)
    if facts.get("signup_phone"):
        facts["phone"] = facts["signup_phone"]
    return facts



# ---- whether she may -----------------------------------------------------------

def _switch_path():
    return stateio.private_dir("sign_ups") / "switch.json"


def status() -> dict:
    """{"on", "ruled_by", "set_by"}. His hand at the keyboard wins; where he
    never touched it, his ruling (`config/rulings.json`, switch "sign_ups")
    decides; with neither, off."""
    try:
        raw = stateio.read_json(_switch_path())
    except (OSError, ValueError):
        raw = {}
    if isinstance(raw, dict) and isinstance(raw.get("on"), bool):
        return {"on": raw["on"], "ruled_by": "", "set_by": str(raw.get("by") or "operator")}
    from aletheia import rulings
    ruling = rulings.for_switch("sign_ups")
    if ruling:
        return {"on": bool(ruling["on"]), "ruled_by": ruling["id"], "set_by": "ruling"}
    return {"on": False, "ruled_by": "", "set_by": ""}


def set_switch(on: bool, *, by: str = "operator") -> dict:
    path = _switch_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    stateio.write_json_atomic(path, {"version": 1, "on": bool(on), "by": by,
                                     "at": dt.datetime.now(dt.timezone.utc).isoformat()})
    if not on:
        from aletheia import standing
        standing.sign_ups_disable(via=by)
    journal.append("decision", "sign-ups", f"signing him up for events turned {'on' if on else 'off'}", actor=by)
    return status()


#: Mail that is about an event worth his time, and about his career - both,
#: because "signing me up for stuff" was said about the job, the move and the
#: house, not about every webinar a vendor mails.
_EVENT_WORDS = re.compile(r"webinar|info(?:rmation(?:al)?)? session|career fair|job fair|hiring event|"
                          r"open house|networking|meet ?up|virtual event|career event|recruiting event|"
                          r"workshop|panel|town ?hall|register (?:now|here|today)|save your (?:spot|seat)|rsvp", re.I)
_CAREER_WORDS = re.compile(r"career|hiring|recruit|job|opportunit|talent|candidate|employer|"
                           r"internship|networking|professional|sioux falls|relocat|housing|home ?buy", re.I)


def consider_mail(event: dict, *, subject: str, text: str, registrar=None,
                  now: dt.datetime | None = None) -> dict | None:
    """An email inviting him to an event: sign him up for it, when the switch
    is on. One link per email (the first event page it names), and nothing at
    all from his own address. Never raises; None when there is nothing to do."""
    try:
        if not status()["on"]:
            return None
        # The words are read without the links: a link's own slug ("...-hiring-night")
        # is the organiser's marketing, not what the email is about.
        hay = _LINK.sub(" ", f"{subject}\n{text[:4000]}")
        if not (_EVENT_WORDS.search(hay) and _CAREER_WORDS.search(hay)):
            return None
        links = [u for u in find_event_links(text) if _key(u) not in registered()]
        if not links:
            return None
        why = "from an email: " + " ".join(subject.split())[:100]
        return (registrar or register)(links[0], why=why, now=now)
    except Exception:
        return None

# ---- doing it ----------------------------------------------------------------

def in_his_hours(slot: dict) -> bool:
    """Evenings from 5:30 pm Central, or any time at the weekend."""
    start = dt.datetime.fromisoformat(slot["start"]).astimezone(ZoneInfo(HIS_ZONE))
    return start.weekday() >= 5 or start.time() >= EVENINGS_FROM


def register(url: str, *, why: str = "", page=None, spender=None, now: dt.datetime | None = None,
             facts: dict | None = None, busy=None, calendar_writer=None, notify=None,
             any_host: bool = False) -> dict:
    """Sign him up on one free event page. Never raises.

    {"state": registered | unconfirmed | needs_grant | costs_money | blocked |
    clashes | already | enough_this_week | not_an_event | failed, "say", ...}.
    `page` is a Playwright-shaped page (tests pass a fake); otherwise her own
    browser profile is opened. `spender(capability, action_id)` returns the
    grant covering the press, or None; otherwise `authority.satisfy`."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if _rehearsal():
        return {"state": "failed", "say": "this is a rehearsal, so I didn't sign you up"}
    if not is_event_page(url) and not (any_host and urlsplit(str(url)).scheme in ("http", "https")):
        return {"state": "not_an_event", "say": "that is not an event's sign-up page I know"}
    done = registered().get(_key(url))
    if done and done.get("state") == "registered":
        return {"state": "already", "say": f"you're already signed up for {done.get('title') or 'that'}"}
    if this_week(now) >= MAX_PER_WEEK:
        return {"state": "enough_this_week",
                "say": f"I've signed you up for {MAX_PER_WEEK} things this week already, so I left this one"}
    facts = _facts() if facts is None else facts
    if not facts.get("email"):
        return {"state": "blocked", "say": "I don't have your email address to sign you up with"}
    action_id = f"signup-{re.sub(r'[^a-z0-9]+', '-', _key(url).casefold())[:60]}"
    session = None
    try:
        if page is None:
            from aletheia import browse
            ok, why_not = browse.available()
            if not ok:
                return {"state": "failed", "say": f"my browser isn't ready ({why_not})"}
            session = browse._Session()
            ctx = session.__enter__()
            page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        _settle(page, 1500)
        body = _text(page)
        title = _title(page, body)
        fields = _read_fields(page)
        stop = _stopped(body, fields, page)
        if stop:
            return _left(url, title, stop, now)
        slot = when(body, now=now)
        if any_host and not is_event_page(url) and not (slot and _EVENT_WORDS.search(body[:6000])):
            # A page she found on her own, on a host that is not an event site, has to say it is an
            # event AND name its one time; a shop's "sign up" is not one, and neither is a
            # newsletter box under "upcoming events" (that is a list, joined by `join_list`).
            return _left(url, title, {"state": "not_an_event", "say": "the page doesn't say it's an event"}, now)
        if slot and not in_his_hours(slot):
            return _left(url, title, {"state": "outside_hours",
                                      "say": f"it's {said_when(slot['start'])}, inside your working day"}, now)
        if slot:
            clash = _clash(slot, busy)
            if clash:
                return _left(url, title, {"state": "clashes", "say": f"it clashes with {clash}"}, now)
        # THE ONE THING THAT REACHES SOMEBODY ELSE, under his grant or not at all.
        if spender is None:
            from aletheia import authority
            spender = authority.satisfy
        grant = spender(CAPABILITY, action_id)
        if not grant:
            return {"state": "needs_grant", "title": title, "url": url,
                    "say": "signing you up for things needs the sign-ups permission, and it isn't on"}
        fills, stops = plan_fields(fields, facts)
        if not any(f["field"] == "email" for f in fills):
            # The form is behind a Register button on most event pages.
            if _press(page, opening=True):
                _settle(page, 1500)
                body = _text(page) or body
                fields = _read_fields(page)
                stop = _stopped(body, fields, page)
                if stop:
                    return _left(url, title, stop, now)
                fills, stops = plan_fields(fields, facts)
        if stops:
            return _left(url, title, {"state": "blocked", "say": stops[0]}, now)
        if not any(f["field"] == "email" for f in fills):
            return _left(url, title, {"state": "blocked", "say": "I couldn't find where to put your email"}, now)
        for f in fills:
            _fill(page, f)
        if not _press(page, opening=False):
            return _left(url, title, {"state": "blocked", "say": "I couldn't find its Register button"}, now)
        _settle(page, 2000)
        after = _text(page)
        confirmed = bool(_CONFIRMED.search(after)) and not _REFUSED.search(after[:2000])
        return _signed_up(url, title, slot, grant=grant, confirmed=confirmed, why=why, now=now,
                          evidence=" ".join(after.split())[:300], calendar_writer=calendar_writer, notify=notify)
    except Exception as exc:  # noqa: BLE001 - never breaks the beat
        return {"state": "failed", "say": f"the page broke ({type(exc).__name__})"}
    finally:
        if session is not None:
            try:
                session.__exit__(None, None, None)
            except Exception:
                pass


def _stopped(body: str, fields: list[dict], page) -> dict | None:
    money = costs_money(body, fields)
    if money:
        return {"state": "costs_money", "say": money}
    captcha = bool(_CAPTCHA.search(body))
    if not captcha:
        try:
            captcha = bool(page.evaluate(_CAPTCHA_JS))
        except Exception:
            captcha = False
    if captcha:
        return {"state": "blocked", "say": "it has a check that you are not a robot"}
    if any(f.get("visible") and f.get("type") == "password" for f in fields):
        return {"state": "blocked", "say": "it wants an account and a password"}
    if _REFUSED.search(body[:3000]) and re.search(r"sold out|closed|full|no longer available", body[:3000], re.I):
        return {"state": "blocked", "say": "registration is closed or full"}
    return None


def _clash(slot: dict, busy) -> str:
    if busy is not None:
        hits = busy(slot["start"], slot["end"])
    else:
        try:
            from aletheia import calendar_reasoning
            hits = calendar_reasoning.conflicts_for(slot["start"], slot["end"])
        except Exception:
            hits = []
    if not hits:
        return ""
    first = hits[0]
    return str(first.get("title") or (first.get("event") or {}).get("title") or "something on your calendar")


def _left(url: str, title: str, stop: dict, now: dt.datetime) -> dict:
    """She did not sign him up, and the page will not be tried again for the
    same reason: written down so the next email about it is not a retry."""
    _remember(url, {"state": stop["state"], "title": title, "at": now.isoformat(), "why": stop["say"]})
    journal.append("event", "sign-ups", f"left {title or _key(url)} unsigned: {stop['say']}", actor=ACTOR)
    return {**stop, "title": title, "url": url}


def _signed_up(url: str, title: str, slot: dict | None, *, grant: str, confirmed: bool, why: str,
               now: dt.datetime, evidence: str, calendar_writer=None, notify=None) -> dict:
    from aletheia import notifications
    name = title or "an event"
    on_calendar = ""
    if slot and confirmed:
        on_calendar = _put_on_calendar(name, slot, calendar_writer)
    state = "registered" if confirmed else "unconfirmed"
    _remember(url, {"state": state, "title": title, "at": now.isoformat(), "slot": slot or {},
                    "grant": grant, "why": why[:200]})
    if confirmed:
        sentence = (f"I signed you up for {name}"
                    + (f", {said_when(slot['start'])}" if slot else "")
                    + (f" ({why})" if why else "")
                    + (f"; {on_calendar}" if on_calendar else
                       "; the confirmation email has the details") + ".")
    else:
        sentence = (f"I pressed Register on {name} and the page didn't say it worked. "
                    "Check your email for a confirmation.")
    (notify or notifications.publish)(
        f"Signed you up: {name}" if confirmed else f"Not sure the sign-up for {name} went through",
        sentence, priority="NORMAL", source="sign-ups",
        about=notifications.CHANGED if confirmed else notifications.FAILED,
        dedupe_key=f"sign-up:{_key(url)}", related={"url": url})
    journal.append("action" if confirmed else "alert", "sign-ups",
                   f"{sentence} (under grant {grant})", actor=ACTOR)
    try:
        from aletheia import autonomy, tools
        autonomy.record(tool="event_signup.register", args={"url": url, "title": title},
                        consequence=tools.OUTWARD, said=sentence, route="sign-ups",
                        undo={"how": autonomy.NONE,
                              "why": "a sign-up reached the organiser; cancel it from their confirmation email"})
    except Exception:
        pass
    return {"state": state, "title": title, "url": url, "slot": slot, "grant": grant,
            "say": sentence, "evidence": evidence}


def _put_on_calendar(name: str, slot: dict, calendar_writer=None) -> str:
    from aletheia import calendar as cal
    eid = f"event-{re.sub(r'[^a-z0-9]+', '-', name.casefold())[:30].strip('-')}-{slot['start'][:10]}"
    held = False
    try:
        cal.create(eid, name, slot["start"], slot["end"], source="sign-ups", status="CONFIRMED", movable=False)
        held = True
    except FileExistsError:
        held = True
    except Exception:
        held = False
    try:
        if calendar_writer is None:
            from aletheia import calendly
            calendar_writer = calendly.put_on_his_calendar
        live = calendar_writer(title=name, start=slot["start"], end=slot["end"]) or {}
    except Exception:
        live = {}
    if live.get("state") == "written":
        return "it's on your calendar"
    return "it's on your calendar here, and the organiser's invitation will add it to yours" if held else ""


# ---- mailing lists: so the invitations arrive ---------------------------------------

#: The pages whose free email lists carry the events he would want, as DATA
#: (`config/sign_up_lists.json`): a reviewed edit adds one, nothing in code
#: names a place. She looks for a free "subscribe" form on each once.
def _lists_path():
    from aletheia.fleet import REPO_ROOT
    return REPO_ROOT / "config" / "sign_up_lists.json"


def list_pages() -> list[dict]:
    try:
        raw = json.loads(_lists_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = raw.get("pages") if isinstance(raw, dict) else None
    return [r for r in rows or [] if isinstance(r, dict) and str(r.get("url") or "").startswith("https://")]


_SUBSCRIBE_BUTTON = re.compile(r"^\s*(?:subscribe(?: now)?|sign ?up(?: now| for (?:updates|our newsletter|emails))?|"
                               r"join(?: (?:the|our) (?:list|newsletter|mailing list))?|get updates|keep me (?:posted|updated)|"
                               r"submit|send)\s*$", re.I)
_SUBSCRIBED = re.compile(r"thank(?:s| you)(?: for (?:subscribing|signing up|joining))?|you(?:'|’| a)?re (?:subscribed|on the list|in\b|all set)|"
                         r"successfully (?:subscribed|signed up)|check your (?:email|inbox)|confirm your (?:email|subscription)",
                         re.I)
_LIST_WORDS = re.compile(r"newsletter|mailing list|email (?:list|updates)|subscribe|stay (?:in the loop|informed|connected)|"
                         r"get (?:our )?(?:updates|emails)", re.I)


def join_list(url: str, *, why: str = "", page=None, spender=None, now: dt.datetime | None = None,
              facts: dict | None = None, notify=None) -> dict:
    """Put his email on one free mailing list so event invitations reach his
    inbox. Never raises. Only his name and email are given; the same walls
    stop her as on an event page (money, an account, a robot check, a box to
    agree to, a question she cannot answer). Tried once per page.

    {"state": joined | unconfirmed | no_list | needs_grant | costs_money | blocked | already | failed, "say"}."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if _rehearsal():
        return {"state": "failed", "say": "this is a rehearsal, so I didn't sign you up"}
    if urlsplit(str(url)).scheme != "https":
        return {"state": "blocked", "say": "only a secure page gets his email"}
    if _key(url) in registered():
        return {"state": "already", "say": "I've already been to that list"}
    facts = _facts() if facts is None else facts
    facts = {k: v for k, v in facts.items() if k in ("first_name", "last_name", "legal_name", "email")}
    if not facts.get("email"):
        return {"state": "blocked", "say": "I don't have your email address to sign you up with"}
    session = None
    try:
        if page is None:
            from aletheia import browse
            ok, why_not = browse.available()
            if not ok:
                return {"state": "failed", "say": f"my browser isn't ready ({why_not})"}
            session = browse._Session()
            page = session.__enter__().new_page()
        page.goto(url, wait_until="domcontentloaded")
        _settle(page, 1500)
        body = _text(page)
        title = _title(page, body)
        fields = _read_fields(page)
        stop = _stopped(body, fields, page)
        if stop:
            return _left(url, title, stop, now)
        fills, stops = plan_fields(fields, facts)
        if not _LIST_WORDS.search(body) or not any(f["field"] == "email" for f in fills):
            return _left(url, title, {"state": "no_list", "say": "there's no free email list on that page"}, now)
        if stops:
            return _left(url, title, {"state": "blocked", "say": stops[0]}, now)
        if spender is None:
            from aletheia import authority
            spender = authority.satisfy
        grant = spender(CAPABILITY, f"list-{re.sub(r'[^a-z0-9]+', '-', _key(url).casefold())[:60]}")
        if not grant:
            return {"state": "needs_grant", "title": title, "url": url,
                    "say": "signing you up for things needs the sign-ups permission, and it isn't on"}
        for f in fills:
            _fill(page, f)
        if not _press_matching(page, _SUBSCRIBE_BUTTON):
            return _left(url, title, {"state": "blocked", "say": "I couldn't find its Subscribe button"}, now)
        _settle(page, 2000)
        after = _text(page)
        confirmed = bool(_SUBSCRIBED.search(after)) and not _REFUSED.search(after[:2000])
        state = "joined" if confirmed else "unconfirmed"
        name = title or _key(url)
        _remember(url, {"state": state, "title": title, "at": now.isoformat(), "grant": grant, "why": why[:200]})
        sentence = (f"I put your email on {name}'s list so their event invitations come to you"
                    if confirmed else f"I tried to join {name}'s email list and the page didn't say it worked")
        from aletheia import notifications
        (notify or notifications.publish)(
            f"Joined a list: {name}" if confirmed else f"Not sure I joined {name}'s list",
            sentence + ".", priority="LOW", source="sign-ups", about=notifications.CHANGED,
            dedupe_key=f"sign-up-list:{_key(url)}", related={"url": url})
        journal.append("action", "sign-ups", f"{sentence} (under grant {grant})", actor=ACTOR)
        try:
            from aletheia import autonomy, tools
            autonomy.record(tool="event_signup.join_list", args={"url": url}, consequence=tools.OUTWARD,
                            said=sentence, route="sign-ups",
                            undo={"how": autonomy.NONE, "why": "unsubscribe from the link in their emails"})
        except Exception:
            pass
        return {"state": state, "title": title, "url": url, "grant": grant, "say": sentence}
    except Exception as exc:  # noqa: BLE001 - never breaks the beat
        return {"state": "failed", "say": f"the page broke ({type(exc).__name__})"}
    finally:
        if session is not None:
            try:
                session.__exit__(None, None, None)
            except Exception:
                pass


_LISTS_TRIED = {"day": ""}


def join_lists(*, now: dt.datetime | None = None, joiner=None) -> list[dict]:
    """The beat's step: when the switch is on, one list page a day that she
    has not been to yet. Never raises."""
    now = now or dt.datetime.now(dt.timezone.utc)
    day = now.date().isoformat()
    if _LISTS_TRIED["day"] == day:
        return []
    try:
        if not status()["on"]:
            return []
        done = registered()
        todo = [r for r in list_pages() if _key(r["url"]) not in done]
        if not todo:
            return []
        _LISTS_TRIED["day"] = day
        row = todo[0]
        out = (joiner or join_list)(row["url"], why=str(row.get("why") or "so event invitations reach you"),
                                    now=now)
        return [{"url": row["url"], "state": out.get("state", "")}]
    except Exception:
        return []


def sign_up_tool(url: str, why: str = "") -> dict:
    """The tool a long mission's task uses (`browser_tools`, "event.register"):
    an event page is registered for, a mailing-list page is joined, both under
    every rule above. Called by `program_run` under his grant."""
    if is_event_page(url):
        return register(url, why=why or "found while working on a mission")
    out = register(url, why=why or "found while working on a mission", any_host=True)
    if out.get("state") == "not_an_event":
        _forget(url)
        return join_list(url, why=why or "found while working on a mission")
    return out


def _forget(url: str) -> None:
    rows = registered()
    if rows.pop(_key(url), None) is not None:
        path = _ledger_path()
        stateio.write_json_atomic(path, {"version": 1, "pages": rows})


def _press_matching(page, pattern) -> bool:
    try:
        buttons = page.evaluate(_BUTTONS_JS) or []
    except Exception:
        return False
    wanted = [b for b in buttons if isinstance(b, dict) and b.get("visible") and pattern.match(str(b.get("text") or ""))]
    wanted = [b for b in wanted if b.get("submit")] or wanted
    if not wanted:
        return False
    try:
        page.locator("button, input[type=submit], a[role=button], a").nth(int(wanted[0]["index"])).click()
        return True
    except Exception:
        return False


# ---- the page, thinly ---------------------------------------------------------

def _settle(page, ms: int) -> None:
    try:
        page.wait_for_load_state("domcontentloaded")
    except Exception:
        pass
    try:
        page.wait_for_timeout(ms)
    except Exception:
        pass


def _text(page) -> str:
    try:
        return str(page.inner_text("body") or "")
    except Exception:
        return ""


def _title(page, body: str) -> str:
    for getter in (lambda: page.inner_text("h1"), lambda: page.title()):
        try:
            text = " ".join(str(getter() or "").split())
        except Exception:
            text = ""
        if text:
            return re.sub(r"\s*[|·-]\s*(?:eventbrite|zoom|meetup|luma|on24)\s*$", "", text, flags=re.I)[:120]
    return " ".join(body.split())[:60]


def _read_fields(page) -> list[dict]:
    try:
        rows = page.evaluate(_FIELDS_JS)
    except Exception:
        return []
    return [r for r in rows or [] if isinstance(r, dict)]


def _fill(page, f: dict) -> None:
    box = page.locator("input, select, textarea").nth(f["index"])
    if f.get("select"):
        box.select_option(label=f["value"])
    else:
        box.fill(f["value"])


def _press(page, *, opening: bool) -> bool:
    """Press the Register button. Opening: the one that reveals the form
    (not a form submit). Otherwise: the form's own submit, preferring one
    that says Register."""
    try:
        buttons = page.evaluate(_BUTTONS_JS) or []
    except Exception:
        return False
    wanted = [b for b in buttons if isinstance(b, dict) and b.get("visible") and _REGISTER_BUTTON.match(str(b.get("text") or ""))]
    if not opening:
        wanted = [b for b in wanted if b.get("submit")] or wanted \
            or [b for b in buttons if isinstance(b, dict) and b.get("visible") and b.get("submit")]
    elif any(b.get("submit") for b in wanted):
        wanted = [b for b in wanted if not b.get("submit")] or wanted
    if not wanted:
        return False
    try:
        page.locator("button, input[type=submit], a[role=button], a").nth(int(wanted[0]["index"])).click()
        return True
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sign him up for a free event, under the sign-ups grant.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    reg = sub.add_parser("register", help="sign him up on one event page")
    reg.add_argument("url")
    sub.add_parser("list", help="what she has signed him up for, and what she left")
    sub.add_parser("on", help="let her sign you up for free events")
    sub.add_parser("off", help="stop her signing you up for things")
    sub.add_parser("status", help="whether she may")
    args = ap.parse_args(argv)
    if args.cmd in ("on", "off"):
        print(json.dumps(set_switch(args.cmd == "on"), indent=1))
        return 0
    if args.cmd == "status":
        print(json.dumps(status(), indent=1))
        return 0
    if args.cmd == "register":
        print(json.dumps(register(args.url, why="asked at the keyboard"), indent=1, default=str))
        return 0
    print(json.dumps(registered(), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
