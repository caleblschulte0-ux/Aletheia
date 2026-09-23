"""Browser goals, whatever they are for, as one mission type in mission control.

Operator direction, 2026-09-16: *"jobs should be the current test case, not
the architecture."* The general browser loop (`browser_loop.pursue`) drives
any goal on any site and checkpoints it in `browser_mission`: a library-card
signup, an appointment request and a job application are the same record.
This provider puts every one of them on the home screen as a card with its
exact stop - "stopped at CAPTCHA on example.com: waiting for you" - and
into Eyes and the ribbon, without knowing what any goal is about.

A card per mission:

    RUNNING    being driven now (its record beats; a stale RUNNING record is
               a crash, and is STOPPED with that said)
    NEEDS YOU  stopped at a boundary only he can pass, a press waiting for
               his yes, or a press whose verdict the site never gave
    STOPPED    refused, manual-only, handed back by the site, or crashed
    DONE       finished (kept for a day, then it is history)

`read` is the only impure function; `build` is pure.
Read-only throughout: nothing here resumes, presses or approves.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from aletheia.mission_control import RECENT_S, Provider, _age_s, _words, duration_words, mission_card

TYPE = "browser_goal"

#: A stopped or finished goal stays on the home screen this long.
KEEP_S = RECENT_S
MAX_CARDS = 12
MAX_HISTORY_LINES = 60

#: Boundary kinds, as words.
KIND_WORDS = {"CAPTCHA": "a CAPTCHA", "SIGN_IN": "a sign-in", "QUESTIONS": "questions only you can answer",
              "WAITING_FOR_CODE": "a verification code", "WAITING_FOR_LINK": "a verification link",
              "ERROR": "a site error", "MANUAL_ONLY": "a site that forbids automation",
              "NO_WAY_FORWARD": "a page with no clear way forward", "DUPLICATE_SUBMIT": "a second press",
              "UNCONFIRMED": "an unconfirmed press", "REJECTED": "the site's refusal",
              "SPENDING": "a payment", "NO_VAULT": "an account it cannot make",
              "APPROVAL_DENIED": "your no", "APPROVAL_EXPIRED": "an expired approval",
              "OUT_OF_STEPS": "its step budget"}

#: What each mission state means on a card.
WAITS_ON_HIM = ("NEEDS_YOU", "AWAITING_APPROVAL")
_HIS_KINDS = ("CAPTCHA", "SIGN_IN", "QUESTIONS", "WAITING_FOR_CODE", "NO_VAULT",
              "ACCOUNT_CREATION_APPROVAL")
STOPPED_STATES = ("REFUSED", "MANUAL_ONLY", "REJECTED")


def _site(url: object) -> str:
    from urllib.parse import urlparse
    try:
        return urlparse(str(url or "")).netloc
    except ValueError:
        return ""


def named_stop(record: dict) -> str:
    """"Stopped at a CAPTCHA on example.com" - the precise boundary. Pure."""
    boundary = record.get("boundary") or {}
    kind = str(boundary.get("kind") or "")
    site = _site(boundary.get("url") or record.get("start_url"))
    what = KIND_WORDS.get(kind, kind.replace("_", " ").lower() or "a boundary")
    return f"Stopped at {what}" + (f" on {site}" if site else "")


def _crashed(record: dict, now: dt.datetime, stale_min: int) -> bool:
    age = _age_s(record.get("beat"), now)
    return age is None or age > stale_min * 60


def card(record: dict, now: dt.datetime, *, stale_min: int = 20) -> dict | None:
    """One browser goal as a mission card. Pure. None when it is history."""
    if not isinstance(record, dict) or not record.get("id"):
        return None
    state = str(record.get("state") or "")
    boundary = record.get("boundary") or {}
    # A wall she left is history, and a wall that is not his never carried
    # a thing to press (2026-09-23: 72 cards "waiting for you", 55 of them
    # for boundaries no tap of his could move).
    if state == "LEFT":
        return None
    if state == "NEEDS_YOU" and str(boundary.get("kind") or "UNKNOWN") not in _HIS_KINDS:
        return None
    goal = " ".join(str(record.get("goal") or "").split())
    site = _site(boundary.get("url") or record.get("start_url"))
    last = str(record.get("last_checkpoint") or "")
    age = _age_s(record.get("beat"), now)
    needs: list[dict] = []
    blockers: list[dict] = []
    receipt = {"kind": "browser_mission", "id": record["id"]}
    in_browser = False
    if state in ("RUNNING", "SUBMITTING") and not _crashed(record, now, stale_min):
        status, in_browser = "RUNNING", True
        step = (last.replace("_", " ") if last else "starting") + (f" on {site}" if site else "")
        nxt = ("Wait for the site's verdict; it is never pressed twice." if state == "SUBMITTING"
               else "Drive on to done or to the next boundary, and say exactly where it stops.")
    elif state in ("RUNNING", "SUBMITTING"):
        if age is not None and age > KEEP_S:
            return None
        status, step = "STOPPED", ""
        blockers.append({"said": f"it stopped moving {duration_words(age)} ago without finishing "
                                 "(the process ended)", "since": record.get("beat"), "source": "browser mission"})
        nxt = ("Nothing, until it is resumed; a press already made is never made again without proof it failed."
               if state == "SUBMITTING" else "Resume it to replay the route it had and carry on.")
    elif state == "SUBMITTED_UNCONFIRMED":
        # Pressed, and the site did not say. That waits on the SITE, not on
        # him: live 2026-09-23 four of these sat under "needs you" saying
        # "waiting for you" with nothing to do. Kept a day, like a done one.
        if age is not None and age > KEEP_S:
            return None
        status, step = "WAITING", "pressed; the site did not say whether it went through"
        nxt = "Nothing: it is never pressed twice. A reply, if one comes, reaches the record."
    elif state in WAITS_ON_HIM:
        status = "NEEDS YOU"
        stop = named_stop(record)
        say = _words(boundary.get("say"), 220)
        if state == "AWAITING_APPROVAL":
            said = f"{stop}: its final press is waiting for your yes"
        else:
            said = f"{stop}: waiting for you" + (f". {say}" if say else "")
        needs.append({"said": said, "blocking": True, "receipt": receipt})
        step = stop
        nxt = "It carries on from here when you do your part; nothing already done is redone."
    elif state in STOPPED_STATES:
        if age is not None and age > KEEP_S:
            return None
        status, step = "STOPPED", named_stop(record)
        blockers.append({"said": _words(boundary.get("say") or named_stop(record), 200),
                         "since": boundary.get("at") or record.get("beat"), "source": "browser mission"})
        nxt = "Nothing: it stopped where it had to."
    elif state == "DONE":
        if age is not None and age > KEEP_S:
            return None
        status, step, nxt = "DONE", "", "Nothing: the site confirmed it."
    else:
        return None
    checkpoints = [c for c in record.get("checkpoints") or [] if isinstance(c, dict)]
    names = []
    for c in checkpoints:
        if c.get("name") not in names:
            names.append(c.get("name"))
    return mission_card(
        id=f"browser:{record['id']}", type=TYPE, title=_words(goal or record["id"], 100), goal=goal,
        status=status, step=step, next=nxt, blockers=blockers, needs=needs,
        progress={"done": len(names), "total": 6, "unit": "checkpoints"} if names else None,
        receipts=[{**receipt, "label": "browser mission record"}], updated=record.get("beat"),
        in_browser=in_browser, source="state/private/browser-missions"
        + (f" - {record.get('skill')} skill" if record.get("skill") else ""))


def activity(records: list[dict]) -> list[dict]:
    """Ribbon lines from what each goal recorded. Pure."""
    items: list[dict] = []
    for record in records:
        if not isinstance(record, dict) or not record.get("id"):
            continue
        goal = _words(record.get("goal"), 80)
        receipt = {"kind": "browser_mission", "id": record["id"]}
        for row in (record.get("history") or [])[-5:]:
            if isinstance(row, dict) and row.get("at") and row.get("did"):
                items.append({"at": row["at"], "tone": "info", "what": "Browser",
                              "said": f"{goal}: {_words(row['did'], 140)}.", "receipt": receipt})
        for attempt in record.get("submits") or []:
            if not isinstance(attempt, dict) or not attempt.get("decided_at"):
                continue
            verdict = str(attempt.get("verdict") or "")
            tone = "good" if verdict == "confirmed" else ("alert" if verdict in ("rejected", "error") else "info")
            said = {"confirmed": "the site confirmed it", "rejected": "the site handed it back",
                    "not_pressed": "the press never reached the page; nothing was sent",
                    "error": "the site errored after the press"}.get(verdict, "the site did not say whether it went through")
            items.append({"at": attempt["decided_at"], "tone": tone, "what": "Browser",
                          "said": f"{goal}: pressed “{_words(attempt.get('button'), 40)}” - {said}.",
                          "receipt": receipt})
        boundary = record.get("boundary") or {}
        if boundary.get("at") and record.get("state") in WAITS_ON_HIM + STOPPED_STATES:
            items.append({"at": boundary["at"], "tone": "alert" if record.get("state") in STOPPED_STATES else "info",
                          "what": "Browser", "said": f"{goal}: {named_stop(record).lower()}.", "receipt": receipt})
    items.sort(key=lambda i: str(i["at"]), reverse=True)
    return items[:MAX_HISTORY_LINES]


def build(reading: dict, ctx: dict) -> dict:
    now = ctx["now"]
    records = [r for r in reading.get("records") or [] if isinstance(r, dict)]
    cards = [c for c in (card(r, now, stale_min=int(reading.get("stale_min") or 20)) for r in records) if c]
    order = {"RUNNING": 0, "NEEDS YOU": 1, "STOPPED": 2, "DONE": 3}
    cards = sorted(cards, key=lambda c: str(c.get("updated") or ""), reverse=True)
    cards = sorted(cards, key=lambda c: order.get(c["status"], 9))[:MAX_CARDS]
    claims = sorted({str(r.get("approval")) for r in records if r.get("approval")})
    return {"missions": cards, "claims": claims, "activity": activity(records), "details": {
        c["id"]: {"type": TYPE, "mission": c["id"].split(":", 1)[1]} for c in cards}}


def read(ctx: dict) -> dict:
    from aletheia import browser_mission as bm
    notes: list[str] = []
    try:
        records = bm.all_missions()
    except Exception as exc:  # noqa: BLE001
        records = []
        notes.append(f"the browser missions could not be read ({type(exc).__name__})")
    return {"records": records, "stale_min": bm.STALE_AFTER_MIN, "notes": notes}


#: A mission's inputs are his answers (and can hold an account password
#: reference); a receipt shows where it stands, not what he told it.
_RECEIPT_DROP = ("inputs", "account", "events")


def receipt(kind: str, ident: str) -> dict | None:
    from aletheia import browser_mission as bm
    if kind != "browser_mission":
        return None
    try:
        record = bm.load(ident)
    except (OSError, ValueError, KeyError):
        return None
    shown: dict[str, Any] = {k: v for k, v in record.items() if k not in _RECEIPT_DROP}
    shown["_explained"] = {"said": bm.describe(record), "stop": named_stop(record) if record.get("boundary") else ""}
    return {"kind": kind, "id": ident, "record": shown}


PROVIDER = Provider(type=TYPE, label="Browser goals", read=read, build=build,
                    subject_labels={"browser": "Browser"}, receipt_kinds=("browser_mission",),
                    receipt=receipt)
