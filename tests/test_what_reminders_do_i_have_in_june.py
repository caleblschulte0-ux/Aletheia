""""What reminders do I have in June" / "this month" went to a model
(2026-10-14) - only this week and next week had a window."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, quick


class MonthWindows(unittest.TestCase):
    def test_a_named_month_and_this_month(self):
        tz = localtime.operator_tz()
        today = dt.datetime.now(tz).replace(hour=9, minute=0, second=0, microsecond=0)
        june = dt.datetime(today.year + (today.month > 6), 6, 3, 9, tzinfo=tz)
        rows = [(today, "buy candy", "reminder"),
                (june, "renew the tags", "reminder")]
        with mock.patch.object(quick, "_coming", return_value=rows):
            said = quick.answer("what reminders do i have in june")
            self.assertTrue(said.startswith("1 reminder in June: renew the tags"), said)
            if today.month != 6:
                said = quick.answer("what reminders do i have this month")
                self.assertTrue(said.startswith("1 reminder this month: buy candy"), said)

    def test_none_says_which_month(self):
        with mock.patch.object(quick, "_coming", return_value=[]):
            self.assertEqual(quick.answer("what reminders do i have in march"), "No reminders in March.")


if __name__ == "__main__":
    unittest.main()
