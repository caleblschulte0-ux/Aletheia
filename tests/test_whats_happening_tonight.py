"""Found 2026-10-16 in the sandbox with every model off: "what's happening
tonight" went to a model; "what's on for this afternoon" said "Nothing on
your calendar this afternoon" with a reminder at 2 pm; and "what's due
before sunday", "by monday", "in the next 3 days" all went to a model.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import calendar, localtime, quick, tasks


def _patterns(said):
    tidy = quick._tidy(said)
    return [name for name, pattern in quick.PATTERNS if pattern.search(tidy)]


class ThePartOfTheDay(unittest.TestCase):
    def test_happening_and_going_on_reach_it(self):
        for said in ("what's happening tonight", "what's going on this afternoon", "anything happening tonight"):
            with self.subTest(said=said):
                self.assertIn("agenda_part", _patterns(said))

    def test_a_reminder_in_that_part_is_named(self):
        tz = localtime.operator_tz()
        now = dt.datetime.now(tz)
        day = now.date() + dt.timedelta(days=1)
        rows = [(dt.datetime.combine(day, dt.time(14, 0), tzinfo=tz), "grab lunch", "reminder"),
                (dt.datetime.combine(day, dt.time(21, 0), tzinfo=tz), "lock the car", "reminder")]
        with mock.patch.object(quick, "_coming", return_value=rows), \
                mock.patch.object(calendar, "all_events", return_value=[]):
            said = quick.answer("what's on tomorrow afternoon")
        self.assertIn("Nothing on your calendar tomorrow afternoon", said)
        self.assertIn("1 reminder: 2 pm", said)
        self.assertIn("grab lunch", said)
        self.assertNotIn("lock the car", said)


class DueByADay(unittest.TestCase):
    def test_the_window_reaches_the_task_list(self):
        for said in ("what's due before sunday", "what's due by monday", "what's due in the next 3 days",
                     "what is due until friday"):
            with self.subTest(said=said):
                self.assertIn("due", _patterns(said))

    def test_by_includes_the_day_and_before_does_not(self):
        tz = localtime.operator_tz()
        now = dt.datetime.now(dt.timezone.utc)
        from aletheia import voice
        monday = dt.date.fromisoformat(voice._spoken_day("monday"))
        at = dt.datetime.combine(monday, dt.time(17, 0), tzinfo=tz)
        rows = [{"task": {"description": "call the bank"}, "when": at, "overdue": False}]
        with mock.patch.object(tasks, "due", return_value=rows), mock.patch.object(tasks, "is_his", return_value=True):
            self.assertIn("call the bank, Monday", quick._due("by monday", now=now))
            self.assertIn("due by Monday", quick._due("by monday", now=now))
        with mock.patch.object(tasks, "due", return_value=[]), mock.patch.object(tasks, "is_his", return_value=True):
            self.assertEqual(quick._due("before monday", now=now), "Nothing due before Monday.")
