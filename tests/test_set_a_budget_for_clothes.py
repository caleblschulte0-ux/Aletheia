""""Set a budget of 200 for groceries" and "my clothes budget is 300" went to
the planner, "how much is left in my clothes budget" answered about his
whole budget, and with no budget at all the question went to a model that
had nothing either (2026-10-24).
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import quick, voice


def _notes(*texts):
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    return mock.patch.object(quick, "_notes", return_value=[{"text": t, "ts": ts} for t in texts])


class SetABudget(unittest.TestCase):
    def _cmd(self, sentence):
        return voice.interpret(sentence).get("command") or {}

    def test_every_way_of_setting_one_is_the_same_note(self):
        for said, kept in (("set a budget of 200 for groceries", "my grocery budget is 200 a month"),
                           ("set my weekly gas budget to 60", "my gas budget is 60 a week"),
                           ("set a monthly budget of 2000", "my budget is 2000 a month"),
                           ("set a budget of 300 for clothes", "my clothes budget is 300 a month"),
                           ("my clothes budget is 300 a month", "my clothes budget is 300 a month")):
            with self.subTest(said=said):
                self.assertEqual(self._cmd(said), {"kind": "note", "text": kept})

    def test_how_he_feels_is_not_a_budget(self):
        self.assertNotEqual(self._cmd("my budget is tight").get("kind"), "note")


class ReadTheRightBudget(unittest.TestCase):
    def test_the_category_asked_about(self):
        with _notes("my budget is 2000 a month", "my clothes budget is 300 a month", "i spent 50 on clothes"):
            self.assertTrue(quick._budget("how much is left in my clothes budget").startswith("$250 left of your $300 clothes budget"))
            self.assertTrue(quick._budget("how much is left in my budget").startswith("$1,950 left of your $2,000 budget"))
            self.assertEqual(quick._budget("how much is left in my shoe budget"), "You haven't told me a shoe budget.")

    def test_none_given_is_said(self):
        with _notes():
            self.assertTrue(quick._budget("how much is left in my grocery budget").startswith("You haven't given me a grocery budget yet."))
            self.assertTrue(quick.answer("am i over budget on gas").startswith("You haven't given me a gas budget yet."))
            self.assertIsNone(quick.answer("how much is left on my gift card"))


if __name__ == "__main__":
    unittest.main()
