""""The furnace filter should be changed every 3 months", "I changed the
furnace filter today", then "when is the furnace filter due" answered "you
changed it today", and "remind me when it's due" went to the planner
(2026-10-14)."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, quick, voice


def _rows(days_ago=0):
    tz = localtime.operator_tz()
    done = (dt.datetime.now(tz) - dt.timedelta(days=days_ago)).replace(hour=12, minute=0, second=0, microsecond=0)
    return done.date(), [{"text": "i changed the furnace filter today", "ts": done.isoformat()},
                         {"text": "the furnace filter should be changed every 3 months", "ts": done.isoformat()}]


class FilterDue(unittest.TestCase):
    def test_how_often_is_a_note(self):
        out = voice._interpret("the furnace filter should be changed every 3 months")
        self.assertEqual(out["command"]["kind"], "note")

    def test_due_three_months_on(self):
        done, rows = _rows(10)
        with mock.patch.object(quick, "_notes", return_value=rows):
            due, doing, _said, last = quick._interval_due("furnace filter")
            self.assertEqual(last, done)
            self.assertEqual((due.year * 12 + due.month) - (done.year * 12 + done.month), 3)
            self.assertEqual(doing, "change the furnace filter")
            said = quick.answer("when is the furnace filter due")
            self.assertIn(f"{(due - dt.datetime.now(localtime.operator_tz()).date()).days} days from now", said)

    def test_never_said_when_done(self):
        with mock.patch.object(quick, "_notes", return_value=_rows()[1][1:]):
            self.assertIn("not when you last did it", quick.answer("when is the furnace filter due"))

    def test_remind_me_on_the_day(self):
        _done, rows = _rows()
        with mock.patch.object(quick, "_notes", return_value=rows):
            out = voice._interpret("remind me when the furnace filter is due")
        self.assertEqual(out["command"]["kind"], "remind_at")
        self.assertEqual(out["command"]["text"], "change the furnace filter")
        self.assertIn("T09:00:00", out["command"]["at"])

    def test_no_interval_hands_on(self):
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIsNone(quick._interval_said("when is my report due"))


if __name__ == "__main__":
    unittest.main()
