import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, mail, outcomes, policy, tasks, verification


class ReconcileCase(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        patches=[
            mock.patch.object(outcomes,"ACTIONS_DIR",root/"actions"),
            mock.patch.object(mail,"MAIL_DIR",root/"mail"),
            mock.patch.object(policy,"APPROVALS_DIR",root/"approvals"),
            mock.patch.object(policy,"HALT_PATH",root/"halt"),
            mock.patch.object(journal,"JOURNAL_PATH",root/"journal.jsonl"),
            mock.patch.object(tasks,"TASKS_DIR",root/"tasks"),
        ]
        for p in patches: p.start(); self.addCleanup(p.stop)

    def test_sent_mail_receipt_becomes_awaiting_delivery_verification(self):
        mail.MAIL_DIR.mkdir(parents=True); policy.request("mail-x","email.send:abc","test","sent",False); policy.decide("mail-x","APPROVED",via="test")
        (mail.MAIL_DIR/"mail-x.sent.json").write_text(json.dumps({"id":"mail-x","outcome":"sent","detail":"smtp accepted","at":"2026-08-26T20:00:00Z"}),encoding="utf-8")
        rows=verification.reconcile_mail_receipts()
        self.assertEqual(rows[0]["status"],"AWAITING_VERIFICATION")
        self.assertEqual(outcomes.load(rows[0]["action_record"])["capability"],"email.send")

    def test_completed_computer_run_auto_verifies(self):
        policy.request("comp-a","computer.control:hash","test","scratch",True); policy.decide("comp-a","APPROVED",via="test")
        journal.append("action","computer:run","COMPLETED run=computer-abc approval=comp-a steps=4")
        rows=verification.reconcile_computer_journal()
        self.assertEqual(rows[0]["status"],"VERIFIED")

    def test_browser_execution_waits_for_goal_proof(self):
        journal.append("action","browser:interact","https://example.test under approval browse-a -> 2 step(s)")
        rows=verification.reconcile_browser_journal()
        self.assertEqual(rows[0]["status"],"AWAITING_VERIFICATION")

    def test_agent_work_order_waits_then_completion_verifies(self):
        t=tasks.create("t1","Do work",assigned_worker="claude")
        tasks.set_status("t1","READY")
        tasks.set_status("t1","WAITING_EXTERNAL","work order issue #42 filed for claude")
        rows=verification.reconcile_agent_tasks(); self.assertEqual(rows[0]["status"],"AWAITING_VERIFICATION")
        tasks.set_status("t1","COMPLETED","work order issue #42 filed for claude; tests green")
        rows=verification.reconcile_agent_tasks(); self.assertEqual(rows[0]["status"],"VERIFIED")

    def test_reconciliation_is_idempotent(self):
        policy.request("comp-a","computer.control:hash","test","scratch",True); policy.decide("comp-a","APPROVED",via="test")
        journal.append("action","computer:run","COMPLETED run=computer-abc approval=comp-a steps=4")
        a=verification.reconcile_computer_journal()[0]
        b=verification.reconcile_computer_journal()[0]
        self.assertEqual(a,b)
        self.assertEqual(len(list(outcomes.ACTIONS_DIR.glob("*.json"))),1)


if __name__=="__main__": unittest.main()
