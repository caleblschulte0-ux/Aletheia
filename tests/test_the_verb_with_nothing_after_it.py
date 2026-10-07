"""A verb with nothing after it, the wind, the humidity and the battery.

    > set a reminder        -> "I could not plan that ... It's on my list"
    > how humid is it       -> "I can't think just now"
    > what's my battery level -> "I don't have anything remembered about 'battery level'"
    > text my wife I love you -> "I don't have a phone number for my wife"

An ask with no content was FILED for a model to plan later; the forecast
she had cached already carried the wind and the humidity; Windows reports
the battery for free; and his "my" came back to him as hers.
"""
import unittest
from unittest import mock

from aletheia import power, quick, speech, voice, weather


def say(said):
    out = voice.interpret(said)
    return out["command"], out["say"]


class TheOneQuestionItNeeds(unittest.TestCase):
    def test_a_bare_verb_asks_for_its_content(self):
        for said, word in (("set a reminder", "remind you about"), ("remind me", "remind you about"),
                           ("take a note", "note say"), ("can you add a task", "the task"),
                           ("set a timer", "how long"), ("set an alarm", "what time")):
            cmd, line = say(said)
            self.assertIsNone(cmd, said)
            self.assertIn(word, line.lower(), said)

    def test_the_full_sentence_still_does_the_thing(self):
        self.assertEqual(say("add a task to call the plumber")[0]["kind"], "task_new")
        self.assertIn(say("remind me at 3 to call mom")[0]["kind"], ("remind_at",))
        self.assertIsNotNone(say("note that the roof leaks")[0])

    def test_calls_and_texts_are_honest_about_where_they_live(self):
        for said in ("did anyone call", "any missed calls", "read my texts"):
            cmd, line = say(said)
            self.assertIsNone(cmd, said)
            self.assertIn("stay on your phone", line)


PERIODS = [{"name": "This Afternoon", "isDaytime": True, "windSpeed": "15 to 25 mph",
            "windDirection": "NW", "relativeHumidity": {"value": 82}},
           {"name": "Tonight", "isDaytime": False, "windSpeed": "5 mph",
            "windDirection": "S", "relativeHumidity": {"value": 60}},
           {"name": "Thursday", "isDaytime": True, "windSpeed": "10 mph",
            "windDirection": "E", "relativeHumidity": {"value": 25}}]


class TheForecastSheAlreadyHas(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(weather, "forecast", return_value={"periods": PERIODS})
        p.start()
        self.addCleanup(p.stop)

    def test_the_questions_reach_the_fast_lane(self):
        self.assertEqual(quick.match("how humid is it")[0], "humidity")
        self.assertEqual(quick.match("is it windy tomorrow"), ("wind", "tomorrow"))

    def test_wind(self):
        self.assertEqual(weather.detail("wind"),
                         "It's windy this afternoon: 15 to 25 mph from the northwest.")
        self.assertEqual(weather.detail("wind", "tonight"),
                         "Not much wind tonight: 5 mph from the south.")
        self.assertEqual(weather.detail("wind", "tomorrow"),
                         "Not much wind on Thursday: 10 mph from the east.")

    def test_humidity(self):
        self.assertEqual(weather.detail("humidity"),
                         "Humidity's around 82% this afternoon - that's muggy.")
        self.assertEqual(weather.detail("humidity", "tomorrow"),
                         "Humidity's around 25% on Thursday - pretty dry.")

    def test_a_missing_number_is_said_not_guessed(self):
        with mock.patch.object(weather, "forecast",
                               return_value={"periods": [{"name": "Today"}]}):
            self.assertIn("doesn't say", weather.detail("humidity"))
            self.assertIn("doesn't say", weather.detail("wind"))


class TheBattery(unittest.TestCase):
    def ask(self, state):
        with mock.patch.object(power, "status", return_value=state):
            return quick.answer("what's my battery level")

    def test_it_reads_what_windows_reports(self):
        self.assertEqual(self.ask({"known": True, "on_ac": False, "battery_percent": 64,
                                   "has_battery": True}),
                         "You're on battery at 64%.")
        self.assertIn("plugged in", self.ask({"known": True, "on_ac": True, "battery_percent": 90,
                                              "has_battery": True}))
        self.assertIn("no battery", self.ask({"known": True, "on_ac": True, "has_battery": False}))

    def test_a_machine_it_cannot_read_says_so(self):
        self.assertIn("can't read a battery", self.ask({"known": False}))


class HisMyIsYour(unittest.TestCase):
    def test_a_missing_number_names_his_relation_as_his(self):
        self.assertEqual(speech.as_she_says_it("my wife"), "your wife")


class PlansWithAPersonAreNotSubscriptions(unittest.TestCase):
    def test_cancel_lunch_is_not_a_cancellation_of_a_service(self):
        for said in ("cancel lunch with sam", "cancel my flight", "cancel dinner tonight",
                     "cancel the interview"):
            self.assertNotEqual(say(said)[0]["kind"], "subscription_cancel", said)

    def test_a_service_still_is(self):
        self.assertEqual(say("cancel my gym membership")[0],
                         {"kind": "subscription_cancel", "subscription": "gym"})
        self.assertEqual(say("cancel netflix")[0]["kind"], "subscription_cancel")


class WhatHeOwns(unittest.TestCase):
    def test_a_thing_he_owns_is_recalled_and_her_stores_are_not(self):
        self.assertEqual(quick.match("what car do I drive"), ("recall_owned", "car"))
        self.assertEqual(quick.match("what kind of phone do i have"), ("recall_owned", "phone"))
        self.assertNotEqual((quick.match("what reminders do I have") or ("",))[0], "recall_owned")
        self.assertEqual(quick.match("what notes do I have")[0], "notes_list")

    def test_his_notes_about_himself_are_what_she_knows_about_him(self):
        notes = [{"text": "my car is a 2014 civic"}, {"text": "the plumber comes tuesday"}]
        with mock.patch.object(quick, "_notes", return_value=notes):
            said = quick._about_him()
            self.assertIn("your car is a 2014 civic", said)
            self.assertNotIn("plumber", said)
            self.assertEqual(quick._recall("car"), "You told me: your car is a 2014 civic.")


if __name__ == "__main__":
    unittest.main()
