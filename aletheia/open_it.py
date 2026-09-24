""""Open it": the page a browser mission stopped on, in HIS browser, on his PC.

His words, 2026-09-23: *"Everything should be one click. Pretend you're an
old lady using it."* A card that said "Stopped at a CAPTCHA on
jobs.example.com: waiting for you" carried no way to get there: the
address sat in a record, and the one thing he could do about it was find
it himself. This is the click.

What it opens is never a free address. `which` names a browser mission or
an application she holds, and the page is the one THAT record stopped on
(the boundary's address, else where it started). A model has no door to
this kind (`intercom.PLANNER_FORBIDDEN`, `agenda.FORBIDDEN_KINDS`); it is
his tap on the page or his own sentence. Opening a page reaches him and
nobody else (`tools.CONSEQUENCE_OF`: visible to him).
"""
from __future__ import annotations

import webbrowser
from urllib.parse import urlparse

from aletheia import journal

ACTOR = "aletheia-open-it"


class NothingToOpen(RuntimeError):
    pass


def page_for(which: str) -> tuple[str, str]:
    """(url, what it is) for a mission or an application he named."""
    from aletheia import apply_run, browser_mission
    key = " ".join(str(which or "").split())
    if not key:
        raise NothingToOpen("say which one")
    record = None
    try:
        if browser_mission.exists(key):
            record = browser_mission.load(key)
    except Exception:
        record = None
    if record is not None:
        boundary = record.get("boundary") if isinstance(record.get("boundary"), dict) else {}
        url = str(boundary.get("url") or record.get("start_url") or "").strip()
        what = " ".join(str(record.get("goal") or key).split())[:80]
        return _http(url, what), what
    matches = apply_run.find(key)
    if not matches:
        raise NothingToOpen(f"I don't have anything matching {key!r} to open.")
    if len(matches) > 1:
        from aletheia import speech
        raise NothingToOpen("More than one matches - "
                            + speech.or_list([apply_run.describe(m) for m in matches[:4]]) + "?")
    record = matches[0]
    mission = None
    try:
        if record.get("mission") and browser_mission.exists(str(record["mission"])):
            mission = browser_mission.load(str(record["mission"]))
    except Exception:
        mission = None
    boundary = (mission or {}).get("boundary") if isinstance((mission or {}).get("boundary"), dict) else {}
    url = str(boundary.get("url") or record.get("url") or record.get("posting") or "").strip()
    return _http(url, apply_run.describe(record)), apply_run.describe(record)


def _http(url: str, what: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise NothingToOpen(f"{what} has no web address I could open.")
    return url


def open_for(which: str, *, opener=None) -> dict:
    """Open the page in his browser and say so. Raises NothingToOpen."""
    url, what = page_for(which)
    opener = opener or webbrowser.open
    try:
        ok = opener(url)
    except Exception as exc:
        raise NothingToOpen(f"I could not open a browser here ({type(exc).__name__}).") from exc
    if ok is False:
        raise NothingToOpen("I could not open a browser on this machine.")
    from aletheia import speech
    site = speech.say_url(urlparse(url).netloc) if hasattr(speech, "say_url") else urlparse(url).netloc
    said = f"Opened {site} in your browser. Do your part there; I carry on from where it stopped."
    journal.append("action", "open_it", f"opened {urlparse(url).netloc} for {what}", actor=ACTOR)
    return {"url": url, "what": what, "said": said}


def action_for(record: dict) -> dict | None:
    """The card's one click for a mission that stopped on something of his."""
    if not isinstance(record, dict) or not record.get("id"):
        return None
    boundary = record.get("boundary") if isinstance(record.get("boundary"), dict) else {}
    url = str(boundary.get("url") or record.get("start_url") or "")
    if urlparse(url).scheme not in ("http", "https"):
        return None
    return {"label": "Open it", "kind": "open_page", "args": {"which": str(record["id"])}}
