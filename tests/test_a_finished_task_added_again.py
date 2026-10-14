""""Call the vet", done, then "add call the vet" said "that's already on your
list" (done is stored COMPLETED, the check looked for DONE); "move call the
vet to tomorrow" went to the planner; and "undo that" after a turn that
changed nothing re-said it (2026-10-14)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import intercom, tasks, voice


class FinishedTask(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(tasks, "TASKS_DIR", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        tasks.create("call-the-vet", "call the vet")
        tasks.set_status("call-the-vet", "COMPLETED", "done")

    def test_added_again_is_added(self):
        said = intercom.execute_command({"kind": "task_new", "id": "call-the-vet-2", "description": "call the vet"}, {}, quote="t")
        self.assertIn("queued", said)

    def test_moving_it_says_it_is_done(self):
        out = voice._interpret("move call the vet to tomorrow")
        self.assertIsNone(out["command"])
        self.assertTrue(out["say"].startswith("You already marked call the vet done."))

    def test_undo_steps_over_a_turn_that_did_nothing(self):
        tasks.create("call-the-vet-2", "call the vet")
        turns = [{"he_asked": "add call the vet", "she_answered": "Added a task: call the vet."},
                 {"he_asked": "add call the vet", "she_answered": "That's already on your list: call the vet."}]
        from aletheia import converse
        with mock.patch.object(converse, "recent", return_value=turns):
            said = intercom._undo_his_last_ask()
        self.assertEqual(said, "Undone: cancelled the task call the vet.")
        self.assertEqual(tasks.load("call-the-vet")["status"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
