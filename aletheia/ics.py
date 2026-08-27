"""Calendar feeds — Phase 14's live read fallback, no model/API key required.

The operator's calendar apps can publish a SECRET ICS URL (Google: Settings ->
"Secret address in iCal format"; Outlook: "Publish calendar"). That URL is a
read-only credential: it lives in ~/.aletheia/calendar.json on the PC, never in
the repo. This module fetches it, parses VEVENTs with the stdlib, and mirrors
busy time into the private local calendar model that availability consumes.

Honesty rules (§104), because a WRONG answer to "am I free at 3?" is worse than
no answer:
- recurring events are expanded within yesterday .. +60 days;
- unsupported RRULEs are counted and surfaced, never silently guessed away;
- TRANSP:TRANSPARENT events do not block time;
- STATUS:TENTATIVE remains tentative and CANCELLED does not block;
- stale mirrored events are cancelled while local non-feed events are untouched.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

from aletheia import calendar, journal, notifications
from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

CONFIG_FILE = Path.home() / ".aletheia" / "calendar.json"
STATE_PATH = private_dir("calendar") / "feeds-state.json"
ACTOR = "aletheia-ics"
WINDOW_PAST_DAYS = 1
WINDOW_FUTURE_DAYS = 60
REFRESH_EVERY_S = 30 * 60
MAX_FEED_BYTES = 5 * 1024 * 1024
_BYDAY = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _config() -> dict:
    if not CONFIG_FILE.exists():
        return {"feeds": []}
    value = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    feeds = value.get("feeds", [])
    if not isinstance(feeds, list):
        raise ValueError("calendar.json feeds must be a list")
    seen: set[str] = set()
    for feed in feeds:
        if not isinstance(feed, dict) or not feed.get("id") or not feed.get("url"):
            raise ValueError("each feed needs id and url")
        feed_id = safe_id(str(feed["id"]), name="calendar feed id")
        if feed_id in seen:
            raise ValueError(f"duplicate calendar feed id {feed_id!r}")
        seen.add(feed_id)
        if not str(feed["url"]).startswith("https://"):
            raise ValueError(f"feed {feed_id}: url must be https")
    return {"feeds": feeds}


def available() -> tuple[bool, str]:
    try:
        feeds = _config()["feeds"]
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return False, f"calendar.json is invalid: {exc}"
    if not feeds:
        return False, ("no calendar feeds configured: put your calendar's secret "
                       f"ICS url in {CONFIG_FILE} as "
                       '{"feeds": [{"id": "personal", "url": "https://..."}]}')
    return True, f"{len(feeds)} feed(s) configured"


# ---- parsing ----------------------------------------------------------------
def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def _unescape(value: str) -> str:
    return (value.replace("\\n", " ").replace("\\N", " ")
                 .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\"))


def _split_prop(line: str) -> tuple[str, dict, str]:
    head, _, value = line.partition(":")
    parts = head.split(";")
    params = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        params[k.upper()] = v
    return parts[0].upper(), params, value


def _parse_dt(value: str, params: dict) -> tuple[dt.datetime, bool]:
    """-> (aware datetime UTC, is_all_day).

    Floating times have no timezone information to recover; the providers this
    fallback targets normally emit Z or TZID. A floating timestamp is therefore
    interpreted as UTC rather than guessed into the operator's zone.
    """
    value = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        d = dt.datetime.strptime(value, "%Y%m%d").replace(tzinfo=dt.timezone.utc)
        return d, True
    if value.endswith("Z"):
        return dt.datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=dt.timezone.utc), False
    naive = dt.datetime.strptime(value, "%Y%m%dT%H%M%S")
    tzid = params.get("TZID")
    tz = ZoneInfo(tzid) if tzid else dt.timezone.utc
    return naive.replace(tzinfo=tz).astimezone(dt.timezone.utc), False


def parse_events(text: str) -> tuple[list[dict], int]:
    """-> (raw events, count skipped for unsupported recurrence)."""
    events, skipped = [], 0
    current: dict | None = None
    for line in _unfold(text):
        name, params, value = _split_prop(line)
        if name == "BEGIN" and value.strip().upper() == "VEVENT":
            current = {"exdates": []}
        elif name == "END" and value.strip().upper() == "VEVENT" and current is not None:
            if "start" in current and "uid" in current:
                if current.get("unsupported_rrule"):
                    skipped += 1
                else:
                    events.append(current)
            current = None
        elif current is None:
            continue
        elif name == "UID":
            current["uid"] = value.strip()
        elif name == "SUMMARY":
            current["title"] = _unescape(value).strip() or "(untitled)"
        elif name == "LOCATION":
            current["location"] = _unescape(value).strip()
        elif name == "STATUS":
            current["status"] = value.strip().upper()
        elif name == "TRANSP":
            current["transparent"] = value.strip().upper() == "TRANSPARENT"
        elif name == "DTSTART":
            current["start"], current["all_day"] = _parse_dt(value, params)
        elif name == "DTEND":
            current["end"], _ = _parse_dt(value, params)
        elif name == "EXDATE":
            for piece in value.split(","):
                try:
                    when, _ = _parse_dt(piece, params)
                    current["exdates"].append(when)
                except ValueError:
                    pass
        elif name == "RRULE":
            rule = {k.upper(): v for k, _, v in
                    (p.partition("=") for p in value.strip().split(";")) if k}
            freq = rule.get("FREQ", "").upper()
            supported_keys = {"FREQ", "INTERVAL", "COUNT", "UNTIL", "BYDAY", "WKST"}
            if freq not in ("DAILY", "WEEKLY") or set(rule) - supported_keys:
                current["unsupported_rrule"] = True
            else:
                current["rrule"] = rule
    return events, skipped


def _expand(event: dict, window_start: dt.datetime,
            window_end: dt.datetime) -> list[tuple[dt.datetime, dt.datetime]]:
    start = event["start"]
    end = event.get("end") or (start + dt.timedelta(days=1 if event.get("all_day") else 0,
                                                    hours=0 if event.get("all_day") else 1))
    duration = end - start
    rule = event.get("rrule")
    if not rule:
        return [(start, end)] if start < window_end and end > window_start else []
    interval = max(1, int(rule.get("INTERVAL", "1")))
    count = int(rule["COUNT"]) if "COUNT" in rule else None
    until = None
    if "UNTIL" in rule:
        until, _ = _parse_dt(rule["UNTIL"], {})
    exdates = {x for x in event["exdates"]}
    out: list[tuple[dt.datetime, dt.datetime]] = []
    if rule["FREQ"] == "DAILY":
        candidates = (start + dt.timedelta(days=i * interval) for i in range(0, 1000))
    else:  # WEEKLY
        bydays = sorted({_BYDAY[d] for d in rule.get("BYDAY", "").split(",") if d}
                        or {start.weekday()})

        def weekly():
            week0 = start - dt.timedelta(days=start.weekday())
            for w in range(0, 200):
                base = week0 + dt.timedelta(weeks=w * interval)
                for wd in bydays:
                    candidate = base + dt.timedelta(days=wd)
                    if candidate >= start:
                        yield candidate
        candidates = weekly()
    emitted = 0
    for occ in candidates:
        if until and occ > until:
            break
        emitted += 1
        if count and emitted > count:
            break
        if occ > window_end:
            break
        if occ in exdates:
            continue
        occ_end = occ + duration
        if occ < window_end and occ_end > window_start:
            out.append((occ, occ_end))
    return out


# ---- mirroring --------------------------------------------------------------
def _stamp(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _event_id(feed_id: str, uid: str, occ_start: dt.datetime) -> str:
    digest = hashlib.sha256(f"{uid}|{_stamp(occ_start)}".encode()).hexdigest()[:16]
    return f"ics-{feed_id}-{digest}"


def refresh(fetch=None, *, now: dt.datetime | None = None) -> dict:
    """Mirror every configured feed into the local calendar. Returns counts."""
    ok, reason = available()
    if not ok:
        raise RuntimeError(reason)
    now = now or dt.datetime.now(dt.timezone.utc)
    window_start = now - dt.timedelta(days=WINDOW_PAST_DAYS)
    window_end = now + dt.timedelta(days=WINDOW_FUTURE_DAYS)
    fetch = fetch or _fetch_url
    totals = {"feeds": 0, "mirrored": 0, "cancelled_stale": 0, "unsupported": 0}
    seen_ids: set[str] = set()
    for feed in _config()["feeds"]:
        raw = fetch(feed["url"])
        events, skipped = parse_events(raw)
        totals["feeds"] += 1
        totals["unsupported"] += skipped
        for event in events:
            if event.get("status") == "CANCELLED" or event.get("transparent"):
                continue
            local_status = "TENTATIVE" if event.get("status") == "TENTATIVE" else "CONFIRMED"
            for occ_start, occ_end in _expand(event, window_start, window_end):
                eid = _event_id(feed["id"], event["uid"], occ_start)
                seen_ids.add(eid)
                record = {
                    "version": 1, "id": eid, "title": event.get("title", "(untitled)"),
                    "start": _stamp(occ_start), "end": _stamp(occ_end),
                    "attendees": [], "source": f"ics:{feed['id']}",
                    "status": local_status, "priority": 3,
                    "movable": False, "created_at": utcnow(), "updated_at": utcnow(),
                }
                if event.get("location"):
                    record["location"] = event["location"]
                try:
                    existing = calendar.load(eid)
                    if (existing["start"], existing["end"], existing["title"], existing["status"]) != (
                            record["start"], record["end"], record["title"], record["status"]):
                        calendar.save({**existing, "title": record["title"],
                                       "start": record["start"], "end": record["end"],
                                       "status": record["status"], "updated_at": utcnow()})
                except (FileNotFoundError, ValueError):
                    calendar.save(record)
                totals["mirrored"] += 1
    # A mirrored event no longer upstream — including one changed to transparent
    # or cancelled — must stop blocking free time.
    for existing in calendar.all_events():
        if existing["id"].startswith("ics-") and existing["id"] not in seen_ids \
                and existing["status"] != "CANCELLED":
            calendar.cancel(existing["id"])
            totals["cancelled_stale"] += 1
    if totals["unsupported"]:
        notifications.publish(
            "Calendar mirror is incomplete",
            f"{totals['unsupported']} event(s) use recurrence rules I can't expand "
            "yet — free-time answers may miss them.",
            priority="IMPORTANT", source="calendar",
            dedupe_key="ics-unsupported-rrule")
    write_json_atomic(STATE_PATH, {"last_refresh": _stamp(now), **totals})
    journal.append("event", "calendar:refresh",
                   f"{totals['mirrored']} mirrored, {totals['cancelled_stale']} stale "
                   f"cancelled, {totals['unsupported']} unsupported across "
                   f"{totals['feeds']} feed(s)", actor=ACTOR)
    return totals


def _fetch_url(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            data = r.read(MAX_FEED_BYTES + 1)
    except Exception as exc:
        # The secret ICS URL is a credential; never include urllib's URL-bearing
        # exception text in Core results/logs.
        raise RuntimeError(f"calendar feed fetch failed: {type(exc).__name__}") from None
    if len(data) > MAX_FEED_BYTES:
        raise ValueError("feed exceeds size cap")
    return data.decode("utf-8", errors="replace")


def refresh_if_due(*, now: dt.datetime | None = None) -> dict | None:
    """Core-tick hook: refresh at most every REFRESH_EVERY_S; None if not due
    or not configured (honest no-op, never an error in the loop)."""
    if not available()[0]:
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    if STATE_PATH.exists():
        state = read_json(STATE_PATH)
        last = state.get("last_refresh")
        if last:
            elapsed = (now - dt.datetime.fromisoformat(
                last.replace("Z", "+00:00"))).total_seconds()
            if elapsed < REFRESH_EVERY_S:
                return None
    return refresh(now=now)
