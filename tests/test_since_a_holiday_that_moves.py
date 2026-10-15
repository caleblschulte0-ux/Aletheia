""""How many days since Labor Day" said "since Sunday 6 September 2026" -
next year's date taken back a year - and "when was Labor Day" went to a
model (2026-10-15, every model off)."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import quick


class SinceAHolidayThatMoves(unittest.TestCase):
    def at(self, day):
        class Fixed(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return dt.datetime(day.year, day.month, day.day, 12, tzinfo=tz)
        return mock.patch.object(dt, "datetime", Fixed)

    def test_the_one_that_was_this_year(self):
        with self.at(dt.date(2026, 10, 15)):
            self.assertEqual(quick._days_since("labor day"), "38 days, since Monday 7 September 2026.")
            self.assertEqual(quick._days_since("memorial day"), "143 days, since Monday 25 May 2026.")
            self.assertEqual(quick._days_since("easter"), "193 days, since Sunday 5 April 2026.")
            self.assertEqual(quick._days_since("thanksgiving"), "322 days, since Thursday 27 November 2025.")

    def test_a_fixed_date_and_a_weekday(self):
        with self.at(dt.date(2026, 10, 15)):
            self.assertEqual(quick._days_since("christmas"), "294 days, since Thursday 25 December 2025.")
            self.assertEqual(quick._days_since("monday"), "3 days, since Monday 12 October 2026.")

    def test_when_was_a_holiday_is_how_long_since(self):
        self.assertEqual(quick._direct("when was labor day"), "how many days since labor day")
        self.assertEqual(quick._direct("when was the last thanksgiving"), "how many days since thanksgiving")
        self.assertNotEqual(quick._direct("when was my last haircut"), "how many days since my last haircut")


if __name__ == "__main__":
    unittest.main()
