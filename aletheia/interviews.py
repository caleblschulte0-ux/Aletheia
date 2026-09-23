"""An employer asks for time; she picks the time, drafts the reply, pencils it in.

His words, the morning of 2026-09-23: *"if I ever get an interview, this is
untested, and we don't need somebody to turn this on yet, but I want it to
be to the point where she'll just auto schedule an interview for me at
sometime between 1 p.m. and 2:30 p.m. Central Time. Preferably, or
something close to that."* And, in the same breath, about mail: *"she
should be allowed to draft them ... Sending them yet? Not yet."*

So, when `runtime._job_reply` reads an employer's reply as an ask for time
and this is ON:

- the times the employer proposed are read by the deterministic parser
  (`reply_understanding.extract_times`, his zone, no model), and the first
  one inside his window on a weekday that his calendar has free is chosen;
  failing that, the free one closest to the window; failing that - or when
  they proposed nothing - the next three weekdays' window starts he is free
  for are offered;
- the reply is DRAFTED and HELD (`mail.draft(held=True)`): it goes when he
  says send, never before, because he does not yet know what she would say;
- the chosen time is pencilled onto his calendar as TENTATIVE (her own
  store, reversible), the application is marked `interview`, and he is told
  in one sentence what she picked and that the draft is waiting.

OFF by default, and off means nothing here happens - the "wants to talk"
notice he already gets is unchanged. `python -m aletheia.interviews on`
at his keyboard turns it on, with his words kept on the switch. The window
is his to move: `python -m aletheia.interviews window 13:00 14:30`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from zoneinfo import ZoneInfo

from aletheia import journal, stateio

ACTOR = "aletheia-interviews"
DEFAULT_WINDOW = {"start": "13:00", "end": "14:30", "timezone": "America/Chicago"}
DURATION_MIN = 30
OFFER_COUNT = 3
OFFER_DAYS = 10
WEEKDAYS = {0, 1, 2, 3, 4}
_ZONE_WORDS = {"America/Chicago": "Central", "America/New_York": "Eastern", "America/Denver": "Mountain",
               "America/Los_Angeles": "Pacific", "America/Phoenix": "Arizona"}


def _path():
    return stateio.private_dir("interviews") / "switch.json"


def status() -> dict:
    try:
        raw = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    win = raw.get("window") if isinstance(raw.get("window"), dict) else {}
    window = {**DEFAULT_WINDOW, **{k: str(v) for k, v in win.items() if k in DEFAULT_WINDOW}}
    return {"on": bool(raw.get("on")), "window": window, "quote": str(raw.get("quote") or ""),
            "command": "python -m aletheia.interviews on"}


def _save(state: dict) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    stateio.write_json_atomic(path, state)


def enable(*, quote: str = "", via: str = "operator") -> dict:
    state = status()
    state.pop("command", None)
    state.update({"on": True, "quote": quote, "since": stateio.utcnow()})
    _save(state)
    journal.append("decision", "interviews",
                   "interview scheduling ON: an employer's ask for time gets a chosen slot in his window, "
                   "a held reply and a pencilled hold" + (f" - his words: {quote}" if quote else ""), actor=via)
    return status()


def disable(*, via: str = "operator") -> dict:
    state = status()
    state.pop("command", None)
    state["on"] = False
    _save(state)
    journal.append("decision", "interviews", "interview scheduling OFF", actor=via)
    return status()


def set_window(start: str, end: str, timezone: str | None = None) -> dict:
    for value in (start, end):
        if not re.fullmatch(r"(?:[01]?\d|2[0-3]):[0-5]\d", str(value)):
            raise ValueError(f"{value!r} is not a time like 13:00")
    tz = timezone or status()["window"]["timezone"]
    ZoneInfo(tz)
    if _clock(start) >= _clock(end):
        raise ValueError("the window must end after it starts")
    state = status()
    state.pop("command", None)
    state["window"] = {"start": start, "end": end, "timezone": tz}
    _save(state)
    journal.append("decision", "interviews", f"interview window {start}-{end} {tz}", actor="operator")
    return status()


def _clock(value: str) -> dt.time:
    hour, minute = str(value).split(":")
    return dt.time(int(hour), int(minute))


def window_words(window: dict | None = None) -> str:
    win = window or status()["window"]
    zone = _ZONE_WORDS.get(win["timezone"], win["timezone"].split("/")[-1].replace("_", " "))
    return f"{_said_clock(_clock(win['start']))} to {_said_clock(_clock(win['end']))} {zone}"


def _said_clock(t: dt.time) -> str:
    hour = t.hour % 12 or 12
    mark = "AM" if t.hour < 12 else "PM"
    return f"{hour}:{t.minute:02d} {mark}" if t.minute else f"{hour} {mark}"


def said_when(stamp: str, window: dict | None = None) -> str:
    """"Thursday 1:00 PM Central" - the way he would say it."""
    win = window or status()["window"]
    zone = ZoneInfo(win["timezone"])
    when = dt.datetime.fromisoformat(stamp).astimezone(zone)
    return (f"{when.strftime('%A')} {_said_clock(when.time())} "
            f"{_ZONE_WORDS.get(win['timezone'], win['timezone'].split('/')[-1].replace('_', ' '))}")


# ---- choosing --------------------------------------------------------------------

def _local(stamp: str, zone: ZoneInfo) -> dt.datetime:
    return dt.datetime.fromisoformat(str(stamp)).astimezone(zone)


def in_window(start: str, window: dict) -> bool:
    """A weekday, starting inside the window (the whole meeting fits)."""
    zone = ZoneInfo(window["timezone"])
    when = _local(start, zone)
    if when.weekday() not in WEEKDAYS:
        return False
    lo, hi = _clock(window["start"]), _clock(window["end"])
    latest = (dt.datetime.combine(when.date(), hi) - dt.timedelta(minutes=DURATION_MIN)).time()
    return lo <= when.time() <= max(lo, latest)


def _distance_min(start: str, window: dict) -> float:
    """Minutes between a proposed start and the window's middle, on its own day."""
    zone = ZoneInfo(window["timezone"])
    when = _local(start, zone)
    lo, hi = _clock(window["start"]), _clock(window["end"])
    middle = (dt.datetime.combine(when.date(), lo, tzinfo=zone)
              + (dt.datetime.combine(when.date(), hi) - dt.datetime.combine(when.date(), lo)) / 2)
    return abs((when - middle).total_seconds()) / 60


