"""Phase 7 computer-control tests: hermetic; no desktop is touched."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import computer, journal, policy


class FakeBackend:
    def __init__(self, fail_at=None):
        self.steps = []
        self.fail_at = fail_at

    def perform(self, step):
        if len(self.steps) == self.fail_at:
            raise RuntimeError("simulated adapter failure")
        self.steps.append(step)
        return {"action": step["action"], "verified": True}


class ComputerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for module, attr, path in (
                (journal, "JOURNAL_PATH", root / "journal.jsonl"),
                (policy, "APPROVALS_DIR", root / "approvals"),
                (policy, "HALT_PATH", root / "halt.json")):
            patch = mock.patch.object(module, attr, path)
            patch.start(); self.addCleanup(patch.stop)
        self.steps = [
            {"action": "open_app", "app": "notepad.exe"},
            {"action": "wait_window", "window": {"title_re": ".*Notepad.*"}},
            {"action": "set_text", "window": {"title_re": ".*Notepad.*"},
             "control": {"control_type": "Edit"}, "text": "hello"},
        ]

    def approve(self, aid="computer-test"):
        policy.request(aid, "run Windows control test", "test",
                       "fake backend receives steps", reversible=True)
        policy.decide(aid, "APPROVED", via="test")
        return aid

    def test_unapproved_plan_is_refused_before_backend(self):
        backend = FakeBackend()
        with self.assertRaises(computer.ApprovalRequired):
            computer.execute(self.steps, "missing", backend=backend)
        self.assertEqual(backend.steps, [])

    def test_malformed_plan_is_refused_before_approval_and_backend(self):
        backend = FakeBackend()
        with self.assertRaises(ValueError):
            computer.execute([{"action": "click", "x": 10, "y": 20}],
                             "anything", backend=backend)
        self.assertEqual(backend.steps, [])

    def test_coordinate_selectors_are_rejected(self):
        errors = computer.validate_steps([
            {"action": "focus_window", "window": {"x": "10", "y": "20"}}])
        self.assertTrue(any("coordinates" in error or "unsupported" in error
                            for error in errors))

    def test_approved_plan_executes_in_order_and_is_journaled(self):
        backend = FakeBackend()
        result = computer.execute(self.steps, self.approve(), backend=backend)
        self.assertEqual(backend.steps, self.steps)
        self.assertEqual(result["steps_done"], 3)
        entries = journal.entries()
        self.assertEqual(len(entries), 3)
        self.assertTrue(all("approval=computer-test" in entry["text"] for entry in entries))

    def test_halt_blocks_even_an_approved_plan(self):
        aid = self.approve("computer-halted")
        policy.halt("stop everything", via="test")
        backend = FakeBackend()
        with self.assertRaises(policy.Halted):
            computer.execute(self.steps, aid, backend=backend)
        self.assertEqual(backend.steps, [])

    def test_halt_is_rechecked_between_steps(self):
        aid = self.approve("computer-mid-halt")

        class HaltingBackend(FakeBackend):
            def perform(inner_self, step):
                result = super().perform(step)
                policy.halt("mid-run stop", via="test")
                return result

        backend = HaltingBackend()
        with self.assertRaises(policy.Halted):
            computer.execute(self.steps, aid, backend=backend)
        self.assertEqual(len(backend.steps), 1)

    def test_adapter_failure_is_journaled_and_stops_the_plan(self):
        backend = FakeBackend(fail_at=1)
        with self.assertRaisesRegex(RuntimeError, "simulated"):
            computer.execute(self.steps, self.approve("computer-fail"), backend=backend)
        entries = journal.entries()
        self.assertEqual(len(entries), 2)
        self.assertIn("FAILED", entries[-1]["text"])

    def test_non_windows_reports_unavailable_honestly(self):
        with mock.patch.object(computer.os, "name", "posix"):
            ok, reason = computer.available()
        self.assertFalse(ok)
        self.assertIn("Windows", reason)


if __name__ == "__main__":
    unittest.main()
