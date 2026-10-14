""""My passport expires June 3 2028", then "how many days until my passport
expires" counted to June 3 of NEXT year; and "how long until I need to water
the plants" came back "I can't think just now" with the reminder set
(2026-10-14, every model off)."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, quick


class TheYearHeSaid(unittest.TestCase):
    def test_counts_to_that_year(self):
        today = dt.datetime.now(localtime.operator_tz()).date()
        year = today.year + 2
        with mock.patch.object(quick, "_notes", return_value=[{"text": f"my passport expires june 3 {year}"}]):
            said = quick.answer("how many days until my passport expires")
        days = (dt.date(year, 6, 3) - today).days
        self.assertTrue(said.startswith(f"{days} days, "), said)
        self.assertIn(str(year), said)

    def test_a_year_gone_is_not_counted_to(self):
        today = dt.datetime.now(localtime.operator_tz()).date()
        with mock.patch.object(quick, "_notes", return_value=[{"text": f"my passport expires june 3 {today.year - 1}"}]):
            self.assertIsNone(quick._date_in_notes("my passport expires", today))


class HowLongUntilINeedTo(unittest.TestCase):
    def test_is_when_the_reminder_comes_next(self):
        self.assertEqual(quick._direct("how long until i need to water the plants"), "when do i water the plants next")
        self.assertEqual(quick._direct("how many days until i have to water the plants again"),
                         "when do i water the plants next")


if __name__ == "__main__":
    unittest.main()
