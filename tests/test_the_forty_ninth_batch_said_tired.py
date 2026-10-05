"""Forty-ninth sandbox batch, 2026-10-05: said the way he talks when tired.

    > yo thea whats good                               [8.2s] a model
    > lemme know when the bread is done in like 20     [4.6s] a plan, an approval
    > gotta call the bank tmrw remind me               [4.5s] a plan, an approval
    > whats the wifi                                   [5.5s] a model
    > nah forget it                                    [11.0s] a model
    > ok cool                                          [8.5s] a model: "Cool. I'm here if you need anything."
    > how much is 20 bucks in euros                    [5.0s] a model
    > whats 10 percent tip on 46                       "That asks me to spend money, and I do not do that"
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import intents, policy, quick, voice


class SaidTired(unittest.TestCase):
    def test_reminders_said_sideways(self):
        d = voice.interpret("thea lemme know when the bread is done in like 20")
        self.assertEqual(d["command"]["kind"], "remind_at")
        self.assertEqual(d["command"]["text"], "the bread is done")
        left = dt.datetime.fromisoformat(d["command"]["at"]) - dt.datetime.now(dt.timezone.utc)
        self.assertTrue(dt.timedelta(minutes=19) < left <= dt.timedelta(minutes=20))
        d = voice.interpret("thea gotta call the bank tmrw remind me")
        self.assertEqual(d["command"]["text"], "call the bank")
        self.assertEqual(dt.datetime.fromisoformat(d["command"]["at"]).hour, 9)
        d = voice.interpret("thea remind me i need to call the bank tomorrow at 3")
        self.assertEqual(dt.datetime.fromisoformat(d["command"]["at"]).hour, 15)
        d = voice.interpret("thea don't let me forget to take the bins out tonight")
        self.assertEqual(d["command"]["text"], "take the bins out")
        self.assertEqual(dt.datetime.fromisoformat(d["command"]["at"]).hour, 21)
        self.assertEqual(voice.interpret("thea ping me in 10")["command"]["text"], "time's up")

    def test_a_nod_and_a_no_ask_for_nothing(self):
        with mock.patch.object(policy, "all_approvals", return_value=[]), \
                mock.patch.object(voice, "_last_ask_is_undoable", return_value=False):
            self.assertEqual(voice.interpret("thea nah forget it")["say"], "Okay - nothing was waiting.")
            for said in ("ok cool", "gotcha", "okay", "cool cool", "makes sense", "ah ok"):
                self.assertEqual(voice.interpret(f"thea {said}"), {"command": None, "say": ""}, said)

    def test_the_wake_word_after_a_yo(self):
        self.assertEqual(voice._as_said_to_her("yo thea whats good"), "whats good")
        self.assertEqual(quick.match("whats good")[0], "greeting")
        self.assertEqual(quick.match("what'd i miss")[0], "today")

    def test_money_questions_are_questions(self):
        self.assertFalse(intents._asks_to_spend("whats 10 percent tip on 46"))
        self.assertTrue(intents._asks_to_spend("tip the driver 5 bucks"))
        self.assertEqual(quick.answer("whats 10 percent tip on 46"), "$4.60 tip at 10 percent - $50.60 all in.")
        self.assertEqual(quick.answer("how much should i tip on 46"), "$9.20 tip at 20 percent - $55.20 all in.")
        self.assertEqual(quick.answer("how much is 20 percent of 50"), "10.")
        self.assertIn("exchange rate", quick.answer("how much is 20 bucks in euros"))
        self.assertEqual(quick.match("whats the wifi")[0], "recall")


if __name__ == "__main__":
    unittest.main()
