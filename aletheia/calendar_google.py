"""Official Google Calendar API adapter for calendar_provider.CalendarProvider.

This module contains no interactive auth UI and no embedded client credentials.
A configured OAuth refresh token is supplied by calendar_live.py. Reads use
Events.list with singleEvents=true so recurring masters are expanded by Google.
Writes use the existing Aletheia hash-bound approval layer above this adapter.

V1 deliberately refuses non-empty attendees on writes. Adding attendees to a
calendar event can send invitations/update notices; that side effect is not yet
represented in calendar_provider's approved plan contract, so silently doing it
would widen authority.
"""
from __future__ import annotations

import datetime as dt
import urllib.parse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aletheia import calendar, calendar_provider
from aletheia.calendar_oauth import OAuthSession

API_ROOT = "https://www.googleapis.com/calendar/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
MAX_PAGES = 100


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _utc_iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


class GoogleCalendarProvider:
    provider_id = "google.calendar"

    def __init__(self, session: OAuthSession, *, calendar_id: str = "primary",
                 timezone: str, allow_writes: bool = False):
        if not isinstance(calendar_id, str) or not calendar_id.strip():
            raise ValueError("Google calendar_id is required")
        try:
            self.timezone = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown Google calendar timezone {timezone!r}") from exc
        self.session = session
        self.calendar_id = calendar_id.strip()
        self.allow_writes = bool(allow_writes)

    def _event_url(self, event_id: str | None = None) -> str:
        base = f"{API_ROOT}/calendars/{_quote(self.calendar_id)}/events"
        return f"{base}/{_quote(event_id)}" if event_id else base

    def _when(self, part: dict, *, end: bool = False) -> str:
        if not isinstance(part, dict):
            raise ValueError("Google event start/end must be objects")
        if part.get("dateTime"):
            return calendar.parse_time(str(part["dateTime"])).isoformat()
        date = part.get("date")
        if not isinstance(date, str) or not date:
            raise ValueError("Google event is missing start/end time")
        day = dt.date.fromisoformat(date)
        # Google all-day DTEND is exclusive. Keeping midnight boundaries in the
        # configured calendar timezone preserves the provider's busy day.
        return dt.datetime.combine(day, dt.time.min, tzinfo=self.timezone).isoformat()

    def _normalize(self, item: dict) -> dict:
        if not isinstance(item, dict) or not item.get("id"):
            raise ValueError("Google event is missing id")
        status_raw = str(item.get("status", "confirmed")).lower()
        status = "CANCELLED" if status_raw == "cancelled" else (
            "TENTATIVE" if status_raw == "tentative" else "CONFIRMED")
        attendees = []
        for attendee in item.get("attendees", []) or []:
            if isinstance(attendee, dict) and isinstance(attendee.get("email"), str) and attendee["email"].strip():
                attendees.append(attendee["email"].strip())
        value = {
            "external_id": str(item["id"]),
            "title": str(item.get("summary") or "(untitled)"),
            "start": self._when(item.get("start", {})),
            "end": self._when(item.get("end", {}), end=True),
            "status": status,
            "attendees": list(dict.fromkeys(attendees)),
        }
        if item.get("location"):
            value["location"] = str(item["location"])
        if item.get("etag"):
            value["etag"] = str(item["etag"])
        if item.get("updated"):
            value["updated_at"] = str(item["updated"])
        return calendar_provider.normalize_event(value)

    def list_events(self, start: str, end: str) -> list[dict]:
        a, b = calendar.parse_time(start), calendar.parse_time(end)
        if b <= a:
            raise ValueError("calendar list end must be after start")
        query = {
            "timeMin": _utc_iso(a), "timeMax": _utc_iso(b),
            "singleEvents": "true", "showDeleted": "false",
            "maxResults": "2500", "timeZone": str(self.timezone),
        }
        out: list[dict] = []
        page_token = None
        seen_tokens: set[str] = set()
        for _ in range(MAX_PAGES):
            q = dict(query)
            if page_token:
                q["pageToken"] = page_token
            url = self._event_url() + "?" + urllib.parse.urlencode(q)
            _, _, payload = self.session.api_request(
                "GET", url, expected={200}, operation="Google Calendar list")
            payload = payload or {}
            items = payload.get("items", [])
            if not isinstance(items, list):
                raise ValueError("Google Calendar list returned invalid items")
            # transparency=transparent means the provider explicitly says this
            # event does not block time. Omitting it from the busy mirror also
            # makes an old busy copy get cancelled by authoritative sync.
            out.extend(self._normalize(item) for item in items
                       if str(item.get("transparency", "opaque")).lower() != "transparent")
            page_token = payload.get("nextPageToken")
            if not page_token:
                return out
            if not isinstance(page_token, str) or page_token in seen_tokens:
                raise ValueError("Google Calendar pagination token is invalid or repeated")
            seen_tokens.add(page_token)
        raise RuntimeError("Google Calendar pagination exceeded page cap")

    def _write_body(self, event: dict) -> dict:
        normalized = calendar_provider.normalize_event({"external_id": "pending", **event})
        if normalized["attendees"]:
            raise ValueError("calendar attendee writes are not supported in provider v1")
        start = calendar.parse_time(normalized["start"])
        end = calendar.parse_time(normalized["end"])
        body = {
            "summary": normalized["title"],
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
        }
        if normalized.get("location"):
            body["location"] = normalized["location"]
        return body

    def _require_write(self) -> None:
        if not self.allow_writes:
            raise PermissionError("live calendar writes are disabled in local calendar configuration")

    def create_event(self, event: dict) -> dict:
        self._require_write()
        body = self._write_body(event)
        _, _, payload = self.session.api_request(
            "POST", self._event_url(), json_body=body, expected={200, 201},
            operation="Google Calendar create")
        return self._normalize(payload or {})

    def update_event(self, external_id: str, event: dict) -> dict:
        self._require_write()
        if not isinstance(external_id, str) or not external_id.strip():
            raise ValueError("Google event id is required")
        body = self._write_body(event)
        _, _, payload = self.session.api_request(
            "PATCH", self._event_url(external_id.strip()), json_body=body,
            expected={200}, operation="Google Calendar update")
        return self._normalize(payload or {})

    def cancel_event(self, external_id: str) -> dict:
        self._require_write()
        if not isinstance(external_id, str) or not external_id.strip():
            raise ValueError("Google event id is required")
        url = self._event_url(external_id.strip())
        status, _, before = self.session.api_request(
            "GET", url, expected={200, 404, 410}, operation="Google Calendar pre-delete read")
        if status != 200 or before is None:
            raise KeyError(external_id)
        prior = self._normalize(before)
        self.session.api_request(
            "DELETE", url, expected={200, 204}, operation="Google Calendar delete")
        verify_status, _, _ = self.session.api_request(
            "GET", url, expected={200, 404, 410}, operation="Google Calendar delete verification")
        if verify_status == 200:
            raise RuntimeError("Google Calendar delete was not verified absent")
        return {**prior, "status": "CANCELLED"}
