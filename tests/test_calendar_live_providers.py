import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (calendar, calendar_google, calendar_graph, calendar_live,
                      calendar_oauth)


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, *, headers=None, json_body=None, form=None,
                expected=None, operation="request"):
        self.calls.append({"method": method, "url": url, "headers": dict(headers or {}),
                           "json": json_body, "form": form, "operation": operation})
        if not self.responses:
            raise AssertionError(f"unexpected request {method} {url}")
        status, payload = self.responses.pop(0)
        if expected is not None and status not in expected:
            raise calendar_oauth.HttpError(status, operation)
        return status, {}, payload


def token(value="tok", expires=3600, refresh_token=None):
    payload = {"access_token": value, "expires_in": expires}
    if refresh_token:
        payload["refresh_token"] = refresh_token
    return 200, payload


def google_event(event_id="g1", *, attendees=None, transparency="opaque"):
    return {
        "id": event_id, "summary": "Appointment",
        "start": {"dateTime": "2026-08-28T17:30:00-05:00"},
        "end": {"dateTime": "2026-08-28T18:00:00-05:00"},
        "status": "confirmed", "attendees": attendees or [],
        "transparency": transparency,
        "etag": '"abc"', "updated": "2026-08-27T10:00:00Z",
    }


def graph_event(event_id="m1", *, show_as="busy"):
    return {
        "id": event_id, "subject": "Dentist",
        "start": {"dateTime": "2026-08-28T22:30:00.0000000", "timeZone": "UTC"},
        "end": {"dateTime": "2026-08-28T23:00:00.0000000", "timeZone": "UTC"},
        "showAs": show_as, "isCancelled": False,
        "@odata.etag": 'W/"abc"', "lastModifiedDateTime": "2026-08-27T15:00:00Z",
    }


class ProviderCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for target, name, value in [
            (calendar, "CALENDAR_DIR", root / "events"),
            (calendar_oauth, "TOKEN_DIR", root / "oauth"),
            (calendar_live, "STATE_PATH", root / "live-state.json"),
        ]:
            p = mock.patch.object(target, name, value); p.start(); self.addCleanup(p.stop)
        self.root = root

    def session(self, provider_id, fake, token_url="https://oauth.example/token"):
        return calendar_oauth.OAuthSession(
            provider_id, token_url=token_url,
            refresh_form={"client_id": "client", "refresh_token": "refresh-secret"},
            transport=fake, cache_path=self.root / f"{provider_id}.json")


class TestOAuth(ProviderCase):
    def test_401_refreshes_once_and_never_surfaces_secrets(self):
        fake = FakeTransport([
            token("old"), (401, {"error": "refresh-secret should never leak"}),
            token("new"), (200, {"ok": True}),
        ])
        session = self.session("test.calendar", fake)
        _, _, payload = session.api_request("GET", "https://api.example/data", expected={200})
        self.assertEqual(payload, {"ok": True})
        api_calls = [c for c in fake.calls if c["url"] == "https://api.example/data"]
        self.assertEqual(api_calls[0]["headers"]["Authorization"], "Bearer old")
        self.assertEqual(api_calls[1]["headers"]["Authorization"], "Bearer new")

    def test_http_error_text_has_no_provider_body_or_credentials(self):
        fake = FakeTransport([token(), (403, {"detail": "refresh-secret client"})])
        session = self.session("test.calendar", fake)
        with self.assertRaises(calendar_oauth.HttpError) as caught:
            session.api_request("GET", "https://api.example/data", expected={200})
        text = str(caught.exception)
        self.assertNotIn("refresh-secret", text)
        self.assertNotIn("client", text)

    def test_rotated_refresh_token_is_used_on_next_refresh(self):
        fake = FakeTransport([token("one", refresh_token="rotated"), token("two")])
        session = self.session("test.calendar", fake)
        session.refresh(); session.refresh()
        self.assertEqual(fake.calls[0]["form"]["refresh_token"], "refresh-secret")
        self.assertEqual(fake.calls[1]["form"]["refresh_token"], "rotated")

    def test_redirect_handler_refuses_redirects(self):
        handler = calendar_oauth._NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, "Found", {},
                                                    "https://evil.example/steal"))


