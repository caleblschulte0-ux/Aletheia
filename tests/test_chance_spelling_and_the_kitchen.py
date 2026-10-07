"""Small questions with exact answers, and the weekend's weather.

2026-10-07, every model off: "flip a coin", "roll a die", "pick a number
between 1 and 10", "spell necessary", "how many ounces in a cup", "do I
need an umbrella" and "what's the weather this weekend" all went to the
planner and came back "I could not plan that". None of them needs thinking.
"""
import unittest
from unittest import mock

from aletheia import quick, weather


def forecast(periods):
    return {"place": "Austin", "periods": periods}


WEEK = [
    {"name": "Today", "isDaytime": True, "temperature": 80, "shortForecast": "Sunny",
     "probabilityOfPrecipitation": {"value": 5}},
    {"name": "Tonight", "isDaytime": False, "temperature": 60, "shortForecast": "Clear",
     "probabilityOfPrecipitation": {"value": 0}},
    {"name": "Thursday", "isDaytime": True, "temperature": 78, "shortForecast": "Chance Rain Showers",
     "probabilityOfPrecipitation": {"value": 60}},
    {"name": "Thursday Night", "isDaytime": False, "temperature": 58, "shortForecast": "Cloudy"},
    {"name": "Friday", "isDaytime": True, "temperature": 75, "shortForecast": "Mostly Sunny"},
    {"name": "Friday Night", "isDaytime": False, "temperature": 55, "shortForecast": "Clear"},
    {"name": "Saturday", "isDaytime": True, "temperature": 82, "shortForecast": "Sunny"},
    {"name": "Saturday Night", "isDaytime": False, "temperature": 62, "shortForecast": "Clear"},
    {"name": "Sunday", "isDaytime": True, "temperature": 70, "shortForecast": "Thunderstorms",
     "probabilityOfPrecipitation": {"value": 80}},
]


class TheWeekendAndTheUmbrella(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(weather, "forecast", return_value=forecast(WEEK))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_weekend_is_two_days(self):
        said = quick.answer("what's the weather this weekend")
        self.assertIn("Saturday in Austin: Sunny, 82 degrees", said)
        self.assertIn("Sunday: Thunderstorms, 70 degrees", said)
        self.assertNotIn("Saturday Night", said)

    def test_an_umbrella_today_is_no_and_tomorrow_is_yes(self):
        self.assertTrue(quick.answer("do i need an umbrella").startswith("Doesn't look like it"))
        said = quick.answer("do i need an umbrella tomorrow")
        self.assertTrue(said.startswith("Looks like it"), said)
        self.assertIn("60% chance", said)

    def test_rain_this_weekend_names_the_wet_day(self):
        said = quick.answer("will it rain this weekend")
        self.assertIn("Sunday", said)
        self.assertNotIn("Saturday", said)

    def test_a_weekend_past_the_forecast_says_so(self):
        with mock.patch.object(weather, "forecast", return_value=forecast(WEEK[:3])):
            self.assertIn("doesn't reach the weekend", quick.answer("what's the weather this weekend"))


class ChanceIsChance(unittest.TestCase):
    def test_a_coin(self):
        self.assertIn(quick.answer("flip a coin"), ("Heads.", "Tails."))

    def test_dice(self):
        self.assertIn(quick.answer("roll a die"), [f"{n}." for n in range(1, 7)])
        self.assertIn("in all", quick.answer("roll two dice"))

    def test_a_number_stays_in_range(self):
        for _ in range(50):
            self.assertTrue(3 <= int(quick.answer("pick a number between 3 and 5").rstrip(".")) <= 5)


class SpellingAndTheKitchen(unittest.TestCase):
    def test_spelling_is_the_letters(self):
        self.assertEqual(quick.answer("how do you spell rhythm"), "Rhythm: R, H, Y, T, H, M.")

    def test_cups_and_spoons(self):
        self.assertEqual(quick.answer("how many ounces in a cup"), "8 ounces.")
        self.assertEqual(quick.answer("how many tablespoons in a cup"), "16 tablespoons.")
        self.assertEqual(quick.answer("what is half a cup in tablespoons"), "8 tablespoons.")
        self.assertEqual(quick.answer("how many ounces in a pound"), "16 ounces.")

    def test_other_how_many_questions_still_reach_their_store(self):
        self.assertNotEqual(quick.match("how many applications have you sent")[0], "volume")
        self.assertEqual(quick.match("how many miles is 10 km")[0], "math")


if __name__ == "__main__":
    unittest.main()
