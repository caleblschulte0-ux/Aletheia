import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import act, journal, policy
from aletheia.fleet import load_fleet
from tests.test_capabilities import RecordingAPI


class PolicyCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        patches = [
            mock.patch.object(policy, "APPROVALS_DIR", base / "approvals"),
            mock.patch.object(policy, "HALT_PATH", base / "policy" / "halt.json"),
            mock.patch.object(journal, "JOURNAL_PATH", base / "journal.jsonl"),
        ]
        for p in patches:
            p.start(); self.addCleanup(p.stop)


class TestKillSwitch(PolicyCase):
    def test_halt_blocks_actions_until_resume(self):
        policy.halt("testing", via="test")
        with self.assertRaises(policy.Halted):
            policy.ensure_not_halted()
        fleet = load_fleet()
        with self.assertRaises(policy.Halted):
            act.dispatch(fleet, "aletheia", "pulse.yml", request=RecordingAPI())
        policy.resume(via="test")
        policy.ensure_not_halted()  # no raise

    def test_corrupt_halt_file_fails_closed(self):
        policy.HALT_PATH.parent.mkdir(parents=True, exist_ok=True)
        policy.HALT_PATH.write_text("{broken", encoding="utf-8")
        with self.assertRaises(policy.Halted):
            policy.ensure_not_halted()


class TestApprovals(PolicyCase):
    def _req(self, aid="ap-1"):
        return policy.request(aid, "send the email", "operator asked",
                              "email goes out", reversible=False, task="t1")

    def test_request_decide_roundtrip(self):
        self._req()
        self.assertFalse(policy.is_approved("ap-1"))
        policy.decide("ap-1", "APPROVED", via="test")
        self.assertTrue(policy.is_approved("ap-1"))

    def test_decided_approval_never_redecided(self):
        self._req()
        policy.decide("ap-1", "DENIED", via="test")
        with self.assertRaises(ValueError):
            policy.decide("ap-1", "APPROVED", via="test")

    def test_request_is_idempotent(self):
        first = self._req()
        again = self._req()
        self.assertEqual(first["requested_at"], again["requested_at"])

    def test_comment_decide_parses_owner_comment(self):
        self._req()
        out = policy.comment_decide(
            f"{policy.ISSUE_PREFIX} ap-1 — send the email", "approve", via="owner")
        self.assertEqual(out, "ap-1 -> APPROVED")

    def test_comment_decide_ignores_chatter(self):
        self._req()
        out = policy.comment_decide(
            f"{policy.ISSUE_PREFIX} ap-1 — send the email",
            "hmm what do you all think?", via="owner")
        self.assertIn("ignoring", out)
        self.assertFalse(policy.is_approved("ap-1"))

    def test_publish_files_issue(self):
        self._req()
        api = RecordingAPI()
        policy.publish("ap-1", "o/r", request_fn=api)
        method, path, body = api.calls[0]
        self.assertEqual((method, path), ("POST", "/repos/o/r/issues"))
        self.assertIn("ap-1", body["title"])


if __name__ == "__main__":
    unittest.main()
