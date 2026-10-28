"""Reminders for the weekend.

2026-10-28, talking to her with the models off:

    > remind me to call mom on sunday at noon
    > what reminders do I have this weekend     (to a model)
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, quick


class ThisWeekend(unittest.TestCase):
    def coming(self, *days_ahead):
        tz = localtime.operator_tz()
        today = dt.datetime.now(tz).replace(hour=12, minute=0, second=0, microsecond=0)
        return [(today + dt.timedelta(days=d), f"thing {d}", "reminder") for d in days_ahead]

    def saturday_offset(self):
        wd = dt.datetime.now(localtime.operator_tz()).weekday()
        return 5 - wd if wd < 6 else -1

    def test_the_weekend_reminder_is_named(self):
        sat = self.saturday_offset()
        sun = sat + 1
        with mock.patch.object(quick, "_coming", return_value=self.coming(sun)):
            said = quick.answer("what reminders do i have this weekend")
        self.assertTrue(said.startswith("1 reminder this weekend: thing"), said)
        with mock.patch.object(quick, "_coming", return_value=self.coming(sun)):
            self.assertTrue(quick.answer("any reminders this weekend").startswith("1 reminder"))

    def test_next_weekend_is_the_one_after(self):
        sun = self.saturday_offset() + 1
        with mock.patch.object(quick, "_coming", return_value=self.coming(sun)):
            self.assertEqual(quick.answer("do i have any reminders next weekend"), "No reminders next weekend.")
        with mock.patch.object(quick, "_coming", return_value=self.coming(sun + 7)):
            self.assertTrue(quick.answer("do i have any reminders next weekend").startswith("1 reminder next weekend"))

    def test_a_weekday_one_is_not_the_weekend(self):
        sat = self.saturday_offset()
        weekday = sat + 2  # the Monday after
        with mock.patch.object(quick, "_coming", return_value=self.coming(weekday)):
            self.assertEqual(quick.answer("what reminders do i have this weekend"), "No reminders this weekend.")


if __name__ == "__main__":
    unittest.main()
