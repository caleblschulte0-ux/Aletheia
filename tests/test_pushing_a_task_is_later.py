"""Talked to her on a Monday, 2026-10-12: "push email Dana to Monday", about a task due Friday,
answered "Email dana is due today now". Pushing is later: the Monday after Friday."""

import datetime as dt
import unittest
from unittest import mock

from aletheia import intercom, localtime, voice

MONDAY = dt.date(2026, 10, 12)


class PushingATaskIsLater(unittest.TestCase):

    def _move(self, said, due):
        task = {"id": "t1", "description": "email dana", "deadline": due}
        with mock.patch.object(localtime, "today", lambda: MONDAY), \
                mock.patch.object(intercom, "_one_task", lambda which: (task, "")), \
                mock.patch.object(voice, "_names_one_open_task", lambda words: True), \
                mock.patch.object(voice, "_the_task_just_added", lambda: "email dana"):
            return (voice._interpret(said)["command"] or {}).get("deadline")

    def test_a_push_lands_after_the_day_it_was_due(self):
        self.assertEqual(self._move("push email dana to monday", "2026-10-16"), "2026-10-19")
        self.assertEqual(self._move("postpone email dana to wednesday", "2026-10-16"), "2026-10-21")
        self.assertEqual(self._move("push it to monday", "2026-10-16"), "2026-10-19")

    def test_a_push_to_a_later_day_is_that_day(self):
        self.assertEqual(self._move("push email dana to thursday", "2026-10-13"), "2026-10-15")

    def test_a_move_to_today_by_name_is_next_week_only_when_it_is_due_later(self):
        self.assertEqual(self._move("move email dana to monday", "2026-10-16"), "2026-10-19")
        self.assertEqual(self._move("move email dana to monday", "2026-10-10"), "2026-10-12")
        # A move earlier is still a move earlier.
        self.assertEqual(self._move("move email dana to wednesday", "2026-10-16"), "2026-10-14")
        self.assertEqual(self._move("move email dana to today", "2026-10-16"), "2026-10-12")


if __name__ == "__main__":
    unittest.main()
