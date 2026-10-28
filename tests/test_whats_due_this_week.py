""""What's on my list for this week" names the week once.

2026-10-28, talking to her with the models off:

    > add take out recycling to my to do list for thursday
    > what's on my list for this week
      1 thing due: take out recycling due tomorrow.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import intercom, localtime, quick


def _task(desc, days):
    tz = localtime.operator_tz()
    when = dt.datetime.combine(dt.datetime.now(tz).date() + dt.timedelta(days=days), dt.time(23, 59), tzinfo=tz)
    return {"id": desc[:4], "description": desc, "deadline": when.isoformat(), "status": "OPEN"}


class DueThisWeek(unittest.TestCase):
    def test_the_window_is_the_head(self):
        with mock.patch.object(intercom, "_open_tasks", return_value=[_task("take out recycling", 1)]):
            said = quick._tasks_due("this week")
        self.assertEqual(said, "1 thing due this week: take out recycling tomorrow.")
        self.assertEqual(said.count(" due "), 1)

    def test_a_late_one_still_says_due_and_late(self):
        with mock.patch.object(intercom, "_open_tasks", return_value=[_task("call the bank", -2)]):
            said = quick._tasks_due("this week")
        self.assertIn("already late", said)


if __name__ == "__main__":
    unittest.main()
