"""Holidays that move, and facts about the calendar, are arithmetic."""
import datetime as dt
import unittest

from aletheia import quick


class HolidaysThatMove(unittest.TestCase):
    def test_known_dates(self):
        today = dt.date(2026, 10, 7)
        self.assertEqual(quick._named_date("labor day", today), dt.date(2027, 9, 6))
        self.assertEqual(quick._named_date("memorial day", today), dt.date(2027, 5, 31))
        self.assertEqual(quick._named_date("mother's day", today), dt.date(2027, 5, 9))
        self.assertEqual(quick._named_date("easter", today), dt.date(2027, 3, 28))
        self.assertEqual(quick._named_date("columbus day", today), dt.date(2026, 10, 12))
        self.assertEqual(quick._named_date("easter", dt.date(2026, 1, 1)), dt.date(2026, 4, 5))

    def test_when_is_labor_day_needs_no_model(self):
        self.assertIn(quick.match("when is labor day")[0], ("until", "until_day"))


class CalendarFacts(unittest.TestCase):
    def test_each_is_answered(self):
        for said in ("what's the date tomorrow", "what was yesterday's date", "what week is it",
                     "how many days in february", "is it a leap year"):
            self.assertEqual(quick.match(said)[0], "calendar_fact", said)
            self.assertTrue(quick.answer(said), said)

    def test_february_this_year(self):
        self.assertRegex(quick.answer("how many days in february"), r"^February has 2[89] days")


if __name__ == "__main__":
    unittest.main()
