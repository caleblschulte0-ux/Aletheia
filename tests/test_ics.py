"""ICS calendar feeds: parsing, honest recurrence, mirroring, staleness."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import calendar, ics, journal, notifications

NOW = dt.datetime(2026, 8, 27, 12, 0, tzinfo=dt.timezone.utc)

FEED = """BEGIN:VCALENDAR\r
BEGIN:VEVENT\r
UID:one@test\r
SUMMARY:Dentist\\, downtown\r
DTSTART:20260828T150000Z\r
DTEND:20260828T160000Z\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:standup@test\r
SUMMARY:Standup\r
DTSTART;TZID=America/Chicago:20260803T090000\r
DTEND;TZID=America/Chicago:20260803T091500\r
RRULE:FREQ=WEEKLY;BYDAY=MO,WE\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:exotic@test\r
SUMMARY:Monthly board\r
DTSTART:20260901T170000Z\r
DTEND:20260901T180000Z\r
RRULE:FREQ=MONTHLY;BYMONTHDAY=1\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:gone@test\r
SUMMARY:Cancelled thing\r
STATUS:CANCELLED\r
DTSTART:20260829T100000Z\r
DTEND:20260829T110000Z\r
END:VEVENT\r
END:VCALENDAR\r
"""


class IcsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        cfg = d / "calendar.json"
        cfg.write_text(json.dumps(
            {"feeds": [{"id": "personal", "url": "https://example.com/secret.ics"}]}))
        for target, attr, value in (
                (ics, "CONFIG_FILE", cfg),
                (ics, "STATE_PATH", d / "feeds-state.json"),
                (calendar, "CALENDAR_DIR", d / "events"),
                (notifications, "NOTICES_DIR", d / "notices"),
                (journal, "JOURNAL_PATH", d / "journal.jsonl")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)

    def refresh(self, feed=FEED):
        return ics.refresh(fetch=lambda url: feed, now=NOW)


class TestParsing(IcsCase):
    def test_unescapes_and_folds(self):
        events, _ = ics.parse_events(
            "BEGIN:VEVENT\r\nUID:x\r\nSUMMARY:Long\r\n  title\\, folded\r\n"
            "DTSTART:20260828T150000Z\r\nEND:VEVENT\r\n")
        # RFC 5545: unfolding strips CRLF + exactly ONE leading space
        self.assertEqual(events[0]["title"], "Long title, folded")

    def test_tzid_converts_to_utc(self):
        events, _ = ics.parse_events(FEED)
        standup = next(e for e in events if e["uid"] == "standup@test")
        self.assertEqual(standup["start"].hour, 14)  # 09:00 Chicago = 14:00 UTC (CDT)

    def test_unsupported_rrule_is_counted_not_guessed(self):
        events, skipped = ics.parse_events(FEED)
        self.assertEqual(skipped, 1)
        self.assertNotIn("exotic@test", [e["uid"] for e in events])


class TestMirroring(IcsCase):
    def test_refresh_mirrors_singles_and_expands_weekly(self):
        totals = self.refresh()
        events = [e for e in calendar.all_events() if e["status"] == "CONFIRMED"]
        titles = {e["title"] for e in events}
        self.assertIn("Dentist, downtown", titles)
        standups = [e for e in events if e["title"] == "Standup"]
        # ~2 per week over the 60-day window
        self.assertGreater(len(standups), 10)
        self.assertEqual(totals["unsupported"], 1)

    def test_unsupported_rrule_raises_a_notification(self):
        self.refresh()
        notes = notifications.all_notifications()
        self.assertTrue(any("recurrence" in n["body"] for n in notes))

    def test_cancelled_upstream_never_mirrors(self):
        self.refresh()
        titles = {e["title"] for e in calendar.all_events()}
        self.assertNotIn("Cancelled thing", titles)

    def test_event_deleted_upstream_is_cancelled_here(self):
        self.refresh()
        without_dentist = FEED.replace("UID:one@test", "UID:one-b@test") \
            .replace("SUMMARY:Dentist\\, downtown", "SUMMARY:Moved dentist")
        totals = self.refresh(without_dentist)
        self.assertGreaterEqual(totals["cancelled_stale"], 1)
        dentist = [e for e in calendar.all_events()
                   if e["title"] == "Dentist, downtown"]
        self.assertTrue(all(e["status"] == "CANCELLED" for e in dentist))

    def test_local_events_are_never_touched(self):
        calendar.create("my-own", "Local plan", "2026-08-30T10:00:00Z",
                        "2026-08-30T11:00:00Z")
        self.refresh()
        self.assertEqual(calendar.load("my-own")["status"], "CONFIRMED")

    def test_refresh_is_idempotent(self):
        first = self.refresh()
        second = self.refresh()
        self.assertEqual(first["mirrored"], second["mirrored"])
        self.assertEqual(second["cancelled_stale"], 0)


class TestDueGate(IcsCase):
    def test_unconfigured_is_honest_noop(self):
        with mock.patch.object(ics, "CONFIG_FILE", Path(self.tmp.name) / "nope.json"):
            self.assertIsNone(ics.refresh_if_due(now=NOW))

    def test_within_interval_skips(self):
        self.refresh()
        with mock.patch.object(ics, "refresh") as r:
            self.assertIsNone(ics.refresh_if_due(now=NOW + dt.timedelta(minutes=5)))
            r.assert_not_called()

    def test_after_interval_refreshes(self):
        self.refresh()
        with mock.patch.object(ics, "refresh", return_value={"feeds": 1}) as r:
            self.assertIsNotNone(ics.refresh_if_due(now=NOW + dt.timedelta(minutes=45)))
            r.assert_called_once()

    def test_http_url_refused(self):
        ics.CONFIG_FILE.write_text(json.dumps(
            {"feeds": [{"id": "bad", "url": "http://insecure.example/cal.ics"}]}))
        ok, reason = ics.available()
        self.assertFalse(ok)
        self.assertIn("https", reason)


if __name__ == "__main__":
    unittest.main()
