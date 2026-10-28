""""I have a meeting with Sarah at 2 tomorrow", then "push it back an hour"
went to the planner (2026-10-28), though "push it to 3" moved it. "It" after a
hold is the hold, moved by that much and kept the same length."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import voice


class PushingTheHoldHeJustMade(unittest.TestCase):
    def setUp(self):
        self.start = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).replace(
            hour=19, minute=0, second=0, microsecond=0)
        self.hold = {"kind": "calendar_hold", "title": "meeting with Sarah",
                     "start": self.start.isoformat(), "minutes": 45}

    def said(self, sentence, hold=True):
        last = self.hold if hold else {}
        with mock.patch.object(voice, "_recent_ask_of", lambda kind, needs, turns=4: last if kind == "calendar_hold" else {}), \
                mock.patch.object(voice, "_hold_as_it_is_now", lambda found: found):
            return voice._interpret(sentence)

    def test_it_moves_by_what_he_said(self):
        for sentence, minutes in (("push it back an hour", 60), ("move it an hour later", 60),
                                  ("bump it back an hour", 60), ("move it up an hour", -60),
                                  ("push it back 30 minutes", 30)):
            command = self.said(sentence)["command"]
            self.assertEqual(command["kind"], "calendar_hold", sentence)
            self.assertEqual(dt.datetime.fromisoformat(command["start"]), self.start + dt.timedelta(minutes=minutes), sentence)
            self.assertEqual(command["replaces"], self.hold["start"])
            self.assertEqual(command["minutes"], 45)
            self.assertEqual(command["title"], "meeting with Sarah")

    def test_with_no_hold_just_made_it_is_not_a_hold(self):
        got = self.said("push it back an hour", hold=False)
        self.assertNotEqual((got.get("command") or {}).get("kind"), "calendar_hold")

    def test_into_the_past_is_refused(self):
        self.hold["start"] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=20)).isoformat()
        got = self.said("move it up an hour")
        self.assertIsNone(got["command"])
        self.assertIn("past", got["say"])


if __name__ == "__main__":
    unittest.main()
