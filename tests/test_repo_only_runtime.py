import datetime as dt
import tempfile
import unittest
from pathlib import Path

from aletheia import devices, proactive, recovery


class Rooted(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        proactive.RULES_DIR = root / "rules"
        proactive.RECEIPTS_DIR = root / "receipts"
        devices.DEVICES_DIR = root / "devices"

    def tearDown(self):
        self.tmp.cleanup()


class TestProactive(Rooted):
    def test_match_is_exact_and_bounded(self):
        rule = proactive.create_rule("r1", event_kind="task.failed", action="surface",
                                     source="tasks", subject_prefix="shorts")
        self.assertTrue(proactive.matches(rule, {"kind": "task.failed", "source": "tasks", "subject": "shorts-finalizer"}))
        self.assertFalse(proactive.matches(rule, {"kind": "task.failed", "source": "other", "subject": "shorts-finalizer"}))

    def test_event_dedupe(self):
        rule = proactive.create_rule("r1", event_kind="x", action="notify")
        event = {"id": "e1", "kind": "x"}
        now = dt.datetime(2026, 8, 26, 12, tzinfo=dt.timezone.utc)
        self.assertIsNotNone(proactive.evaluate(rule, event, now=now))
        self.assertIsNone(proactive.evaluate(rule, event, now=now))

    def test_cooldown(self):
        rule = proactive.create_rule("r1", event_kind="x", action="surface", cooldown_minutes=60)
        t0 = dt.datetime(2026, 8, 26, 12, tzinfo=dt.timezone.utc)
        self.assertIsNotNone(proactive.evaluate(rule, {"id": "e1", "kind": "x"}, now=t0))
        self.assertIsNone(proactive.evaluate(rule, {"id": "e2", "kind": "x"}, now=t0 + dt.timedelta(minutes=30)))
        self.assertIsNotNone(proactive.evaluate(rule, {"id": "e3", "kind": "x"}, now=t0 + dt.timedelta(minutes=61)))

    def test_rule_does_not_execute_action(self):
        rule = proactive.create_rule("r1", event_kind="x", action="enqueue")
        receipt = proactive.evaluate(rule, {"id": "e1", "kind": "x"},
                                     now=dt.datetime(2026, 8, 26, 12, tzinfo=dt.timezone.utc))
        self.assertEqual(receipt["proposal"]["kind"], "enqueue")


class TestRecovery(Rooted):
    def test_terminal_never_retries(self):
        self.assertEqual(recovery.next_step(failure_code="permission_denied", attempts=0, max_attempts=3)["decision"], "STOP")

    def test_retry_budget(self):
        self.assertEqual(recovery.next_step(failure_code="timeout", attempts=3, max_attempts=3)["reason"], "retry_budget_exhausted")

    def test_backoff_increases(self):
        self.assertLess(recovery.delay_seconds(1), recovery.delay_seconds(2))

    def test_jitter_is_deterministic(self):
        self.assertEqual(recovery.delay_seconds(3, jitter_key="task-a"),
                         recovery.delay_seconds(3, jitter_key="task-a"))

    def test_retry_has_due_time(self):
        now = dt.datetime(2026, 8, 26, 12, tzinfo=dt.timezone.utc)
        step = recovery.next_step(failure_code="transport", attempts=0, max_attempts=3, now=now)
        self.assertEqual(step["decision"], "RETRY")
        self.assertGreater(step["delay_seconds"], 0)


class TestDevices(Rooted):
    def test_unverified_device_cannot_be_used(self):
        d = devices.register("lamp", name="Lamp", kind="light", room="office",
                             provider="home-assistant", external_id="light.lamp", abilities=["on", "off"])
        with self.assertRaises(RuntimeError):
            devices.require_ability(d, "on")

    def test_observed_online_can_use_declared_ability(self):
        devices.register("lamp", name="Lamp", kind="light", room="office",
                         provider="home-assistant", external_id="light.lamp", abilities=["on", "off"])
        d = devices.mark_observed("lamp", online=True, observed_state={"on": False})
        devices.require_ability(d, "on")

    def test_undeclared_ability_refused(self):
        devices.register("lamp", name="Lamp", kind="light", room="office",
                         provider="ha", external_id="light.lamp", abilities=["on"])
        d = devices.mark_observed("lamp", online=True, observed_state={})
        with self.assertRaises(ValueError):
            devices.require_ability(d, "unlock")

    def test_room_filter(self):
        devices.register("lamp", name="Lamp", kind="light", room="Office", provider="ha", external_id="1", abilities=["on"])
        devices.register("tv", name="TV", kind="media", room="Living", provider="ha", external_id="2", abilities=["play"])
        self.assertEqual([d["id"] for d in devices.in_room("office")], ["lamp"])


if __name__ == "__main__":
    unittest.main()
