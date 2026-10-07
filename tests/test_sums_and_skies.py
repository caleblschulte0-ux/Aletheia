"""Sums, calendar arithmetic, the sun and the moon - with no model.

Found 2026-10-07 in the sandbox with every model off: each of these said
"I can't think just now" while the answer was arithmetic.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import quick, weather


class TheSky(unittest.TestCase):
    def test_sunrise_and_sunset_are_computed_here(self):
        rise, set_ = weather.sun_times(dt.date(2026, 10, 7), lat=41.88, lon=-87.63)
        # Chicago on 7 October 2026: about 11:53 and 23:22 UTC.
        self.assertEqual((rise.hour, set_.hour), (11, 23))
        self.assertLess(abs(rise.minute - 53), 4)
        self.assertLess(abs(set_.minute - 22), 4)

    def test_the_sun_never_setting_is_said(self):
        self.assertEqual(weather.sun_times(dt.date(2026, 6, 21), lat=80.0, lon=0.0), (None, None))

    def test_asked_out_loud(self):
        with mock.patch.object(weather, "_where_on_earth", return_value=(41.88, -87.63, "Chicago")):
            self.assertTrue(quick.answer("what time is sunset").startswith("Sunset is at"))
            self.assertIn("tomorrow", quick.answer("when does the sun rise tomorrow"))

    def test_no_postcode_is_the_weather_sentence(self):
        with mock.patch.object(weather, "where_he_is", return_value=("", "where you live")), \
                mock.patch.object(weather.stateio, "read_json", side_effect=FileNotFoundError):
            self.assertIn("postcode", quick.answer("when is sunset"))

    def test_the_moon(self):
        self.assertTrue(quick.answer("what's the moon phase").startswith("It's a"))
        self.assertTrue(quick.answer("when is the next full moon").startswith("The next full moon"))


class Sums(unittest.TestCase):
    def test_money(self):
        self.assertEqual(quick.answer("what's 20 percent off 50"), "$40 - you save $10.")
        self.assertEqual(quick.answer("split 84 dollars 3 ways"), "$28 each.")
        self.assertEqual(quick.answer("split 100 three ways"), "$33.33 each.")

    def test_area(self):
        self.assertEqual(quick.answer("what's the square footage of 12 by 14"), "168 square feet.")


class CalendarArithmetic(unittest.TestCase):
    def test_a_weekday_with_a_year(self):
        self.assertEqual(quick.answer("what day was july 4 2020"), "July 4, 2020 was a Saturday.")

    def test_days_between(self):
        self.assertEqual(quick.answer("how many days between march 1 and april 15"), "45 days.")
        self.assertEqual(quick.answer("how many days between january 1 2024 and january 1 2025"), "366 days.")

    def test_left_in_the_year(self):
        self.assertIn("days left in", quick.answer("how many days left in the year"))
        self.assertIn("weeks", quick.answer("how many weeks are left in the year"))

    def test_the_old_date_questions_still_answer(self):
        self.assertEqual(quick.match("what day is it")[0], "date")
        self.assertEqual(quick.match("what day is it tomorrow")[0], "date")

    def test_time_difference(self):
        self.assertIn("London", quick.answer("what's the time difference with london"))


if __name__ == "__main__":
    unittest.main()
