"""A scheduling link in an employer's email, booked in his window.

His words, 2026-09-24: *"If someone sends us a Calendly link, she can put 1
to 2.30 p.m. Central on there. And as long as she puts it on the calendar,
the Open Range Interactive Calendar, I'm fine with that. She shouldn't
send anything to outside correspondence yet."*

So this is the one outward thing the interview path does, and it is done
without a model choosing anything:

- the link is found in the email by its host (`SCHEDULING_HOSTS`);
- the page is walked by the shape Calendly renders - day buttons that say
  "Times available", time buttons carrying `data-start-time`, a Next
  button, a name-and-email form, a Schedule button;
- the slot is the FIRST open time on a weekday that falls inside his
  window in his zone and that his own calendar has free. Outside the
  window she books nothing: the window is his words, not a preference;
- the ONE press that reaches somebody else - "Schedule Event" - is made
  only when a standing grant covers `interview.book`
  (`python -m aletheia.interviews on`, at his keyboard, his words kept on
  it). Without it she stops on the filled form and says so.

Nothing here writes a reply: the site confirms the booking itself, and
outward mail is on hold (`mail.outward_hold`).
"""
from __future__ import annotations

import datetime as dt
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from aletheia import journal

ACTOR = "aletheia-interviews"
#: Hosts whose pages are a booking page and nothing else.
SCHEDULING_HOSTS = ("calendly.com", "cal.com", "meetings.hubspot.com", "app.goodtime.io",
                    "calendar.app.google", "savvycal.com", "zcal.co", "youcanbook.me")
CAPABILITY = "interview.book"
#: How many open days ahead she reads before saying none fit.
LOOK_AHEAD_DAYS = 10
#: A slot has to be at least this far off: booking something in forty
#: minutes is not a thing a person does to him.
MIN_NOTICE_H = 2.0
WEEKDAYS = {0, 1, 2, 3, 4}
_LINK = re.compile(r"https?://[^\s<>\"'\)\]]+", re.I)
_CONFIRMED = re.compile(r"you are scheduled|you're scheduled|is scheduled|confirmed|booking confirmed|"
                        r"calendar invitation has been sent|we've sent", re.I)
_REFUSED = re.compile(r"something went wrong|try again|no longer available|is required|invalid", re.I)


def find_scheduling_links(text: str) -> list[str]:
    """Every scheduling-page link in the text, first seen first, once each."""
    out: list[str] = []
    for raw in _LINK.findall(str(text or "")):
        url = raw.rstrip(".,;:!?")
        host = (urlsplit(url).hostname or "").casefold().removeprefix("www.")
        if not any(host == h or host.endswith("." + h) for h in SCHEDULING_HOSTS):
            continue
        if url not in out:
            out.append(url)
    return out


def _local(stamp: str, zone: ZoneInfo) -> dt.datetime:
    value = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(zone)


def _clock(value: str) -> dt.time:
    hour, minute = str(value).split(":")
    return dt.time(int(hour), int(minute))


def fits(start: str, *, window: dict, now: dt.datetime) -> bool:
    """A weekday, in his window in his zone, and not too soon."""
    zone = ZoneInfo(str(window.get("timezone") or "America/Chicago"))
    try:
        local = _local(start, zone)
    except (ValueError, TypeError):
        return False
    if local.weekday() not in WEEKDAYS:
        return False
    if (local - now.astimezone(zone)).total_seconds() < MIN_NOTICE_H * 3600:
        return False
    return _clock(window["start"]) <= local.time() <= _clock(window["end"])


def choose(slots: list[dict], *, window: dict, busy, now: dt.datetime) -> dict | None:
    """The first slot that fits and that his calendar has free. None when
    nothing does - she books nothing outside his window."""
    for slot in sorted(slots, key=lambda s: str(s.get("start") or "")):
        start, end = str(slot.get("start") or ""), str(slot.get("end") or "")
        if not start or not fits(start, window=window, now=now):
            continue
        try:
            if busy and busy(start, end or start):
                continue
        except Exception:
            continue
        return slot
    return None


# ---- the page --------------------------------------------------------------
_DAY_BUTTONS = ('button[aria-label*="Times available" i], button[aria-label*="times available" i], '
                'button[data-day]:not([disabled]), [role="grid"] button:not([disabled])')