class TestGoogle(ProviderCase):
    def test_list_expands_and_pages(self):
        fake = FakeTransport([
            token(), (200, {"items": [google_event("g1")], "nextPageToken": "p2"}),
            (200, {"items": [google_event("g2")]}),
        ])
        provider = calendar_google.GoogleCalendarProvider(
            self.session("google.calendar", fake), timezone="America/Chicago")
        values = provider.list_events("2026-08-28T00:00:00Z", "2026-08-30T00:00:00Z")
        self.assertEqual([v["external_id"] for v in values], ["g1", "g2"])
        first_url, second_url = fake.calls[1]["url"], fake.calls[2]["url"]
        self.assertIn("singleEvents=true", first_url)
        self.assertIn("pageToken=p2", second_url)

    def test_all_day_uses_configured_calendar_timezone(self):
        item = {"id": "day", "summary": "Away", "start": {"date": "2026-08-28"},
                "end": {"date": "2026-08-29"}, "status": "confirmed"}
        fake = FakeTransport([token(), (200, {"items": [item]})])
        provider = calendar_google.GoogleCalendarProvider(
            self.session("google.calendar", fake), timezone="America/Chicago")
        value = provider.list_events("2026-08-27T00:00:00Z", "2026-08-30T00:00:00Z")[0]
        self.assertIn("-05:00", value["start"])
        self.assertEqual(calendar.parse_time(value["end"]) - calendar.parse_time(value["start"]),
                         dt.timedelta(days=1))

    def test_transparent_event_does_not_block_busy_mirror(self):
        fake = FakeTransport([token(), (200, {"items": [google_event(transparency="transparent")]})])
        provider = calendar_google.GoogleCalendarProvider(
            self.session("google.calendar", fake), timezone="America/Chicago")
        self.assertEqual(provider.list_events("2026-08-28T00:00:00Z", "2026-08-30T00:00:00Z"), [])

    def test_attendee_write_refused_before_network(self):
        fake = FakeTransport([])
        provider = calendar_google.GoogleCalendarProvider(
            self.session("google.calendar", fake), timezone="America/Chicago", allow_writes=True)
        with self.assertRaisesRegex(ValueError, "attendee"):
            provider.create_event({"title": "Meet", "start": "2026-08-28T10:00:00-05:00",
                                   "end": "2026-08-28T11:00:00-05:00",
                                   "attendees": ["person@example.com"]})
        self.assertEqual(fake.calls, [])

    def test_writes_disabled_before_token_or_network(self):
        fake = FakeTransport([])
        provider = calendar_google.GoogleCalendarProvider(
            self.session("google.calendar", fake), timezone="America/Chicago", allow_writes=False)
        with self.assertRaises(PermissionError):
            provider.create_event({"title": "Meet", "start": "2026-08-28T10:00:00-05:00",
                                   "end": "2026-08-28T11:00:00-05:00", "attendees": []})
        self.assertEqual(fake.calls, [])

    def test_delete_requires_verified_absence(self):
        fake = FakeTransport([token(), (200, google_event()), (204, None), (404, None)])
        provider = calendar_google.GoogleCalendarProvider(
            self.session("google.calendar", fake), timezone="America/Chicago", allow_writes=True)
        result = provider.cancel_event("g1")
        self.assertEqual(result["status"], "CANCELLED")
        self.assertEqual([c["method"] for c in fake.calls[1:]], ["GET", "DELETE", "GET"])


