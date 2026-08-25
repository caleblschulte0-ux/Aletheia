"""Phase 7 computer-control tests: hermetic; no desktop is touched."""
import json
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

    def approve(self, aid="computer-test", steps=None):
        steps = self.steps if steps is None else steps
        policy.request(aid, computer.approval_action(steps), "test",
                       "fake backend receives steps", reversible=True)
        policy.decide(aid, "APPROVED", via="test")
        return aid

    @staticmethod
    def computer_step_entries():
        return [entry for entry in journal.entries()
                if entry["subject"].startswith("computer:")
                and entry["subject"] != "computer:run"]

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

    def test_plan_and_input_bounds_are_enforced(self):
        self.assertIn("maximum", computer.validate_steps(
            [{"action": "open_app", "app": "notepad.exe"}]
            * (computer.MAX_STEPS + 1))[0])
        errors = computer.validate_steps([
            {"action": "open_app", "app": "notepad.exe",
             "arguments": ["x"] * (computer.MAX_ARGUMENTS + 1)},
            {"action": "set_text", "window": {"title": "Notepad"},
             "control": {"control_type": "Document"},
             "text": "x" * (computer.MAX_TEXT_CHARS + 1)},
            {"action": "wait_window", "window": {"title_re": "("}},
        ])
        self.assertTrue(any("arguments" in error for error in errors))
        self.assertTrue(any(".text" in error for error in errors))
        self.assertTrue(any("regular expression" in error for error in errors))

    def test_observation_and_screenshot_inputs_are_bounded(self):
        errors = computer.validate_steps([
            {"action": "list_windows",
             "max_results": computer.MAX_OBSERVATIONS + 1},
            {"action": "inspect_controls", "window": {"title": "Notepad"},
             "max_results": 0},
            {"action": "screenshot_window", "window": {"title": "Notepad"},
             "filename": "../outside.png"},
            {"action": "screenshot_window", "window": {"title": "Notepad"},
             "filename": "..\\outside.png"},
        ])
        self.assertTrue(any("max_results" in error for error in errors))
        self.assertTrue(any("filename" in error for error in errors))
        self.assertEqual(computer.validate_steps([
            {"action": "list_windows", "max_results": 10},
            {"action": "screenshot_window", "window": {"title": "Notepad"},
             "filename": "notepad.png"},
        ]), [])

    def test_approved_plan_executes_in_order_and_is_journaled(self):
        backend = FakeBackend()
        result = computer.execute(self.steps, self.approve(), backend=backend)
        self.assertEqual(backend.steps, self.steps)
        self.assertEqual(result["steps_done"], 3)
        entries = self.computer_step_entries()
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
        entries = self.computer_step_entries()
        self.assertEqual(len(entries), 2)
        self.assertIn("FAILED", entries[-1]["text"])

    def test_non_windows_reports_unavailable_honestly(self):
        with mock.patch.object(computer.os, "name", "posix"):
            ok, reason = computer.available()
        self.assertFalse(ok)
        self.assertIn("Windows", reason)

    def test_approval_is_single_use_even_after_success(self):
        plan = self.steps[:1]
        aid = self.approve("computer-once", plan)
        computer.execute(plan, aid, backend=FakeBackend())
        second = FakeBackend()
        with self.assertRaisesRegex(computer.ApprovalRequired, "already consumed"):
            computer.execute(plan, aid, backend=second)
        self.assertEqual(second.steps, [])

    def test_approval_for_different_plan_is_refused(self):
        aid = self.approve("computer-wrong-plan", self.steps[:1])
        backend = FakeBackend()
        with self.assertRaisesRegex(computer.ApprovalRequired, "exact computer plan"):
            computer.execute(self.steps, aid, backend=backend)
        self.assertEqual(backend.steps, [])

    def test_sensitive_backend_evidence_is_redacted_only_in_journal(self):
        class SensitiveBackend:
            def perform(inner_self, step):
                return {"action": step["action"], "verified": True,
                        "text": "secret typed text"}

        aid = self.approve("computer-redact", self.steps[:1])
        result = computer.execute(self.steps[:1], aid, backend=SensitiveBackend())
        self.assertEqual(result["results"][0]["text"], "secret typed text")
        entry = self.computer_step_entries()[-1]
        self.assertNotIn("secret typed text", entry["text"])
        self.assertIn("redacted_fields", entry["text"])

    def test_backend_exception_message_is_not_persisted(self):
        class LeakyFailure:
            def perform(inner_self, step):
                raise RuntimeError("secret desktop content")

        aid = self.approve("computer-error-redact", self.steps[:1])
        with self.assertRaisesRegex(RuntimeError, "secret desktop content"):
            computer.execute(self.steps[:1], aid, backend=LeakyFailure())
        entry = self.computer_step_entries()[-1]
        self.assertIn("RuntimeError", entry["text"])
        self.assertNotIn("secret desktop content", entry["text"])

    def test_backend_must_return_structured_evidence(self):
        class BadEvidence:
            def perform(inner_self, step):
                return "done"

        aid = self.approve("computer-bad-evidence", self.steps[:1])
        with self.assertRaisesRegex(computer.VerificationFailed, "non-object"):
            computer.execute(self.steps[:1], aid, backend=BadEvidence())
        self.assertIn("VerificationFailed", self.computer_step_entries()[-1]["text"])

    def test_harmless_acceptance_example_validates(self):
        plan = json.loads(Path("examples/computer/notepad-acceptance.json")
                          .read_text(encoding="utf-8"))
        self.assertEqual(computer.validate_steps(plan), [])
        self.assertEqual(plan[0]["app"], "notepad.exe")
        self.assertFalse(any(step["action"] == "close_window" for step in plan))


if __name__ == "__main__":
    unittest.main()