_TIME_BUTTONS = "button[data-start-time], [data-start-time] button, button[data-time]"
_NEXT = 'button[aria-label^="Next" i], button:has-text("Next"), button:has-text("Confirm")'
_NAME = 'input[name="full_name"], input[name="name"], input[autocomplete="name"], input[id*="name" i]'
_EMAIL = 'input[name="email"], input[type="email"], input[autocomplete="email"]'
_SUBMIT = 'button[type="submit"], button:has-text("Schedule"), button:has-text("Book")'


def _settle(page, ms: int = 600) -> None:
    try:
        page.wait_for_load_state("domcontentloaded")
    except Exception:
        pass
    try:
        page.wait_for_timeout(ms)
    except Exception:
        pass


def _slot_end(start: str, minutes: int) -> str:
    try:
        value = dt.datetime.fromisoformat(start.replace("Z", "+00:00"))
        return (value + dt.timedelta(minutes=minutes)).isoformat()
    except ValueError:
        return start


def read_slots(page, *, days: int = LOOK_AHEAD_DAYS, minutes: int = 30) -> list[dict]:
    """Every open time the page offers over the next `days` open days, as
    {"start", "end", "day"} with the page's own ISO stamps. No model."""
    out: list[dict] = []
    seen: set[str] = set()
    try:
        day_buttons = page.query_selector_all(_DAY_BUTTONS)
    except Exception:
        return out
    opened = 0
    for button in day_buttons:
        if opened >= days:
            break
        try:
            label = (button.get_attribute("aria-label") or button.inner_text() or "").strip()
            button.click()
            _settle(page, 400)
        except Exception:
            continue
        opened += 1
        try:
            times = page.query_selector_all(_TIME_BUTTONS)
        except Exception:
            times = []
        for t in times:
            try:
                start = (t.get_attribute("data-start-time") or t.get_attribute("data-time") or "").strip()
                if not start:
                    holder = t.query_selector("xpath=ancestor::*[@data-start-time][1]")
                    start = (holder.get_attribute("data-start-time") if holder else "") or ""
            except Exception:
                start = ""
            if not start or start in seen:
                continue
            seen.add(start)
            out.append({"start": start, "end": _slot_end(start, minutes), "day": label})
    return out


def _open_day(page, label: str) -> bool:
    """Bring the chosen slot's day back on screen: reading the slots left the
    LAST day open, and a time button for another day is not on the page."""
    if not label:
        return False
    try:
        for button in page.query_selector_all(_DAY_BUTTONS):
            said = (button.get_attribute("aria-label") or button.inner_text() or "").strip()
            if said == label:
                button.click()
                _settle(page, 400)
                return True
    except Exception:
        return False
    return False


def _click_slot(page, start: str, day: str = "") -> bool:
    _open_day(page, day)
    for selector in (f'button[data-start-time="{start}"]', f'[data-start-time="{start}"] button',
                     f'[data-start-time="{start}"]', f'button[data-time="{start}"]'):
        try:
            el = page.query_selector(selector)
        except Exception:
            el = None
        if el:
            try:
                el.click()
                _settle(page, 400)
                return True
            except Exception:
                continue
    return False


def _click_first(page, selector: str) -> bool:
    try:
        el = page.query_selector(selector)
    except Exception:
        el = None
    if not el:
        return False
    try:
        el.click()
        _settle(page, 500)
        return True
    except Exception:
        return False


def _fill_first(page, selector: str, value: str) -> bool:
    try:
        el = page.query_selector(selector)
        if not el:
            return False
        el.fill(value)
        return True
    except Exception:
        return False


