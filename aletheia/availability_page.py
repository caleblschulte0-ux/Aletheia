"""An "enter your availability" page, filled in his window and sent.

His words, 2026-10-07: *"I get an interview. That she automatically sets up
for me. At sometime between 1 p.m. ... and 2:30 ... Central."* Both of his
first two interview invites (Via, Northspyre) were a Greenhouse availability
request: a week calendar the candidate click-and-drags across to paint the
hours he is free, then submits; the recruiter books from those hours. The
Calendly walker cannot do that (there is no slot to press), so both sat
unanswered until he did it by hand.

So, without a model choosing anything:

- the page is read as a time grid by the shape calendar widgets render: a
  row per half hour carrying `data-time="13:00:00"` and a column per day
  carrying `data-date="2026-10-08"` (FullCalendar, which Greenhouse's
  scheduler is built on, renders exactly that);
- on every weekday from tomorrow through `DAYS_AHEAD`, his window
  (1:00-2:30 PM Central by his ruling) is painted with one drag, unless his
  own calendar is busy then. The page shows times in the browser's zone,
  which is his PC's; a page whose grid does not carry his window's rows is
  refused rather than guessed at;
- the ONE press that reaches somebody else - Submit - is made only under
  the interviews standing grant (`interview.book`, his words kept on it).
  Without it she stops on the painted page and says so.

Anything that does not look like that grid is a refusal with a reason, and
the caller hands him the link.
"""
from __future__ import annotations

import datetime as dt
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from aletheia import journal

ACTOR = "aletheia-interviews"
CAPABILITY = "interview.book"
DAYS_AHEAD = 10
MAX_WEEKS = 3
WEEKDAYS = {0, 1, 2, 3, 4}
_NEXT_WEEK = ("button.fc-next-button, [aria-label*='next' i], button:has-text('Next week'), "
              "button:has-text('Next')")
_SUBMIT = re.compile(r"^\s*(submit|send)(\s+(my\s+)?availability)?\s*$", re.I)
_SENT = re.compile(r"thank you|thanks|submitted|received|has been sent|we'?ll be in touch", re.I)
_REFUSED = re.compile(r"something went wrong|try again|expired|no longer|invalid|error", re.I)


def _clock(value: str) -> dt.time:
    hour, minute = str(value).split(":")[:2]
    return dt.time(int(hour), int(minute))


def days_to_mark(*, window: dict, now: dt.datetime, busy=None, days: int = DAYS_AHEAD) -> list[dict]:
    """The weekdays from tomorrow whose window he is free for, as local
    start/end stamps in his zone."""
    zone = ZoneInfo(str(window.get("timezone") or "America/Chicago"))
    lo, hi = _clock(window.get("start") or "13:00"), _clock(window.get("end") or "14:30")
    day = now.astimezone(zone).date() + dt.timedelta(days=1)
    out = []
    for _ in range(days):
        if day.weekday() in WEEKDAYS:
            start = dt.datetime.combine(day, lo, tzinfo=zone)
            end = dt.datetime.combine(day, hi, tzinfo=zone)
            if not (busy and busy(start.isoformat(), end.isoformat())):
                out.append({"date": day.isoformat(), "start": start.isoformat(), "end": end.isoformat()})
        day += dt.timedelta(days=1)
    return out


def _settle(page, ms: int = 700) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=ms * 4)
    except Exception:
        pass
    try:
        page.wait_for_timeout(ms)
    except Exception:
        pass


def _box(page, selector: str):
    try:
        handle = page.query_selector(selector)
        return handle.bounding_box() if handle else None
    except Exception:
        return None


def _row_top(page, clock: dt.time):
    """The y of the top edge of the row that starts at `clock`."""
    return _box(page, f"[data-time='{clock.strftime('%H:%M:%S')}']")


def _column(page, date: str):
    """The day column: the grid's own column first, a header cell last."""
    for selector in (f"td.fc-timegrid-col[data-date='{date}']", f".fc-timegrid-col[data-date='{date}']",
                     f"td.fc-day[data-date='{date}']", f"th[data-date='{date}']", f"[data-date='{date}']"):
        box = _box(page, selector)
        if box and box.get("width"):
            return box
    return None


