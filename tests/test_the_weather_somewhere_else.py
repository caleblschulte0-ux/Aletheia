""""What's the weather like in Chicago" went to the planner (2026-10-07).
A town by name is one more free lookup in front of the same forecast, and
the answer always says which town it read."""
import unittest
from unittest import mock

from aletheia import quick, weather

GEO = {"results": [
    {"name": "Springfield", "latitude": 39.8, "longitude": -89.6, "country_code": "US",
     "admin1": "Illinois", "population": 116565},
    {"name": "Springfield", "latitude": 37.2, "longitude": -93.3, "country_code": "US",
     "admin1": "Missouri", "population": 169176},
]}
PERIODS = [{"name": "Today", "temperature": 61, "shortForecast": "Sunny", "isDaytime": True},
           {"name": "Tonight", "temperature": 44, "shortForecast": "Clear", "isDaytime": False},
           {"name": "Thursday", "temperature": 65, "shortForecast": "Partly Cloudy", "isDaytime": True}]


class ATownByName(unittest.TestCase):
    def setUp(self):
        self.asked = []

        def fake_get(url):
            self.asked.append(url)
            return GEO
        patches = [mock.patch.object(weather, "_get", side_effect=fake_get),
                   mock.patch.object(weather, "_periods", return_value=PERIODS)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_the_biggest_town_of_that_name_and_it_says_which(self):
        said = quick.answer("what's the weather like in springfield")
        self.assertIn("Springfield, Missouri", said)
        self.assertIn("Sunny, 61 degrees", said)

    def test_a_named_state_wins(self):
        self.assertIn("Springfield, Illinois", quick.answer("weather in springfield il"))
        self.assertIn("Springfield, Illinois", quick.answer("how's the weather in springfield, illinois"))
        self.assertTrue(self.asked[-1].split("name=")[1].startswith("springfield&"))

    def test_tomorrow_is_the_first_period_after_tonight(self):
        self.assertIn("Thursday", quick.answer("what's the weather in springfield tomorrow"))

    def test_nowhere_says_so(self):
        with mock.patch.object(weather, "_get", return_value={"results": []}):
            said = quick.answer("what's the weather in atlantis")
        self.assertIn("couldn't find a place called Atlantis", said)

    def test_his_own_forecast_is_untouched(self):
        self.assertEqual(quick.match("what's the weather")[0], "weather")
        self.assertEqual(quick.match("what's the weather like tomorrow")[0], "weather")


class WhenIsHisThing(unittest.TestCase):
    def setUp(self):
        import datetime as dt
        now = dt.datetime.now(dt.timezone.utc)
        self.rows = [(now + dt.timedelta(hours=30), "Dentist", "calendar"),
                     (now + dt.timedelta(hours=26), "call the recruiter back", "reminder"),
                     (now + dt.timedelta(days=3), "Meeting with Dana", "calendar")]
        p = mock.patch.object(quick, "_coming", return_value=self.rows)
        p.start()
        self.addCleanup(p.stop)

    def test_the_named_thing_not_the_generic_noun(self):
        said = quick.answer("what time is my dentist appointment")
        self.assertTrue(said.startswith("Dentist is "), said)

    def test_with_whom(self):
        self.assertTrue(quick.answer("when is my meeting with dana").startswith("Meeting with Dana is "))

    def test_a_reminder_counts(self):
        self.assertIn("You have a reminder", quick.answer("when is my call with the recruiter"))

    def test_nothing_by_that_name_is_left_to_think_about(self):
        # It may be in his mail, which a model can read: quick only ever
        # removes latency, never an answer.
        self.assertIsNone(quick.answer("when is my flight"))

    def test_the_older_readers_keep_their_sentences(self):
        self.assertEqual(quick.match("when is my next meeting")[0], "next_meeting")
        self.assertEqual(quick.match("when is my interview")[0], "interview_when")
        self.assertIsNone(quick.match("when are my meetings today"))


class HisRemindersOnADay(unittest.TestCase):
    def test_only_that_days_reminders(self):
        import datetime as dt
        from aletheia import localtime
        tz = localtime.operator_tz()
        tomorrow = (dt.datetime.now(tz) + dt.timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        rows = [(tomorrow, "take my pills", "reminder"), (tomorrow + dt.timedelta(days=1), "gym", "reminder"),
                (tomorrow, "Dentist", "calendar")]
        with mock.patch.object(quick, "_coming", return_value=rows):
            said = quick.answer("what are my reminders for tomorrow")
        self.assertEqual(said, "1 reminder tomorrow: 9 am, take your pills.")
