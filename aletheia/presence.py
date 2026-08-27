"""What the wall should actually be showing (Playbook §88, §89).

§88 defines the wall as current focus, next appointment, active projects,
agents working, important alerts, Aletheia activity, room state, time.
§89 adds the negative: do not make it a corporate dashboard.

What it shows instead is the fleet — an orbital map of six repositories,
three of which are empty stubs with nothing but a README, each given the
same visual weight as the systems that actually run. Meanwhile the things
that define her now are on it nowhere: approvals waiting on him, a meeting
being negotiated, an errand stopped at a bank's verification step, what
she is doing this second. He could stand in front of the wall while three
of his own decisions sat unmade six feet away.

Worse, the only data source is `pulse.collect`, which runs in GitHub
Actions on a six-hourly cron. Measured while writing this: the wall was
rendering a picture of the world **10.5 hours old**. A locally-running
Aletheia never refreshed her own display.

So this module builds the OTHER block — the one about her — from live
local state, cheaply enough to run on every Core beat. It is deliberately
kept separate from the fleet block rather than merged into it, and it
carries its OWN timestamp, because merging would let a fresh local read
make six-hour-old repository data look current. The wall shows two ages
because there really are two ages (§107: nothing renders as live that
isn't).
"""
from __future__ import annotations

import datetime as dt

MAX_ITEMS = 6


def _safe(fn, default):
    """Any one source failing must not blank the whole wall."""
    try:
        return fn()
    except Exception:
        return default


def _approvals() -> list[dict]:
    from aletheia import policy, voice
    pending = [a for a in policy.all_approvals() if a.get("state") == "PENDING"]
    return [{"label": voice.approval_label(a), "since": a.get("requested_at")}
            for a in pending[:MAX_ITEMS]]


def _notifications() -> list[dict]:
    """Unread notices, deduplicated by the words on screen.

    Two notices can carry different dedupe keys and the same title — the
    same subsystem failing twice, say — and the wall then shows the same
    sentence twice, which reads as a bug in the wall rather than as two
    events.
    """
    from aletheia import notifications, speech
    seen, out = set(), []
    for notice in notifications.all_notifications(state="UNREAD", limit=30):
        title = speech.tidy(speech.strip_ids(str(notice.get("title", ""))))
        if not title or title.casefold() in seen:
            continue
        seen.add(title.casefold())
        out.append({"title": title, "priority": notice.get("priority", "NORMAL"),
                    "at": notice.get("created_at")})
        if len(out) >= MAX_ITEMS:
            break
    return out


def _meetings() -> list[dict]:
    from aletheia import scheduling
    out = []
    for record in scheduling.all_negotiations():
        if record.get("state") not in scheduling.LIVE_STATES:
            continue
        out.append({"person": record.get("person", ""),
                    "state": record.get("state"),
                    "detail": (record.get("history") or [{}])[-1].get("detail", "")[:90]})
        if len(out) >= MAX_ITEMS:
            break
    return out


def _next_appointment(now: dt.datetime) -> dict | None:
    from aletheia import calendar
    upcoming = []
    for event in calendar.all_events():
        if event.get("status") == "CANCELLED":
            continue
        try:
            start = calendar.parse_time(event["start"])
        except (KeyError, ValueError, TypeError):
            continue
        if start >= now:
            upcoming.append((start, event))
    if not upcoming:
        return None
    start, event = min(upcoming, key=lambda pair: pair[0])
    from aletheia import speech
    return {"title": str(event.get("title", ""))[:80],
            "when": speech.humanize_time(start.isoformat()),
            "start": start.isoformat()}


def _working() -> list[dict]:
    """What she has in flight right now — the "agents working" of §88."""
    from aletheia import errands, followups, intents
    out = []
    thinking = _safe(followups.pending_count, 0)
    if thinking:
        out.append({"what": "thinking", "detail": f"{thinking} in progress"})
    for record in _safe(lambda: intents.all_intents(state=intents.PROPOSED), []):
        out.append({"what": "plan waiting on you",
                    "detail": str(record.get("summary", ""))[:80]})
        if len(out) >= MAX_ITEMS:
            return out
    for record in _safe(lambda: errands.all_errands(), []):
        if record.get("state") in (errands.PROPOSED, errands.RUNNING):
            out.append({"what": f"errand {record['state'].lower()}",
                        "detail": str(record.get("site", ""))[:60]})
        elif record.get("state") == errands.AT_BOUNDARY:
            out.append({"what": "errand needs you",
                        "detail": str(record.get("detail", ""))[:80]})
        if len(out) >= MAX_ITEMS:
            break
    return out


def snapshot(now: dt.datetime | None = None) -> dict:
    """The live block about HER. Cheap enough for every beat, never raises."""
    now = now or dt.datetime.now(dt.timezone.utc)
    from aletheia import liveness, policy
    approvals = _safe(_approvals, [])
    notices = _safe(_notifications, [])
    meetings = _safe(_meetings, [])
    working = _safe(_working, [])
    halted = _safe(policy.halted, None)
    age = _safe(liveness.age_seconds, None)
    waiting = len(approvals) + sum(1 for m in meetings if m["state"] == "BOOKING")
    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "halted": bool(halted),
        "heartbeat_age_s": None if age is None else round(age, 1),
        "waiting_on_you": approvals,
        "waiting_count": waiting,
        "notifications": notices,
        "meetings": meetings,
        "working": working,
        "next_appointment": _safe(lambda: _next_appointment(now), None),
        # One line for the top of the wall: the answer to "do I need to do
        # anything?" without reading a single panel.
        "headline": _headline(halted, approvals, notices, working),
    }


def _headline(halted, approvals: list[dict], notices: list[dict],
              working: list[dict]) -> str:
    from aletheia import speech
    if halted:
        return "HALTED — nothing acts until you resume"
    if approvals:
        return (f"{speech.count_phrase(len(approvals), 'decision')} waiting: "
                + speech.and_list([a["label"] for a in approvals[:3]]))
    urgent = [n for n in notices if n.get("priority") in ("URGENT", "IMPORTANT")]
    if urgent:
        return urgent[0]["title"]
    if working:
        return speech.and_list([w["what"] for w in working[:3]])
    return "All quiet"
