""""Skip it this week" after a repeating reminder.

"Remind me every Friday to take out the trash", then "skip it this week"
(2026-10-12, every model off) was queued for a model. Skipping one time was
already a door ("skip the trash reminder tomorrow"); "it" is the reminder he
just set. And "this week" said twice skipped next week as well.
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import act, intercom, localtime, scheduler, voice


def turns(*pairs):
    return [{"he_asked": said, "she_answered": answered} for said, answered in pairs]


class SkipItThisWeek(unittest.TestCase):
    def test_it_is_the_reminder_he_just_set(self):
        recent = turns(("remind me every friday to take out the trash",
                        "Every Friday at 9 am I'll remind you: take out the trash."))
        with mock.patch("aletheia.converse.recent", return_value=recent):
            got = voice.interpret("thea skip it this week")["command"]
        self.assertEqual(got, {"kind": "reminder_off", "which": "take out the trash", "once": "this week"})

    def test_tomorrow_after_a_daily_one(self):
        recent = turns(("remind me every day at 8 to take my pills", "Every day at 8 am I'll remind you: take your pills."))
        with mock.patch("aletheia.converse.recent", return_value=recent):
            got = voice.interpret("thea skip it tomorrow")["command"]
        self.assertEqual(got["kind"], "reminder_off")
        self.assertEqual(got["once"], "tomorrow")

    def test_it_never_looks_back_forever(self):
        # Each earlier "skip it" is re-read while looking back; it must not look back again.
        recent = turns(("skip it this week", "Skipped."), ("skip it", "Skipped."), ("skip it this week", ""))
        with mock.patch("aletheia.converse.recent", return_value=recent):
            got = voice.interpret("thea skip it this week")
        self.assertNotEqual((got.get("command") or {}).get("kind"), "reminder_off")

    def test_with_nothing_repeating_before_it_nothing_is_skipped(self):
        with mock.patch("aletheia.converse.recent", return_value=turns(("what time is it", "9 am."))):
            got = voice.interpret("thea skip it this week")
        self.assertNotEqual((got.get("command") or {}).get("kind"), "reminder_off")


class ThisWeekIsOnce(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for attr in ("SCHEDULE_DIR", "RECEIPT_DIR"):
            patcher = mock.patch.object(scheduler, attr, Path(tmp.name) / attr)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _daily(self):
        scheduler.create("r-daily", {"kind": "notify_operator", "text": "stretch"}, kind="daily",
                         timezone=localtime.operator_timezone(), time="23:59")
        return scheduler.load("r-daily")

    def test_said_twice_it_does_not_skip_next_week_too(self):
        found = self._daily()
        today = dt.datetime.now(localtime.operator_tz()).date()
        if today.weekday() == 6 and dt.datetime.now(localtime.operator_tz()).hour == 23:
            self.skipTest("the last minute of the week")
        intercom._skip_once(found, "this week")
        with self.assertRaises(act.Refused) as said:
            intercom._skip_once(scheduler.load("r-daily"), "this week")
        self.assertIn("already skipped this week", str(said.exception))


if __name__ == "__main__":
    unittest.main()
