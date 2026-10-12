""""Remind me in 20 minutes to check the oven", "how long until that", and
"remind me to take out the trash every Tuesday night", "when is that"
(2026-10-12: both went to a model).

Straight after she confirmed a one-off reminder, "how long until that" is the
time left on it. After a repeating one, "when is that" is the when her own
confirmation already said. After anything else, neither is the reminder.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import converse, policy, voice


def said(sentence, last_answer, at=None):
    turns = [{"he_asked": "remind me to check the oven", "she_answered": last_answer}]
    just = {"id": "r1", "kind": "once", "at": at, "command": {"text": "check the oven"}} if at else None
    with mock.patch.object(policy, "all_approvals", return_value=[]), \
            mock.patch.object(converse, "recent", return_value=turns), \
            mock.patch.object(voice, "_the_reminder_just_set", return_value=just):
        return voice._interpret(sentence)


def soon(minutes):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutes, seconds=20)).isoformat()


class HowLongUntilThat(unittest.TestCase):
    def test_after_a_reminder_it_is_the_time_left(self):
        for sentence in ("how long until that", "how long till it goes off", "how much longer until that",
                         "how long is left", "how many minutes until it"):
            got = said(sentence, "I'll remind you today at 6:49 pm: check the oven.", at=soon(20))
            self.assertIsNone(got["command"], sentence)
            self.assertTrue(got["say"].startswith("In 20 minutes, "), got["say"])
            self.assertTrue(got["say"].endswith(": check the oven."), got["say"])

    def test_hours_and_minutes(self):
        got = said("how long until that", "I'll remind you tomorrow at 9 am: check the oven.", at=soon(14 * 60 + 30))
        self.assertTrue(got["say"].startswith("In 14 hours and 30 minutes, "), got["say"])

    def test_a_new_time_after_it_still_moves_the_reminder(self):
        turns = [{"he_asked": "remind me tomorrow at 9 to call mom", "she_answered": "I'll remind you tomorrow at 9 am: call mom."},
                 {"he_asked": "how long until that", "she_answered": "In 14 hours, tomorrow at 9 am: call mom."}]
        with mock.patch.object(converse, "recent", side_effect=lambda limit=1: turns[-limit:]):
            self.assertTrue(voice._she_just_named_a_reminder())

    def test_after_anything_else_it_is_not(self):
        got = said("how long until that", "It's 54 degrees and cloudy.", at=soon(20))
        self.assertNotIn("oven", str((got or {}).get("say") or ""), got)


class WhenIsThatRepeating(unittest.TestCase):
    def test_it_says_back_her_own_when(self):
        for sentence in ("when is that", "what time is it", "when's that again"):
            got = said(sentence, "Every Tuesday at 9 pm I'll remind you: take out the trash.")
            self.assertEqual({"command": None, "say": "That's every Tuesday at 9 pm: take out the trash."}, got)

    def test_not_after_an_answer_that_set_nothing(self):
        got = said("when is that", "Every Tuesday is trash day, you told me.")
        self.assertNotIn("I'll remind you", str((got or {}).get("say") or ""))


if __name__ == "__main__":
    unittest.main()
