import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import events, notifications, proactive, runtime, handler

UTC = dt.timezone.utc


class TestRuntime(unittest.TestCase):
    def test_due_schedule_revalidates_before_execution(self):
        spec = {"id": "s", "command": {"kind": "bad"}}
        with mock.patch.object(runtime.scheduler, "all_schedules", return_value=[spec]), \
             mock.patch.object(runtime.scheduler, "occurrence_at_or_before", return_value=dt.datetime(2026, 8, 26, tzinfo=UTC)), \
             mock.patch.object(runtime.intercom, "validate_kind_args", return_value=["bad kind"]), \
             mock.patch.object(runtime.scheduler, "claim_due") as claim:
            out = runtime.run_due_schedules({"repos": {}}, now=dt.datetime(2026, 8, 26, tzinfo=UTC))
        self.assertEqual(out[0]["outcome"], "invalid")
        claim.assert_not_called()

    def test_halt_prevents_schedule_claim(self):
        spec = {"id": "s", "command": {"kind": "note", "text": "x"}}
        with mock.patch.object(runtime.scheduler, "all_schedules", return_value=[spec]), \
             mock.patch.object(runtime.scheduler, "occurrence_at_or_before", return_value=dt.datetime(2026, 8, 26, tzinfo=UTC)), \
             mock.patch.object(runtime.intercom, "validate_kind_args", return_value=[]), \
             mock.patch.object(runtime.policy, "halted", return_value={"reason": "stop"}), \
             mock.patch.object(runtime.scheduler, "claim_due") as claim:
            out = runtime.run_due_schedules({"repos": {}}, now=dt.datetime(2026, 8, 26, tzinfo=UTC))
        self.assertEqual(out[0]["outcome"], "halted")
        claim.assert_not_called()

    def test_due_schedule_executes_exact_claim(self):
        spec = {"id": "s", "command": {"kind": "note", "text": "x"}}
        receipt = {"occurrence": "2026-08-26T12:00:00+00:00"}
        with mock.patch.object(runtime.scheduler, "all_schedules", return_value=[spec]), \
             mock.patch.object(runtime.scheduler, "occurrence_at_or_before", return_value=dt.datetime(2026, 8, 26, 12, tzinfo=UTC)), \
             mock.patch.object(runtime.intercom, "validate_kind_args", return_value=[]), \
             mock.patch.object(runtime.policy, "halted", return_value=None), \
             mock.patch.object(runtime.scheduler, "claim_due", return_value=receipt), \
             mock.patch.object(runtime.intercom, "execute_command", return_value="journaled") as execute:
            out = runtime.run_due_schedules({"repos": {}}, now=dt.datetime(2026, 8, 26, 12, tzinfo=UTC))
        self.assertEqual(out[0]["outcome"], "done")
        execute.assert_called_once()

    def test_reply_transition_publishes_notification(self):
        before = [{"id": "e", "status": "WAITING", "thread_id": "t"}]
        after = [{"id": "e", "status": "REPLIED", "thread_id": "t", "reply_message_id": "m"}]
        with mock.patch.object(runtime.communications, "all_expectations", return_value=before), \
             mock.patch.object(runtime.communications, "evaluate_all", return_value=after), \
             mock.patch.object(runtime.notifications, "publish") as publish:
            out = runtime.evaluate_replies(now=dt.datetime(2026, 8, 26, tzinfo=UTC))
        self.assertEqual(out[0]["to"], "REPLIED")
        publish.assert_called_once()

    def test_gap_materialization_pauses_task(self):
        task = {"id": "t", "status": "QUEUED", "required_capabilities": ["phone.call"]}
        report = {"available": [], "blocked": [{"id": "phone.call", "status": "NOT_BUILT"}],
                  "unknown": [], "satisfied": False}
        with mock.patch.object(runtime.tasks, "all_tasks", return_value=[task]), \
             mock.patch.object(runtime.gaps, "assess", return_value=report), \
             mock.patch.object(runtime.gaps, "materialize", return_value=[{"id": "build-phone-call"}]), \
             mock.patch.object(runtime.tasks, "set_status", return_value={"status": "WAITING_DEPENDENCY"}) as status:
            out = runtime.reconcile_task_gaps(registry={})
        self.assertEqual(out[0]["gap_tasks"], ["build-phone-call"])
        status.assert_called_once()

    def test_closed_gap_resumes_only_gap_blocked_task(self):
        task = {"id": "t", "status": "WAITING_DEPENDENCY", "result": "capability gap: x=NOT_BUILT",
                "required_capabilities": ["x"]}
        report = {"available": ["x"], "blocked": [], "unknown": [], "satisfied": True}
        with mock.patch.object(runtime.tasks, "all_tasks", return_value=[task]), \
             mock.patch.object(runtime.gaps, "assess", return_value=report), \
             mock.patch.object(runtime.tasks, "set_status", return_value={"status": "QUEUED"}) as status:
            out = runtime.reconcile_task_gaps(registry={})
        self.assertEqual(out[0]["action"], "resumed")
        status.assert_called_once_with("t", "QUEUED", "capability gap: closed; original work resumed")


