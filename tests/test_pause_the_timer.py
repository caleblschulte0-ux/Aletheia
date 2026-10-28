""""Pause the timer" said "I can't pause a timer" (2026-10-28). Pausing turns
the timer's reminder off; resuming starts it again with what it had left."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import scheduler, voice



def spec(text, at, enabled, off):
    return {"kind": "once", "enabled": enabled, "at": at.isoformat(), "command": {"text": text},
            "updated_at": off.isoformat(), "created_at": (off - dt.timedelta(minutes=5)).isoformat()}


class PausingATimer(unittest.TestCase):
    def test_pause_turns_it_off_and_says_what_is_left(self):
        soon = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=7, seconds=5)
        with mock.patch.object(voice, "_running_once", return_value=[(soon, "your 10-minute timer is up")]):
            got = voice._interpret("pause the timer")
        self.assertEqual(got["command"], {"kind": "reminder_off", "which": "your 10-minute timer is up"})
        self.assertIn("7 minutes left", got["say"])

    def test_nothing_running_is_said(self):
        with mock.patch.object(voice, "_running_once", return_value=[]):
            got = voice._interpret("pause the timer")
        self.assertIsNone(got["command"])

    def test_a_named_one_is_picked_by_name(self):
        now = dt.datetime.now(dt.timezone.utc)
        running = [(now + dt.timedelta(minutes=3), "your 8-minute pasta timer is up"),
                   (now + dt.timedelta(minutes=9), "your 10-minute timer is up")]
        with mock.patch.object(voice, "_running_once", return_value=running):
            got = voice._interpret("pause the pasta timer")
            self.assertEqual(got["command"]["which"], "your 8-minute pasta timer is up")
            self.assertIsNone(voice._interpret("pause the timer")["command"])

    def test_resume_starts_it_with_what_it_had_left(self):
        off = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=2)
        paused = spec("your 10-minute timer is up", off + dt.timedelta(minutes=6), enabled=False, off=off)
        with mock.patch.object(scheduler, "all_schedules", return_value=[paused]):
            for sentence in ("resume the timer", "unpause the timer"):
                got = voice._interpret(sentence)
                self.assertEqual(got["command"]["kind"], "remind_at", sentence)
                left = dt.datetime.fromisoformat(got["command"]["at"]) - dt.datetime.now(dt.timezone.utc)
                self.assertAlmostEqual(left.total_seconds(), 360, delta=5)

    def test_one_that_went_off_is_not_resumed(self):
        now = dt.datetime.now(dt.timezone.utc)
        rang = spec("your 10-minute timer is up", now - dt.timedelta(minutes=1), enabled=False, off=now)
        with mock.patch.object(scheduler, "all_schedules", return_value=[rang]):
            self.assertIsNone(voice._interpret("resume the timer")["command"])


if __name__ == "__main__":
    unittest.main()
