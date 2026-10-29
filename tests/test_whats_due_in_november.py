""""What's due in November" answers from the list.

2026-10-29, talking to her with the models off:

    > what's due in november
      I can't think just now...

"This month" and "next month" were hers; a month by name went to a model.
"""
import calendar
import datetime as dt
import unittest
from unittest import mock

from aletheia import intercom, localtime, quick


def _task(desc, days):
    tz = localtime.operator_tz()
    when = dt.datetime.combine(dt.datetime.now(tz).date() + dt.timedelta(days=days), dt.time(23, 59), tzinfo=tz)
    return {"id": desc[:4], "description": desc, "deadline": when.isoformat(), "status": "OPEN"}, when


class DueInAMonth(unittest.TestCase):
    def test_the_sentence_reaches_the_list(self):
        self.assertEqual(quick.match("what's due in november")[0], "tasks_due")

    def test_a_task_in_that_month_is_named_once(self):
        task, when = _task("renew my license", 40)
        name = calendar.month_name[when.month]
        with mock.patch.object(intercom, "_open_tasks", return_value=[task]), \
                mock.patch.object(quick, "_noted_dates", return_value=[]):
            said = quick._tasks_due(f"due in {name.lower()}")
        self.assertTrue(said.startswith(f"1 thing due in {name}: renew my license"), said)
        self.assertEqual(said.count(" due "), 1, said)

    def test_a_month_with_nothing_says_so(self):
        task, when = _task("renew my license", 40)
        other = calendar.month_name[(when.month % 12) + 1]
        with mock.patch.object(intercom, "_open_tasks", return_value=[task]), \
                mock.patch.object(quick, "_noted_dates", return_value=[]):
            said = quick._tasks_due(f"due in {other.lower()}")
        self.assertEqual(said, f"Nothing on your list is due in {other}.")


if __name__ == "__main__":
    unittest.main()
