"""The beat: a failure is not work, a slow subsystem cannot eat the hour,
and an approval acts now rather than at the next tick.

All three were found by reading what the running Core actually reported.
`/api/runtime` said `mail_events: 1` whether the mail poller had produced
one event or raised one exception, which is the worst possible tie.
"""
import datetime as dt
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from aletheia import core, journal, runtime

NOW = dt.datetime(2026, 8, 27, 20, 0, tzinfo=dt.timezone.utc)
FLEET = {"repos": {}}


class FailuresAreNotWorkCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(journal, "JOURNAL_PATH",
                              Path(self.tmp.name) / "journal.jsonl")
        p.start(); self.addCleanup(p.stop)
        core._FAILURES_SEEN.clear()
        core._FAILURE_STREAK.clear()
        self.addCleanup(core._FAILURES_SEEN.clear)
        self.addCleanup(core._FAILURE_STREAK.clear)

    def quiet_tick(self, **overrides):
        """runtime.tick with every subsystem stubbed to do nothing."""
        self.install_stubs(**overrides)
        return runtime.tick(FLEET, now=NOW)

    def quiet_tick_with_budget(self, budget_s, **overrides):
        self.install_stubs(**overrides)
        return runtime.tick(FLEET, now=NOW, budget_s=budget_s)

    def install_stubs(self, **overrides):
        """Stub every subsystem WITHOUT running a beat, so a helper that
        wants a specific budget does not spend the stubs on a warm-up tick."""
        patches = {
            "run_due_schedules": [], "poll_mail_events": [],
            "mirror_pulse_events": [], "evaluate_replies": [],
            "process_new_events": [], "reconcile_task_gaps": [],
            "_run_approved_intents": [], "_run_authorized_errands": [],
            "_observe_room": [], "_reconcile_scheduling": [],
            "_refresh_calendar": [],
        }
        started = []
        for name, value in patches.items():
            if not hasattr(runtime, name):
                continue
            side = overrides.get(name)
            p = (mock.patch.object(runtime, name, side_effect=side) if side
                 else mock.patch.object(runtime, name, return_value=value))
            started.append(p); p.start(); self.addCleanup(p.stop)
        for extra in ("verification", "handler", "attention"):
            module = getattr(runtime, extra, None)
            if module is None:
                continue
            for fn in ("reconcile_durable_receipts", "reconcile_all", "reconcile"):
                if hasattr(module, fn):
                    p = mock.patch.object(module, fn, return_value=[])
                    p.start(); self.addCleanup(p.stop)

    def test_a_healthy_beat_reports_no_failures(self):
        summary = self.quiet_tick()
        self.assertEqual(summary["failures"], [])
        self.assertEqual(summary["skipped"], [])

    def test_a_raising_subsystem_is_a_failure_not_an_event(self):
        summary = self.quiet_tick(
            poll_mail_events=RuntimeError("imap refused the login"))
        # the tie that started this: it must NOT read as one mail event
        self.assertEqual(summary["mail_events"], [])
        self.assertEqual(len(summary["failures"]), 1)
        self.assertEqual(summary["failures"][0]["producer"], "mail")
        self.assertIn("imap refused", summary["failures"][0]["error"])

    def test_one_broken_subsystem_does_not_stop_the_others(self):
        summary = self.quiet_tick(poll_mail_events=RuntimeError("down"))
        self.assertIn("capability_gaps", summary)

    def test_a_single_blip_is_journaled_but_not_announced(self):
        # A transient IMAP timeout on one beat is not news. The old code
        # published an IMPORTANT notification for it that nothing ever
        # cleared, and the wall was headlined by a healed network blip for
        # hours.
        with mock.patch("aletheia.notifications.publish") as publish:
            core._surface_failures([{"producer": "mail", "error": "timeout"}])
        publish.assert_not_called()
        self.assertTrue([e for e in journal.entries(journal.JOURNAL_PATH)
                         if e["kind"] == "alert"])

    def test_a_persistent_failure_is_announced_once(self):
        failures = [{"producer": "mail", "error": "RuntimeError: down"}]
        with mock.patch("aletheia.notifications.publish") as publish:
            for _ in range(5):
                core._surface_failures(failures)
        self.assertEqual(publish.call_count, 1, "it nagged every beat")
        rows = [e for e in journal.entries(journal.JOURNAL_PATH)
                if e["kind"] == "alert"]
        self.assertEqual(len(rows), 5, "every beat should still be journaled")

    def test_a_new_failure_is_always_heard(self):
        with mock.patch("aletheia.notifications.publish") as publish:
            for error in ("A", "A", "B"):
                core._surface_failures([{"producer": "mail", "error": error}])
        self.assertEqual(publish.call_count, 2)

    def test_recovery_acknowledges_the_alarm_and_journals_it(self):
        failures = [{"producer": "mail", "error": "down"}]
        notices = [{"id": "n1", "dedupe_key": "runtime-failure:mail:down"},
                   {"id": "n2", "dedupe_key": "something-else"}]
        with mock.patch("aletheia.notifications.publish"):
            core._surface_failures(failures)
            core._surface_failures(failures)      # now it is loud
        with mock.patch("aletheia.notifications.all_notifications",
                        return_value=notices),              mock.patch("aletheia.notifications.set_state") as set_state:
            core._clear_recovered([])             # the next beat succeeds
        set_state.assert_called_once_with("n1", "ACKNOWLEDGED")
        self.assertTrue([e for e in journal.entries(journal.JOURNAL_PATH)
                         if "recovered" in e["text"]])

    def test_a_blip_that_never_got_loud_needs_no_quieting(self):
        with mock.patch("aletheia.notifications.publish"):
            core._surface_failures([{"producer": "mail", "error": "blip"}])
        with mock.patch("aletheia.notifications.all_notifications") as listed:
            core._clear_recovered([])
        listed.assert_not_called()
        self.assertEqual(core._FAILURE_STREAK, {})

    def test_a_notification_failure_never_breaks_the_beat(self):
        with mock.patch("aletheia.notifications.publish",
                        side_effect=OSError("disk full")):
            core._surface_failures([{"producer": "mail", "error": "A"}])


