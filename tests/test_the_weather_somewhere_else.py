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
