"""Deterministic Phase 15 meeting-planning primitive.

Resolves the person exactly, searches calendar availability under explicit
constraints, and produces a contact/slot plan. It does not email anyone or
create an external calendar event; those are separate approval/provider steps.
"""
from __future__ import annotations

import datetime as dt

from aletheia import calendar, contacts


def propose(person: str, *, start_day: str, end_day: str, duration_minutes: int = 30,
            timezone: str, not_before: str = "09:00", not_after: str = "17:00",
            buffer_minutes: int = 0, weekdays_only: bool = True,
            limit: int = 5, events: list[dict] | None = None,
            contact_records: list[dict] | None = None) -> dict:
    contact = contacts.resolve(person, contacts=contact_records)
    try:
        sh, sm = map(int, not_before.split(":"))
        eh, em = map(int, not_after.split(":"))
        work_start, work_end = dt.time(sh, sm), dt.time(eh, em)
    except (TypeError, ValueError) as exc:
        raise ValueError("not_before/not_after must be HH:MM") from exc
    days = {0, 1, 2, 3, 4} if weekdays_only else None
    slots = calendar.find_slots(dt.date.fromisoformat(start_day), dt.date.fromisoformat(end_day),
                                duration_minutes=duration_minutes, timezone=timezone,
                                work_start=work_start, work_end=work_end, events=events,
                                buffer_minutes=buffer_minutes, weekdays=days, limit=limit)
    if not slots:
        return {"status": "NO_SLOT", "person": contact["id"], "slots": [],
                "reason": "no local calendar slot matches the supplied constraints"}
    return {
        "status": "PROPOSED",
        "person": contact["id"],
        "display_name": contact["display_name"],
        "slots": [{"start": start, "end": end} for start, end in slots],
        "next_steps": [
            "select a slot",
            "contact the person using an authorized communication capability",
            "create the real calendar event only after the external provider confirms",
            "track the reply/confirmation as a durable expectation",
        ],
    }
