""""What do I need to do before December" went to a model with a task due
November 30 on the list (2026-10-28). Before or by a month, a weekday or the
end of the week or month reads the list."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import intercom, localtime, quick

TZ = dt.timezone(dt.timedelta(hours=-5))


class DueBeforeADay(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 10, 27, 22, 0, tzinfo=TZ)  # a Tuesday
        rows = [{"id": "a", "description": "renew my license", "deadline": "2026-11-30T23:59:00-05:00"},
                {"id": "b", "description": "fix the fence", "deadline": "2026-10-31T23:59:00-05:00"},
                {"id": "c", "description": "call the bank", "deadline": "2026-10-20T12:00:00-05:00"},
                {"id": "d", "description": "buy a gift"}]
        for p in (mock.patch.object(intercom, "_open_tasks", return_value=rows),
                  mock.patch.object(localtime, "operator_tz", return_value=TZ)):
            p.start()
            self.addCleanup(p.stop)

    def by(self, word, when):
        return quick._tasks_due_by(intercom._open_tasks(), word, when, self.now)

    def test_the_phrasings_reach_it(self):
        for said, rest in (("what do I need to do before december", "before december"),
                           ("what's due by friday", "by friday"),
                           ("what do I have to get done by the end of the month", "by the end of the month")):
            self.assertEqual(quick.match(said), ("tasks_due", rest), said)

    def test_before_a_month(self):
        got = self.by("before", "december")
        self.assertTrue(got.startswith("3 things due before December: call the bank, overdue; fix the fence"), got)
        self.assertIn("renew your license, due Monday November 30", got)
        self.assertNotIn("gift", got)

    def test_by_a_weekday_includes_that_day_and_before_does_not(self):
        with mock.patch("aletheia.voice._spoken_day", return_value="2026-10-31"):
            self.assertIn("fix the fence", self.by("by", "saturday"))
            self.assertNotIn("fix the fence", self.by("before", "saturday"))

    def test_the_end_of_the_month(self):
        got = self.by("by", "the end of the month")
        self.assertIn("fix the fence", got)
        self.assertNotIn("license", got)


if __name__ == "__main__":
    unittest.main()
