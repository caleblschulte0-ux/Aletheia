import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import outcomes, verification


class VerificationCase(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        p=mock.patch.object(outcomes,"ACTIONS_DIR",Path(self.tmp.name)/"actions"); p.start(); self.addCleanup(p.stop)

    def test_browser_execution_is_not_goal_verification(self):
        a=verification.execution_record(
            "browser.interact",provider="aletheia.local",intent="submit form",plan={"steps":["click"]},
            succeeded=True,result_summary="steps ran",
            evidence=[{"id":"steps","kind":"equals","observed":1,"expected":1}])
        self.assertEqual(a["status"],"AWAITING_VERIFICATION")
        self.assertFalse(verification.profile("browser.interact")["auto_verify_execution"])

    def test_email_send_is_not_auto_verified(self):
        a=verification.execution_record(
            "email.send",provider="smtp",intent="send message",plan={"draft":"hash"},
            succeeded=True,result_summary="smtp accepted",
            evidence=[{"id":"smtp","kind":"truthy","observed":True}])
        self.assertEqual(a["status"],"AWAITING_VERIFICATION")

    def test_computer_readback_can_auto_verify_bounded_plan(self):
        a=verification.execution_record(
            "computer.control",provider="windows-uia",intent="type scratch text",plan={"text":"abc"},
            succeeded=True,result_summary="readback matched",
            evidence=[{"id":"readback","kind":"equals","observed":"abc","expected":"abc"}])
        self.assertEqual(a["status"],"VERIFIED")

    def test_calendar_provider_state_can_auto_verify(self):
        a=verification.execution_record(
            "calendar.write",provider="fake.calendar",intent="create event",plan={"title":"Meet"},
            succeeded=True,result_summary="provider matched",
            evidence=[{"id":"provider","kind":"truthy","observed":True}])
        self.assertEqual(a["status"],"VERIFIED")

    def test_failure_is_retryable_without_fake_evidence(self):
        a=verification.execution_record(
            "automation.execute",provider="aletheia.local",intent="scheduled command",plan={"id":"x"},
            succeeded=False,result_summary="transport failure")
        self.assertEqual(a["status"],"FAILED_RETRYABLE")
        self.assertEqual(a["evidence"],[])

    def test_deterministic_action_reuse_requires_same_plan(self):
        aid=verification.new_action_id("automation.execute",seed={"schedule":"x","occurrence":"1"})
        verification.begin("automation.execute",provider="local",intent="x",plan={"a":1},action_id=aid)
        self.assertEqual(verification.begin("automation.execute",provider="local",intent="x",plan={"a":1},action_id=aid)["id"],aid)
        with self.assertRaises(ValueError):
            verification.begin("automation.execute",provider="local",intent="x",plan={"a":2},action_id=aid)


if __name__=="__main__": unittest.main()
