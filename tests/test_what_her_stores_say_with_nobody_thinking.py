""""Set a timer for ten minutes for the pasta" went to the planner; "when is
my next dentist appointment" with nothing booked and "what's on my list for
this weekend" both came back "I can't think just now"; "what's on my list for
next week" read a task due this Saturday; and "add file taxes to my list for
next Tuesday" kept the day in the task with nothing due (2026-10-14, every
model off)."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import intercom, localtime, quick, voice


class Timer(unittest.TestCase):
    def test_a_named_timer_said_in_words(self):
        out = voice._interpret("set a timer for ten minutes for the pasta")
        self.assertEqual(out["command"]["kind"], "remind_at")
        self.assertIn("pasta", out["command"]["text"])
        left = dt.datetime.fromisoformat(out["command"]["at"]) - dt.datetime.now(dt.timezone.utc)
        self.assertAlmostEqual(left.total_seconds(), 600, delta=30)


class NothingBooked(unittest.TestCase):
    def test_says_what_she_checked(self):
        with mock.patch.object(quick, "_coming", return_value=[]), mock.patch.object(quick, "_notes", return_value=[]):
            said = quick.when_nobody_can_think("when is my next dentist appointment")
        self.assertIn("Nothing on your calendar or in your reminders mentions your dentist appointment", said)
        self.assertNotIn("you have no", said.casefold())

    def test_only_for_that_question(self):
        self.assertIsNone(quick.when_nobody_can_think("what's the capital of peru"))


class ListByWindow(unittest.TestCase):
    def _tasks(self, *days):
        now = dt.datetime.now(localtime.operator_tz())
        return [{"id": f"t{i}", "description": f"task {i}", "status": "QUEUED",
                 "deadline": (now.date() + dt.timedelta(days=d)).isoformat()} for i, d in enumerate(days)]

    def test_this_weekend(self):
        now = dt.datetime.now(localtime.operator_tz())
        sat = (5 - now.weekday()) % 7 if now.weekday() != 6 else 0
        with mock.patch.object(intercom, "_open_tasks", return_value=self._tasks(sat)):
            said = quick.answer("what's on my list for this weekend")
        self.assertEqual(said, "1 thing due this weekend: task 0.")

    def test_next_week_starts_on_monday(self):
        now = dt.datetime.now(localtime.operator_tz())
        monday = 7 - now.weekday()
        with mock.patch.object(intercom, "_open_tasks", return_value=self._tasks(monday - 1, monday + 1)):
            said = quick.answer("what's on my list for next week")
        self.assertIn("task 1", said)
        self.assertNotIn("task 0", said)


class WhichTuesday(unittest.TestCase):
    def test_a_task_for_next_tuesday_asks_which(self):
        with mock.patch.object(localtime, "today", return_value=dt.date(2026, 10, 14)):
            out = voice._new_task("file taxes for next tuesday")
        self.assertIsNone(out["command"])
        self.assertEqual(out["say"], "Which Tuesday — the 20th, or the week after on the 27th?")

    def test_a_date_on_the_list_is_its_deadline(self):
        out = voice._interpret("add renew tags to my list for november 3")
        self.assertEqual(out["command"]["kind"], "task_new")
        self.assertTrue(out["command"]["deadline"].endswith("-11-03"))


if __name__ == "__main__":
    unittest.main()
