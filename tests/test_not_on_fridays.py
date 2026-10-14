""""Weekdays at 7", then "not on Fridays" / "skip Mondays" (2026-10-14: to a
model); "make it 8" after "make it weekdays" (to a model, because the
follow-up turn read alone is nothing); and "make it the 1st" after a monthly
reminder (to a model).
"""
import unittest
from unittest import mock

from aletheia import intercom, policy, voice


def said(sentence):
    with mock.patch.object(policy, "all_approvals", return_value=[]):
        return voice.interpret(f"thea {sentence}")["command"]


WEEKDAYS = {"kind": "weekly", "time": "07:00", "weekdays": [0, 1, 2, 3, 4], "command": {"text": "check email"}}


def recent(kind, *_a):
    return {"kind": "remind_weekly", "days": ["weekday"], "time": "07:00", "text": "check email"} if kind == "remind_weekly" else {}


class NotOnFridays(unittest.TestCase):
    def test_a_day_comes_off_the_repeat(self):
        with mock.patch.object(voice, "_recent_ask_of", side_effect=recent), \
                mock.patch.object(intercom, "_one_reminder", return_value=(WEEKDAYS, "")):
            got = said("not on fridays")
            both = said("except mondays and fridays")
            skips = said("skip mondays")
            once = said("skip friday")
        self.assertEqual((got["kind"], got["days"], got["replaces"]),
                         ("remind_weekly", ["monday", "tuesday", "wednesday", "thursday"], "check email"))
        self.assertEqual(both["days"], ["tuesday", "wednesday", "thursday"])
        self.assertEqual(skips["days"], ["tuesday", "wednesday", "thursday", "friday"])
        self.assertNotEqual(once.get("days"), ["monday", "tuesday", "wednesday", "thursday"])


class TheRepeatSheConfirmed(unittest.TestCase):
    def test_her_confirmation_rebuilds_the_reminder(self):
        turn = {"he_asked": "make it weekdays", "she_answered": "Weekdays at 7 am I'll remind you: check your email."}
        with mock.patch.object(policy, "all_approvals", return_value=[]):
            got = voice._the_repeat_she_confirmed(turn, "remind_weekly")
        self.assertEqual((got["kind"], got["time"], got["text"]), ("remind_weekly", "07:00", "check my email"))
        self.assertEqual(voice._the_repeat_she_confirmed({"she_answered": "Noted."}, "remind_weekly"), {})
        self.assertEqual(voice._the_repeat_she_confirmed(turn, "remind_at"), {})


class MakeItTheFirst(unittest.TestCase):
    def test_the_monthly_one_moves_to_that_day(self):
        monthly = {"kind": "remind_monthly", "day": 15, "time": "09:00", "text": "pay rent"}
        with mock.patch.object(voice, "_recent_ask_of", side_effect=lambda kind, *_a: monthly if kind == "remind_monthly" else {}):
            got = said("make it the 1st")
        self.assertEqual(got, {"kind": "remind_monthly", "day": 1, "time": "09:00", "text": "pay rent", "replaces": "pay rent"})


if __name__ == "__main__":
    unittest.main()
