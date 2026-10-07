"""What he got done, and what to do first, from the task store.

    > what have I done today          -> "I can't think just now"
    > what's my most important task   -> "I don't have anything remembered about 'most important task'"
    > clear my completed tasks        -> filed for a model to plan later
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, quick, tasks


def task(tid, desc, status="PENDING", updated=None, deadline=None, created="2026-10-01T00:00:00Z"):
    return {"id": tid, "description": desc, "status": status, "created_at": created,
            "updated_at": updated or created, "deadline": deadline}


class WhatHeGotDone(unittest.TestCase):
    def test_finished_today_and_yesterday_are_told_apart(self):
        now = dt.datetime.now(localtime.operator_tz())
        today = now.astimezone(dt.timezone.utc).isoformat()
        yesterday = (now - dt.timedelta(days=1)).astimezone(dt.timezone.utc).isoformat()
        rows = [task("t1", "call the plumber", "COMPLETED", today),
                task("t2", "buy a gift", "COMPLETED", yesterday),
                task("t3", "renew my passport")]
        with mock.patch.object(tasks, "all_tasks", return_value=rows):
            self.assertEqual(quick.answer("what have I done today"), "1 task done today: call the plumber.")
            self.assertEqual(quick.answer("what did I finish yesterday"), "1 task done yesterday: buy a gift.")
        with mock.patch.object(tasks, "all_tasks", return_value=[]):
            self.assertEqual(quick.answer("what tasks did I finish"), "Nothing ticked off your list today.")


class WhatToDoFirst(unittest.TestCase):
    def test_the_nearest_deadline_comes_first_and_says_why(self):
        rows = [task("t1", "buy a gift"),
                task("t2", "renew my passport", deadline="2026-10-09T23:59:00-05:00"),
                task("t3", "file taxes", deadline="2026-10-20T23:59:00-05:00")]
        with mock.patch.object(tasks, "all_tasks", return_value=rows):
            said = quick.answer("what's my most important task")
        self.assertTrue(said.startswith("Renew my passport - it has the nearest deadline"), said)

    def test_with_no_deadlines_the_oldest_waits_longest(self):
        rows = [task("t1", "buy a gift", created="2026-10-03T00:00:00Z"),
                task("t2", "call mom", created="2026-10-01T00:00:00Z")]
        with mock.patch.object(tasks, "all_tasks", return_value=rows):
            self.assertIn("Call mom - nothing has a deadline", quick.answer("what's my top priority"))

    def test_clearing_finished_tasks_says_they_are_already_off(self):
        self.assertIn("already off your list", quick.answer("clear my completed tasks"))


if __name__ == "__main__":
    unittest.main()
