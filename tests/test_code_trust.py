import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import code_trust, journal, policy


class CodeTrustCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        patches = [
            mock.patch.object(code_trust, "GRANT_PATH", root / "grant.json"),
            mock.patch.object(code_trust, "CLAIMS_DIR", root / "claims"),
            mock.patch.object(journal, "JOURNAL_PATH", root / "journal.jsonl"),
            mock.patch.object(policy, "APPROVALS_DIR", root / "approvals"),
            mock.patch.object(policy, "HALT_PATH", root / "halt.json"),
            mock.patch.object(code_trust, "load_fleet", return_value={"owner": "me"}),
        ]
        for patch in patches:
            patch.start(); self.addCleanup(patch.stop)
        self.now = dt.datetime.now(dt.timezone.utc)

    def enable(self, **kw):
        return code_trust.enable(now=self.now, via="test", **kw)

    def test_enable_is_bounded_and_operator_approved(self):
        grant = self.enable(days=5, max_prs=2)
        self.assertTrue(policy.is_approved(grant["approval_id"]))
        self.assertTrue(code_trust.active(now=self.now))
        self.assertIn("no default-branch", grant["scope"])

    def test_private_repo_is_refused_before_claim_consumption(self):
        self.enable(max_prs=2)
        with self.assertRaises(code_trust.CodeTrustRequired):
            code_trust.claim(repo_full_name="me/private", private=True, task_id="fix-one")
        self.assertEqual(code_trust.status(now=self.now)["used"], 0)

    def test_claims_are_owner_scoped_and_budgeted(self):
        self.enable(max_prs=1)
        claim = code_trust.claim(repo_full_name="me/public", private=False, task_id="fix-one")
        self.assertEqual(claim["slot"], 1)
        self.assertEqual(code_trust.status(now=self.now)["prs_left"], 0)
        with self.assertRaises(code_trust.CodeTrustRequired):
            code_trust.claim(repo_full_name="me/public", private=False, task_id="fix-two")

    def test_foreign_owner_is_refused(self):
        self.enable()
        with self.assertRaises(code_trust.CodeTrustRequired):
            code_trust.claim(repo_full_name="someone/public", private=False, task_id="fix-one")

    def test_kill_switch_wins(self):
        self.enable()
        policy.halt("stop", via="test")
        with self.assertRaises(policy.Halted):
            code_trust.claim(repo_full_name="me/public", private=False, task_id="fix-one")


if __name__ == "__main__":
    unittest.main()
