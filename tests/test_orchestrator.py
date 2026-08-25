import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, orchestrator, plans, tasks


class OrchestratorCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        for target, attr in ((plans, "PLANS_DIR"), (tasks, "TASKS_DIR"),
                             (journal, "JOURNAL_PATH")):
            p = mock.patch.object(target, attr, base / attr.lower())
            p.start(); self.addCleanup(p.stop)
        plans.new_plan("book-doctor", "Book the doctor", "appointment after work")
        plans.add_step("book-doctor", "find the office number")
        plans.add_step("book-doctor", "call and negotiate a slot")
        plans.add_step("book-doctor", "confirm and record the appointment")


class TestCompile(OrchestratorCase):
    def test_steps_become_chained_tasks(self):
        created = orchestrator.compile_goal("book-doctor")
        self.assertEqual([t["id"] for t in created],
                         ["book-doctor-s1", "book-doctor-s2", "book-doctor-s3"])
        self.assertEqual(tasks.load("book-doctor-s2")["dependencies"],
                         ["book-doctor-s1"])
        self.assertEqual([t["id"] for t in tasks.ready()], ["book-doctor-s1"])

    def test_compile_is_idempotent(self):
        orchestrator.compile_goal("book-doctor")
        self.assertEqual(orchestrator.compile_goal("book-doctor"), [])

    def test_closed_plan_refuses_compilation(self):
        plans.set_plan("book-doctor", "dropped", "changed my mind")
        with self.assertRaises(ValueError):
            orchestrator.compile_goal("book-doctor")


class TestSync(OrchestratorCase):
    def setUp(self):
        super().setUp()
        orchestrator.compile_goal("book-doctor")

    def test_completed_with_evidence_marks_step_done(self):
        tasks.set_status("book-doctor-s1", "COMPLETED", "number found: 555-0100")
        summary = orchestrator.sync_goal("book-doctor")
        self.assertEqual(summary["steps_done"], [1])
        self.assertEqual([t["id"] for t in tasks.ready()], ["book-doctor-s2"])

    def test_completed_without_evidence_gets_no_credit(self):
        tasks.set_status("book-doctor-s1", "COMPLETED")  # no note
        summary = orchestrator.sync_goal("book-doctor")
        self.assertEqual(summary["steps_done"], [])
        self.assertEqual(summary["unverified"], [1])

    def test_goal_closes_when_every_step_verified(self):
        for n, evidence in ((1, "number found"), (2, "booked Wed 5:45"),
                            (3, "calendar entry + confirmation recorded")):
            tasks.set_status(f"book-doctor-s{n}", "COMPLETED", evidence)
        summary = orchestrator.sync_goal("book-doctor")
        self.assertEqual(summary["plan_state"], "done")

    def test_running_task_shows_step_doing(self):
        tasks.set_status("book-doctor-s1", "RUNNING")
        orchestrator.sync_goal("book-doctor")
        step = plans.load("book-doctor")["steps"][0]
        self.assertEqual(step["state"], "doing")


if __name__ == "__main__":
    unittest.main()
