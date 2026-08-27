import datetime as dt
import unittest
from unittest import mock

from aletheia import runtime


class CalendarRuntimeCase(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 8, 27, 16, 0, tzinfo=dt.timezone.utc)

    def test_official_provider_is_authoritative_over_ics(self):
        with mock.patch("aletheia.calendar_live.available", return_value=(True, "configured")), \
             mock.patch("aletheia.calendar_live.refresh_if_due", return_value={
                 "provider": "google.calendar", "remote_count": 3, "conflicts": []}) as live, \
             mock.patch("aletheia.ics.available") as ics_available, \
             mock.patch("aletheia.ics.refresh_if_due") as ics_refresh:
            result = runtime._refresh_calendar(self.now)
        self.assertEqual(result, [{"action": "refreshed", "provider": "google.calendar",
                                   "remote_count": 3, "conflicts": 0}])
        live.assert_called_once_with(now=self.now)
        ics_available.assert_not_called()
        ics_refresh.assert_not_called()

    def test_ics_is_fallback_when_no_official_provider(self):
        with mock.patch("aletheia.calendar_live.available", return_value=(False, "none")), \
             mock.patch("aletheia.ics.available", return_value=(True, "configured")), \
             mock.patch("aletheia.ics.refresh_if_due", return_value={
                 "feeds": 1, "mirrored": 4, "cancelled_stale": 0, "unsupported": 0}) as refresh:
            result = runtime._refresh_calendar(self.now)
        self.assertEqual(result[0]["provider"], "ics")
        self.assertEqual(result[0]["mirrored"], 4)
        refresh.assert_called_once_with(now=self.now)

    def test_unconfigured_calendar_is_quiet_noop(self):
        with mock.patch("aletheia.calendar_live.available", return_value=(False, "none")), \
             mock.patch("aletheia.ics.available", return_value=(False, "none")):
            self.assertEqual(runtime._refresh_calendar(self.now), [])

    def test_tick_runs_calendar_before_attention(self):
        order = []
        def calendar_hook(now):
            order.append("calendar"); return [{"action": "refreshed"}]
        def attention_hook(now=None):
            order.append("attention"); return []
        patches = [
            mock.patch.object(runtime, "run_due_schedules", return_value=[]),
            mock.patch.object(runtime, "poll_mail_events", return_value=[]),
            mock.patch.object(runtime, "mirror_pulse_events", return_value=[]),
            mock.patch.object(runtime.verification, "reconcile_durable_receipts", return_value=[]),
            mock.patch.object(runtime, "evaluate_replies", return_value=[]),
            mock.patch.object(runtime, "process_new_events", return_value=[]),
            mock.patch.object(runtime, "reconcile_task_gaps", return_value=[]),
            mock.patch.object(runtime.handler, "reconcile_all", return_value=[]),
            mock.patch.object(runtime, "_run_approved_intents", return_value=[]),
            mock.patch.object(runtime, "_run_authorized_errands", return_value=[]),
            mock.patch.object(runtime, "_observe_room", return_value=[]),
            mock.patch.object(runtime, "_refresh_calendar", side_effect=calendar_hook),
            mock.patch.object(runtime.attention, "reconcile", side_effect=attention_hook),
        ]
        for patcher in patches:
            patcher.start(); self.addCleanup(patcher.stop)
        result = runtime.tick({"repos": {}}, now=self.now, registry={"capabilities": []})
        self.assertEqual(result["calendar"], [{"action": "refreshed"}])
        self.assertEqual(order, ["calendar", "attention"])


if __name__ == "__main__":
    unittest.main()
