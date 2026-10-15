""""Do I have anything tomorrow" names tomorrow's reminders.

Found 2026-10-15 in the sandbox with every model off: a reminder set for
12:30 tomorrow, then "do I have anything tomorrow" answered "Free tomorrow
9 am to 5 pm" and nothing else, while "what's happening monday" already
named Monday's reminders. A question about one hour or one part of the
day is about that hour, and does not get the list.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import calendar as cal
from aletheia import intercom, localtime, quick


class AnythingTomorrow(unittest.TestCase):
    def setUp(self):
        tz = localtime.operator_tz()
        self.tomorrow = dt.datetime.now(tz).date() + dt.timedelta(days=1)
        lunch = dt.datetime.combine(self.tomorrow, dt.time(12, 30), tzinfo=tz)
        later = dt.datetime.combine(self.tomorrow + dt.timedelta(days=3), dt.time(9, 0), tzinfo=tz)
        rows = [(lunch, "eat lunch", "reminder"), (later, "call the vet", "reminder"),
                (lunch, "a task", "task")]
        for patch in (mock.patch.object(quick, "_coming", return_value=rows),
                      mock.patch.object(cal, "free_slots", return_value=[]),
                      mock.patch.object(intercom, "_nothing_on_it_at_all", return_value="")):
            patch.start()
            self.addCleanup(patch.stop)

    def ask(self, **extra):
        return intercom.free_time_answer({"kind": "free_time", "day": self.tomorrow.isoformat(), **extra})

    def test_the_whole_day_names_that_days_reminder_and_no_other(self):
        said = self.ask()
        self.assertIn("1 reminder", said)
        self.assertIn("eat lunch", said)
        self.assertNotIn("call the vet", said)
        self.assertNotIn("a task", said)

    def test_a_part_of_the_day_does_not_get_the_list(self):
        self.assertNotIn("eat lunch", self.ask(part="morning"))

    def test_no_reminders_adds_nothing(self):
        with mock.patch.object(quick, "_coming", return_value=[]):
            self.assertNotIn("reminder", self.ask())

    def test_an_unreadable_store_still_answers(self):
        with mock.patch.object(quick, "_coming", side_effect=OSError("gone")):
            self.assertTrue(self.ask())


class OnTheListAgain(unittest.TestCase):
    """"Put milk on the list again" went to the planner, and "put milk back
    on the list" put "milk back" on it (2026-10-15)."""

    def test_again_too_and_back_are_the_same_ask(self):
        from aletheia import voice
        for said in ("put milk on the list again", "add milk to the shopping list too",
                     "put milk back on the list", "add milk to my list as well"):
            with self.subTest(said=said):
                self.assertEqual(voice._interpret(said)["command"], {"kind": "shopping_add", "item": "milk"})

    def test_a_question_is_still_not_a_write(self):
        from aletheia import voice
        out = voice._interpret("why did you add milk to the list again")
        self.assertNotEqual((out["command"] or {}).get("kind"), "shopping_add")
