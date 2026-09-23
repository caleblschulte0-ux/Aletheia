"""His words, the morning of 2026-09-23: "Yeah, it can make its own accounts.
I don't give a shit." Five "press 'Create Account'" approvals from the
general browser's job missions sat on his page when he said it; nothing
could spend the jobs grant on them because the loop asks `web.commit`, a
word the registry does not know. The grant covers the ACT the button is."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import authority, campaign, capabilities, journal, jobs_grant, policy, standing


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(root / "private")})
        env.start(); self.addCleanup(env.stop)
        for module, attr, value in (
                (authority, "GRANTS_DIR", root / "grants"),
                (authority, "CLAIMS_DIR", root / "claims"),
                (policy, "APPROVALS_DIR", root / "approvals"),
                (journal, "JOURNAL_PATH", root / "journal.jsonl")):
            p = mock.patch.object(module, attr, value)
            p.start(); self.addCleanup(p.stop)


def pending(aid, reason):
    return policy.request(aid, "click Create Account", reason=reason,
                          consequence="presses it", reversible=False, capability="web.commit")


def old_grant():
    """A jobs grant from before accounts were hers, made the way a grant is made."""
    policy.request("standing-jobs-old", "standing authority over application.submit", reason="test",
                   consequence="test", reversible=True)
    policy.decide("standing-jobs-old", "APPROVED", via="operator")
    return authority.create("standing-jobs-old", capability_ids=["application.submit"],
                            approval_id="standing-jobs-old", expires="2099-01-01T00:00:00Z", max_uses=10)


class TheRegistryAndTheGrant(Isolated):
    def test_account_creation_is_grantable_on_his_words(self):
        self.assertEqual(capabilities.get("account.create")["approval_policy"], "registry_grant")
        self.assertIn("account.create", standing.JOBS_CAPABILITIES)
        self.assertIn("application.submit", standing.JOBS_CAPABILITIES)

    def test_the_grant_covers_both_and_an_old_grant_is_replaced(self):
        old = old_grant()
        grant = standing.jobs_enable(quote="it can make its own accounts")
        self.assertNotEqual(grant["id"], old["id"])
        self.assertEqual(sorted(grant["capability_ids"]), ["account.create", "application.submit"])
        self.assertFalse(authority.load(old["id"])["enabled"], "the narrower grant is revoked")
        self.assertEqual(standing.jobs_enable()["id"], grant["id"], "a grant that already covers both is kept")
        self.assertTrue(standing.jobs_status()["accounts"])


class WhichActTheButtonIs(unittest.TestCase):
    def test_a_job_missions_buttons(self):
        job = {"id": "bm-apply-for-this-job-cc109e843e", "gate": {"button": "Create Account"}}
        self.assertEqual(jobs_grant.capability_for(job), "account.create")
        for label in ("Sign up", "Register", "Create an account", "Join now"):
            self.assertEqual(jobs_grant.capability_for({**job, "gate": {"button": label}}), "account.create", label)
        for label in ("send", "Submit application", "Apply"):
            self.assertEqual(jobs_grant.capability_for({**job, "gate": {"button": label}}), "application.submit", label)
        self.assertEqual(jobs_grant.capability_for({**job, "gate": {"button": "Next"},
                                                    "boundary": {"kind": "ACCOUNT_CREATION_APPROVAL"}}),
                         "account.create")

    def test_a_mission_of_his_own_is_not_the_hunts(self):
        self.assertIsNone(jobs_grant.capability_for({"id": "bm-order-flowers-1", "gate": {"button": "Create Account"}}))
        self.assertIsNone(jobs_grant.capability_for(None))


class TheBeatApprovesUnderTheGrant(Isolated):
    MISSIONS = {
        "bm-apply-for-this-job-aaaa": {"id": "bm-apply-for-this-job-aaaa", "gate": {"button": "Create Account"}},
        "bm-apply-for-this-job-bbbb": {"id": "bm-apply-for-this-job-bbbb", "gate": {"button": "send"}},
        "bm-buy-a-lamp-cccc": {"id": "bm-buy-a-lamp-cccc", "gate": {"button": "Create Account"}},
    }

    def test_job_missions_are_approved_and_his_own_wait(self):
        standing.jobs_enable(quote="it can make its own accounts")
        pending("bm-apply-for-this-job-aaaa--g2-commit-9c26e1001990", "press 'Create Account' for CSM — Autodesk")
        pending("bm-apply-for-this-job-bbbb--g2-commit-8bc97fc04266", "press 'send' for Account Manager II — PNC")
        pending("bm-buy-a-lamp-cccc--g2-commit-0000000000aa", "press 'Create Account' on a lamp shop")
        decided = jobs_grant.approve_under_the_grant(load_mission=lambda mid: self.MISSIONS[mid])
        self.assertEqual(sorted(d["capability"] for d in decided), ["account.create", "application.submit"])
        self.assertEqual(policy.load("bm-apply-for-this-job-aaaa--g2-commit-9c26e1001990")["state"], "APPROVED")
        self.assertEqual(policy.load("bm-apply-for-this-job-bbbb--g2-commit-8bc97fc04266")["state"], "APPROVED")
        self.assertEqual(policy.load("bm-buy-a-lamp-cccc--g2-commit-0000000000aa")["state"], "PENDING")
        self.assertEqual(policy.load("bm-apply-for-this-job-aaaa--g2-commit-9c26e1001990")["decided_via"],
                         "standing-grant")
        self.assertIn("approved under the jobs grant (account.create)",
                      journal.JOURNAL_PATH.read_text(encoding="utf-8"))
        # decided once: a second pass finds nothing pending and spends nothing more
        self.assertEqual(jobs_grant.approve_under_the_grant(load_mission=lambda mid: self.MISSIONS[mid]), [])

    def test_without_a_grant_nothing_is_approved(self):
        pending("bm-apply-for-this-job-aaaa--g2-commit-9c26e1001990", "press 'Create Account' for CSM — Autodesk")
        self.assertEqual(jobs_grant.approve_under_the_grant(load_mission=lambda mid: self.MISSIONS[mid]), [])
        self.assertEqual(policy.load("bm-apply-for-this-job-aaaa--g2-commit-9c26e1001990")["state"], "PENDING")

    def test_a_grant_without_accounts_sends_but_makes_no_account(self):
        old_grant()
        pending("bm-apply-for-this-job-aaaa--g2-commit-9c26e1001990", "press 'Create Account' for CSM — Autodesk")
        pending("bm-apply-for-this-job-bbbb--g2-commit-8bc97fc04266", "press 'send' for Account Manager II — PNC")
        decided = jobs_grant.approve_under_the_grant(load_mission=lambda mid: self.MISSIONS[mid])
        self.assertEqual([d["capability"] for d in decided], ["application.submit"])
        self.assertEqual(policy.load("bm-apply-for-this-job-aaaa--g2-commit-9c26e1001990")["state"], "PENDING")


class AnAnswerGivenMidBatchIsKept(unittest.TestCase):
    def test_kept_when_the_process_cannot_start(self):
        kept = {}
        with mock.patch.object(campaign, "_launch", return_value={"started": False, "why": "a batch is running"}), \
             mock.patch.object(campaign, "open_questions", return_value=[
                 {"label": "Country dropdown (the page would not take the answer I have)", "url": "https://x"}]), \
             mock.patch("aletheia.profile.remember_question",
                        side_effect=lambda label, value, source="operator": kept.update({label: value}) or {"ok": 1}):
            out = campaign.start_answer("Country dropdown", "United States")
        self.assertTrue(out["kept"])
        self.assertEqual(kept, {"Country dropdown (the page would not take the answer I have)": "United States"})
        self.assertIn("kept that", campaign.answer_words(out))

    def test_a_started_answer_is_unchanged(self):
        with mock.patch.object(campaign, "_launch", return_value={"started": True}):
            out = campaign.start_answer("the relocation one", "yes")
        self.assertNotIn("kept", out)
        self.assertIn("Got it", campaign.answer_words(out))


if __name__ == "__main__":
    unittest.main()
