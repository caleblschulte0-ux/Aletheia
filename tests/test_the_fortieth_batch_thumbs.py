"""Fortieth sandbox batch, 2026-10-05: the way his thumbs type, and a crash.

    > yep (with two approvals waiting)   IndexError in the Core's request
                                         handler; the connection dropped
    > whats my adress / remnd me at 3 to call mom / add a tsk to call the bank
                                         a model, the planner, the planner
    > whats on my calender tmrw          [4.0s] a model, GUESSING his day
    > nvm / k                            [8.0s] [8.5s] models
    > sounds good                        [9.0s] a model saying it isn't quite a yes
"""
import unittest
from unittest import mock

from aletheia import quick, voice

PENDING = [{"id": "ap-1", "state": "PENDING", "requested_at": "2026-10-05T02:00:00Z", "plan": {"summary": "Remind you at 3 pm to call mom"}},
           {"id": "ap-2", "state": "PENDING", "requested_at": "2026-10-05T02:01:00Z", "plan": {"summary": "Add a task to call the bank"}}]


class ABareYesWithTwoWaiting(unittest.TestCase):
    def test_it_offers_the_choice_instead_of_crashing(self):
        with mock.patch("aletheia.policy.all_approvals", return_value=PENDING), \
             mock.patch.object(voice, "approval_label", side_effect=lambda a: a["plan"]["summary"]):
            out = voice.interpret("yep")
        self.assertIsNone(out["command"])
        self.assertIn("Which one", out["say"])

    def test_sounds_good_says_what_a_yes_would_be(self):
        with mock.patch("aletheia.policy.all_approvals", return_value=PENDING), \
             mock.patch.object(voice, "approval_label", side_effect=lambda a: a["plan"]["summary"]):
            out = voice.interpret("sounds good")
        self.assertIsNone(out["command"])
        self.assertTrue(out["say"].startswith("If that's a yes to Remind you at 3 pm to call mom, say approve"), out["say"])
        with mock.patch("aletheia.policy.all_approvals", return_value=[]):
            self.assertEqual(voice.interpret("sounds good")["say"], "Okay.")


class HisThumbs(unittest.TestCase):
    def test_the_typos_reach_the_rules(self):
        self.assertEqual(voice.interpret("remnd me at 3 to call mom")["command"]["kind"], "remind_at")
        self.assertEqual(voice.interpret("add a tsk to call the bank")["command"]["kind"], "task_new")
        self.assertEqual(quick.match("whats on my calender tmrw"), ("agenda", "tomorrow"))
        self.assertIsNotNone(voice.interpret("whats my adress")["say"])
        from aletheia import policy
        with mock.patch.object(policy, "all_approvals", return_value=[]), \
                mock.patch.object(voice, "_last_ask_is_undoable", return_value=False):
            self.assertEqual(voice.interpret("nvm")["say"], "Okay - nothing was waiting.")
        self.assertFalse(voice.worth_answering("k"))


if __name__ == "__main__":
    unittest.main()
