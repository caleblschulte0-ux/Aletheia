""""What do I have this weekend" names the tasks due in it.

Found 2026-10-15 in the sandbox with every model off: a task due Sunday,
then "what do I have this weekend" said "Nothing on your calendar this
weekend" and stopped, the same hole reminders had until 2026-10-08. And
"what tasks are due sunday" went to a model while "what's due sunday"
was answered from the list.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, quick, tasks


class TasksInAnEmptyWindow(unittest.TestCase):
    def setUp(self):
        tz = localtime.operator_tz()
        self.now = dt.datetime.now(tz)
        self.first = self.now.date() + dt.timedelta(days=1)
        self.last = self.first + dt.timedelta(days=1)
        at = lambda d: dt.datetime.combine(d, dt.time(17, 0), tzinfo=tz)
        rows = [{"task": {"description": "clean the garage"}, "when": at(self.last), "overdue": False},
                {"task": {"description": "far off"}, "when": at(self.last + dt.timedelta(days=5)), "overdue": False},
                {"task": {"description": "late already"}, "when": at(self.now.date() - dt.timedelta(days=2)), "overdue": True}]
        for patch in (mock.patch.object(tasks, "due", return_value=rows),
                      mock.patch.object(tasks, "is_his", return_value=True)):
            patch.start()
            self.addCleanup(patch.stop)

    def test_the_task_inside_the_window_is_named_with_its_day(self):
        said = quick._tasks_between(self.first, self.last, self.now)
        self.assertIn("1 task due: clean the garage, " + self.last.strftime("%A"), said)
        self.assertNotIn("far off", said)
        self.assertNotIn("late already", said)

    def test_after_reminders_it_is_joined_with_and(self):
        with mock.patch.object(quick, "_reminders_between", return_value=" You do have 1 reminder: x."):
            said = quick._reminders_and_tasks_between(self.first, self.last, self.now)
        self.assertEqual(said.count("You do have"), 1)
        self.assertIn(" And 1 task due", said)

    def test_an_unreadable_list_adds_nothing(self):
        with mock.patch.object(tasks, "due", side_effect=OSError("gone")):
            self.assertEqual(quick._tasks_between(self.first, self.last, self.now), "")


class WhatTasksAreDueOnADay(unittest.TestCase):
    def test_the_weekday_reaches_the_task_list(self):
        for said in ("what tasks are due sunday", "which tasks are due on friday", "what things are due monday"):
            with self.subTest(said=said):
                tidy = quick._tidy(said)
                self.assertIn("due", [name for name, pattern in quick.PATTERNS if pattern.search(tidy)])
