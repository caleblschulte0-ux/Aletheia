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


if __name__ == "__main__":
    unittest.main()
