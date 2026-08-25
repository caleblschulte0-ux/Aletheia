import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import director, journal, plans, policy, tasks
from tests.test_capabilities import RecordingAPI


class DirectorCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        patches = [
            mock.patch.object(plans, "PLANS_DIR", base / "plans"),
            mock.patch.object(tasks, "TASKS_DIR", base / "tasks"),
            mock.patch.object(journal, "JOURNAL_PATH", base / "journal.jsonl"),
            mock.patch.object(policy, "APPROVALS_DIR", base / "approvals"),
            mock.patch.object(policy, "HALT_PATH", base / "halt.json"),
        ]
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        tasks.create("fix-shorts", "Diagnose and repair the failing finalizer",
                     assigned_worker="claude")

    def test_first_pass_requests_approval_not_work_order(self):
        api = RecordingAPI()
        actions = director.dispatch_ready("o/r", request=api)
        self.assertEqual(actions[0]["action"], "approval_requested")
        # the only network write is the 🔐 approval issue — no work order yet
        posts = [c for c in api.calls if c[0] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertIn(policy.ISSUE_PREFIX, posts[0][2]["title"])
        self.assertEqual(tasks.load("fix-shorts")["status"], "QUEUED")

    def test_pending_approval_waits_silently(self):
        director.dispatch_ready("o/r", request=RecordingAPI())
        api = RecordingAPI()
        self.assertEqual(director.dispatch_ready("o/r", request=api), [])
        self.assertEqual([c for c in api.calls if c[0] == "POST"], [])

    def test_approved_task_gets_work_order_and_waits_external(self):
        director.dispatch_ready("o/r", request=RecordingAPI())
        policy.decide("delegate-fix-shorts", "APPROVED", via="test")
        api = RecordingAPI()
        actions = director.dispatch_ready("o/r", request=api)
        self.assertEqual(actions[0]["action"], "work_order_filed")
        t = tasks.load("fix-shorts")
        self.assertEqual(t["status"], "WAITING_EXTERNAL")
        body = [c for c in api.calls if c[0] == "POST"][0][2]["body"]
        for section in ("GOAL", "AUTHORITY", "SUCCESS CRITERIA", "REPORTING"):
            self.assertIn(section, body)

    def test_denied_delegation_blocks_the_task(self):
        director.dispatch_ready("o/r", request=RecordingAPI())
        policy.decide("delegate-fix-shorts", "DENIED", via="test")
        actions = director.dispatch_ready("o/r", request=RecordingAPI())
        self.assertEqual(actions[0]["action"], "blocked_by_denial")
        self.assertEqual(tasks.load("fix-shorts")["status"], "BLOCKED")

    def test_halted_director_dispatches_nothing(self):
        policy.halt("stop everything", via="test")
        with self.assertRaises(policy.Halted):
            director.dispatch_ready("o/r", request=RecordingAPI())

    def test_unassigned_tasks_are_left_alone(self):
        tasks.create("solo", "no worker on this one")
        director.dispatch_ready("o/r", request=RecordingAPI())
        self.assertEqual(tasks.load("solo")["status"], "QUEUED")


if __name__ == "__main__":
    unittest.main()
