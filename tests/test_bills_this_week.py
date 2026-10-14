""""What bills do I have this week" went to a model, and "what bills are due
this month" said "No subscriptions are being tracked" with his car insurance
noted as due on the 15th (2026-10-14)."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, quick, voice


class TheBillsDay(unittest.TestCase):
    TODAY = dt.date(2026, 10, 14)

    def test_monthly_and_dated(self):
        self.assertEqual(quick._bill_day("my car insurance is due on the 15th every month", self.TODAY), dt.date(2026, 10, 15))
        self.assertEqual(quick._bill_day("the water bill is due on the 3rd", self.TODAY), dt.date(2026, 11, 3))
        self.assertEqual(quick._bill_day("my registration is due November 30", self.TODAY), dt.date(2026, 11, 30))
        self.assertEqual(quick._bill_day("rent is due on the 31st", dt.date(2026, 11, 5)), dt.date(2026, 12, 31))
        self.assertIsNone(quick._bill_day("my phone bill is 85 dollars a month", self.TODAY))


class AWindow(unittest.TestCase):
    def _rows(self, days_ahead):
        day = dt.datetime.now(localtime.operator_tz()).date() + dt.timedelta(days=days_ahead)
        return [{"text": f"my car insurance is due {day.strftime('%B')} {day.day}"}]

    def test_this_week_lists_it(self):
        today = dt.datetime.now(localtime.operator_tz()).date()
        ahead = 6 - today.weekday()                 # Sunday of this week
        with mock.patch.object(quick, "_notes", return_value=self._rows(ahead)), \
                mock.patch.object(quick, "_coming", return_value=[]):
            said = quick.answer("what bills do i have this week")
        self.assertTrue(said.startswith("Due this week: your car insurance on "), said)

    def test_next_week_says_nothing_and_the_next(self):
        today = dt.datetime.now(localtime.operator_tz()).date()
        ahead = 6 - today.weekday() + 14            # two weeks out
        with mock.patch.object(quick, "_notes", return_value=self._rows(ahead)), \
                mock.patch.object(quick, "_coming", return_value=[]):
            said = quick.answer("any bills next week")
        self.assertTrue(said.startswith("Nothing due next week that you've told me about. The next is your car insurance,"), said)

    def test_the_subscriptions_door_reads_his_bills_first(self):
        with mock.patch.object(quick, "_notes", return_value=self._rows(0)), \
                mock.patch.object(quick, "_coming", return_value=[]):
            out = voice._interpret("what bills are due this month")
        self.assertIsNone(out["command"])
        self.assertIn("your car insurance on", out["say"])
        with mock.patch.object(quick, "_notes", return_value=[]), mock.patch.object(quick, "_coming", return_value=[]):
            self.assertEqual(voice._interpret("what subscriptions do i have")["command"], {"kind": "subscriptions"})


if __name__ == "__main__":
    unittest.main()
