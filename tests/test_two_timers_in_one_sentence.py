"""'Set a 3 minute tea timer and a 10 minute pasta timer' (2026-10-28) went
to the planner whole: the second timer has no verb of its own, so neither
half read alone. The second one borrows the first one's verb."""
import unittest

from aletheia import voice


class TwoTimersInOneSentence(unittest.TestCase):
    def test_the_second_timer_borrows_the_verb(self):
        self.assertEqual(voice.two_asks("set a 3 minute tea timer and a 10 minute pasta timer"),
                         ["set a 3 minute tea timer", "set a 10 minute pasta timer"])
        self.assertEqual(voice.two_asks("start a 25 minute focus timer and a 5 minute break timer"),
                         ["start a 25 minute focus timer", "start a 5 minute break timer"])

    def test_another_is_another_timer(self):
        self.assertEqual(voice.two_asks("set a timer for 3 minutes and another for 10 minutes"),
                         ["set a timer for 3 minutes", "set a timer for 10 minutes"])
        self.assertEqual(voice.two_asks("set a timer for 5 minutes and another one for 10 minutes"),
                         ["set a timer for 5 minutes", "set a timer for 10 minutes"])

    def test_each_half_is_a_real_timer(self):
        for half in voice.two_asks("set a 3 minute tea timer and a 10 minute pasta timer"):
            kind = (voice.interpret(half).get("command") or {}).get("kind")
            self.assertNotIn(kind, (None, "intent"), half)

    def test_one_timer_is_not_split(self):
        self.assertIsNone(voice.two_asks("set a 10 minute pasta timer"))


if __name__ == "__main__":
    unittest.main()