def choose_slot(proposed: list[dict], *, now: dt.datetime, window: dict, busy) -> dict | None:
    """The employer's proposal to take: inside his window and free, else the
    free one closest to it (a weekday first). None when nothing they offered
    is in the future and free."""
    future = [p for p in proposed or [] if p.get("start") and p.get("end")
              and dt.datetime.fromisoformat(p["start"]) > now]
    free = [p for p in future if not busy(p["start"], p["end"])]
    if not free:
        return None
    inside = [p for p in free if in_window(p["start"], window)]
    if inside:
        return {**inside[0], "fit": "in the window"}
    zone = ZoneInfo(window["timezone"])
    free.sort(key=lambda p: (_local(p["start"], zone).weekday() not in WEEKDAYS, _distance_min(p["start"], window)))
    return {**free[0], "fit": "closest to the window"}


def offer_slots(*, now: dt.datetime, window: dict, busy, count: int = OFFER_COUNT,
                days: int = OFFER_DAYS) -> list[dict]:
    """The next weekdays' window starts he is free for, from tomorrow."""
    zone = ZoneInfo(window["timezone"])
    lo = _clock(window["start"])
    day = now.astimezone(zone).date() + dt.timedelta(days=1)
    out: list[dict] = []
    for _ in range(days):
        if day.weekday() in WEEKDAYS:
            start = dt.datetime.combine(day, lo, tzinfo=zone)
            end = start + dt.timedelta(minutes=DURATION_MIN)
            if not busy(start.isoformat(), end.isoformat()):
                out.append({"start": start.isoformat(), "end": end.isoformat(), "quote": ""})
                if len(out) >= count:
                    break
        day += dt.timedelta(days=1)
    return out


def reply_text(*, his_name: str, company: str, chosen: dict | None, offers: list[dict],
               window: dict) -> str:
    """Short, plain, his. Nothing in it comes from the employer's words."""
    first = (his_name or "").split()[0] if his_name else ""
    if chosen:
        body = (f"Thank you for reaching out. {said_when(chosen['start'], window)} works well for me - "
                f"I'll plan on that unless you'd prefer another time.")
    elif offers:
        listed = "; ".join(said_when(o["start"], window) for o in offers)
        body = (f"Thank you for reaching out. I'd be glad to talk. I'm available {listed}; "
                f"if none of those suit, anything {window_words(window)} on a weekday works for me.")
    else:
        body = (f"Thank you for reaching out. I'd be glad to talk. Weekdays {window_words(window)} "
                f"work best for me; please send a time that suits you.")
    return f"Hello,\n\n{body}\n\nBest regards,\n{first or his_name}".rstrip()


# ---- the act ---------------------------------------------------------------------

