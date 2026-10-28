""""Remind me to call mom in 2 hours", then "actually make that 3 hours"
(2026-10-28) went to the planner. It is the same reminder at the new wait,
and the old one is replaced."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import voice


def after(said):
    return mock.patch("aletheia.converse.recent",
                      return_value=[{"he_asked": said, "she_answered": "I'll remind you today at 8 pm: call mom."}])


class MakeThatThreeHours(unittest.TestCase):
    def test_the_same_reminder_at_the_new_wait(self):
        with after("thea remind me to call mom in 2 hours"):
            cmd = voice.interpret("actually make that 3 hours")["command"]
        self.assertEqual((cmd["kind"], cmd["text"], cmd["replaces"]), ("remind_at", "call mom", "call mom"))
        wait = dt.datetime.fromisoformat(cmd["at"]) - dt.datetime.now(dt.timezone.utc)
        self.assertAlmostEqual(wait.total_seconds(), 3 * 3600, delta=120)

    def test_the_wait_said_first(self):
        with after("remind me in 20 minutes to check the oven"):
            cmd = voice.interpret("make it 30 minutes")["command"]
        self.assertEqual(cmd["text"], "check the oven")
        wait = dt.datetime.fromisoformat(cmd["at"]) - dt.datetime.now(dt.timezone.utc)
        self.assertAlmostEqual(wait.total_seconds(), 30 * 60, delta=120)

    def test_without_a_wait_before_it_nothing_moves(self):
        with after("what time is it"):
            got = voice.interpret("make it 3 hours")
        self.assertNotEqual((got.get("command") or {}).get("kind"), "remind_at")


if __name__ == "__main__":
    unittest.main()
