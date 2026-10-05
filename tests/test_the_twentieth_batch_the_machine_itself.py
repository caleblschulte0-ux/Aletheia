"""Twentieth sandbox batch, 2026-10-05: money, time and the machine itself.

    > how much do I spend a month on subscriptions   [4.5s] a model
    > what subscriptions do I have                   "About 15.99 a month" - no $
    > how long is left on the timer                  [5.0s] a model
    > what version are you on                        "On claude/... at 26db655 — ..."
    > when did you last restart                      [5.0s] "I can't find a record"
    > what's using the most memory                   [7.0s] "open a terminal, run top"
    > is the core running                            "No fleet reading yet"
"""
import datetime as dt
import sys
import types
import unittest
from unittest import mock

from aletheia import intercom, quick, running


class TheSubscriptionsTotal(unittest.TestCase):
    ROWS = [{"merchant": "netflix", "amount": 15.99, "cadence": "monthly"},
            {"merchant": "gym", "cadence": "monthly"}]

    def test_the_total_names_the_rows_and_the_unpriced(self):
        with mock.patch("aletheia.subscriptions.all_subscriptions", return_value=self.ROWS):
            said = quick.answer("how much do i spend a month on subscriptions")
        self.assertTrue(said.startswith("About $15.99 a month across 2 subscriptions: netflix and gym."), said)
        self.assertIn("no price I know", said)
        with mock.patch("aletheia.subscriptions.all_subscriptions", return_value=[]):
            self.assertTrue(quick.answer("what do my subscriptions cost").startswith("Nothing:"))

    def test_the_list_says_dollars(self):
        with mock.patch("aletheia.subscriptions.all_subscriptions", return_value=self.ROWS[:1]):
            said = intercom.execute_command({"kind": "subscriptions"}, {"repos": {}})
        self.assertEqual(said, "1 active: netflix. About $15.99 a month.")


class TheTimer(unittest.TestCase):
    def test_what_is_left_and_none(self):
        soon = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=9, seconds=40)).replace(microsecond=0)
        timer = {"version": 1, "id": "t1", "kind": "once", "at": soon.isoformat(), "enabled": True,
                 "created_at": soon.isoformat(),
                 "command": {"kind": "notify_operator", "text": "your 10-minute timer is up"}}
        with mock.patch("aletheia.scheduler.all_schedules", return_value=[timer]):
            said = quick.answer("how long is left on the timer")
        self.assertTrue(said.startswith("About 10 minutes left; your 10-minute timer goes off "), said)
        with mock.patch("aletheia.scheduler.all_schedules", return_value=[]):
            self.assertEqual(quick.answer("is there a timer running"), "No timer running.")


class TheMachineItself(unittest.TestCase):
    def test_the_version_is_the_change_not_the_hash(self):
        info = {"branch": "claude/some-branch", "commit": "26db655", "subject": "His phrase reaches the reader",
                "running_old_code": False}
        said = running.version_spoken(info)
        self.assertIn("His phrase reaches the reader", said)
        self.assertNotIn("26db655", said)
        self.assertNotIn("claude/", said)
        self.assertIn("restart me", running.version_spoken({"subject": "x", "running_old_code": True}))

    def test_uptime_falls_back_to_the_process_a_core_runs_in(self):
        fake = types.SimpleNamespace(PROCESS_STARTED_AT=dt.datetime.now(dt.timezone.utc).timestamp() - 125, SERVERS=[object()])
        with mock.patch("aletheia.liveness.uptime_seconds", return_value=None), \
             mock.patch.dict(sys.modules, {"aletheia.core": fake}):
            said = quick.answer("when did you last restart")
            core = quick.answer("is the core running")
        self.assertTrue(said.startswith("Up 2 minutes, since "), said)
        self.assertTrue(core.startswith("Yes, the Core is running - I'm it."), core)

    def test_nothing_known_is_still_nothing_invented(self):
        with mock.patch("aletheia.liveness.uptime_seconds", return_value=None), \
             mock.patch.dict(sys.modules, {"aletheia.core": None}):
            self.assertIsNone(quick._uptime())

    def test_memory_by_program_is_a_number_or_an_honest_no(self):
        said = quick.answer("what's using the most memory")
        self.assertTrue(said.endswith("in the machine.") or said.startswith("I can't read this machine's memory"), said)


if __name__ == "__main__":
    unittest.main()
