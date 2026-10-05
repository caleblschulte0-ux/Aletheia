"""Forty-eighth sandbox batch, 2026-10-05: timers, the heating, and small talk.

    > add 5 minutes to the timer        [5.5s] a plan, an approval
    > pause the timer                   [4.6s] a plan, an approval
    > set a second timer for 3 minutes  [4.5s] a plan, an approval
    > how many timers do I have         [6.0s] a model
    > is the heating on                 [6.5s] a model reading "python -m aletheia.apply room http://<hub>:8123 <token>" out loud
    > I'm bored                         [9.5s] a model offering trivia and twenty questions, which do not exist
    > thank you so much / you're the best   [7.5s] a model, re-reading the approval queue
    > how are you feeling               [7.5s] a model
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import cannot, quick, scheduler, voice


def _timer(text, at):
    return {"id": "t-" + "".join(c for c in text if c.isalnum())[:12], "version": 1, "kind": "once", "at": at, "enabled": True,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "command": {"kind": "notify_operator", "text": text}}


class Timers(unittest.TestCase):
    def setUp(self):
        self.at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10)
        rows = [_timer("your 10 minute timer is up", self.at.isoformat())]
        p = mock.patch.object(scheduler, "all_schedules", return_value=rows)
        p.start(); self.addCleanup(p.stop)

    def test_minutes_added_to_the_timer(self):
        d = voice.interpret("thea add 5 minutes to the timer")
        self.assertEqual(d["command"]["kind"], "remind_at")
        self.assertEqual(d["command"]["replaces"], "your 10 minute timer is up")
        self.assertEqual(dt.datetime.fromisoformat(d["command"]["at"]), self.at + dt.timedelta(minutes=5))
        d = voice.interpret("thea give me five more minutes")
        self.assertEqual(dt.datetime.fromisoformat(d["command"]["at"]), self.at + dt.timedelta(minutes=5))
        d = voice.interpret("thea take 2 minutes off the timer")
        self.assertEqual(dt.datetime.fromisoformat(d["command"]["at"]), self.at - dt.timedelta(minutes=2))

    def test_pause_and_a_second_timer(self):
        self.assertEqual(voice.interpret("thea pause the timer")["command"], {"kind": "reminder_off", "which": "timer"})
        d = voice.interpret("thea set a second timer for 3 minutes")
        self.assertEqual(d["command"]["kind"], "remind_at")
        self.assertIn("3-minute timer", d["command"]["text"])
        self.assertEqual(voice.interpret("thea start another timer for 2 minutes")["command"]["kind"], "remind_at")

    def test_how_many_timers(self):
        self.assertEqual(quick.match("how many timers do I have")[0], "timers")
        said = quick.answer("how many timers do I have")
        self.assertTrue(said.startswith("1 timer: 10 minute timer with "), said)
        with mock.patch.object(scheduler, "all_schedules", return_value=[]):
            self.assertEqual(quick.answer("any timers running"), "No timers running.")


class SmallTalk(unittest.TestCase):
    def test_the_heating_is_a_room_question(self):
        said = cannot.answer("is the heating on")
        self.assertIsNotNone(said)
        self.assertNotIn("<", said or "")
        self.assertIsNotNone(cannot.answer("what's the thermostat set to"))

    def test_thanks_and_praise_ask_for_nothing(self):
        for said in ("thank you so much", "thanks a bunch", "much appreciated", "thanks again thea"):
            self.assertEqual(voice.interpret(f"thea {said}")["say"], "Any time.", said)
        for said in ("you're the best", "nice work", "good job", "that was perfect"):
            self.assertEqual(voice.interpret(f"thea {said}")["say"], "Thanks - glad it helped.", said)

    def test_feeling_and_bored(self):
        self.assertEqual(quick.match("how are you feeling")[0], "status")
        self.assertIn(quick.match("are you ok")[0], ("status", "halted"))
        self.assertEqual(quick.match("I'm bored")[0], "bored")
        said = quick.answer("I'm bored")
        self.assertTrue(said.startswith("I don't have games."), said)
        self.assertNotIn("trivia", said)


if __name__ == "__main__":
    unittest.main()