class TestEventConsumption(unittest.TestCase):
    """The bus actually reaches the operator: watcher triggers and
    proactive proposals become notifications, exactly once."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.events_dir = root / "events"
        self.watchers_dir = root / "watchers"
        self.cursor = root / "cursor.json"
        for module, attr, path in (
            (notifications, "NOTICES_DIR", root / "notices"),
            (proactive, "RULES_DIR", root / "rules"),
            (proactive, "RECEIPTS_DIR", root / "receipts"),
        ):
            patcher = mock.patch.object(module, attr, path)
            patcher.start(); self.addCleanup(patcher.stop)

    def process(self, now=None):
        return runtime.process_new_events(
            now=now or dt.datetime(2026, 8, 26, 12, tzinfo=UTC),
            cursor_path=self.cursor, events_dir=self.events_dir,
            watchers_dir=self.watchers_dir)

    def emit(self, event_id, kind="mail.reply", subject="person:alice"):
        return events.emit(kind, subject, f"summary of {event_id}", source="test",
                           event_id=event_id, events_dir=self.events_dir,
                           watchers_dir=self.watchers_dir)

    def test_watcher_trigger_becomes_notification_once(self):
        events.create_watcher({"kind": "mail.reply"}, note="tell me",
                              created_by="operator", watcher_id="w1",
                              watchers_dir=self.watchers_dir)
        self.emit("evt-a")
        first = self.process()
        self.assertEqual([a["action"] for a in first], ["watcher_notified"])
        self.assertEqual(notifications.unread_count(), 1)
        # second tick: cursor advanced, nothing new, no duplicate notice
        self.assertEqual(self.process(), [])
        self.assertEqual(notifications.unread_count(), 1)

    def test_proactive_rule_notifies_and_enqueue_creates_task(self):
        proactive.create_rule("r1", event_kind="mail.reply", action="enqueue")
        self.emit("evt-b")
        with mock.patch.object(runtime.tasks, "create") as create:
            actions = self.process()
        self.assertIn("rule_enqueue", [a["action"] for a in actions])
        create.assert_called_once()
        self.assertEqual(notifications.unread_count(), 1)

    def test_unmatched_event_advances_cursor_quietly(self):
        self.emit("evt-c", kind="calendar.changed")
        self.assertEqual(self.process(), [])
        self.assertEqual(notifications.unread_count(), 0)


class TestScheduleFailureSurfaces(unittest.TestCase):
    def test_failing_schedule_publishes_notification(self):
        spec = {"id": "s", "command": {"kind": "note", "text": "x"}}
        receipt = {"occurrence": "2026-08-26T12:00:00+00:00"}
        with mock.patch.object(runtime.scheduler, "all_schedules", return_value=[spec]),              mock.patch.object(runtime.scheduler, "occurrence_at_or_before", return_value=dt.datetime(2026, 8, 26, 12, tzinfo=UTC)),              mock.patch.object(runtime.intercom, "validate_kind_args", return_value=[]),              mock.patch.object(runtime.policy, "halted", return_value=None),              mock.patch.object(runtime.scheduler, "claim_due", return_value=receipt),              mock.patch.object(runtime.intercom, "execute_command", side_effect=RuntimeError("boom")),              mock.patch.object(runtime, "evaluate_replies", return_value=[]),              mock.patch.object(runtime, "process_new_events", return_value=[]),              mock.patch.object(runtime, "reconcile_task_gaps", return_value=[]),              mock.patch.object(runtime.notifications, "publish") as publish:
            out = runtime.tick({"repos": {}}, now=dt.datetime(2026, 8, 26, 12, tzinfo=UTC))
        self.assertEqual(out["schedules"][0]["outcome"], "error")
        publish.assert_called_once()


class TestHandler(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(handler, "REQUESTS_DIR", Path(self.tmp.name) / "requests")
        patcher.start(); self.addCleanup(patcher.stop)

    def test_blocked_request_persists_gap_tasks(self):
        report = {"available": [], "blocked": [{"id": "x", "status": "NOT_BUILT"}], "unknown": [], "satisfied": False}
        with mock.patch.object(handler.gaps, "assess", return_value=report), \
             mock.patch.object(handler.gaps, "materialize", return_value=[{"id": "build-x"}]):
            value = handler.create("r", intent="do x", required_capabilities=["x"], command={"kind": "note", "text": "x"})
        self.assertEqual(value["state"], "BLOCKED_CAPABILITY")
        self.assertEqual(value["gap_tasks"], ["build-x"])

    def test_refresh_resumes_request_when_gap_closes(self):
        blocked = {"available": [], "blocked": [{"id": "x", "status": "NOT_BUILT"}], "unknown": [], "satisfied": False}
        ready = {"available": ["x"], "blocked": [], "unknown": [], "satisfied": True}
        with mock.patch.object(handler.gaps, "assess", return_value=blocked), \
             mock.patch.object(handler.gaps, "materialize", return_value=[]):
            handler.create("r", intent="do x", required_capabilities=["x"])
        with mock.patch.object(handler.gaps, "assess", return_value=ready):
            value = handler.refresh("r")
        self.assertEqual(value["state"], "READY")

    def test_completion_requires_evidence(self):
        ready = {"available": [], "blocked": [], "unknown": [], "satisfied": True}
        with mock.patch.object(handler.gaps, "assess", return_value=ready):
            handler.create("r", intent="done", required_capabilities=[])
        with self.assertRaises(ValueError):
            handler.complete("r", evidence="")
        self.assertEqual(handler.complete("r", evidence="verified receipt")["state"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
