"""A reminder paused is a reminder kept, and a skipped one explains a day.

2026-10-28, talking to her with the models off:

    > pause my vitamin reminder                 (to the planner)
    > resume my vitamin reminder                (to the planner)
    > turn off my vitamin reminder, then
    > what reminders do I have                  You have no reminders set.
    > skip tomorrow's vitamin reminder, then
    > what reminders do I have tomorrow         No reminders tomorrow.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import intercom, localtime, quick, scheduler, voice


def spec(enabled=True, updated=None, skips=None):
    now = dt.datetime.now(dt.timezone.utc)
    return {"version": 1, "id": "remind-daily-v", "kind": "daily",
            "command": {"kind": "notify_operator", "text": "take your vitamins"},
            "enabled": enabled, "created_at": "2026-01-01T00:00:00Z",
            "updated_at": (updated or now).strftime("%Y-%m-%dT%H:%M:%SZ"), "timezone": "America/Chicago",
            "time": "07:00", **({"skips": skips} if skips else {})}


class Paused(unittest.TestCase):
    def test_he_can_say_it(self):
        self.assertEqual(voice.interpret("pause my vitamin reminder")["command"],
                         {"kind": "reminder_off", "which": "vitamin"})
        self.assertEqual(voice.interpret("resume my vitamin reminder")["command"],
                         {"kind": "reminder_on", "which": "vitamin"})
        self.assertEqual(voice.interpret("pause my reminders")["command"]["which"], "all reminders")
        self.assertEqual(voice.interpret("resume yourself")["command"]["kind"], "resume")

    def test_a_stopped_one_is_still_named(self):
        with mock.patch.object(scheduler, "all_schedules", return_value=[spec(enabled=False)]):
            said = intercom._reminders_answer()
        self.assertTrue(said.startswith("None are on right now. You stopped this one this week: take your vitamins"), said)
        self.assertIn('Say "resume my vitamins reminder" to put it back.', said)

    def test_one_stopped_long_ago_is_not_news(self):
        old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)
        with mock.patch.object(scheduler, "all_schedules", return_value=[spec(enabled=False, updated=old)]):
            self.assertEqual(intercom._reminders_answer(), "You have no reminders set.")


class Skipped(unittest.TestCase):
    def test_a_skipped_day_says_so(self):
        tz = localtime.operator_tz()
        tomorrow = dt.datetime.now(tz).date() + dt.timedelta(days=1)
        at = dt.datetime.combine(tomorrow, dt.time(7, 0), tzinfo=tz).astimezone(dt.timezone.utc)
        row = spec(skips=[at.strftime("%Y-%m-%dT%H:%M")])
        with mock.patch.object(scheduler, "all_schedules", return_value=[row]):
            self.assertEqual(quick._skipped_on(tomorrow.isoformat(), tz), ["take your vitamins"])
            self.assertEqual(quick._skipped_on((tomorrow + dt.timedelta(days=1)).isoformat(), tz), [])


if __name__ == "__main__":
    unittest.main()
