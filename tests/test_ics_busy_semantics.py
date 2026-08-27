import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import calendar, ics, journal, notifications


class IcsBusyCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for target, name, value in [
            (ics, "CONFIG_FILE", root / "calendar.json"),
            (ics, "STATE_PATH", root / "feed-state.json"),
            (calendar, "CALENDAR_DIR", root / "events"),
            (journal, "JOURNAL_PATH", root / "journal.jsonl"),
            (notifications, "NOTICES_DIR", root / "notices"),
        ]:
            p = mock.patch.object(target, name, value); p.start(); self.addCleanup(p.stop)
        ics.CONFIG_FILE.write_text(json.dumps({"feeds": [{"id": "personal", "url": "https://calendar.example/secret.ics"}]}), encoding="utf-8")
        self.now = dt.datetime(2026, 8, 27, 16, 0, tzinfo=dt.timezone.utc)

    @staticmethod
    def event(*, transp="OPAQUE", status="CONFIRMED"):
        return ("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:one\nSUMMARY:Focus\n"
                "DTSTART:20260828T150000Z\nDTEND:20260828T160000Z\n"
                f"TRANSP:{transp}\nSTATUS:{status}\nEND:VEVENT\nEND:VCALENDAR\n")

    def test_transparent_event_never_blocks_calendar(self):
        totals = ics.refresh(fetch=lambda _: self.event(transp="TRANSPARENT"), now=self.now)
        self.assertEqual(totals["mirrored"], 0)
        self.assertEqual(calendar.all_events(), [])

    def test_tentative_event_stays_tentative(self):
        ics.refresh(fetch=lambda _: self.event(status="TENTATIVE"), now=self.now)
        self.assertEqual(calendar.all_events()[0]["status"], "TENTATIVE")

    def test_busy_event_becoming_transparent_cancels_old_copy(self):
        ics.refresh(fetch=lambda _: self.event(), now=self.now)
        self.assertEqual(calendar.all_events()[0]["status"], "CONFIRMED")
        ics.refresh(fetch=lambda _: self.event(transp="TRANSPARENT"),
                    now=self.now + dt.timedelta(minutes=31))
        self.assertEqual(calendar.all_events()[0]["status"], "CANCELLED")

    def test_feed_id_must_be_safe_and_unique(self):
        ics.CONFIG_FILE.write_text(json.dumps({"feeds": [
            {"id": "../escape", "url": "https://calendar.example/a"}
        ]}), encoding="utf-8")
        ok, reason = ics.available()
        self.assertFalse(ok)
        self.assertIn("calendar.json is invalid", reason)

    def test_fetch_error_never_echoes_secret_url(self):
        secret = "https://calendar.example/super-secret-token/basic.ics"
        with mock.patch.object(ics.urllib.request, "urlopen",
                               side_effect=RuntimeError(secret)):
            with self.assertRaises(RuntimeError) as caught:
                ics._fetch_url(secret)
        self.assertNotIn("super-secret-token", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
