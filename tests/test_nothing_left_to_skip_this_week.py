""""Skip the trash reminder this week" on a Wednesday, the trash on Tuesdays
(2026-10-28): "I can't do that: it doesn't go off again this week". Nothing
was refused; there was simply nothing left to skip, and she says so."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import act, intercom, localtime, scheduler, voice


class NothingLeftToSkip(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for attr in ("SCHEDULE_DIR", "RECEIPT_DIR"):
            patcher = mock.patch.object(scheduler, attr, Path(tmp.name) / attr)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_it_is_a_sentence_not_a_refusal(self):
        today = dt.datetime.now(localtime.operator_tz()).date()
        if today.weekday() == 0:
            self.skipTest("on a Monday every day of the week is still ahead")
        scheduler.create("r-trash", {"kind": "notify_operator", "text": "take out the trash"}, kind="weekly",
                         timezone=localtime.operator_timezone(), time="00:01", weekdays=[today.weekday() - 1])
        with self.assertRaises(act.Refused) as said:
            intercom._skip_once(scheduler.load("r-trash"), "this week")
        reason = str(said.exception)
        self.assertTrue(reason.startswith("Nothing to skip: it doesn't go off again this week."), reason)
        self.assertEqual(voice.spoken_reply("reminder_off", "refused", reason), reason)


if __name__ == "__main__":
    unittest.main()
