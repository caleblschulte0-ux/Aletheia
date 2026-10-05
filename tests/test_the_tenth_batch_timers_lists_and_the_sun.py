"""Tenth sandbox batch, 2026-10-05, frontier on:

    > set a 20 minute timer        [4.0s] Here's what I'd do: Set a 20 minute timer
                                   ... Say approve         (a timer FOR 20 minutes is 0.0 s)
    > cancel the timer             [5.5s] Here's what I'd do: Cancel the 20 minute
                                   timer. Say approve
    > clear the shopping list      [6.0s] a model, for what the handler does for "everything"
    > what time is sunset          [6.0s] "... in the Chicago area it's around 6:15 PM"
                                   - a city she was never told and a number made up
"""
import unittest
from unittest import mock

from aletheia import quick, voice


class ATimerHoweverHeSaysIt(unittest.TestCase):
    def test_the_amount_before_the_word(self):
        for said in ("set a 20 minute timer", "start a twenty-minute timer", "give me a 5 min timer"):
            cmd = voice.interpret(said)["command"]
            self.assertEqual(cmd["kind"], "remind_at", said)
            self.assertIn("timer is up", cmd["text"])

    def test_cancel_the_timer_is_the_reminder_off(self):
        for said in ("cancel the timer", "stop my timer", "turn off the alarm"):
            cmd = voice.interpret(said)["command"]
            self.assertEqual(cmd["kind"], "reminder_off", said)


class ClearTheListIsEverything(unittest.TestCase):
    def test_phrasings(self):
        for said in ("clear the shopping list", "empty my grocery list", "take everything off the list",
                     "clear out the whole shopping list"):
            self.assertEqual(voice.interpret(said)["command"], {"kind": "shopping_off", "item": "everything"}, said)


class SunsetIsNotGuessed(unittest.TestCase):
    def test_no_city_no_number(self):
        with mock.patch("aletheia.profile.known", return_value={}):
            said = quick.answer("what time is sunset")
        self.assertIn("I don't have a sunset lookup", said)
        self.assertIn("tell me your city", said)
        self.assertNotIn("PM", said)

    def test_with_a_city_she_names_the_one_sentence(self):
        with mock.patch("aletheia.profile.known", return_value={"city": "Springfield"}):
            said = quick.answer("when does the sun set tonight")
        self.assertIn("sunset in Springfield", said)
        self.assertNotIn("tell me your city", said)


if __name__ == "__main__":
    unittest.main()
