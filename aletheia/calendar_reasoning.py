"""Calendar reasoning as general agency: free time, conflicts, holds, deadlines.

Continuity brief IV.16: interviews, tours, appointments, reminders, deadlines,
follow-up dates and travel windows, and conflicts across all of them - general
calendar capability, not code for any one mission. The deterministic engine is
`aletheia.calendar` (aware datetimes, overlaps, buffers, free-slot search); this
module adds what an ASSISTANT needs on top of it:

- **Travel buffers.** Two things in different places cannot be back to back. When
  both have a location and they differ, the gap between them must fit the travel
  time (`travel_minutes`, an estimator the caller may supply; a flat default
  otherwise, never a network call inside a check).
- **His timezone.** Every window ("next week", "Friday afternoon") is resolved in
  `localtime.operator_timezone()`, and every sentence is rendered there with the
  reference time passed in - never the process's zone (CLAUDE.md: "remind me at 3"
  confirmed back as "tomorrow at 8 am").
- **Holds.** A hold is a TENTATIVE event in HER calendar model - local, private,
  reversible, reaching nobody - so placing, moving and releasing one never asks.
  Confirming one onto a LIVE calendar is `calendar.write`: operator_always, a
  write plan hash-bound to the exact event (`calendar_provider`), executed once
  after he approves. That rule is the provider's, unchanged.
- **Deadlines.** A date something is due becomes a durable work item
  (`work_engine`, kind "deadline") that wakes before it is due and tells him.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from typing import Callable
from zoneinfo import ZoneInfo

from aletheia import calendar, journal, stateio

ACTOR = "aletheia-calendar-reasoning"
DEFAULT_TRAVEL_BUFFER_MIN = 30
DEFAULT_DAY_START = dt.time(9, 0)
DEFAULT_DAY_END = dt.time(18, 0)
HOLD_PREFIX = "hold-"
Estimator = Callable[[str, str], int]


def tz_name(timezone: str | None = None) -> str:
    if timezone:
        ZoneInfo(timezone)
        return timezone
    from aletheia import localtime
    return localtime.operator_timezone()


def _zone(timezone: str | None = None) -> ZoneInfo:
    return ZoneInfo(tz_name(timezone))


def _utc(now: dt.datetime | None) -> dt.datetime:
    value = now or dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(dt.timezone.utc)


def human(stamp: str, *, timezone: str | None = None, now: dt.datetime | None = None,
          relative: bool = True) -> str:
    """"Friday, September 18 at 10 am" in HIS zone; "today"/"tomorrow" relative to `now`
    when said TO HIM. An email to someone else uses `relative=False`: "tomorrow"
    in a message read two days later names the wrong day."""
    zone = _zone(timezone)
    when = calendar.parse_time(stamp).astimezone(zone)
    ref = _utc(now).astimezone(zone)
    clock = when.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").replace(" AM", " am").replace(" PM", " pm")
    if not relative:
        return f"{when.strftime('%A, %B')} {when.day} at {clock}"
    days = (when.date() - ref.date()).days
    if days == 0:
        return f"today at {clock}"
    if days == 1:
        return f"tomorrow at {clock}"
    return f"{when.strftime('%A, %B')} {when.day} at {clock}"


# ---- windows -----------------------------------------------------------------------

def window(words: str, *, now: dt.datetime | None = None, timezone: str | None = None) -> tuple[dt.date, dt.date]:
    """A spoken stretch of days -> (first, last) dates in his zone. ValueError when
    the words are not a window; never a guess."""
    zone = _zone(timezone)
    today = _utc(now).astimezone(zone).date()
    said = " ".join(str(words or "").lower().replace("the ", "").split()).strip(" ?.")
    if said in ("", "today"):
        return today, today
    if said == "tomorrow":
        return today + dt.timedelta(days=1), today + dt.timedelta(days=1)
    if said in ("this week", "rest of week", "rest of this week"):
        return today, today + dt.timedelta(days=6 - today.weekday())
    if said == "next week":
        start = today + dt.timedelta(days=7 - today.weekday())
        return start, start + dt.timedelta(days=6)
    if said in ("this weekend", "weekend"):
        saturday = today + dt.timedelta(days=(5 - today.weekday()) % 7)
        return saturday, saturday + dt.timedelta(days=1)
    if said in ("next few days", "few days", "next couple of days"):
        return today, today + dt.timedelta(days=3)
    if said in ("next two weeks", "next 2 weeks", "two weeks"):
        return today, today + dt.timedelta(days=13)
    names = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    if said in names:
        ahead = (names.index(said) - today.weekday()) % 7
        day = today + dt.timedelta(days=ahead)
        return day, day
    try:
        day = dt.date.fromisoformat(said)
        return day, day
    except ValueError:
        pass
    raise ValueError(f"I don't know which days {words!r} means")


# ---- travel and conflicts ------------------------------------------------------------

def _place(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def travel_minutes(a: str | None, b: str | None, *, estimator: Estimator | None = None) -> int:
    """Minutes to get from one place to another. 0 when either is unknown or
    they are the same place. A flat, honest default when nobody can estimate."""
    if not _place(a) or not _place(b) or _place(a) == _place(b):
        return 0
    if estimator is not None:
        try:
            return max(0, int(estimator(str(a), str(b))))
        except Exception:  # noqa: BLE001 - an estimator failing is not a free road
            return DEFAULT_TRAVEL_BUFFER_MIN
    return DEFAULT_TRAVEL_BUFFER_MIN


def conflicts_for(start: str, end: str, *, location: str | None = None, events: list[dict] | None = None,
                  estimator: Estimator | None = None, include_tentative: bool = True,
                  ignore: set[str] | None = None) -> list[dict]:
    """Every event that clashes with [start, end): an overlap, or too little time
    to travel between two different places. Each says which and why."""
    a, b = calendar.parse_time(start), calendar.parse_time(end)
    if b <= a:
        raise ValueError("end must be after start")
    out = []
    for event in calendar.all_events() if events is None else events:
        if event.get("status") == "CANCELLED" or event.get("id") in (ignore or set()):
            continue
        if event.get("status") == "TENTATIVE" and not include_tentative:
            continue
        e_start, e_end = calendar.parse_time(event["start"]), calendar.parse_time(event["end"])
        base = {"id": event.get("id"), "title": event.get("title"), "start": event["start"],
                "end": event["end"], "location": event.get("location"), "status": event.get("status")}
        if calendar.overlaps(a, b, e_start, e_end):
            out.append({**base, "kind": "overlap", "why": f"it overlaps {event.get('title')}"})
            continue
        need = travel_minutes(event.get("location"), location, estimator=estimator)
        if not need:
            continue
        gap = (a - e_end) if e_end <= a else (e_start - b)
        gap_min = int(gap.total_seconds() // 60)
        if 0 <= gap_min < need:
            out.append({**base, "kind": "travel", "needed_minutes": need, "gap_minutes": gap_min,
                        "why": (f"only {gap_min} minutes from {event.get('title')} and the trip takes "
                                f"about {need}")})
    return out


def find_free(first: dt.date, last: dt.date, *, minutes: int = 60, location: str | None = None,
              part: str | None = None, events: list[dict] | None = None, estimator: Estimator | None = None,
              day_start: dt.time = DEFAULT_DAY_START, day_end: dt.time = DEFAULT_DAY_END,
              step_minutes: int = 30, limit: int = 40, now: dt.datetime | None = None,
              timezone: str | None = None) -> list[dict]:
    """Free slots between two dates, in his zone, honoring travel buffers and
    never in the past. Each slot says when in words."""
    zone_name = tz_name(timezone)
    source = calendar.all_events() if events is None else events
    raw = calendar.find_slots(first, last, duration_minutes=minutes, timezone=zone_name, work_start=day_start,
                              work_end=day_end, events=source, step_minutes=step_minutes, limit=2000)
    if part:
        raw = calendar.in_part(raw, part)
    floor = _utc(now)
    out = []
    for start, end in raw:
        if calendar.parse_time(start) < floor:
            continue
        if location and conflicts_for(start, end, location=location, events=source, estimator=estimator):
            continue
        out.append({"start": start, "end": end, "human": human(start, timezone=zone_name, now=now)})
        if len(out) >= limit:
            break
    return out


def spread(slots: list[dict], count: int = 3) -> list[dict]:
    """A few slots worth offering: different days first, then different hours."""
    chosen: list[dict] = []
    days: set[str] = set()
    for slot in slots:
        day = slot["start"][:10]
        if day not in days:
            chosen.append(slot)
            days.add(day)
        if len(chosen) >= count:
            return chosen
    for slot in slots:
        if slot not in chosen and all(abs((calendar.parse_time(slot["start"]) - calendar.parse_time(c["start"]))
                                          .total_seconds()) >= 2 * 3600 for c in chosen):
            chosen.append(slot)
        if len(chosen) >= count:
            break
    return sorted(chosen, key=lambda s: s["start"])


def evaluate(times: list[dict], *, minutes: int = 60, location: str | None = None, events: list[dict] | None = None,
             estimator: Estimator | None = None, now: dt.datetime | None = None,
             timezone: str | None = None, ignore: set[str] | None = None) -> list[dict]:
    """Proposed times (from a reply) checked against his calendar: free or not, and why."""
    floor = _utc(now)
    out = []
    for proposal in times:
        start = calendar.parse_time(proposal["start"])
        end = start + dt.timedelta(minutes=minutes)
        clashes = [] if start < floor else conflicts_for(start.isoformat(), end.isoformat(), location=location,
                                                         events=events, estimator=estimator, ignore=ignore)
        out.append({"start": start.isoformat(), "end": end.isoformat(), "quote": proposal.get("quote", ""),
                    "human": human(start.isoformat(), timezone=timezone, now=now),
                    "free": start >= floor and not clashes, "past": start < floor, "conflicts": clashes})
    return out


def free_words(slots: list[dict], *, first: dt.date, last: dt.date, timezone: str | None = None,
               purpose: str = "") -> str:
    """Availability as a person says it: stretches, not fifteen-minute steps."""
    zone = _zone(timezone)
    for_what = f" for {purpose}" if purpose else ""
    if not slots:
        return f"Nothing free{for_what} between {first.strftime('%A %B')} {first.day} and {last.strftime('%A %B')} {last.day}."
    merged = calendar.merge_slots([(s["start"], s["end"]) for s in slots])
    parts = []
    for a, b in merged[:4]:
        start, end = calendar.parse_time(a).astimezone(zone), calendar.parse_time(b).astimezone(zone)
        clock = lambda t: t.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ").replace(" AM", " am").replace(" PM", " pm")  # noqa: E731
        parts.append(f"{start.strftime('%A')} {clock(start)} to {clock(end)}")
    from aletheia import speech
    more = ", and more after that" if len(merged) > 4 else ""
    return f"Free{for_what}: {speech.and_list(parts)}{more}."


# ---- holds -------------------------------------------------------------------------

def holds_dir():
    return stateio.private_dir("calendar-holds")


def _hold_record_path(event_id: str):
    return holds_dir() / f"{stateio.safe_id(event_id, name='hold id')}.json"


def hold_id(title: str, start: str, thread_id: str = "") -> str:
    digest = hashlib.sha256(f"{thread_id}|{title}|{calendar.parse_time(start).isoformat()}".encode()).hexdigest()
    return f"{HOLD_PREFIX}{digest[:14]}"


def hold(title: str, start: str, end: str, *, location: str | None = None, thread_id: str = "",
         purpose: str = "", events: list[dict] | None = None, estimator: Estimator | None = None,
         timezone: str | None = None, now: dt.datetime | None = None) -> dict:
    """Pencil something in: a TENTATIVE event in her own calendar. Local and
    reversible, so it asks nobody. Refused (with the clashes named) when it
    would overlap or leave no time to travel. Idempotent per thread/title/time."""
    title = " ".join(str(title or "").split())
    if not title:
        raise ValueError("a hold needs a title")
    event_id = hold_id(title, start, thread_id)
    try:
        existing = calendar.load(event_id)
        if existing.get("status") != "CANCELLED":
            return {"event": existing, "created": False, "conflicts": [], "record": load_hold(event_id)}
    except (ValueError, OSError):
        pass
    clashes = conflicts_for(start, end, location=location, events=events, estimator=estimator,
                            ignore={event_id})
    if clashes:
        return {"event": None, "created": False, "conflicts": clashes,
                "why": "; ".join(c["why"] for c in clashes)}
    try:
        event = calendar.create(event_id, title, calendar.parse_time(start).isoformat(),
                                calendar.parse_time(end).isoformat(), location=location,
                                source=f"hold:{thread_id or 'caleb'}", status="TENTATIVE", movable=True)
    except FileExistsError:
        event = calendar.update(event_id, status="TENTATIVE", start=calendar.parse_time(start).isoformat(),
                                end=calendar.parse_time(end).isoformat())
    record = {"version": 1, "id": event_id, "thread_id": thread_id, "purpose": purpose, "state": "HELD",
              "created_at": stateio.utcnow(), "updated_at": stateio.utcnow(), "history": []}
    _save_hold(record, f"held {human(event['start'], timezone=timezone, now=now)}")
    journal.append("action", f"calendar:{event_id}", f"pencilled in {title} (tentative, her calendar only)",
                   actor=ACTOR)
    return {"event": event, "created": True, "conflicts": [], "record": record}


def load_hold(event_id: str) -> dict | None:
    try:
        return stateio.read_json(_hold_record_path(event_id))
    except (ValueError, OSError):
        return None


def _save_hold(record: dict, did: str) -> dict:
    record["updated_at"] = stateio.utcnow()
    record.setdefault("history", []).append({"at": record["updated_at"], "did": did[:200]})
    record["history"] = record["history"][-20:]
    stateio.write_json_atomic(_hold_record_path(record["id"]), record)
    return record


def move_hold(event_id: str, start: str, end: str, *, events: list[dict] | None = None,
              estimator: Estimator | None = None) -> dict:
    event = calendar.load(event_id)
    clashes = conflicts_for(start, end, location=event.get("location"), events=events, estimator=estimator,
                            ignore={event_id})
    if clashes:
        return {"event": event, "moved": False, "conflicts": clashes, "why": "; ".join(c["why"] for c in clashes)}
    event = calendar.update(event_id, start=calendar.parse_time(start).isoformat(),
                            end=calendar.parse_time(end).isoformat())
    record = load_hold(event_id) or {"version": 1, "id": event_id, "state": "HELD", "history": []}
    _save_hold(record, f"moved to {event['start']}")
    return {"event": event, "moved": True, "conflicts": []}


def release_hold(event_id: str, why: str = "released") -> dict:
    event = calendar.cancel(event_id)
    record = load_hold(event_id) or {"version": 1, "id": event_id, "history": []}
    record["state"] = "RELEASED"
    _save_hold(record, why)
    journal.append("action", f"calendar:{event_id}", f"released the hold on {event.get('title')}", actor=ACTOR)
    return event


def confirm_hold(event_id: str, *, provider=None, provider_id: str | None = None) -> dict:
    """He and the other side agreed: the hold becomes CONFIRMED in her calendar.

    If a live calendar can be written (a provider passed in, or a configured one
    that allows writes), a CREATE write plan is built and its hash-bound
    `calendar.write` approval filed - operator_always, exactly the provider's
    rule. Nothing is written live here; `execute_approved_writes` does that once
    he says yes."""
    event = calendar.update(event_id, status="CONFIRMED")
    record = load_hold(event_id) or {"version": 1, "id": event_id, "history": []}
    record["state"] = "CONFIRMED"
    target = provider_id or getattr(provider, "provider_id", None)
    if target is None:
        try:
            from aletheia import calendar_live
            if calendar_live.available()[0] and calendar_live.config().get("allow_writes"):
                target = {"google": "google.calendar", "microsoft": "microsoft.graph.calendar"}.get(
                    calendar_live.config()["provider"])
        except Exception:
            target = None
    if target and not record.get("write_approval"):
        from aletheia import calendar_provider
        body = {"title": event["title"], "start": event["start"], "end": event["end"]}
        if event.get("location"):
            body["location"] = event["location"]
        plan = calendar_provider.build_write_plan("CREATE", target, event=body)
        approval_id = f"calwrite-{event_id}"[:60]
        calendar_provider.request_write_approval(approval_id, plan,
                                                 reason=f"put {event['title']} on your live calendar")
        record.update({"write_plan": plan, "write_approval": approval_id, "write_state": "AWAITING_APPROVAL"})
    _save_hold(record, "confirmed" + (" - live calendar write waiting for approval" if record.get("write_approval") else ""))
    journal.append("action", f"calendar:{event_id}", f"confirmed {event['title']}", actor=ACTOR)
    return {"event": event, "record": record}


def execute_approved_writes(*, provider=None) -> list[dict]:
    """Write every confirmed hold he approved onto the live calendar, once each."""
    from aletheia import calendar_provider, intercom, policy
    done = []
    directory = holds_dir()
    if not directory.is_dir():
        return done
    for path in sorted(directory.glob(f"{HOLD_PREFIX}*.json")):
        try:
            record = stateio.read_json(path)
        except ValueError:
            continue
        if record.get("write_state") != "AWAITING_APPROVAL" or not record.get("write_approval"):
            continue
        ok, _why = policy.usable(record["write_approval"])
        if not ok:
            continue
        if intercom.rehearsing() and not getattr(provider, "rehearsal_safe", False) \
                and not isinstance(provider, calendar_provider.InMemoryCalendarProvider):
            done.append({"hold": record["id"], "outcome": "rehearsal", "detail": "not written: a rehearsal"})
            continue
        target = provider
        if target is None:
            from aletheia import calendar_live
            target = calendar_live.build_provider()
        record["write_state"] = "WRITING"
        _save_hold(record, "writing to the live calendar")
        try:
            result = calendar_provider.execute_write_plan(record["write_plan"], record["write_approval"], target)
        except Exception as exc:  # noqa: BLE001
            record["write_state"] = "FAILED"
            _save_hold(record, f"the live calendar refused it ({type(exc).__name__})")
            done.append({"hold": record["id"], "outcome": "failed", "detail": str(exc)[:200]})
            continue
        record.update({"write_state": "WRITTEN", "external_id": result.get("external_id")})
        _save_hold(record, "on the live calendar, verified")
        done.append({"hold": record["id"], "outcome": "written", "external_id": result.get("external_id")})
    return done


def upcoming_holds(*, now: dt.datetime | None = None) -> list[dict]:
    floor = _utc(now)
    out = []
    for event in calendar.all_events():
        if not str(event.get("id", "")).startswith(HOLD_PREFIX) or event.get("status") == "CANCELLED":
            continue
        if calendar.parse_time(event["end"]) < floor:
            continue
        out.append({**event, "record": load_hold(event["id"])})
    return out


def conflicts_now(*, now: dt.datetime | None = None, days: int = 14, estimator: Estimator | None = None) -> list[dict]:
    """Clashes among upcoming events (holds included): what mission control shows."""
    floor = _utc(now)
    horizon = floor + dt.timedelta(days=days)
    events = [e for e in calendar.all_events() if e.get("status") != "CANCELLED"
              and floor <= calendar.parse_time(e["start"]) <= horizon]
    seen, out = set(), []
    for event in events:
        for clash in conflicts_for(event["start"], event["end"], location=event.get("location"), events=events,
                                   estimator=estimator, ignore={event["id"]}):
            key = tuple(sorted((event["id"], clash["id"])))
            if key in seen:
                continue
            seen.add(key)
            out.append({"a": event.get("title"), "a_id": event["id"], "b": clash["title"], "b_id": clash["id"],
                        "kind": clash["kind"], "start": min(event["start"], clash["start"]), "why": clash["why"]})
    return out


# ---- deadlines ---------------------------------------------------------------------

DEADLINE_KIND = "deadline"


def track_deadline(title: str, due: str, *, lead_hours: float = 24.0, ref: str = "",
                   now: dt.datetime | None = None) -> dict:
    """A date something is due, as a durable work item that wakes `lead_hours`
    before it and tells him. Idempotent per title and due time."""
    from aletheia import work_engine, work_states as ws
    due_at = calendar.parse_time(due).astimezone(dt.timezone.utc)
    wake = due_at - dt.timedelta(hours=max(0.0, float(lead_hours)))
    stamp = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    return work_engine.add(
        f"due: {title}", kind=DEADLINE_KIND, state=ws.BLOCKED_EXTERNAL, requires=[],
        reason="waiting for the date", next=f"tell Caleb before it is due ({stamp(due_at)})",
        payload={"due": stamp(due_at), "wake_at": stamp(wake), "title": title, "ref": ref, "reminded": False},
        key=f"deadline:{title}:{stamp(due_at)}", now=now)


def run_deadline(item: dict, now: dt.datetime) -> dict:
    """The work engine's runner for a deadline that woke: tell him, then wait for
    the due time itself, then finish."""
    from aletheia import notifications, work_states as ws
    payload = dict(item.get("payload") or {})
    due = calendar.parse_time(str(payload.get("due")))
    title = str(payload.get("title") or item.get("title"))
    now = _utc(now)
    if now >= due:
        notifications.publish(f"Due now: {title}", f"{title} was due {human(due.isoformat(), now=now)}.",
                              about=notifications.NEEDS_YOU,
                              priority="IMPORTANT", source="deadlines", dedupe_key=f"deadline-due:{item['id']}")
        return {"state": ws.DONE, "reason": "", "next": "", "payload": {"reminded": True}}
    notifications.publish(f"Coming up: {title}", f"{title} is due {human(due.isoformat(), now=now)}.",
                          about=notifications.NEEDS_YOU,
                          priority="IMPORTANT", source="deadlines", dedupe_key=f"deadline-soon:{item['id']}")
    return {"state": ws.BLOCKED_EXTERNAL, "reason": "reminded him; waiting for the due time",
            "next": "say it is due when the time comes", "payload": {"reminded": True, "wake_at": payload.get("due")}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Free time, holds, conflicts and deadlines.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_free = sub.add_parser("free", help="when am I free")
    p_free.add_argument("when", nargs="?", default="next week")
    p_free.add_argument("--minutes", type=int, default=60)
    p_free.add_argument("--location", default="")
    sub.add_parser("holds")
    sub.add_parser("conflicts")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "free":
            first, last = window(args.when)
            slots = find_free(first, last, minutes=args.minutes, location=args.location or None)
            print(free_words(slots, first=first, last=last))
        elif args.cmd == "holds":
            print(json.dumps(upcoming_holds(), indent=2))
        else:
            print(json.dumps(conflicts_now(), indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
