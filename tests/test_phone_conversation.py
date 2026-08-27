import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import calls, journal, phone_conversation, policy


class PhoneConversationCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for target, name, path in [
            (calls, "PLANS_DIR", root / "plans"),
            (calls, "AUTH_DIR", root / "auth"),
            (calls, "RESULTS_DIR", root / "results"),
            (policy, "APPROVALS_DIR", root / "approvals"),
            (policy, "HALT_PATH", root / "halt.json"),
            (journal, "JOURNAL_PATH", root / "journal.jsonl"),
        ]:
            p = mock.patch.object(target, name, path); p.start(); self.addCleanup(p.stop)
        plan = calls.propose(
            "doctor", contact_ref="doctor-office", purpose="ask for appointment options",
            allowed_disclosures=["name", "availability"],
            forbidden_topics=["payment card", "medical consent"],
            success_condition="collect appointment choices after 5:30", max_minutes=8)
        policy.request("call-ok", calls.approval_action(plan), reason="operator asked",
                       consequence="phone call", reversible=False)
        policy.decide("call-ok", "APPROVED", via="test")
        calls.authorize("doctor", "call-ok")

    def test_brief_carries_exact_identity_and_boundaries(self):
        brief = phone_conversation.build("doctor")
        self.assertEqual(brief["identity_disclosure"], calls.IDENTITY_DISCLOSURE)
        self.assertEqual(brief["allowed_disclosures"], ["name", "availability"])
        self.assertIn("payment card", brief["forbidden_topics"])
        self.assertEqual(brief["max_minutes"], 8)
        self.assertEqual(phone_conversation.validate(brief, "doctor"), brief)

    def test_tampered_brief_is_refused(self):
        brief = phone_conversation.build("doctor")
        brief["forbidden_topics"] = []
        with self.assertRaises(ValueError):
            phone_conversation.validate(brief, "doctor")

    def test_rehashing_tampered_content_still_refused_against_approved_plan(self):
        brief = phone_conversation.build("doctor")
        brief["allowed_disclosures"].append("social security number")
        material = {k:v for k,v in brief.items() if k != "brief_sha256"}
        brief["brief_sha256"] = phone_conversation._hash(material)
        with self.assertRaisesRegex(ValueError, "does not match"):
            phone_conversation.validate(brief, "doctor")

    def test_provider_prompt_contains_no_extra_operator_authority(self):
        brief = phone_conversation.build("doctor")
        prompt = phone_conversation.provider_prompt(brief, "doctor")
        self.assertIn(calls.IDENTITY_DISCLOSURE, prompt)
        self.assertIn("payment card", prompt)
        self.assertIn("medical consent", prompt)
        self.assertIn("Maximum call duration: 8 minutes", prompt)
        self.assertNotIn("pretend to be", prompt.lower())

    def test_halt_blocks_brief_generation_through_execution_envelope(self):
        policy.halt("stop calls", via="test")
        with self.assertRaises(policy.Halted):
            phone_conversation.build("doctor")


if __name__ == "__main__":
    unittest.main()