def _paint(page, date: str, lo: dt.time, hi: dt.time) -> bool:
    """One drag down the day's column from the top of `lo` to the top of `hi`."""
    col, top, bottom = _column(page, date), _row_top(page, lo), _row_top(page, hi)
    if not (col and top and bottom) or bottom["y"] <= top["y"]:
        return False
    x = col["x"] + col["width"] / 2
    y0, y1 = top["y"] + 2, bottom["y"] - 2
    try:
        page.mouse.move(x, y0)
        page.mouse.down()
        page.mouse.move(x, (y0 + y1) / 2, steps=5)
        page.mouse.move(x, y1, steps=5)
        page.mouse.up()
        _settle(page, 300)
        return True
    except Exception:
        return False


def _press_submit(page) -> bool:
    try:
        for handle in page.query_selector_all("button, input[type=submit], a[role=button]"):
            label = (handle.inner_text() or handle.get_attribute("value") or "").strip()
            if _SUBMIT.match(label) and handle.is_enabled():
                handle.click()
                return True
    except Exception:
        return False
    return False


def _next_week(page) -> bool:
    try:
        handle = page.query_selector(_NEXT_WEEK)
        if handle and handle.is_enabled():
            handle.click()
            _settle(page)
            return True
    except Exception:
        pass
    return False


def mark(url: str, *, window: dict, busy=None, now: dt.datetime | None = None, page=None,
         spender=None) -> dict:
    """Paint his window on every free weekday ahead and send it. Never raises.

    {"state": sent | needs_grant | unconfirmed | failed, "days": [...], ...}.
    `page` is a Playwright page (tests); otherwise her own browser profile.
    `spender(capability, action_id)` returns the grant or None.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    action_id = f"avail-{re.sub(r'[^a-z0-9]+', '-', urlsplit(url).path.casefold())[-24:]}-{now:%Y%m%d%H%M}"
    wanted = days_to_mark(window=window, now=now, busy=busy)
    if not wanted:
        return {"state": "failed", "why": "no free weekday in your window in the next two weeks", "days": []}
    lo, hi = _clock(window.get("start") or "13:00"), _clock(window.get("end") or "14:30")
    session = None
    try:
        if page is None:
            from aletheia import browse
            ok, why = browse.available()
            if not ok:
                return {"state": "failed", "why": f"her browser is not ready: {why}", "days": []}
            session = browse._Session()
            page = session.__enter__().new_page()
        page.goto(url, wait_until="domcontentloaded")
        _settle(page, 1500)
        if not (_row_top(page, lo) and _row_top(page, hi)):
            return {"state": "failed", "why": "the page did not show a time grid with your window on it", "days": []}
        painted: list[str] = []
        remaining = list(wanted)
        for _ in range(MAX_WEEKS):
            for day in list(remaining):
                if _column(page, day["date"]) is None:
                    continue
                if _paint(page, day["date"], lo, hi):
                    painted.append(day["date"])
                remaining.remove(day)
            if not remaining or not _next_week(page):
                break
        if not painted:
            return {"state": "failed", "why": "none of your free days could be marked on the page", "days": []}
        if spender is None:
            from aletheia import authority
            spender = authority.satisfy
        grant = spender(CAPABILITY, action_id)
        if not grant:
            return {"state": "needs_grant", "days": painted, "action": action_id}
        if not _press_submit(page):
            return {"state": "failed", "why": "no Submit button on the page", "days": painted}
        _settle(page, 1500)
        try:
            body = page.inner_text("body") or ""
        except Exception:
            body = ""
        confirmed = bool(_SENT.search(body)) and not _REFUSED.search(body[:1500])
        try:
            from aletheia import stateio
            folder = stateio.private_dir("interviews")
            folder.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(folder / f"{action_id}.png"), full_page=True)
        except Exception:
            pass
        journal.append("action" if confirmed else "alert", "interviews",
                       (f"sent availability for {len(painted)} day(s) on {urlsplit(url).hostname} under grant {grant}"
                        if confirmed else f"pressed Submit on {urlsplit(url).hostname} and the page did not confirm it"),
                       actor=ACTOR)
        return {"state": "sent" if confirmed else "unconfirmed", "days": painted, "grant": grant,
                "evidence": " ".join(body.split())[:300]}
    except Exception as exc:
        return {"state": "failed", "why": f"{type(exc).__name__}: {exc}"[:200], "days": []}
    finally:
        if session is not None:
            try:
                session.__exit__(None, None, None)
            except Exception:
                pass