class BudgetCase(FailuresAreNotWorkCase):
    def test_a_zero_budget_skips_everything_and_fails_nothing(self):
        summary = self.quiet_tick_with_budget(0.0)
        self.assertTrue(summary["skipped"], "nothing was skipped on a zero budget")
        self.assertEqual(summary["failures"], [],
                         "running out of time was counted as a failure")

    def test_a_generous_budget_skips_nothing(self):
        summary = self.quiet_tick_with_budget(60.0)
        self.assertEqual(summary["skipped"], [])

    def test_a_slow_subsystem_defers_the_rest_rather_than_running_late(self):
        # The sync loop that pulls commands and stamps the heartbeat is this
        # same thread, so a browser-shaped minute must not hold it hostage.
        # Driven by a fake clock rather than real sleeps: a budget test that
        # depends on wall time fails on a busy machine and teaches nothing.
        ran = []
        clock = iter([0.0,        # deadline is computed here
                      0.0,        # first guarded call: inside budget
                      99.0, 99.0, 99.0, 99.0, 99.0, 99.0, 99.0, 99.0,
                      99.0, 99.0, 99.0, 99.0, 99.0, 99.0, 99.0, 99.0])

        def tick_clock():
            try:
                return next(clock)
            except StopIteration:
                return 99.0

        with mock.patch.object(runtime.time, "monotonic", tick_clock):
            summary = self.quiet_tick_with_budget(
                1.0, run_due_schedules=lambda *a, **k: ran.append("schedules") or [])
        self.assertEqual(ran, ["schedules"],
                         "the first subsystem should still run")
        self.assertTrue(summary["skipped"], "the rest should have been deferred")
        self.assertEqual(summary["failures"], [],
                         "running out of time was counted as a failure")


class KickCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(journal, "JOURNAL_PATH",
                              Path(self.tmp.name) / "journal.jsonl")
        p.start(); self.addCleanup(p.stop)

    def wait_idle(self, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with core._KICK_LOCK:
                if not core._KICKING:
                    return True
            time.sleep(0.01)
        return False

    def test_approving_runs_the_unblocked_work_immediately(self):
        ran = []
        with mock.patch.object(runtime, "_run_approved_intents",
                               side_effect=lambda f: ran.append("intents")), \
             mock.patch.object(runtime, "_run_authorized_errands",
                               side_effect=lambda: ran.append("errands")), \
             mock.patch.object(runtime, "_reconcile_scheduling",
                               side_effect=lambda n: ran.append("meetings")):
            self.assertTrue(core.kick_approved_work(FLEET))
            self.assertTrue(self.wait_idle())
        self.assertEqual(sorted(ran), ["errands", "intents", "meetings"])

    def test_a_second_approval_joins_rather_than_races(self):
        gate = mock.Mock(side_effect=lambda f: time.sleep(0.3))
        with mock.patch.object(runtime, "_run_approved_intents", gate), \
             mock.patch.object(runtime, "_run_authorized_errands", lambda: None), \
             mock.patch.object(runtime, "_reconcile_scheduling", lambda n: None):
            self.assertTrue(core.kick_approved_work(FLEET))
            self.assertFalse(core.kick_approved_work(FLEET),
                             "a second kick started a competing run")
            self.assertTrue(self.wait_idle())

    def test_a_throwing_step_does_not_strand_the_lock(self):
        with mock.patch.object(runtime, "_run_approved_intents",
                               side_effect=RuntimeError("boom")), \
             mock.patch.object(runtime, "_run_authorized_errands", lambda: None), \
             mock.patch.object(runtime, "_reconcile_scheduling", lambda n: None):
            core.kick_approved_work(FLEET)
            self.assertTrue(self.wait_idle())
        # the lock is free, so the next approval still acts
        with core._KICK_LOCK:
            self.assertFalse(core._KICKING)


if __name__ == "__main__":
    unittest.main()
