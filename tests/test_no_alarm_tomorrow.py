""""No alarm tomorrow" (2026-10-12).

"Turn off my alarm for tomorrow" turned a weekday alarm off for good;
"turn off tomorrow's alarm" and "no alarm tomorrow" went to the planner;
skipping a one-off alarm told him to say "cancel the wake up reminder";
and the skip read "Skipped tomorrow at 7 am: wake up."
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import act, intercom, localtime, policy, scheduler, speech, voice


def said(sentence):
    with mock.patch.object(policy, "all_approvals", return_value=[]):
        return voice.interpret(f"thea {sentence}")["command"]


class TheDayIsOnce(unittest.TestCase):
    def test_phrasings(self):
        for sentence, day in (("turn off my alarm for tomorrow", "tomorrow"), ("turn off tomorrow's alarm", "tomorrow"),
                              ("no alarm tomorrow", "tomorrow"), ("cancel my alarm for today", "today"),
                              ("i don't need an alarm tomorrow", "tomorrow")):
            self.assertEqual(said(sentence), {"kind": "reminder_off", "which": "wake up", "once": day}, sentence)

    def test_without_a_day_it_is_still_the_whole_alarm(self):
        self.assertEqual(said("cancel my alarm"), {"kind": "reminder_off", "which": "wake up"})
        self.assertEqual(said("cancel my 6:30 alarm"), {"kind": "reminder_off", "which": "wake up 6:30"})


class SkippingAOneOff(unittest.TestCase):
    def test_tomorrows_one_off_is_turned_off(self):
        tz = localtime.operator_tz()
        at = dt.datetime.combine(dt.datetime.now(tz).date() + dt.timedelta(days=1), dt.time(6, 30), tzinfo=tz)
        found = {"id": "r1", "kind": "once", "at": at.isoformat(), "command": {"text": "wake up"}}
        with mock.patch.object(scheduler, "set_enabled") as off:
            got = intercom._skip_once(found, "tomorrow")
        off.assert_called_once_with("r1", False)
        self.assertTrue(got.startswith("Alarm off: tomorrow at 6:30"), got)

    def test_a_one_off_on_another_day_is_not_touched(self):
        tz = localtime.operator_tz()
        at = dt.datetime.combine(dt.datetime.now(tz).date() + dt.timedelta(days=3), dt.time(6, 30), tzinfo=tz)
        found = {"id": "r1", "kind": "once", "at": at.isoformat(), "command": {"text": "wake up"}}
        with mock.patch.object(scheduler, "set_enabled") as off, self.assertRaises(act.Refused):
            intercom._skip_once(found, "tomorrow")
        off.assert_not_called()


class TheReceipt(unittest.TestCase):
    def test_an_alarm_skipped_says_alarm(self):
        got = speech.spoken_receipt("reminder_off", "reminder r1 skipped — wake up won't go off tomorrow at 7 am; next Wednesday at 7 am")
        self.assertEqual(got, "No alarm tomorrow at 7 am. It's back Wednesday at 7 am.")


if __name__ == "__main__":
    unittest.main()
