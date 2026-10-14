""""I spent 30 eating out" (2026-10-14: a model answered "journaled"), "how
much on groceries" after the week's total, "how much do I have left for
eating out", and "how much is left on the timer" (all three to a model).
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import policy, quick, voice


def said(sentence):
    with mock.patch.object(policy, "all_approvals", return_value=[]):
        return voice.interpret(f"thea {sentence}")


NOW = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class EatingOut(unittest.TestCase):
    def test_it_is_kept_as_spending_on_it(self):
        self.assertEqual(said("i spent 30 eating out")["command"], {"kind": "note", "text": "I spent 30 on eating out"})

    def test_left_for_eating_out_reads_the_budget(self):
        rows = [{"text": "my budget for eating out is 200 a month", "ts": NOW},
                {"text": "I spent 30 on eating out", "ts": NOW}]
        with mock.patch.object(quick, "_notes", return_value=rows):
            got = quick.answer("how much do i have left for eating out")
        self.assertIn("$170 left of your $200 budget", got)


class HowMuchOnGroceries(unittest.TestCase):
    def test_the_same_window_one_thing(self):
        rows = [{"text": "i spent 45 dollars on groceries", "ts": NOW}, {"text": "i spent 20 on gas", "ts": NOW}]
        with mock.patch.object(quick, "_notes", return_value=rows), \
                mock.patch.object(voice, "_her_last_answer",
                                  return_value="$65 this week, from what you've told me: $45 on groceries and $20 on gas."):
            got = said("how much on groceries")
        self.assertEqual(got["say"], "$45 on groceries this week, from what you've told me.")


class LeftOnTheTimer(unittest.TestCase):
    def test_how_much_is_left_on_the_timer_is_the_timer(self):
        self.assertTrue(any(name == "timer_left" and p.match("how much is left on the timer") for name, p in quick.PATTERNS))


if __name__ == "__main__":
    unittest.main()
