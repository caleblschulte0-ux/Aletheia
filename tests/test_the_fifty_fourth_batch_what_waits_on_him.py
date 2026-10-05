"""Fifty-fourth sandbox batch, 2026-10-05: what waits on him, asked about.

    > what would the first one do exactly   [6.1s] a model, describing a capability lookup
    > why do you need my approval for that  [20.5s] a model
    > deny the rest                         [9.0s] a model
    > clear them (the notifications)        [4.0s] a plan, an approval
    > when's the next brief                 [5.5s] a model
    > what's your daily allowance           [4.5s] a model: "I don't have the number"
"""
import unittest
from unittest import mock

from aletheia import autonomy, needs_you, policy, quick, voice


class WhatWaitsOnHim(unittest.TestCase):
    def test_the_first_one_and_why(self):
        with mock.patch.object(needs_you, "items", return_value=[]):
            self.assertEqual(quick.answer("what would the first one do exactly"),
                             "Nothing is waiting on you right now, so there's no first one.")
            self.assertIsNone(quick.answer("what does that do"))
            self.assertTrue(quick.answer("why do you need my approval for that").startswith("Nothing is waiting on your approval right now."))
        rows = [{"id": "a1", "kind": "approval", "what": "the email to Dana", "why": "it reaches somebody else", "if_ignored": "it stays unsent"},
                {"id": "a2", "kind": "approval", "what": "the text to Sam", "why": "", "if_ignored": ""}]
        with mock.patch.object(needs_you, "items", return_value=rows):
            self.assertEqual(quick.answer("what would the first one do exactly"),
                             "the email to Dana. it reaches somebody else. If you leave it: it stays unsent.")
            self.assertEqual(quick.answer("what exactly would the second one do"), "the text to Sam.")
            self.assertIn("The first thing waiting is the email to Dana.", quick.answer("why are you asking me"))

    def test_deny_the_rest_and_clear_them(self):
        self.assertEqual(voice.interpret("thea deny the rest")["command"]["id"], "all")
        self.assertEqual(voice.interpret("thea no to the others")["command"]["id"], "all")
        for said in ("clear them", "mark them all read", "dismiss my notifications", "clear my notifications"):
            self.assertEqual(voice.interpret(f"thea {said}")["command"], {"kind": "notify_clear"}, said)
        self.assertIn("isn't built", voice.interpret("thea mark the dana email as read")["say"])

    def test_the_brief_and_the_allowance(self):
        said = quick.answer("when's the next brief")
        self.assertTrue(said.startswith("The morning brief is posted by GitHub at "), said)
        self.assertIn("the next one is", said)
        with mock.patch.object(autonomy, "counts", return_value={"day": 7, "day_limit": 120, "session": 0, "session_limit": 24}):
            self.assertEqual(quick.answer("what's your daily allowance"),
                             "120 reversible things a day on my own; 7 used today, 113 left. Past that, anything else becomes a handoff to you.")


if __name__ == "__main__":
    unittest.main()
