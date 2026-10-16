"""Two reminder phrasings found 2026-10-16 in the sandbox with every model off.

"Set a reminder for every weekday at 7am to stretch" asked "When should I
remind you about every weekday at 7am to stretch?", and "set a reminder for
tomorrow at 7am to stretch" went to a model. And "remind me in 2 hours"
(a timer, on purpose) followed by "to check the laundry" went to a model
instead of saying what the timer was for.
"""
import unittest
from unittest import mock

from aletheia import converse, intercom, voice


class WhenFirst(unittest.TestCase):
    def test_set_a_reminder_for_when_to_what_is_remind_me(self):
        for said, same in (("set a reminder for every weekday at 7am to stretch", "remind me every weekday at 7am to stretch"),
                           ("set a reminder every weekday at 7am to stretch", "remind me every weekday at 7am to stretch"),
                           ("set a reminder for tomorrow at 7am to stretch", "remind me tomorrow at 7am to stretch"),
                           ("add a reminder for monday at 9 to call the bank", "remind me monday at 9 to call the bank")):
            with self.subTest(said=said):
                got = voice._interpret(said)["command"]
                self.assertNotEqual(got.get("kind"), "intent")
                self.assertEqual(got, voice._interpret(same)["command"])

    def test_without_a_what_it_is_not_rewritten(self):
        self.assertEqual(voice._interpret("set a reminder for tomorrow")["command"]["kind"], "intent")


class WhatTheTimerWasFor(unittest.TestCase):
    TURN = [{"he_asked": "remind me in 2 hours", "she_answered": "Timer set for 2 hours - it goes off today at 5:18 am."}]
    TIMER = {"kind": "once", "at": "2026-10-16T10:18:00+00:00", "text": "your 2-hour timer is up"}

    def test_to_what_names_it_at_the_same_time(self):
        with mock.patch.object(converse, "recent", return_value=self.TURN), \
                mock.patch.object(voice, "_recent_reminder_ask", return_value={"text": "your 2-hour timer is up"}), \
                mock.patch.object(intercom, "_one_reminder", return_value=(self.TIMER, "")):
            cmd = voice._interpret("to check the laundry")["command"]
        self.assertEqual(cmd, {"kind": "remind_at", "at": self.TIMER["at"], "text": "check the laundry",
                               "replaces": "your 2-hour timer is up"})

    def test_after_a_plain_timer_it_is_not_taken(self):
        turn = [{"he_asked": "set a timer for 2 hours", "she_answered": "Timer set for 2 hours - it goes off today at 5:18 am."}]
        with mock.patch.object(converse, "recent", return_value=turn):
            self.assertIsNone(voice._naming_the_timer("check the laundry"))


class ABillDueOnTheNth(unittest.TestCase):
    """"My car insurance is due on the 15th", said on the 7th, was never
    due again once the 15th passed (2026-10-16: a test failed on the 16th)."""

    def test_it_comes_round_again_next_month(self):
        import datetime as dt
        from aletheia import quick
        said, ts = "my car insurance is due on the 15th", "2026-10-07T22:00:00-05:00"
        self.assertEqual(quick._relative_in_note(said, ts, dt.date(2026, 10, 16)), dt.date(2026, 11, 15))
        self.assertEqual(quick._relative_in_note(said, ts, dt.date(2026, 10, 9)), dt.date(2026, 10, 15))

    def test_a_one_off_on_the_nth_still_passes(self):
        import datetime as dt
        from aletheia import quick
        self.assertIsNone(quick._relative_in_note("the party is on the 15th", "2026-10-07T22:00:00-05:00",
                                                  dt.date(2026, 10, 16)))