def consider(event: dict, entry: dict, *, subject: str, text: str = "", now: dt.datetime | None = None,
             busy=None, drafter=None, holder=None, marker=None, notify=None, known: dict | None = None) -> dict:
    """An employer's ask for time, acted on when the switch is on. Never raises."""
    state = status()
    if not state["on"]:
        return {"state": "off"}
    now = now or dt.datetime.now(dt.timezone.utc)
    window = state["window"]
    try:
        from aletheia import calendar as cal
        busy = busy or (lambda s, e: bool(cal.conflicts(s, e)))
        if known is None:
            from aletheia import profile
            known = profile.known()
        company = str(entry.get("company") or "the employer")
        proposed: list[dict] = []
        if text:
            from aletheia import reply_understanding as ru
            proposed = ru.extract_times(ru.fresh_text(text), reference=now, timezone=window["timezone"],
                                        minutes=DURATION_MIN)
        chosen = choose_slot(proposed, now=now, window=window, busy=busy)
        offers = [] if chosen else offer_slots(now=now, window=window, busy=busy)
        sender = str((event.get("attributes") or {}).get("sender") or "").strip()
        body = reply_text(his_name=str(known.get("full_name") or known.get("name") or ""),
                          company=company, chosen=chosen, offers=offers, window=window)
        draft = None
        if sender:
            from aletheia import mail
            drafter = drafter or (lambda to, subj, text_: mail.draft(to, subj, text_, requested_via="interviews", held=True))
            draft = drafter(sender, f"Re: {subject}"[:150], body)
        hold = None
        if chosen:
            holder = holder or (lambda eid, title, s, e: cal.create(eid, title, s, e, source="interviews",
                                                                    status="TENTATIVE", movable=True))
            eid = f"interview-{re.sub(r'[^a-z0-9]+', '-', company.casefold())[:30]}-{chosen['start'][:10]}"
            try:
                hold = holder(eid, f"Interview: {company}", chosen["start"], chosen["end"])
            except FileExistsError:
                hold = {"id": eid}
        try:
            from aletheia import apply_run
            (marker or apply_run.mark)(entry["id"], "interview",
                                       note=(f"asked for time; {said_when(chosen['start'], window)} chosen"
                                             if chosen else "asked for time; times offered"))
        except Exception:
            pass
        when = (f"I picked {said_when(chosen['start'], window)}"
                + (" (the closest of theirs to your window)" if chosen.get("fit") != "in the window" else "")
                if chosen else f"none of their times fit, so I offered {len(offers)} in your window")
        sentence = (f"{company} wants to talk. {when}"
                    + (" and pencilled it in" if hold else "")
                    + (f". The reply is drafted and held - say send it when you want it to go." if draft
                       else ". I could not find their address, so the reply is yours to write."))
        from aletheia import notifications
        (notify or notifications.publish)(
            f"{company} wants to talk", sentence, priority="IMPORTANT", source="interviews",
            about=notifications.CHANGED, dedupe_key=f"interview:{entry.get('id')}:{event.get('id')}",
            related={"application": entry.get("id"), "draft": (draft or {}).get("id", ""),
                     "event": (hold or {}).get("id", "")})
        journal.append("action", "interviews", sentence, actor=ACTOR)
        return {"state": "drafted", "chosen": chosen, "offers": offers, "draft": (draft or {}).get("id"),
                "hold": (hold or {}).get("id")}
    except Exception as exc:
        try:
            journal.append("event", "interviews",
                           f"could not act on {entry.get('company') or 'an employer'}'s ask for time "
                           f"({type(exc).__name__}); the notice still reached him", actor=ACTOR)
        except Exception:
            pass
        return {"state": "error", "error_type": type(exc).__name__}


def spoken() -> str:
    state = status()
    if not state["on"]:
        return ("Interviews are yours to schedule; I only tell you when an employer asks. "
                "'python -m aletheia.interviews on' at your keyboard lets me pick a time "
                f"{window_words(state['window'])}, draft the reply and hold it for your send.")
    return (f"When an employer asks for time I pick a slot {window_words(state['window'])} on a weekday "
            "you're free, pencil it in and draft the reply - it goes when you say send.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Interview scheduling: a slot in his window, a held reply.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    on = sub.add_parser("on")
    on.add_argument("--quote", default="", help="his own words, kept on the switch")
    sub.add_parser("off")
    sub.add_parser("status")
    win = sub.add_parser("window")
    win.add_argument("start")
    win.add_argument("end")
    win.add_argument("--timezone", default=None)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "on":
            enable(quote=args.quote)
        elif args.cmd == "off":
            disable()
        elif args.cmd == "window":
            set_window(args.start, args.end, args.timezone)
        print(json.dumps(status(), indent=2))
        print(spoken())
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
