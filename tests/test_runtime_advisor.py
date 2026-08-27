import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import advisor, events, proactive, runtime


NOW = dt.datetime(2026, 8, 27, 18, 0, tzinfo=dt.timezone.utc)


class RuntimeAdvisorCase(unittest.TestCase):
    # NB: the helper below must not be called `run`. unittest calls
    # TestCase.run(result) to execute a test, so a helper of that name
    # replaces the runner itself and `unittest discover` dies with
    # "run() takes 1 positional argument but 2 were given" — taking the
    # WHOLE suite down, not just this file (found in review 2026-08-27).
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.events_dir = root / "events"
        self.watchers_dir = root / "watchers"
        self.cursor = root / "cursor.json"
        self.event = events.emit(
            "mail.reply", "thread:test", "Reply received", source="mail",
            event_id="evt-20260827T180000000000Z-test",
            occurred_at="2026-08-27T18:00:00Z",
            events_dir=self.events_dir, watchers_dir=self.watchers_dir)["event"]

    def process(self):
        return runtime.process_new_events(
            now=NOW, cursor_path=self.cursor,
            events_dir=self.events_dir, watchers_dir=self.watchers_dir)

    def test_enabled_advisor_result_is_folded_into_event_actions(self):
        with mock.patch.object(proactive, "all_rules", return_value=[]), \
             mock.patch.object(advisor, "evaluate_event",
                               return_value={"event": self.event["id"], "outcome": "notify"}) as judge:
            actions = self.process()
        judge.assert_called_once()
        self.assertIn({"event": self.event["id"], "action": "advisor_notify"}, actions)

    def test_disabled_advisor_none_adds_no_noise(self):
        with mock.patch.object(proactive, "all_rules", return_value=[]), \
             mock.patch.object(advisor, "evaluate_event", return_value=None):
            actions = self.process()
        self.assertFalse(any(a["action"].startswith("advisor_") for a in actions))

    def test_advisor_failure_is_sanitized_and_does_not_block_cursor(self):
        with mock.patch.object(proactive, "all_rules", return_value=[]), \
             mock.patch.object(advisor, "evaluate_event",
                               side_effect=RuntimeError("secret provider detail")):
            actions = self.process()
        advisor_actions = [a for a in actions if a["action"].startswith("advisor_")]
        self.assertEqual(advisor_actions, [{"event": self.event["id"],
                                            "action": "advisor_error",
                                            "error_type": "RuntimeError"}])
        self.assertNotIn("secret provider detail", str(actions))
        # Deterministic event handling advances even when optional advice fails.
        second = self.process()
        self.assertEqual(second, [])

    def test_advisor_is_called_after_deterministic_rule_processing(self):
        order = []
        rule = {"version": 1, "id": "r1", "event_kind": "mail.reply",
                "action": "notify", "cooldown_minutes": 0, "persistent": True,
                "enabled": True, "created_at": "2026-08-27T17:00:00Z",
                "priority": "NORMAL"}
        receipt = {"proposal": {"kind": "notify", "priority": "NORMAL"}}
        with mock.patch.object(proactive, "all_rules", return_value=[rule]), \
             mock.patch.object(proactive, "evaluate",
                               side_effect=lambda *a, **k: order.append("rule") or receipt), \
             mock.patch.object(advisor, "evaluate_event",
                               side_effect=lambda *a, **k: order.append("advisor") or None):
            self.process()
        self.assertEqual(order, ["rule", "advisor"])


if __name__ == "__main__":
    unittest.main()
