"""Standing authority that is actually spent — and the ceiling on it.

`aletheia.authority` could record delegated authority since the systems
layer landed, and nothing consumed it: grants were written, `allows()` was
tested, and every approval still went to the operator anyway. A grant
nobody consumes is a promise, not a permission.

The consumer is `policy.request(..., capability=...)`. What matters most
here is what a grant can NEVER reach.
"""
import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import authority, capabilities, journal, policy


def tomorrow() -> str:
    return (dt.datetime.now(dt.timezone.utc)
            + dt.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


class GrantConsumptionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ,
                              {"ALETHEIA_PRIVATE_STATE": str(root / "private")})
        env.start(); self.addCleanup(env.stop)
        for module, attr, value in (
                (authority, "GRANTS_DIR", root / "grants"),
                (authority, "CLAIMS_DIR", root / "claims"),
                (policy, "APPROVALS_DIR", root / "approvals"),
                (journal, "JOURNAL_PATH", root / "journal.jsonl")):
            p = mock.patch.object(module, attr, value)
            p.start(); self.addCleanup(p.stop)
        (root / "approvals").mkdir(parents=True, exist_ok=True)

    def standing_approval(self, aid="ap-standing"):
        policy.request(aid, "grant standing authority", "he said so",
                       "she stops asking about this class of thing", True)
        policy.decide(aid, "APPROVED", via="operator")
        return aid

    def grant(self, capability_ids, grant_id="g1", **kw):
        return authority.create(grant_id, capability_ids=capability_ids,
                                approval_id=self.standing_approval(),
                                expires=tomorrow(), **kw)

    def ask(self, aid, capability):
        return policy.request(aid, f"do {capability}", "because", "something happens",
                              True, capability=capability)

    # ---- the ceiling: what a grant can never reach --------------------

    def test_a_grant_cannot_be_created_over_a_high_risk_capability(self):
        for cid in ("email.send", "errand.run", "intent.execute",
                    "browser.interact", "computer.control"):
            with self.assertRaises(ValueError, msg=cid):
                self.grant([cid], grant_id=f"g-{cid.replace('.', '-')}")

    def test_high_risk_approvals_stay_pending_even_with_grants_around(self):
        self.grant(["agent.delegate"])
        approval = self.ask("ap-mail", "email.send")
        self.assertEqual(approval["state"], "PENDING")
        self.assertNotIn("decided_via", approval)

    def test_a_grant_forged_to_cover_a_high_risk_capability_is_still_refused(self):
        # defence in depth: allows() re-checks the registry at spend time,
        # so a grant file edited on disk buys nothing
        grant = self.grant(["agent.delegate"])
        grant["capability_ids"].append("email.send")
        from aletheia import stateio
        stateio.write_json_atomic(authority._path("g1"), grant)
        self.assertIsNone(authority.satisfy("email.send", "act-1"))
        self.assertEqual(self.ask("ap-mail", "email.send")["state"], "PENDING")

    # ---- the ordinary case --------------------------------------------

    def test_a_covered_capability_is_approved_by_the_grant(self):
        self.grant(["agent.delegate"])
        approval = self.ask("ap-1", "agent.delegate")
        self.assertEqual(approval["state"], "APPROVED")
        self.assertEqual(approval["decided_via"], "grant:g1")
        self.assertEqual(approval["capability"], "agent.delegate")

    def test_without_a_grant_the_same_ask_waits_for_him(self):
        self.assertEqual(self.ask("ap-1", "agent.delegate")["state"], "PENDING")

    def test_a_request_with_no_capability_is_unchanged(self):
        self.grant(["agent.delegate"])
        approval = policy.request("ap-x", "something", "r", "c", True)
        self.assertEqual(approval["state"], "PENDING")

    def test_every_grant_use_leaves_a_claim_receipt(self):
        self.grant(["agent.delegate"], max_uses=5)
        self.ask("ap-1", "agent.delegate")
        self.assertEqual(len(authority._claims("g1")), 1)

    def test_the_grant_that_authorized_it_is_journaled(self):
        self.grant(["agent.delegate"])
        self.ask("ap-1", "agent.delegate")
        rows = [e for e in journal.entries(journal.JOURNAL_PATH)
                if e["subject"] == "approval:ap-1"]
        self.assertEqual(rows[-1]["kind"], "decision")
        self.assertIn("standing grant g1", rows[-1]["text"])

    # ---- the bounds ----------------------------------------------------

    def test_a_grant_stops_working_when_its_uses_run_out(self):
        self.grant(["agent.delegate"], max_uses=2)
        self.assertEqual(self.ask("ap-1", "agent.delegate")["state"], "APPROVED")
        self.assertEqual(self.ask("ap-2", "agent.delegate")["state"], "APPROVED")
        self.assertEqual(self.ask("ap-3", "agent.delegate")["state"], "PENDING")

    def test_a_revoked_grant_stops_authorizing_immediately(self):
        self.grant(["agent.delegate"])
        self.assertEqual(self.ask("ap-1", "agent.delegate")["state"], "APPROVED")
        authority.revoke("g1")
        self.assertEqual(self.ask("ap-2", "agent.delegate")["state"], "PENDING")

    def test_an_expired_grant_authorizes_nothing(self):
        self.grant(["agent.delegate"])
        later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2)
        self.assertIsNone(authority.satisfy("agent.delegate", "act-1", now=later))
        self.assertEqual(authority.active_grants(now=later), [])

    def test_a_grant_does_not_leak_to_a_capability_it_does_not_name(self):
        self.grant(["agent.delegate"])
        self.assertEqual(self.ask("ap-1", "audio.route")["state"], "PENDING")

    def test_a_corrupt_grant_file_authorizes_nothing(self):
        self.grant(["agent.delegate"])
        authority._path("g1").write_text("{ broken", encoding="utf-8")
        self.assertEqual(authority.active_grants(), [])
        self.assertEqual(self.ask("ap-1", "agent.delegate")["state"], "PENDING")

    def test_a_broken_grant_store_never_approves_by_accident(self):
        # policy must fail CLOSED if authority itself raises
        with mock.patch.object(authority, "satisfy",
                               side_effect=RuntimeError("disk gone")):
            self.assertEqual(self.ask("ap-1", "agent.delegate")["state"], "PENDING")

    def test_one_claim_cannot_be_double_spent(self):
        self.grant(["agent.delegate"], max_uses=5)
        self.assertIsNotNone(authority.satisfy("agent.delegate", "act-1"))
        # the same action id again writes no second receipt
        self.assertIsNone(authority.satisfy("agent.delegate", "act-1"))
        self.assertEqual(len(authority._claims("g1")), 1)


class RegistryTruthCase(unittest.TestCase):
    def test_the_dangerous_capabilities_are_all_declared_ungrantable(self):
        # This is what makes the L4 rule structural rather than remembered:
        # anything that spends, sends, binds or destroys must be declared
        # high-risk or operator_always in the registry itself.
        for cid in ("purchase.execute", "finance.transact", "subscription.cancel",
                    "reservation.book", "email.send", "errand.run",
                    "intent.execute", "computer.control", "browser.interact"):
            entry = capabilities.get(cid)
            self.assertTrue(
                entry["risk_class"] == "high"
                or entry["approval_policy"] == "operator_always",
                f"{cid} could be covered by a standing grant")


if __name__ == "__main__":
    unittest.main()
