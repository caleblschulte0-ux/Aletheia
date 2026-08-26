import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import outcomes


class OutcomeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(outcomes, "ACTIONS_DIR", Path(self.tmp.name) / "actions")
        patcher.start(); self.addCleanup(patcher.stop)


class TestActionRecords(OutcomeCase):
    def test_plan_hash_detects_tampering(self):
        value = outcomes.start("a1", capability="email.send", provider="local", intent="send",
                               plan={"to": "x@example.com"})
        value["plan"]["to"] = "attacker@example.com"
        outcomes.write_json_atomic(outcomes._path("a1"), value)
        with self.assertRaises(ValueError):
            outcomes.load("a1")

    def test_success_requires_evidence_before_verified(self):
        outcomes.start("a1", capability="x", provider="local", intent="do x", plan={"x": 1})
        outcomes.add_attempt("a1", outcome="SUCCEEDED")
        with self.assertRaises(ValueError):
            outcomes.verify("a1")
        outcomes.add_evidence("a1", "e1", kind="equals", observed=2, expected=2)
        self.assertEqual(outcomes.verify("a1")["status"], "VERIFIED")

    def test_failed_evidence_becomes_retryable(self):
        outcomes.start("a1", capability="x", provider="local", intent="do x", plan={})
        outcomes.add_attempt("a1", outcome="SUCCEEDED")
        outcomes.add_evidence("a1", "e1", kind="truthy", observed=False)
        self.assertEqual(outcomes.verify("a1")["status"], "FAILED_RETRYABLE")

    def test_terminal_action_cannot_take_another_attempt(self):
        outcomes.start("a1", capability="x", provider="local", intent="do x", plan={})
        outcomes.add_attempt("a1", outcome="FAILED_TERMINAL")
        with self.assertRaises(ValueError):
            outcomes.add_attempt("a1", outcome="SUCCEEDED")

    def test_cancel_is_idempotent(self):
        outcomes.start("a1", capability="x", provider="local", intent="do x", plan={})
        self.assertEqual(outcomes.cancel("a1", "operator stopped")["status"], "CANCELLED")
        self.assertEqual(outcomes.cancel("a1", "again")["result"], "operator stopped")


if __name__ == "__main__":
    unittest.main()
