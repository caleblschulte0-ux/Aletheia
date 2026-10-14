""""What do I have in November" / "what's on my calendar next month" went
to a model (2026-10-14) - only this month had a window."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import calendar, localtime, quick


class MonthAgenda(unittest.TestCase):
    def test_a_named_month_and_next_month(self):
        tz = localtime.operator_tz()
        now = dt.datetime.now(tz)
        month = now.month % 12 + 1
        start = dt.datetime(now.year + (month == 1), month, 3, 14, tzinfo=tz)
        name = start.strftime("%B")
        event = {"title": "dentist", "start": start.isoformat()}
        with mock.patch.object(calendar, "all_events", return_value=[event]), \
                mock.patch.object(quick, "_plans_told", return_value=""):
            said = quick.answer(f"what do i have in {name.lower()}")
            self.assertTrue(said.startswith(f"In {name}: dentist {start.strftime('%A')} the 3rd at 2 pm"), said)
            said = quick.answer("what's on my calendar next month")
            self.assertTrue(said.startswith("Next month: dentist"), said)
            said = quick.answer("what's happening in " + name.lower())
            self.assertTrue(said.startswith(f"In {name}:"), said)

    def test_empty_says_the_month(self):
        with mock.patch.object(calendar, "all_events", return_value=[]), \
                mock.patch.object(quick, "_plans_told", return_value=""), \
                mock.patch.object(quick, "_reminders_between", return_value=""):
            self.assertEqual(quick.answer("what do i have in march"), "Nothing on your calendar in March.")


if __name__ == "__main__":
    unittest.main()
