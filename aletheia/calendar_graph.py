"""Official Microsoft Graph calendar adapter.

Reads use calendarView, which expands recurring series in a bounded window.
Graph paging returns @odata.nextLink; every next link is origin-checked before a
bearer token is attached so a malicious/provider-corrupt response cannot turn
pagination into credential exfiltration.

Writes remain behind Aletheia's generic hash-bound calendar approval layer and
also require local allow_writes=true. V1 refuses attendee writes because Graph
sends meeting invitations when attendees are supplied; that additional external
communication is not represented in the current approved calendar plan.
"""
from __future__ import annotations

import datetime as dt
import re
import urllib.parse

from aletheia import calendar, calendar_provider
from aletheia.calendar_oauth import OAuthSession

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
MAX_PAGES = 100
_UTC_PREFER = 'outlook.timezone="UTC"'


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _trim_fraction(value: str) -> str:
    # Graph commonly emits seven fractional digits; datetime supports six.
    return re.sub(r"(\.\d{6})\d+(?=$|Z|[+-]\d\d:\d\d$)", r"\1", value)


def _as_utc(value: dt.datetime) -> dt.datetime:
    return value.astimezone(dt.timezone.utc)


class MicrosoftGraphCalendarProvider:
    provider_id = "microsoft.graph.calendar"

    def __init__(self, session: OAuthSession, *, calendar_id: str | None = None,
                 allow_writes: bool = False):
        self.session = session
        self.calendar_id = calendar_id.strip() if isinstance(calendar_id, str) and calendar_id.strip() else None
        self.allow_writes = bool(allow_writes)

    def _calendar_base(self) -> str:
        if self.calendar_id:
            return f"{GRAPH_ROOT}/me/calendars/{_quote(self.calendar_id)}"
        return f"{GRAPH_ROOT}/me/calendar"

    def _event_url(self, event_id: str) -> str:
        # Events are addressable from /me/events regardless of their calendar.
        return f"{GRAPH_ROOT}/me/events/{_quote(event_id)}"

    def _parse_part(self, part: dict) -> str:
        if not isinstance(part, dict) or not isinstance(part.get("dateTime"), str):
            raise ValueError("Graph event is missing dateTime")
        raw = _trim_fraction(part["dateTime"].strip())
        # CalendarView is always requested with Prefer: UTC. If Graph returns a
        # naive datetime tagged with anything else, refuse rather than guess a
        # Windows/IANA timezone mapping.
        try:
            parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Graph event returned invalid dateTime") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            zone = str(part.get("timeZone", "")).upper()
            if zone not in {"UTC", "ETC/UTC", "GMT", "GMT STANDARD TIME"}:
                raise ValueError("Graph event ignored requested UTC timezone")
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return _as_utc(parsed).isoformat()

    def _normalize(self, item: dict) -> dict:
        if not isinstance(item, dict) or not item.get("id"):
            raise ValueError("Graph event is missing id")
        if item.get("isCancelled"):
            status = "CANCELLED"
        elif str(item.get("showAs", "")).lower() == "tentative":
            status = "TENTATIVE"
        else:
            status = "CONFIRMED"
        attendees = []
        for attendee in item.get("attendees", []) or []:
            address = (attendee.get("emailAddress", {}).get("address")
                       if isinstance(attendee, dict) else None)
            if isinstance(address, str) and address.strip():
                attendees.append(address.strip())
        value = {
            "external_id": str(item["id"]),
            "title": str(item.get("subject") or "(untitled)"),
            "start": self._parse_part(item.get("start", {})),
            "end": self._parse_part(item.get("end", {})),
            "status": status,
            "attendees": list(dict.fromkeys(attendees)),
        }
        location = item.get("location")
        if isinstance(location, dict) and location.get("displayName"):
            value["location"] = str(location["displayName"])
        if item.get("@odata.etag"):
            value["etag"] = str(item["@odata.etag"])
        if item.get("lastModifiedDateTime"):
            value["updated_at"] = str(item["lastModifiedDateTime"])
        return calendar_provider.normalize_event(value)

    @staticmethod
    def _safe_next(url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.netloc.lower() != "graph.microsoft.com":
            raise ValueError("Graph pagination nextLink left the approved origin")
        if not parsed.path.startswith("/v1.0/"):
            raise ValueError("Graph pagination nextLink left v1.0 API")
        return url

    def list_events(self, start: str, end: str) -> list[dict]:
        a, b = calendar.parse_time(start), calendar.parse_time(end)
        if b <= a:
            raise ValueError("calendar list end must be after start")
        query = urllib.parse.urlencode({
            "startDateTime": _as_utc(a).isoformat(),
            "endDateTime": _as_utc(b).isoformat(),
            "$top": "1000",
        })
        url = f"{self._calendar_base()}/calendarView?{query}"
        out: list[dict] = []
        seen: set[str] = set()
        for _ in range(MAX_PAGES):
            _, _, payload = self.session.api_request(
                "GET", url, headers={"Prefer": _UTC_PREFER}, expected={200},
                operation="Microsoft Graph calendarView")
            payload = payload or {}
            values = payload.get("value", [])
            if not isinstance(values, list):
                raise ValueError("Graph calendarView returned invalid value list")
            out.extend(self._normalize(item) for item in values)
            next_url = payload.get("@odata.nextLink")
            if not next_url:
                return out
            if not isinstance(next_url, str):
                raise ValueError("Graph calendarView returned invalid nextLink")
            url = self._safe_next(next_url)
            if url in seen:
                raise ValueError("Graph calendarView repeated nextLink")
            seen.add(url)
        raise RuntimeError("Graph calendarView pagination exceeded page cap")

    def _write_body(self, event: dict) -> dict:
        normalized = calendar_provider.normalize_event({"external_id": "pending", **event})
        if normalized["attendees"]:
            raise ValueError("calendar attendee writes are not supported in provider v1")
        start = _as_utc(calendar.parse_time(normalized["start"]))
        end = _as_utc(calendar.parse_time(normalized["end"]))
        fmt = "%Y-%m-%dT%H:%M:%S"
        body = {
            "subject": normalized["title"],
            "start": {"dateTime": start.strftime(fmt), "timeZone": "UTC"},
            "end": {"dateTime": end.strftime(fmt), "timeZone": "UTC"},
        }
        if normalized.get("location"):
            body["location"] = {"displayName": normalized["location"]}
        return body

    def _require_write(self) -> None:
        if not self.allow_writes:
            raise PermissionError("live calendar writes are disabled in local calendar configuration")

    def create_event(self, event: dict) -> dict:
        self._require_write()
        body = self._write_body(event)
        url = f"{self._calendar_base()}/events"
        _, _, payload = self.session.api_request(
            "POST", url, headers={"Prefer": _UTC_PREFER}, json_body=body,
            expected={200, 201}, operation="Microsoft Graph event create")
        return self._normalize(payload or {})

    def update_event(self, external_id: str, event: dict) -> dict:
        self._require_write()
        if not isinstance(external_id, str) or not external_id.strip():
            raise ValueError("Graph event id is required")
        body = self._write_body(event)
        _, _, payload = self.session.api_request(
            "PATCH", self._event_url(external_id.strip()), headers={"Prefer": _UTC_PREFER},
            json_body=body, expected={200}, operation="Microsoft Graph event update")
        return self._normalize(payload or {})

    def cancel_event(self, external_id: str) -> dict:
        self._require_write()
        if not isinstance(external_id, str) or not external_id.strip():
            raise ValueError("Graph event id is required")
        url = self._event_url(external_id.strip())
        status, _, before = self.session.api_request(
            "GET", url, headers={"Prefer": _UTC_PREFER}, expected={200, 404},
            operation="Microsoft Graph pre-delete read")
        if status != 200 or before is None:
            raise KeyError(external_id)
        prior = self._normalize(before)
        self.session.api_request(
            "DELETE", url, expected={204}, operation="Microsoft Graph event delete")
        verify_status, _, _ = self.session.api_request(
            "GET", url, headers={"Prefer": _UTC_PREFER}, expected={200, 404},
            operation="Microsoft Graph delete verification")
        if verify_status == 200:
            raise RuntimeError("Microsoft Graph delete was not verified absent")
        return {**prior, "status": "CANCELLED"}
