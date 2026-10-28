"""Taking back a task he just dropped.

2026-10-28, talking to her with the models off:

    > add a task to file my taxes due april 15
    > delete the taxes task
      Took it off your list: file my taxes.
    > undo that
      Nothing to undo: I haven't done anything on my own in the last two days...
"""
import unittest
from unittest import mock

from aletheia import converse, intercom, tasks


class PutItBack(unittest.TestCase):
    def test_the_dropped_task_comes_back_with_its_day(self):
        turns = [{"he_asked": "delete the taxes task", "she_answered": "Took it off your list: file my taxes."}]
        gone = [{"id": "t1", "status": "CANCELLED", "description": "file my taxes", "deadline": "2027-04-15",
                 "updated_at": "2026-10-28T17:00:00Z"},
                {"id": "t0", "status": "CANCELLED", "description": "file my taxes", "updated_at": "2025-01-01T00:00:00Z"}]
        with mock.patch.object(converse, "recent", return_value=turns), \
                mock.patch.object(tasks, "all_tasks", return_value=gone), \
                mock.patch.object(intercom, "execute_command", return_value="ok") as run:
            self.assertEqual(intercom._undo_his_last_ask(), "Undone: file my taxes is back on your list.")
        cmd = run.call_args[0][0]
        self.assertEqual((cmd["kind"], cmd["description"], cmd["deadline"]), ("task_new", "file my taxes", "2027-04-15"))

    def test_a_named_list_is_not_a_task(self):
        turns = [{"he_asked": "take towels off my packing list", "she_answered": "Took it off your packing list: towels."}]
        with mock.patch.object(converse, "recent", return_value=turns), \
                mock.patch.object(intercom, "execute_command", return_value="ok") as run:
            intercom._undo_his_last_ask()
        self.assertFalse(any(c[0][0].get("kind") == "task_new" for c in run.call_args_list))


if __name__ == "__main__":
    unittest.main()
