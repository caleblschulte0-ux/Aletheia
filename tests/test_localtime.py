"""The operator's clock: "tomorrow at 9" is his tomorrow and his 9.

2026-09-02 20:00 in Chicago, the planner told only the UTC instant
(already the 3rd): "remind me tomorrow at 9am" compiled to
2026-09-04T09:00:00Z — wrong day, wrong hour. These hold the repair.
"""
from __future__ import annotations

import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import localtime, memory, planner


class TimezoneSourceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(memory, "MEMORY_DIR", Path(self.tmp.name), create=True)
        p.start(); self.addCleanup(p.stop)
        # whatever memory's real store attribute is, recall goes through _load
        self.recall = mock.patch.object(memory, "recall", return_value=None)
        self.recall.start(); self.addCleanup(self.recall.stop)
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start(); self.addCleanup(env.stop)
        os.environ.pop(localtime.ENV, None)

    def test_the_default_is_what_the_repo_already_assumed(self):
        self.assertEqual(localtime.operator_timezone(), "America/Chicago")

    def test_the_environment_beats_the_default(self):
        os.environ[localtime.ENV] = "Europe/Berlin"
        self.assertEqual(localtime.operator_timezone(), "Europe/Berlin")

    def test_his_own_word_in_memory_beats_the_environment(self):
        os.environ[localtime.ENV] = "Europe/Berlin"
        self.recall.stop()
        with mock.patch.object(memory, "recall", return_value="America/Denver") as recall:
            self.assertEqual(localtime.operator_timezone(), "America/Denver")
        recall.assert_called_once_with("identity", "timezone")
        self.recall.start()

    def test_an_invalid_name_falls_through_rather_than_raising(self):
        os.environ[localtime.ENV] = "Mars/Olympus"
        self.recall.stop()
        with mock.patch.object(memory, "recall", return_value="not a zone"):
            self.assertEqual(localtime.operator_timezone(), "America/Chicago")
        self.recall.start()

    def test_a_broken_memory_store_does_not_break_the_clock(self):
        self.recall.stop()
        with mock.patch.object(memory, "recall", side_effect=RuntimeError("disk")):
            self.assertEqual(localtime.operator_timezone(), "America/Chicago")
        self.recall.start()


class DescribeNowCase(unittest.TestCase):
    def test_the_real_failure_reads_correctly_now(self):
        # 2026-09-03T01:04:50Z is Wednesday 2026-09-02 20:04 in Chicago (CDT)
        text = localtime.describe_now("2026-09-03T01:04:50Z", timezone="America/Chicago")
        self.assertIn("The current time is 2026-09-03T01:04:50Z (UTC)", text)
        self.assertIn("Wednesday 2026-09-02 20:04 (America/Chicago, UTC-05:00)", text)
        self.assertIn("2026-09-02T20:04:50-05:00", text)
        self.assertIn("HIS local time", text)

    def test_an_aware_datetime_and_its_string_agree(self):
        now = dt.datetime(2026, 12, 25, 15, 30, tzinfo=dt.timezone.utc)
        self.assertEqual(localtime.describe_now(now, timezone="America/Chicago"),
                         localtime.describe_now("2026-12-25T15:30:00Z", timezone="America/Chicago"))
        self.assertIn("09:30 (America/Chicago, UTC-06:00)",
                      localtime.describe_now(now, timezone="America/Chicago"))

    def test_a_naive_time_is_refused(self):
        with self.assertRaises(ValueError):
            localtime.describe_now(dt.datetime(2026, 1, 1, 12, 0))
        with self.assertRaises(ValueError):
            localtime.describe_now("2026-01-01T12:00:00")

    def test_now_defaults_to_the_real_clock(self):
        text = localtime.describe_now(timezone="UTC")
        self.assertIn(dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"), text)


class PlannerPromptCase(unittest.TestCase):
    REGISTRY = {"revision": 1, "capabilities": [
        {"id": "task.persist", "status": "AVAILABLE", "risk_class": "low",
         "approval_policy": "none", "description": "", "provider": "aletheia.local",
         "caller": "x"}]}

    def test_the_planner_is_told_his_local_time_and_the_rule(self):
        with mock.patch.object(localtime, "operator_timezone", return_value="America/Chicago"):
            prompt = planner.system_prompt(self.REGISTRY, now="2026-09-03T01:04:50Z")
        self.assertIn("The current time is 2026-09-03T01:04:50Z (UTC)", prompt)
        self.assertIn("Wednesday 2026-09-02 20:04 (America/Chicago, UTC-05:00)", prompt)
        self.assertIn("in the operator's LOCAL time given below, never in UTC", prompt)


if __name__ == "__main__":
    unittest.main()


class HisDayNotTheProcessDay(unittest.TestCase):
    """2026-10-06 19:08 in Chicago, in a UTC process (a container, an Actions runner):
    "remind me tomorrow at 9 to email Sam" was confirmed for THURSDAY at 9, because
    the day came from `date.today()` - the process's day, already the 7th - while
    the hour was correctly his. The day has to come from his clock too."""

    EVENING = dt.datetime(2026, 10, 6, 19, 8, tzinfo=localtime.operator_tz())

    def setUp(self):
        for p in (mock.patch.object(localtime, "operator_timezone", return_value="America/Chicago"),
                  mock.patch.object(localtime, "now", return_value=self.EVENING)):
            p.start()
            self.addCleanup(p.stop)

    def test_today_is_his_calendar_day(self):
        self.assertEqual(localtime.today(), dt.date(2026, 10, 6))

    def test_tomorrow_said_in_his_evening_is_his_tomorrow(self):
        from aletheia import voice
        self.assertEqual(voice._spoken_day("tomorrow"), "2026-10-07")
        self.assertEqual(voice._spoken_day("wednesday"), "2026-10-07")
        at = voice.interpret("thea remind me tomorrow at 9 to email Sam")["command"]["at"]
        self.assertEqual(dt.datetime.fromisoformat(at),
                         dt.datetime(2026, 10, 7, 9, 0, tzinfo=localtime.operator_tz()))

    def test_next_friday_counts_from_his_day(self):
        from aletheia import voice
        self.assertIn("the 9th, or the week after on the 16th", voice._ambiguous_next_weekday("next friday"))

    def test_a_journal_line_from_his_evening_is_said_as_today(self):
        from aletheia import intercom
        self.assertEqual(intercom._day_words("2026-10-07T00:30:00Z"), "today")
        self.assertEqual(intercom._day_words("2026-10-06T04:00:00Z"), "yesterday")
