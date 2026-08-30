"""API-credential standing permission is local, expiring and budgeted."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, policy, secret_trust


class SecretTrustCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        patches = [
            mock.patch.object(secret_trust, "GRANT_PATH", root / "grant.json"),
            mock.patch.object(secret_trust, "CLAIMS_DIR", root / "claims"),
            mock.patch.object(journal, "JOURNAL_PATH", root / "journal.jsonl"),
            mock.patch.object(policy, "APPROVALS_DIR", root / "approvals"),
            mock.patch.object(policy, "HALT_PATH", root / "halt.json"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.now = dt.datetime(2026, 8, 30, 2, 0, tzinfo=dt.timezone.utc)

    def test_enable_is_bounded_and_operator_approved(self):
        grant = secret_trust.enable(days=7, max_actions=3, now=self.now, via="test")
        self.assertTrue(policy.is_approved(grant["approval_id"]))
        status = secret_trust.status(now=self.now)
        self.assertTrue(status["active"])
        self.assertEqual(status["actions_left"], 3)
        self.assertIn("no passwords/2FA", status["scope"])

    def test_expiry_and_disable_end_authority(self):
        secret_trust.enable(days=1, now=self.now, via="test")
        self.assertIsNone(secret_trust.active(now=self.now + dt.timedelta(days=2)))
        self.assertTrue(secret_trust.disable(via="test"))
        self.assertIsNone(secret_trust.active(now=self.now))

    def test_claims_are_hard_budget_and_contain_no_secret_value(self):
        secret_trust.enable(days=1, max_actions=1, now=self.now, via="test")
        claim = secret_trust.claim("create_capture", host="api.example.com", alias="main-key")
        self.assertEqual(claim["host"], "api.example.com")
        self.assertEqual(claim["alias"], "main-key")
        self.assertNotIn("value", claim)
        with self.assertRaises(secret_trust.SecretTrustRequired):
            secret_trust.claim("fill_alias", host="api.example.com", alias="main-key")

    def test_kill_switch_beats_live_secret_grant(self):
        secret_trust.enable(days=1, now=self.now, via="test")
        policy.halt("test", via="test")
        with self.assertRaises(policy.Halted):
            secret_trust.claim("fill_alias", host="api.example.com", alias="main-key")

    def test_limits_fail_closed(self):
        with self.assertRaises(ValueError):
            secret_trust.enable(days=0, now=self.now)
        with self.assertRaises(ValueError):
            secret_trust.enable(max_actions=secret_trust.MAX_ACTIONS + 1, now=self.now)


if __name__ == "__main__":
    unittest.main()
