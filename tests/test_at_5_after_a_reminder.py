""""At 5" straight after a reminder (2026-10-12).

"Remind me to pick up dry cleaning tomorrow" sets it for 9 am. "At 5", "6 pm
instead" and "what time" went to a model; and once "at 5" was in the
conversation, the next "actually make it thursday" could not find the reminder
either. A bare time said straight after she set one is its new time, and read
back later it is a follow-up like "make it 5".
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import converse, intercom, policy, voice

SET = {"he_asked": "remind me to pick up dry cleaning tomorrow",
       "she_answered": "I'll remind you tomorrow at 9 am: pick up dry cleaning."}
FOUND = {"id": "r1", "kind": "once", "at": "2030-10-13T14:00:00+00:00", "command": {"text": "pick up dry cleaning"}}


def said(sentence, turns):
    with mock.patch.object(policy, "all_approvals", return_value=[]), \
            mock.patch.object(converse, "recent", side_effect=lambda limit=4: turns[-limit:]), \
            mock.patch.object(intercom, "_one_reminder", return_value=(FOUND, "")):
        return voice._interpret(sentence)


def hour(got):
    return dt.datetime.fromisoformat(got["command"]["at"]).hour


class ABareTime(unittest.TestCase):
    def test_moves_the_reminder_she_just_set(self):
        for sentence, h in (("at 5", 17), ("6 pm instead", 18), ("actually at 4pm", 16)):
            got = said(sentence, [SET])
            self.assertEqual(got["command"]["kind"], "remind_at", sentence)
            self.assertEqual(got["command"]["replaces"], "pick up dry cleaning", sentence)
            self.assertEqual(hour(got), h, sentence)

    def test_what_time_says_it(self):
        self.assertTrue(said("what time", [SET])["say"].endswith(": pick up dry cleaning."))

    def test_read_back_it_is_a_follow_up(self):
        turns = [SET, {"he_asked": "at 5", "she_answered": "I'll remind you tomorrow at 5 pm: pick up dry cleaning."}]
        got = said("6 pm instead", turns)
        self.assertEqual(got["command"]["text"], "pick up dry cleaning")
        self.assertEqual(hour(got), 18)

    def test_after_anything_else_it_is_not_a_reminder(self):
        turns = [{"he_asked": "what's the weather", "she_answered": "It's 54 degrees."}]
        got = said("at 5", turns)
        self.assertNotEqual(((got or {}).get("command") or {}).get("replaces"), "pick up dry cleaning")


if __name__ == "__main__":
    unittest.main()