class TestGraph(ProviderCase):
    def test_calendar_view_pages_and_normalizes_utc(self):
        next_link = ("https://graph.microsoft.com/v1.0/me/calendar/calendarView?"
                     "startDateTime=x&endDateTime=y&$skiptoken=abc")
        fake = FakeTransport([
            token(), (200, {"value": [graph_event("m1")], "@odata.nextLink": next_link}),
            (200, {"value": [graph_event("m2")]}),
        ])
        provider = calendar_graph.MicrosoftGraphCalendarProvider(
            self.session("microsoft.graph.calendar", fake))
        values = provider.list_events("2026-08-28T00:00:00Z", "2026-08-30T00:00:00Z")
        self.assertEqual([v["external_id"] for v in values], ["m1", "m2"])
        self.assertEqual(calendar.parse_time(values[0]["start"]).utcoffset(), dt.timedelta(0))
        self.assertEqual(fake.calls[1]["headers"]["Prefer"], 'outlook.timezone="UTC"')

    def test_free_event_does_not_block_busy_mirror(self):
        fake = FakeTransport([token(), (200, {"value": [graph_event(show_as="free")]})])
        provider = calendar_graph.MicrosoftGraphCalendarProvider(
            self.session("microsoft.graph.calendar", fake))
        self.assertEqual(provider.list_events("2026-08-28T00:00:00Z", "2026-08-30T00:00:00Z"), [])

    def test_next_link_may_not_exfiltrate_bearer(self):
        fake = FakeTransport([
            token(), (200, {"value": [], "@odata.nextLink": "https://evil.example/steal"}),
        ])
        provider = calendar_graph.MicrosoftGraphCalendarProvider(
            self.session("microsoft.graph.calendar", fake))
        with self.assertRaisesRegex(ValueError, "origin"):
            provider.list_events("2026-08-28T00:00:00Z", "2026-08-30T00:00:00Z")
        self.assertEqual(len(fake.calls), 2)  # token + first Graph page; evil URL untouched

    def test_attendee_write_refused_before_network(self):
        fake = FakeTransport([])
        provider = calendar_graph.MicrosoftGraphCalendarProvider(
            self.session("microsoft.graph.calendar", fake), allow_writes=True)
        with self.assertRaisesRegex(ValueError, "attendee"):
            provider.create_event({"title": "Meet", "start": "2026-08-28T10:00:00-05:00",
                                   "end": "2026-08-28T11:00:00-05:00",
                                   "attendees": ["person@example.com"]})
        self.assertEqual(fake.calls, [])

    def test_delete_requires_verified_absence(self):
        fake = FakeTransport([token(), (200, graph_event()), (204, None), (404, None)])
        provider = calendar_graph.MicrosoftGraphCalendarProvider(
            self.session("microsoft.graph.calendar", fake), allow_writes=True)
        result = provider.cancel_event("m1")
        self.assertEqual(result["status"], "CANCELLED")
        self.assertEqual([c["method"] for c in fake.calls[1:]], ["GET", "DELETE", "GET"])


class TestLiveConfigAndSync(ProviderCase):
    def google_config(self, *, allow_writes=False):
        path = self.root / "calendar-live.json"
        path.write_text(json.dumps({
            "provider": "google", "calendar_id": "primary", "timezone": "America/Chicago",
            "allow_writes": allow_writes,
            "oauth": {"client_id": "client", "client_secret": "secret",
                      "refresh_token": "refresh"},
        }), encoding="utf-8")
        return path

    def test_available_never_prints_secrets(self):
        path = self.google_config()
        ok, reason = calendar_live.available(path)
        self.assertTrue(ok)
        self.assertNotIn("refresh", reason)
        self.assertNotIn("secret", reason)

    def test_live_refresh_mirrors_and_throttles(self):
        path = self.google_config()
        fake = FakeTransport([token(), (200, {"items": [google_event()]})])
        now = dt.datetime(2026, 8, 27, 16, 0, tzinfo=dt.timezone.utc)
        result = calendar_live.refresh(now=now, transport=fake, path=path)
        self.assertEqual(result["remote_count"], 1)
        self.assertEqual(len(calendar.all_events()), 1)
        # A second due-check inside 30 minutes does not touch the provider.
        again = calendar_live.refresh_if_due(
            now=now + dt.timedelta(minutes=10), transport=fake, path=path)
        self.assertIsNone(again)
        self.assertEqual(len(fake.calls), 2)

    def test_busy_event_becoming_transparent_cancels_old_busy_copy(self):
        path = self.google_config()
        now = dt.datetime(2026, 8, 27, 16, 0, tzinfo=dt.timezone.utc)
        first = FakeTransport([token(), (200, {"items": [google_event()]})])
        calendar_live.refresh(now=now, transport=first, path=path)
        self.assertEqual(calendar.all_events()[0]["status"], "CONFIRMED")
        second = FakeTransport([(200, {"items": [google_event(transparency="transparent")]})])
        calendar_live.refresh(now=now + dt.timedelta(minutes=31), transport=second, path=path)
        self.assertEqual(calendar.all_events()[0]["status"], "CANCELLED")

    def test_microsoft_tenant_is_path_safe(self):
        path = self.root / "calendar-live.json"
        path.write_text(json.dumps({
            "provider": "microsoft", "oauth": {"client_id": "client",
            "refresh_token": "refresh", "tenant": "../evil"}}), encoding="utf-8")
        ok, reason = calendar_live.available(path)
        self.assertFalse(ok)
        self.assertIn("tenant", reason)


if __name__ == "__main__":
    unittest.main()
