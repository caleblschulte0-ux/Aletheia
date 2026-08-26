"""The phone-call and purchase authorization layers (ChatGPT branch 2 keepers).

Neither module can touch the world: calls.py cannot dial, purchases.py has no
checkout. What these tests hold is the AUTHORITY shape — content-bound
approvals, unalterable identity disclosure, halt supremacy, exactly-once
records — so a future adapter inherits gates that already work.
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import calls, policy, purchases


class GatedCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for module, attr, path in (
            (calls, "PLANS_DIR", root / "call-plans"),
            (calls, "AUTH_DIR", root / "call-auth"),
            (calls, "RESULTS_DIR", root / "call-results"),
            (purchases, "PROPOSALS_DIR", root / "buy-proposals"),
            (purchases, "AUTH_DIR", root / "buy-auth"),
            (purchases, "RESULTS_DIR", root / "buy-results"),
            (policy, "APPROVALS_DIR", root / "approvals"),
            (policy, "HALT_PATH", root / "halt.json"),
        ):
            patcher = mock.patch.object(module, attr, path)
            patcher.start(); self.addCleanup(patcher.stop)

    def approve(self, approval_id, action):
        policy.request(approval_id, action, "test", "test", reversible=True)
        return policy.decide(approval_id, "APPROVED", via="test", because="operator approved in test")


class TestCalls(GatedCase):
    def plan(self, cid="call-1"):
        return calls.propose(cid, contact_ref="contact:dentist",
                             purpose="reschedule the cleaning",
                             allowed_disclosures=["Caleb's first name"],
                             forbidden_topics=["payment details"], max_minutes=5)

    def test_identity_disclosure_cannot_be_altered(self):
        value = self.plan()
        self.assertIn("AI assistant", value["plan"]["identity_disclosure"])
        # tamper on disk -> load refuses (hash first, disclosure check backstop)
        import json
        path = calls._plan_path("call-1")
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["plan"]["identity_disclosure"] = "a human calling"
        path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(ValueError):
            calls.load_plan("call-1")

    def test_envelope_requires_bound_approval_and_no_halt(self):
        value = self.plan()
        with self.assertRaises((PermissionError, FileNotFoundError)):
            calls.authorize("call-1", "missing")  # no approval at all fails closed
        self.approve("ap-call", calls.approval_action(value))
        calls.authorize("call-1", "ap-call")
        envelope = calls.execution_envelope("call-1")
        self.assertEqual(envelope["plan"]["max_minutes"], 5)
        policy.halt("test stop", via="test")
        with self.assertRaises(policy.Halted):  # the kill switch outranks approval
            calls.execution_envelope("call-1")

    def test_wrong_approval_action_refused(self):
        self.plan()
        self.approve("ap-other", "authorize call other sha256:beef")
        with self.assertRaises(PermissionError):
            calls.authorize("call-1", "ap-other")

    def test_outcome_requires_authorization_and_records_once(self):
        value = self.plan()
        with self.assertRaises((ValueError, FileNotFoundError)):
            calls.record_outcome("call-1", status="COMPLETED", summary="done")
        self.approve("ap-call", calls.approval_action(value))
        calls.authorize("call-1", "ap-call")
        calls.record_outcome("call-1", status="NO_ANSWER", summary="rang out")
        with self.assertRaises(FileExistsError):
            calls.record_outcome("call-1", status="COMPLETED", summary="again")


class TestPurchases(GatedCase):
    ITEMS = [{"description": "desk chair", "quantity": 1, "unit_price": "149.99"}]

    def test_total_is_computed_and_hash_bound(self):
        value = purchases.propose("buy-1", merchant="Store", items=self.ITEMS)
        self.assertEqual(value["plan"]["total"], "149.99")
        import json
        path = purchases._proposal_path("buy-1")
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["plan"]["total"] = "0.01"  # tamper the price after proposing
        path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(ValueError):
            purchases.load_proposal("buy-1")

    def test_authorization_binds_to_exact_content(self):
        value = purchases.propose("buy-1", merchant="Store", items=self.ITEMS)
        self.approve("ap-buy", purchases.approval_action(value))
        purchases.authorize("buy-1", "ap-buy")
        envelope = purchases.execution_envelope("buy-1")
        self.assertEqual(envelope["plan"]["merchant"], "Store")
        # a second authorization cannot be created
        with self.assertRaises(FileExistsError):
            purchases.authorize("buy-1", "ap-buy")

    def test_result_records_total_mismatch_honestly(self):
        value = purchases.propose("buy-1", merchant="Store", items=self.ITEMS)
        self.approve("ap-buy", purchases.approval_action(value))
        purchases.authorize("buy-1", "ap-buy")
        result = purchases.record_result("buy-1", status="EXECUTED",
                                         order_reference="ord-9",
                                         observed_total="159.99")
        self.assertFalse(result["total_matches"])

    def test_money_validation_refuses_bad_amounts(self):
        for bad in ("-1.00", "1.999", "not-money"):
            with self.assertRaises(ValueError):
                purchases.propose(f"buy-{bad[:3].strip('-.')}" if bad[0].isalpha() else "buy-bad",
                                  merchant="Store",
                                  items=[{"description": "x", "quantity": 1, "unit_price": bad}])

    def test_expired_plan_cannot_be_authorized(self):
        future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=1)).isoformat()
        value = purchases.propose("buy-exp", merchant="Store", items=self.ITEMS,
                                  expires_at=future)
        self.approve("ap-exp", purchases.approval_action(value))
        import time
        time.sleep(1.2)
        with self.assertRaises(PermissionError):
            purchases.authorize("buy-exp", "ap-exp")


if __name__ == "__main__":
    unittest.main()
