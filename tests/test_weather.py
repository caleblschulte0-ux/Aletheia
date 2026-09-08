"""The most ordinary question anybody asks, and it reached nothing.

"What's the weather" was a 25-80 second planner round trip ending in an
apology. Registered NOT_BUILT this morning with a ticket saying it was
"a source decision rather than a build" — and it was.

NO NETWORK IN THIS FILE. CLAUDE.md is explicit: where a verifier makes a
real attempt the TESTS must not pay for it, "or the suite becomes a
live-network test that answers differently on a train". Every call is
stubbed; the live proof is in the registry entry, where it belongs.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import quick, weather

FORECAST = {
    "properties": {"periods": [
        {"name": "Today", "temperature": 83, "temperatureUnit": "F",
         "shortForecast": "Partly Sunny"},
        {"name": "Tonight", "temperature": 59, "temperatureUnit": "F",
         "shortForecast": "Mostly Clear"},
        {"name": "Wednesday", "temperature": 77, "temperatureUnit": "F",
         "shortForecast": "Sunny"},
    ]}
}
POINT = {"places": [{"place name": "Hartford", "state abbreviation": "SD",
                     "latitude": "43.6155", "longitude": "-96.9501"}]}
GRID = {"properties": {"forecast": "https://api.weather.gov/gridpoints/FSD/91,68/forecast"}}


class WeatherCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ,
                              {"ALETHEIA_PRIVATE_STATE": self.tmp.name})
        env.start()
        self.addCleanup(env.stop)
        self.calls = []

        def fake_get(url):
            self.calls.append(url)
            if "zippopotam" in url:
                return POINT
            if "/points/" in url:
                return GRID
            return FORECAST

        p = mock.patch.object(weather, "_get", side_effect=fake_get)
        p.start()
        self.addCleanup(p.stop)
        here = mock.patch.object(weather, "where_he_is",
                                 return_value=("57033", "Hartford, SD"))
        here.start()
        self.addCleanup(here.stop)


class ItAnswersTheQuestionAskedCase(WeatherCase):
    def test_now_tonight_and_a_named_day(self):
        self.assertIn("Partly Sunny", weather.spoken())
        self.assertIn("Mostly Clear", weather.spoken("tonight"))
        self.assertIn("Sunny, 77", weather.spoken("wednesday"))

    def test_tomorrow_is_tomorrow_and_not_today(self):
        """The service says Today / Tonight / Wednesday, so "tomorrow"
        matched nothing and the first draft answered with TODAY's
        forecast under today's label — a different question than the one
        he asked, answered confidently."""
        said = weather.spoken("tomorrow")
        self.assertIn("Wednesday", said)
        self.assertIn("77", said)
        self.assertNotIn("83", said)

    def test_tomorrow_with_nothing_but_today_says_so(self):
        only_today = {"properties": {"periods": [FORECAST["properties"]["periods"][0]]}}
        with mock.patch.object(weather, "_get",
                               side_effect=lambda u: POINT if "zippo" in u
                               else GRID if "/points/" in u else only_today):
            said = weather.spoken("tomorrow")
        self.assertIn("only have today", said)

    def test_it_names_the_place_so_a_wrong_one_is_visible(self):
        """There are at least four Hartfords."""
        self.assertIn("Hartford, SD", weather.spoken())


class ItAsksTheNetworkOnceCase(WeatherCase):
    def test_a_second_question_costs_no_calls(self):
        weather.spoken()
        first = len(self.calls)
        weather.spoken("tonight")
        weather.spoken("tomorrow")
        self.assertEqual(len(self.calls), first, self.calls)


class ItSaysWhatWentWrongCase(WeatherCase):
    def test_no_postcode_on_file_asks_for_one(self):
        with mock.patch.object(weather, "where_he_is", return_value=("", "")):
            said = weather.spoken()
        self.assertIn("don't know where you are", said)

    def test_an_unreachable_service_says_so_and_never_raises(self):
        with mock.patch.object(weather, "_get", side_effect=OSError("no net")):
            said = weather.spoken()
        self.assertTrue(said)
        self.assertIn("couldn't", said.lower())

    def test_a_postcode_that_resolves_to_nothing_names_the_fix(self):
        with mock.patch.object(weather, "_get",
                               side_effect=lambda u: {"places": []}):
            said = weather.spoken()
        self.assertIn("57033", said)
        self.assertIn("tell me where you live", said)

    def test_it_never_raises_whatever_happens(self):
        with mock.patch.object(weather, "forecast",
                               side_effect=RuntimeError("boom")):
            self.assertTrue(weather.spoken())


class ThroughTheFastLaneCase(WeatherCase):
    def test_the_ordinary_phrasings_reach_it_without_a_model(self):
        quick.warm()
        for said in ("what's the weather", "whats the weather tomorrow",
                     "weather tonight", "how is the weather",
                     "is it going to rain tomorrow"):
            with self.subTest(said=said):
                self.assertTrue(quick.answer(said), said)

    def test_a_broken_weather_module_falls_through_rather_than_lying(self):
        with mock.patch.object(weather, "spoken", side_effect=RuntimeError("x")):
            self.assertIsNone(quick.answer("what's the weather"))


if __name__ == "__main__":
    unittest.main()
