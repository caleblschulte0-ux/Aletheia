""""Remind me every weekday at 7 to take my pills", "pause it for a week"
(2026-10-12: to a model, and with none running, nothing).

Every time it would go off in that span is skipped and it comes back on its
own; "turn it back on" clears the skips; the list says it is paused. Too
frequent a reminder, or a one-off, is told so in words. And "turn it back on"
re-reads his last few sentences, one of which ("pause it for a week") looks
back in turn: that has to end, not re-read itself until the room times out.
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import act, converse, intercom, localtime, policy, scheduler, voice


def said(sentence):
    with mock.patch.object(policy, "all_approvals", return_value=[]):
        return voice.interpret(f"thea {sentence}")["command"]


class ThePhrasings(unittest.TestCase):
    def test_it_after_a_repeating_reminder(self):
        with mock.patch.object(voice, "_recent_ask_of", return_value={"text": "take my pills"}):
            self.assertEqual(said("pause it for a week"),
                             {"kind": "reminder_off", "which": "take my pills", "once": "for 7 days"})
            self.assertEqual(said("pause it for 2 weeks")["once"], "for 14 days")
            self.assertEqual(said("pause that for three days")["once"], "for 3 days")

    def test_a_named_reminder(self):
        self.assertEqual(said("pause my pills reminder for a few days"),
                         {"kind": "reminder_off", "which": "pills", "once": "for 3 days"})


class ThePause(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for attr, sub in (("SCHEDULE_DIR", "defs"), ("RECEIPT_DIR", "receipts")):
            patcher = mock.patch.object(scheduler, attr, Path(tmp.name) / sub)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.tz = localtime.operator_tz()

    def daily(self, sid="pills"):
        return scheduler.create(sid, {"kind": "notify_operator", "title": "Reminder", "text": "take my pills"},
                                kind="daily", timezone=str(self.tz), time="07:00")

    def test_a_week_skips_every_time_in_it_and_comes_back(self):
        spec = self.daily()
        now = dt.datetime.now(dt.timezone.utc)
        said_ = intercom._skip_once(spec, "for 7 days")
        self.assertTrue(said_.startswith("Paused for a week: take your pills. It's back "), said_)
        back = scheduler.next_occurrence(scheduler.load("pills"), now)
        self.assertGreaterEqual(back - now, dt.timedelta(days=6, hours=23))
        self.assertLess(back - now, dt.timedelta(days=8))
        listed = intercom._reminders_answer()
        self.assertIn(", paused until ", listed)
        back_on = intercom._reminder_back_on("take my pills")
        self.assertTrue(back_on.startswith("Back on: take your pills"), back_on)
        self.assertNotIn("paused", intercom._reminders_answer())

    def test_whole_weeks_are_said_as_weeks(self):
        self.assertTrue(intercom._skip_once(self.daily(), "for 14 days").startswith("Paused for 2 weeks:"))

    def test_too_often_is_said_rather_than_half_done(self):
        spec = scheduler.create("stretch", {"kind": "notify_operator", "title": "Reminder", "text": "stretch"},
                                kind="interval", every_minutes=30,
                                anchor=dt.datetime.now(dt.timezone.utc).isoformat())
        with self.assertRaises(act.Refused) as caught:
            intercom._skip_once(spec, "for 1 days")
        self.assertIn("too often", str(caught.exception))
        self.assertFalse(scheduler.load("stretch").get("skips"))

    def test_a_one_off_is_told_to_cancel(self):
        at = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).isoformat()
        spec = scheduler.create("bob", {"kind": "notify_operator", "title": "Reminder", "text": "call bob"},
                                kind="once", at=at)
        with self.assertRaises(act.Refused) as caught:
            intercom._skip_once(spec, "for 7 days")
        self.assertIn("only goes off once", str(caught.exception))


class PutItBackEnds(unittest.TestCase):
    def test_turn_it_back_on_after_a_pause_neither_hangs_nor_loses_it(self):
        turns = [{"he_asked": "remind me every weekday at 7 to take my pills",
                  "she_answered": "Weekdays at 7 am I'll remind you: take your pills."},
                 {"he_asked": "pause it for a week", "she_answered": "Paused for a week: take your pills."},
                 {"he_asked": "turn it back on", "she_answered": "Back on: take your pills."},
                 {"he_asked": "pause it for 2 weeks", "she_answered": "Paused for 2 weeks: take your pills."}]
        with mock.patch.object(converse, "recent", side_effect=lambda limit=4: turns[-limit:]):
            self.assertEqual(said("put it back"), {"kind": "reminder_on", "which": "take my pills"})


if __name__ == "__main__":
    unittest.main()
