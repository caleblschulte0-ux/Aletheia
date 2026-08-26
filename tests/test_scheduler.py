import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import scheduler

UTC = dt.timezone.utc


class SchedulerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for attr, path in (("SCHEDULE_DIR", root / "defs"), ("RECEIPT_DIR", root / "receipts")):
            patcher = mock.patch.object(scheduler, attr, path)
            patcher.start(); self.addCleanup(patcher.stop)


class TestScheduler(SchedulerCase):
    def test_once_claims_exactly_once(self):
        spec = scheduler.create("once", {"kind": "note"}, kind="once", at="2026-08-26T15:00:00+00:00")
        now = dt.datetime(2026, 8, 26, 16, tzinfo=UTC)
        self.assertIsNotNone(scheduler.claim_due(spec, now=now))
        self.assertIsNone(scheduler.claim_due(spec, now=now))

    def test_interval_uses_occurrence_receipts(self):
        spec = scheduler.create("pulse", {"kind": "status"}, kind="interval", every_minutes=60,
                                anchor="2026-08-26T12:00:00+00:00")
        first = scheduler.claim_due(spec, now=dt.datetime(2026, 8, 26, 13, 30, tzinfo=UTC))
        second = scheduler.claim_due(spec, now=dt.datetime(2026, 8, 26, 14, 1, tzinfo=UTC))
        self.assertEqual(first["occurrence"], "2026-08-26T13:00:00+00:00")
        self.assertEqual(second["occurrence"], "2026-08-26T14:00:00+00:00")

    def test_daily_respects_timezone(self):
        spec = scheduler.create("morning", {"kind": "brief"}, kind="daily",
                                timezone="America/Chicago", time="08:00")
        occurrence = scheduler.occurrence_at_or_before(spec, dt.datetime(2026, 8, 26, 14, tzinfo=UTC))
        self.assertEqual(occurrence, dt.datetime(2026, 8, 26, 13, tzinfo=UTC))

    def test_weekly_only_selected_days(self):
        spec = scheduler.create("monday", {"kind": "brief"}, kind="weekly",
                                timezone="UTC", time="09:00", weekdays=[0])
        now = dt.datetime(2026, 8, 26, 12, tzinfo=UTC)  # Wednesday
        occurrence = scheduler.occurrence_at_or_before(spec, now)
        self.assertEqual(occurrence.weekday(), 0)

    def test_disabled_schedule_never_due(self):
        scheduler.create("x", {"kind": "note"}, kind="once", at="2026-08-26T12:00:00+00:00")
        spec = scheduler.set_enabled("x", False)
        self.assertIsNone(scheduler.claim_due(spec, now=dt.datetime(2026, 8, 27, tzinfo=UTC)))

    def test_next_occurrence(self):
        spec = scheduler.create("x", {"kind": "note"}, kind="interval", every_minutes=30,
                                anchor="2026-08-26T12:00:00+00:00")
        nxt = scheduler.next_occurrence(spec, dt.datetime(2026, 8, 26, 12, 31, tzinfo=UTC))
        self.assertEqual(nxt, dt.datetime(2026, 8, 26, 13, 0, tzinfo=UTC))

    def test_invalid_specs_fail_closed(self):
        with self.assertRaises(ValueError):
            scheduler.create("bad", {"kind": "x"}, kind="weekly", timezone="UTC", time="09:00")


if __name__ == "__main__":
    unittest.main()
