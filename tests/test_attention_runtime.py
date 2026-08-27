import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import attention, notifications, proactive, runtime


class AttentionRuntimeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for target, name, path in [
            (attention, "POLICY_PATH", root / "attention-policy.json"),
            (attention, "DELIVERY_DIR", root / "attention-delivery"),
            (notifications, "NOTICES_DIR", root / "notifications"),
            (proactive, "RULES_DIR", root / "rules"),
            (proactive, "RECEIPTS_DIR", root / "receipts"),
        ]:
            p = mock.patch.object(target, name, path); p.start(); self.addCleanup(p.stop)
        self.root = root

    def test_proactive_rule_carries_explicit_priority(self):
        rule = proactive.create_rule("urgent-mail", event_kind="mail.received", action="notify",
                                     priority="URGENT")
        event = {"id":"evt-1", "kind":"mail.received", "source":"mail",
                 "subject":"mail:x", "summary":"message"}
        receipt = proactive.evaluate(rule, event,
                                     now=dt.datetime(2026,8,27,3,0,tzinfo=dt.timezone.utc))
        self.assertEqual(receipt["priority"], "URGENT")
        self.assertEqual(receipt["proposal"]["priority"], "URGENT")

    def test_invalid_proactive_priority_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "priority"):
            proactive.create_rule("bad", event_kind="x", action="notify", priority="WAKE_THE_HOUSE")

    def test_runtime_attention_runs_after_schedule_failure_notification(self):
        attention.configure(quiet_enabled=True, timezone="America/Chicago",
                            quiet_start="22:00", quiet_end="07:00")
        now = dt.datetime(2026,8,27,5,0,tzinfo=dt.timezone.utc)  # midnight CDT
        fake_schedule = [{"schedule":"night-job", "outcome":"error",
                          "detail":"provider down", "occurrence":"2026-08-27T05:00:00Z"}]
        patches = [
            mock.patch.object(runtime, "run_due_schedules", return_value=fake_schedule),
            mock.patch.object(runtime, "poll_mail_events", return_value=[]),
            mock.patch.object(runtime, "mirror_pulse_events", return_value=[]),
            mock.patch.object(runtime.verification, "reconcile_durable_receipts", return_value=[]),
            mock.patch.object(runtime, "evaluate_replies", return_value=[]),
            mock.patch.object(runtime, "process_new_events", return_value=[]),
            mock.patch.object(runtime, "reconcile_task_gaps", return_value=[]),
            mock.patch.object(runtime.handler, "reconcile_all", return_value=[]),
        ]
        for patch in patches:
            patch.start(); self.addCleanup(patch.stop)
        result = runtime.tick({}, now=now)
        self.assertEqual(len(result["attention"]), 1)
        record = result["attention"][0]
        self.assertEqual(record["state"], "DEFERRED")
        self.assertEqual(record["original_priority"], "IMPORTANT")
        notices = notifications.all_notifications()
        self.assertEqual(len(notices), 1)
        self.assertIn("night-job", notices[0]["title"])

    def test_attention_failure_is_isolated_from_runtime(self):
        now = dt.datetime(2026,8,27,15,0,tzinfo=dt.timezone.utc)
        patches = [
            mock.patch.object(runtime, "run_due_schedules", return_value=[]),
            mock.patch.object(runtime, "poll_mail_events", return_value=[]),
            mock.patch.object(runtime, "mirror_pulse_events", return_value=[]),
            mock.patch.object(runtime.verification, "reconcile_durable_receipts", return_value=[]),
            mock.patch.object(runtime, "evaluate_replies", return_value=[]),
            mock.patch.object(runtime, "process_new_events", return_value=[]),
            mock.patch.object(runtime, "reconcile_task_gaps", return_value=[]),
            mock.patch.object(runtime.handler, "reconcile_all", return_value=[]),
            mock.patch.object(runtime.attention, "reconcile", side_effect=ValueError("bad policy")),
        ]
        for patch in patches:
            patch.start(); self.addCleanup(patch.stop)
        result = runtime.tick({}, now=now)
        self.assertEqual(result["attention"][0]["producer"], "attention")
        self.assertIn("bad policy", result["attention"][0]["detail"])


if __name__ == "__main__":
    unittest.main()
