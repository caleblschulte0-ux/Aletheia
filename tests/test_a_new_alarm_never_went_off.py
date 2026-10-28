""""Set an alarm for weekdays at 7", then at 5 pm "turn off my alarm for
today" (2026-10-28): "it already went off today at 7 am" - an alarm that did
not exist at 7. One set after today's time starts tomorrow, and she says so."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import act, intercom, localtime, scheduler


class ANewAlarmNeverWentOff(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for attr in ("SCHEDULE_DIR", "RECEIPT_DIR"):
            patcher = mock.patch.object(scheduler, attr, Path(tmp.name) / attr)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _daily(self):
        now = dt.datetime.now(localtime.operator_tz())
        if now.hour == 0 and now.minute < 2:
            self.skipTest("the first minutes of the day")
        scheduler.create("r-wake", {"kind": "notify_operator", "text": "alarm"}, kind="daily",
                         timezone=localtime.operator_timezone(), time="00:01")
        return scheduler.load("r-wake")

    def test_set_after_todays_time_it_starts_tomorrow(self):
        with self.assertRaises(act.Refused) as said:
            intercom._skip_once(self._daily(), "today")
        self.assertIn("starts tomorrow", str(said.exception))
        self.assertNotIn("already went off", str(said.exception))

    def test_one_that_did_go_off_still_says_so(self):
        found = self._daily()
        found["created_at"] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).isoformat()
        with self.assertRaises(act.Refused) as said:
            intercom._skip_once(found, "today")
        self.assertIn("already went off today", str(said.exception))


if __name__ == "__main__":
    unittest.main()
