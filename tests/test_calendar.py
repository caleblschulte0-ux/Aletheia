import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import calendar


class CalendarCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(calendar, "CALENDAR_DIR", Path(self.tmp.name) / "calendar")
        patcher.start(); self.addCleanup(patcher.stop)


class TestCalendar(CalendarCase):
    def test_timezone_required(self):
        with self.assertRaises(ValueError):
            calendar.create("x", "meeting", "2026-08-26T10:00:00", "2026-08-26T11:00:00")

    def test_conflict_and_touching_boundary(self):
        event = calendar.create("x", "meeting", "2026-08-26T10:00:00-05:00", "2026-08-26T11:00:00-05:00")
        self.assertEqual(calendar.conflicts("2026-08-26T10:30:00-05:00", "2026-08-26T10:45:00-05:00", events=[event]), [event])
        self.assertEqual(calendar.conflicts("2026-08-26T11:00:00-05:00", "2026-08-26T11:30:00-05:00", events=[event]), [])

    def test_cancelled_event_does_not_block(self):
        event = calendar.create("x", "meeting", "2026-08-26T10:00:00-05:00", "2026-08-26T11:00:00-05:00")
        event["status"] = "CANCELLED"
        self.assertEqual(calendar.conflicts("2026-08-26T10:15:00-05:00", "2026-08-26T10:30:00-05:00", events=[event]), [])

    def test_buffer_blocks_adjacent_slot(self):
        event = calendar.create("x", "meeting", "2026-08-26T10:00:00-05:00", "2026-08-26T11:00:00-05:00")
        self.assertEqual(len(calendar.conflicts("2026-08-26T11:15:00-05:00", "2026-08-26T11:30:00-05:00", events=[event], buffer_after=30)), 1)

    def test_free_slots_obey_work_window(self):
        event = calendar.create("x", "meeting", "2026-08-26T09:30:00-05:00", "2026-08-26T10:00:00-05:00")
        slots = calendar.free_slots(dt.date(2026, 8, 26), duration_minutes=30, timezone="America/Chicago",
                                    work_start=dt.time(9), work_end=dt.time(11), events=[event], step_minutes=30)
        self.assertEqual(slots[0][0], "2026-08-26T09:00:00-05:00")
        self.assertEqual(slots[1][0], "2026-08-26T10:00:00-05:00")

    def test_find_slots_across_days_and_weekdays(self):
        slots = calendar.find_slots(dt.date(2026, 8, 29), dt.date(2026, 8, 31), duration_minutes=30,
                                    timezone="America/Chicago", work_start=dt.time(17, 30), work_end=dt.time(19),
                                    weekdays={0, 1, 2, 3, 4}, limit=2)
        self.assertTrue(all(slot[0].startswith("2026-08-31") for slot in slots))

    def test_update_and_cancel(self):
        calendar.create("x", "meeting", "2026-08-26T10:00:00-05:00", "2026-08-26T11:00:00-05:00")
        self.assertTrue(calendar.update("x", movable=True)["movable"])
        self.assertEqual(calendar.cancel("x")["status"], "CANCELLED")


if __name__ == "__main__":
    unittest.main()
