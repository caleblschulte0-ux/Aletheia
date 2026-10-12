""""Remind me to call grandma Sunday at noon", "what time is that" (2026-10-12).

Asked straight after she confirmed a reminder, "what time is that", "when is
it again" and "what day is that" went to a model. "That" is only the reminder
when her last answer set one; after anything else it is left alone.
"""
import unittest
from unittest import mock

from aletheia import converse, policy, voice

JUST = {"id": "r1", "kind": "once", "at": "2026-10-18T18:00:00+00:00", "command": {"text": "call grandma"}}


def said(sentence, last_answer):
    turns = [{"he_asked": "remind me to call grandma on sunday at noon", "she_answered": last_answer}]
    with mock.patch.object(policy, "all_approvals", return_value=[]), \
            mock.patch.object(converse, "recent", return_value=turns), \
            mock.patch.object(voice, "_the_reminder_just_set", return_value=JUST):
        return voice._interpret(sentence)


class WhatTimeIsThat(unittest.TestCase):
    def test_after_a_reminder_it_is_the_reminder(self):
        for sentence in ("what time is that", "when is it again", "what day is that", "when's that",
                         "what time did i say"):
            got = said(sentence, "I'll remind you Sunday at 12 pm: call grandma.")
            self.assertIsNone(got["command"], sentence)
            self.assertTrue(got["say"].startswith("That's "), sentence)
            self.assertTrue(got["say"].endswith(": call grandma."), sentence)

    def test_after_anything_else_it_is_not(self):
        got = said("what time is that", "It's 54 degrees and cloudy.")
        self.assertNotIn("grandma", str((got or {}).get("say") or ""), got)


if __name__ == "__main__":
    unittest.main()