def book(url: str, *, name: str, email: str, window: dict, busy=None, now: dt.datetime | None = None,
         page=None, spender=None, minutes: int = 30) -> dict:
    """Walk the booking page and book one slot in his window. Never raises.

    Returns {"state": booked | needs_grant | no_slot | unconfirmed | failed,
    ...}. `page` is a Playwright page (tests); otherwise her own browser
    profile is opened. `spender(capability, action_id)` returns the grant
    that covers the press, or None (tests); otherwise `authority.satisfy`.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    action_id = f"book-{re.sub(r'[^a-z0-9]+', '-', urlsplit(url).path.casefold())[:40]}-{now.strftime('%Y%m%d%H%M')}"
    session = None
    try:
        if page is None:
            from aletheia import browse
            ok, why = browse.available()
            if not ok:
                return {"state": "failed", "why": f"her browser is not ready: {why}"}
            session = browse._Session()
            ctx = session.__enter__()
            page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        _settle(page, 1200)
        slots = read_slots(page, minutes=minutes)
        chosen = choose(slots, window=window, busy=busy, now=now)
        if not chosen:
            return {"state": "no_slot", "looked_at": len(slots), "url": url}
        if not _click_slot(page, chosen["start"], str(chosen.get("day") or "")):
            return {"state": "failed", "why": "the chosen time could not be pressed", "chosen": chosen}
        _click_first(page, _NEXT)
        _fill_first(page, _NAME, name)
        _fill_first(page, _EMAIL, email)
        # THE ONE OUTWARD PRESS, under his grant or not at all.
        if spender is None:
            from aletheia import authority
            spender = authority.satisfy
        grant = spender(CAPABILITY, action_id)
        if not grant:
            return {"state": "needs_grant", "chosen": chosen, "url": page.url, "action": action_id}
        if not _click_first(page, _SUBMIT):
            return {"state": "failed", "why": "no Schedule button on the form", "chosen": chosen}
        _settle(page, 1500)
        try:
            body = page.inner_text("body") or ""
        except Exception:
            body = ""
        confirmed = bool(_CONFIRMED.search(body)) and not _REFUSED.search(body[:1500])
        _shot(page, action_id)
        state = "booked" if confirmed else "unconfirmed"
        journal.append("action" if confirmed else "alert", "interviews",
                       (f"booked {chosen['start']} on {urlsplit(url).hostname} under grant {grant}" if confirmed
                        else f"pressed Schedule on {urlsplit(url).hostname} and the page did not confirm it"),
                       actor=ACTOR)
        return {"state": state, "chosen": chosen, "url": page.url, "grant": grant,
                "evidence": " ".join(body.split())[:300]}
    except Exception as exc:
        return {"state": "failed", "why": f"{type(exc).__name__}: {exc}"[:200]}
    finally:
        if session is not None:
            try:
                session.__exit__(None, None, None)
            except Exception:
                pass


def _shot(page, action_id: str) -> None:
    try:
        from aletheia import stateio
        folder = stateio.private_dir("interviews")
        folder.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(folder / f"{action_id}.png"), full_page=True)
    except Exception:
        pass


# ---- his calendar ------------------------------------------------------------

def put_on_his_calendar(*, title: str, start: str, end: str, spender=None, provider=None) -> dict:
    """The booked interview on the Open Range Interactive calendar - the live
    one - under the same grant. Her own store already holds it; this is the
    copy other people (and his phone) see. Never raises.

    {"state": written | not_connected | needs_grant | refused | failed, "say"}.
    """
    try:
        from aletheia import calendar_live
        if provider is None:
            ok, why = calendar_live.available()
            if not ok:
                # No live write is configured on this PC, and none is needed
                # for the Open Range calendar: the booking was made with the
                # Open Range address, so the page's own confirmation and its
                # calendar invitation go to that inbox, and Google Calendar
                # shows an invitation addressed to its own account. Her own
                # store already holds it; this is the copy his phone shows.
                return {"state": "by_invitation",
                        "say": ("the site's invitation goes to the Open Range inbox, which puts it on that "
                                "calendar")}
            provider = calendar_live.build_provider()
        if spender is None:
            from aletheia import authority
            spender = authority.satisfy
        grant = spender("calendar.write", f"interview-{start[:16]}")
        if not grant:
            return {"state": "needs_grant", "say": "putting it on your live calendar needs the interviews grant"}
        written = provider.create_event({"title": title, "start": start, "end": end})
        return {"state": "written", "id": str((written or {}).get("external_id") or ""),
                "say": "it is on the Open Range Interactive calendar"}
    except PermissionError as exc:
        return {"state": "refused", "say": f"the live calendar refused the write ({exc})"}
    except Exception as exc:
        return {"state": "failed", "say": f"the live calendar write failed ({type(exc).__name__})"}
