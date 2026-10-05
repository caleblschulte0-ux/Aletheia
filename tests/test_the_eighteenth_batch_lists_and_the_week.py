"""Eighteenth sandbox batch, 2026-10-05.

    > take eggs off                         [4.2s] the planner, and an approval
                                            to undo a thing she adds in 0.0s
    > move that to monday                   "I haven't set a reminder just now
                                            that I could move." - she had; a
                                            day was not a time
    > add a task to renew my passport by the 20th
                                            the deadline stayed in the words
    > what's due this week                  [3.0s] a model
    > what did I ask you to do today        "No fleet reading yet" - swallowed
                                            as a repository called "i ask you to"
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, quick, voice

TODAY = localtime.today()


def _next(weekday: int) -> dt.date:
    return TODAY + dt.timedelta(days=(weekday - TODAY.weekday()) % 7 or 7)


class TakeItOff(unittest.TestCase):
    def test_a_thing_on_the_list_comes_off_without_naming_the_list(self):
        with mock.patch.object(voice, "_on_the_shopping_list", return_value=True):
            self.assertEqual(voice.interpret("take eggs off")["command"], {"kind": "shopping_off", "item": "eggs"})
        with mock.patch.object(voice, "_on_the_shopping_list", return_value=False):
            self.assertNotEqual(voice.interpret("take eggs off")["command"].get("kind"), "shopping_off")


class TheTwentieth(unittest.TestCase):
    def test_a_bare_ordinal_is_the_next_such_day(self):
        got = dt.date.fromisoformat(voice._spoken_day("the 20th"))
        self.assertEqual(got.day, 20)
        self.assertGreaterEqual(got, TODAY)
        self.assertLess((got - TODAY).days, 62)

    def test_a_month_and_a_day_read_too(self):
        got = dt.date.fromisoformat(voice._spoken_day("the 20th of october"))
        self.assertEqual((got.month, got.day), (10, 20))
        self.assertGreaterEqual(got, TODAY)

    def test_the_deadline_leaves_the_description(self):
        out = voice.interpret("add a task to renew my passport by the 20th")["command"]
        self.assertEqual(out["description"], "renew my passport")
        self.assertEqual(dt.date.fromisoformat(out["deadline"]).day, 20)


class MoveThatToMonday(unittest.TestCase):
    def setUp(self):
        friday = dt.datetime.combine(_next(4), dt.time(9, 0), tzinfo=localtime.operator_tz())
        self.previous = {"kind": "remind_at", "at": friday.isoformat(), "text": "call the bank"}

    def test_a_day_keeps_the_hour_and_a_day_with_a_time_takes_both(self):
        monday = _next(0).isoformat()
        with mock.patch.object(voice, "_previous_reminder_ask", return_value=self.previous):
            moved = voice.interpret("move that to monday")["command"]
            self.assertEqual(moved["kind"], "remind_at")
            self.assertEqual(moved["at"][:16], f"{monday}T09:00")
            self.assertEqual(moved["replaces"], "call the bank")
            self.assertEqual(voice.interpret("move that to monday at 10")["command"]["at"][:16], f"{monday}T10:00")
            self.assertEqual(voice.interpret("move that to 10 on monday")["command"]["at"][:16], f"{monday}T10:00")

    def test_a_bare_hour_never_lands_in_the_small_hours(self):
        with mock.patch.object(voice, "_previous_reminder_ask", return_value=self.previous):
            self.assertEqual(voice.interpret("make that 4")["command"]["at"][11:16], "16:00")

    def test_what_she_could_not_read_is_said(self):
        with mock.patch.object(voice, "_previous_reminder_ask", return_value=self.previous):
            out = voice.interpret("move that to whenever")
        self.assertIsNone(out["command"])
        self.assertIn("couldn't read 'whenever'", out["say"])


class WhatIsDue(unittest.TestCase):
    def test_his_words_are_not_a_repository(self):
        self.assertEqual(quick.match("what did i ask you to do today"), ("asked_on", "today"))

    def test_tasks_and_reminders_inside_the_window(self):
        in_three_days = (TODAY + dt.timedelta(days=3)).isoformat()
        far = (TODAY + dt.timedelta(days=40)).isoformat()
        tasks = [{"id": "passport", "description": "renew my passport", "status": "QUEUED", "deadline": in_three_days},
                 {"id": "later", "description": "sort the garage", "status": "QUEUED", "deadline": far},
                 {"id": "build-x", "description": "a ticket of hers", "status": "QUEUED", "deadline": in_three_days,
                  "required_capabilities": ["x"]}]
        soon = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2)).replace(microsecond=0)
        reminder = {"version": 1, "id": "r1", "kind": "once", "at": soon.isoformat(), "enabled": True,
                    "created_at": soon.isoformat(), "command": {"kind": "notify_operator", "text": "call the bank"}}
        with mock.patch("aletheia.tasks.all_tasks", return_value=tasks), \
             mock.patch("aletheia.scheduler.all_schedules", return_value=[reminder]):
            said = quick.answer("what's due this week")
            nothing = quick.answer("anything due today")
        self.assertTrue(said.startswith("This week: "), said)
        self.assertIn("renew my passport by", said)
        self.assertIn("a reminder to call the bank", said)
        self.assertNotIn("garage", said)
        self.assertNotIn("ticket", said)
        self.assertTrue(nothing.startswith("Nothing due today"), nothing)


if __name__ == "__main__":
    unittest.main()
