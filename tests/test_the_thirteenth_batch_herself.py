"""Thirteenth sandbox batch, 2026-10-05: questions about herself.

    > how often do you check mail     [7.6s] "I don't check on a schedule ...
                                      not watching it in the background" -
                                      a model, about a poll that runs on
                                      every beat of the Core
"""
import unittest
from unittest import mock

from aletheia import quick


class HowOftenSheReadsTheInbox(unittest.TestCase):
    def test_not_set_up_says_so_and_what_happens_once_it_is(self):
        with mock.patch("aletheia.mail.available", return_value=(False, "mail isn't set up yet")):
            said = quick.answer("how often do you check mail")
        self.assertTrue(said.startswith("I'm not reading your inbox yet: mail isn't set up yet."), said)
        self.assertIn("every beat", said)

    def test_set_up_says_the_cadence_from_the_core_and_the_lookback(self):
        with mock.patch("aletheia.mail.available", return_value=(True, "ok")), \
             mock.patch("aletheia.core.SYNC_INTERVAL_S", 60), \
             mock.patch("aletheia.mail.POLL_LOOKBACK_S", 48 * 3600):
            for q in ("are you watching my email", "do you check my inbox automatically"):
                said = quick.answer(q)
                self.assertTrue(said.startswith("Yes. I read your inbox on every beat, about every 60 seconds"), (q, said))
                self.assertIn("48 hours", said)


class TheReplyRateIsTheFunnel(unittest.TestCase):
    def test_nothing_sent_says_so(self):
        with mock.patch("aletheia.hunt_funnel.read", return_value=None):
            said = quick.answer("what's my reply rate")
        self.assertTrue(said.startswith("No applications have gone out through me"), said)

    def test_the_numbers_come_from_the_funnel(self):
        funnel = {"totals": {"found": 40, "filled": 30, "sent": 20, "replies": 3, "interviews": 1, "rejections": 2}}
        with mock.patch("aletheia.hunt_funnel.read", return_value=funnel):
            said = quick.answer("how many employers replied")
        self.assertEqual(said, "3 replies to 20 applications in the last 30 days - 15 percent heard back, "
                               "1 interview, 2 said no.")


class HowManyApplicationsThisWeek(unittest.TestCase):
    def test_the_verbless_question_is_the_window_count(self):
        with mock.patch("aletheia.quick._applied_in_window", return_value="4 sent this week.") as counted:
            self.assertEqual(quick.answer("how many applications this week"), "4 sent this week.")
            counted.assert_called_once_with("this week")


if __name__ == "__main__":
    unittest.main()
