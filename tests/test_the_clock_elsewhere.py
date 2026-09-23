"""Night sweep 2026-09-23, every frontier off: "what time is it in Tokyo",
"what's the date next Friday" and "how long until my next meeting" each
waited on a model for arithmetic she can do."""
import datetime as dt
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from aletheia import quick


class TheClockElsewhere(unittest.TestCase):
    def test_a_city_a_country_and_a_zone_word_are_answered_with_the_gap(self):
        with mock.patch("aletheia.localtime.operator_tz", return_value=ZoneInfo("America/Chicago")):
            said = quick.answer("what time is it in Tokyo")
            self.assertRegex(said, r"^\d{1,2}:\d{2} [ap]m on \w+ in Tokyo - 14 hours ahead of you\.$")
            self.assertIn("in London", quick.answer("what's the time in London"))
            self.assertIn("ahead of you", quick.answer("time in India"))
            self.assertIn("in Sioux Falls - the same as yours", quick.answer("what time is it in sioux falls"))
            self.assertIn("UTC", quick.answer("what time is it in UTC"))
        self.assertIsNone(quick.answer("what time is it in Narnia"), "an unknown place is a model's")

    def test_the_date_of_a_named_day(self):
        with mock.patch("aletheia.localtime.operator_tz", return_value=ZoneInfo("America/Chicago")):
            said = quick.answer("what's the date next Friday")
            today = dt.datetime.now(ZoneInfo("America/Chicago")).date()
            ahead = (4 - today.weekday()) % 7 or 7
            friday = today + dt.timedelta(days=ahead)
            self.assertTrue(said.startswith(f"Friday the {friday.day}"), said)
            self.assertIn("of December", quick.answer("what date is Christmas"))
            self.assertIsNone(quick.answer("what's the date of the meeting"), "not a named day")

    def test_how_long_until_my_next_meeting_is_the_calendar_shape(self):
        """The "until" shape claims it first; it hands a meeting to the calendar."""
        with mock.patch("aletheia.presence._next_appointment", return_value=None):
            self.assertEqual(quick.answer("how long until my next meeting"), "Nothing on your calendar coming up.")


if __name__ == "__main__":
    unittest.main()
