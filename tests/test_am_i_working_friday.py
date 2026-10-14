""""I work 8 to 5 Monday through Friday", then "am I working tomorrow" went
to the planner, "do I work today" said "but not which days", "I have Friday
off" did not count as a day off, and "how many hours do I work a week" was
"I can't think" (2026-10-14)."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, quick

NOW = dt.datetime.now(localtime.operator_tz()).isoformat()
WEEK = {"text": "i work 8 to 5 monday through friday", "ts": NOW}



class WorkDays(unittest.TestCase):
    def test_hours_between_work_and_the_days(self):
        with mock.patch.object(quick, "_notes", return_value=[WEEK]):
            self.assertTrue(quick.answer("am i working thursday").startswith("Yes - you told me you work 8 to 5"))
            self.assertTrue(quick.answer("do i work saturday").startswith("No - you told me you work 8 to 5"))
            self.assertTrue(quick.answer("am i working sunday").startswith("No"))

    def test_a_named_day_off(self):
        with mock.patch.object(quick, "_notes", return_value=[{"text": "i have friday off", "ts": NOW}, WEEK]):
            self.assertEqual(quick.answer("am i working friday"), "No - you told me you have Friday off.")

    def test_hours_a_week(self):
        with mock.patch.object(quick, "_notes", return_value=[WEEK]):
            self.assertTrue(quick.answer("how many hours do i work a week").startswith("About 45 hours - 9 a day, 5 days a week."))
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIsNone(quick._work_week())


if __name__ == "__main__":
    unittest.main()
