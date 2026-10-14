""""How many timers do I have" said "2 reminders: your 5-minute timer -
going off ..." (2026-10-14). Asked about timers, it says timers."""
import unittest
from unittest import mock

from aletheia import voice


class HowManyTimers(unittest.TestCase):
    def test_timers_and_their_count(self):
        two = "5 minutes left on your 5-minute timer and 10 minutes left on your 10-minute timer"
        with mock.patch.object(voice, "_timer_left", return_value=two):
            self.assertEqual(voice._interpret("how many timers do i have")["say"], f"2 timers: {two}")
            self.assertEqual(voice._interpret("list my timers")["say"], two)
        with mock.patch.object(voice, "_timer_left", return_value="No timer is running."):
            self.assertEqual(voice._interpret("how many timers do i have")["say"], "No timer is running.")

    def test_reminders_are_still_reminders(self):
        self.assertEqual(voice._interpret("how many reminders do i have")["command"]["kind"], "reminders")


if __name__ == "__main__":
    unittest.main()
