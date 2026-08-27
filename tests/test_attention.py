import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import attention, notifications


class AttentionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        patches = [
            mock.patch.object(attention, "POLICY_PATH", root / "policy.json"),
            mock.patch.object(attention, "DELIVERY_DIR", root / "delivery"),
            mock.patch.object(notifications, "NOTICES_DIR", root / "notifications"),
        ]
        for patch in patches:
            patch.start(); self.addCleanup(patch.stop)

    def notice(self, priority="NORMAL", created="2026-08-27T02:00:00Z", key="n"):
        with mock.patch.object(notifications, "utcnow", return_value=created):
            return notifications.publish("Test notice", "Something happened", priority=priority,
                                         dedupe_key=key, source="test")

    def quiet_policy(self, *, bypass=None, escalations=None):
        return attention.configure(
            quiet_enabled=True, timezone="America/Chicago",
            quiet_start="22:00", quiet_end="07:00",
            bypass_priorities=bypass or [], escalations=escalations or [])

    def test_zero_intrusion_defaults_are_ready_and_never_escalate(self):
        notice = self.notice()
        now = dt.datetime(2026, 8, 27, 3, 0, tzinfo=dt.timezone.utc)
        record = attention.reconcile_notice(notice, now=now)
        self.assertEqual(record["state"], "READY")
        self.assertEqual(record["effective_priority"], "NORMAL")
        self.assertEqual(record["escalations"], [])

    def test_cross_midnight_quiet_hours_defer_until_local_morning(self):
        policy = self.quiet_policy()
        notice = self.notice(created="2026-08-27T02:30:00Z")  # 21:30 CDT, just before quiet
        now = dt.datetime(2026, 8, 27, 4, 0, tzinfo=dt.timezone.utc)  # 23:00 CDT
        record = attention.reconcile_notice(notice, now=now, policy_value=policy)
        self.assertEqual(record["state"], "DEFERRED")
        self.assertEqual(record["deliver_after"], "2026-08-27T12:00:00Z")  # 07:00 CDT

    def test_same_day_quiet_window_is_supported(self):
        policy = attention.configure(quiet_enabled=True, timezone="America/Chicago",
                                     quiet_start="13:00", quiet_end="15:00")
        notice = self.notice(created="2026-08-27T18:15:00Z")
        now = dt.datetime(2026, 8, 27, 19, 0, tzinfo=dt.timezone.utc)  # 14:00 CDT
        record = attention.reconcile_notice(notice, now=now, policy_value=policy)
        self.assertEqual(record["state"], "DEFERRED")
        self.assertEqual(record["deliver_after"], "2026-08-27T20:00:00Z")

    def test_urgent_only_bypasses_quiet_when_configured(self):
        notice = self.notice(priority="URGENT")
        now = dt.datetime(2026, 8, 27, 5, 0, tzinfo=dt.timezone.utc)  # midnight CDT
        blocked = attention.reconcile_notice(notice, now=now, policy_value=self.quiet_policy())
        self.assertEqual(blocked["state"], "DEFERRED")
        # Fresh attention store for the same notice under an explicit bypass policy.
        attention._delivery_path(notice["id"]).unlink()
        ready = attention.reconcile_notice(notice, now=now,
                                           policy_value=self.quiet_policy(bypass=["URGENT"]))
        self.assertEqual(ready["state"], "READY")
        self.assertTrue(ready["quiet_bypassed"])

    def test_chained_escalation_uses_age_from_original_notice(self):
        policy = attention.configure(
            escalations=[
                {"from":"NORMAL", "to":"IMPORTANT", "after_minutes":30},
                {"from":"IMPORTANT", "to":"URGENT", "after_minutes":120},
            ])
        notice = self.notice(created="2026-08-27T00:00:00Z")
        at_45 = attention.reconcile_notice(
            notice, now=dt.datetime(2026,8,27,0,45,tzinfo=dt.timezone.utc), policy_value=policy)
        self.assertEqual(at_45["effective_priority"], "IMPORTANT")
        at_180 = attention.reconcile_notice(
            notice, now=dt.datetime(2026,8,27,3,0,tzinfo=dt.timezone.utc), policy_value=policy)
        self.assertEqual(at_180["effective_priority"], "URGENT")
        self.assertEqual(len(at_180["escalations"]), 2)

    def test_escalation_can_eventually_bypass_quiet_hours(self):
        policy = self.quiet_policy(
            bypass=["URGENT"],
            escalations=[
                {"from":"NORMAL", "to":"IMPORTANT", "after_minutes":30},
                {"from":"IMPORTANT", "to":"URGENT", "after_minutes":120},
            ])
        notice = self.notice(created="2026-08-27T01:00:00Z")  # 20:00 CDT
        now = dt.datetime(2026,8,27,5,0,tzinfo=dt.timezone.utc)  # midnight CDT, age 4h
        record = attention.reconcile_notice(notice, now=now, policy_value=policy)
        self.assertEqual(record["effective_priority"], "URGENT")
        self.assertEqual(record["state"], "READY")
        self.assertTrue(record["quiet_bypassed"])

    def test_acknowledgement_cancels_deferred_attention(self):
        policy = self.quiet_policy()
        notice = self.notice()
        now = dt.datetime(2026,8,27,5,0,tzinfo=dt.timezone.utc)
        self.assertEqual(attention.reconcile_notice(notice, now=now, policy_value=policy)["state"], "DEFERRED")
        notifications.set_state(notice["id"], "ACKNOWLEDGED")
        cancelled = attention.reconcile_notice(notifications.load(notice["id"]), now=now, policy_value=policy)
        self.assertEqual(cancelled["state"], "CANCELLED")

    def test_reconcile_is_idempotent_one_record_per_notice(self):
        notice = self.notice()
        now = dt.datetime(2026,8,27,3,0,tzinfo=dt.timezone.utc)
        first = attention.reconcile(now=now)
        second = attention.reconcile(now=now)
        self.assertEqual(first, second)
        self.assertEqual(len(list(attention.DELIVERY_DIR.glob("*.json"))), 1)

    def test_delivery_requires_ready_state_and_observed_evidence(self):
        notice = self.notice()
        now = dt.datetime(2026,8,27,3,0,tzinfo=dt.timezone.utc)
        attention.reconcile_notice(notice, now=now)
        with self.assertRaises(ValueError):
            attention.mark_delivered(notice["id"], provider="push", evidence="", now=now)
        delivered = attention.mark_delivered(notice["id"], provider="test-provider",
                                             evidence="provider receipt 123", now=now)
        self.assertEqual(delivered["state"], "DELIVERED")
        self.assertEqual(attention.mark_delivered(notice["id"], provider="ignored",
                                                 evidence="ignored", now=now), delivered)

    def test_invalid_escalation_chains_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "strictly increase"):
            attention.configure(escalations=[{"from":"IMPORTANT","to":"NORMAL","after_minutes":60}])
        with self.assertRaisesRegex(ValueError, "thresholds"):
            attention.configure(escalations=[
                {"from":"NORMAL","to":"IMPORTANT","after_minutes":120},
                {"from":"IMPORTANT","to":"URGENT","after_minutes":60},
            ])


if __name__ == "__main__":
    unittest.main()
