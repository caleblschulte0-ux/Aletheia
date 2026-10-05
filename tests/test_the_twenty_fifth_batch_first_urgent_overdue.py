"""Twenty-fifth sandbox batch, 2026-10-05: the day's shape and the alarms.

    > what's first               [5.0s] a model ("what should I do first" was instant)
    > anything urgent            [4.0s] the brief: "no fleet reading yet"
    > what's overdue             [3.5s] a model
    > turn off the 6:30 alarm    [4.5s] the planner, and an approval
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import intercom, localtime, quick, voice


class TheDaysShape(unittest.TestCase):
    def test_first_and_urgent_are_the_focus_answer(self):
        self.assertEqual(quick.match("what's first")[0], "focus")
        self.assertEqual(quick.match("anything urgent")[0], "focus")
        self.assertEqual(quick.match("what's urgent right now")[0], "focus")

    def test_overdue_names_the_tasks_and_how_late(self):
        two_days_ago = (localtime.today() - dt.timedelta(days=2)).isoformat()
        far = (localtime.today() + dt.timedelta(days=30)).isoformat()
        tasks = [{"id": "p", "description": "renew my passport", "status": "QUEUED", "deadline": two_days_ago},
                 {"id": "g", "description": "sort the garage", "status": "QUEUED", "deadline": far}]
        with mock.patch("aletheia.tasks.all_tasks", return_value=tasks):
            said = quick.answer("what's overdue")
        self.assertEqual(said, "Overdue: renew my passport, due 2 days ago.")
        with mock.patch("aletheia.tasks.all_tasks", return_value=tasks[1:]):
            self.assertEqual(quick.answer("is anything overdue"), "Nothing's overdue.")


class AnAlarmByItsTime(unittest.TestCase):
    def test_the_sentence_carries_the_time(self):
        self.assertEqual(voice.interpret("turn off the 6:30 alarm")["command"], {"kind": "reminder_off", "which": "6:30"})
        self.assertEqual(voice.interpret("cancel the 7 am alarm")["command"], {"kind": "reminder_off", "which": "7 am"})
        self.assertEqual(voice.interpret("turn off the alarm")["command"], {"kind": "reminder_off", "which": "alarm"})

    def test_the_store_finds_it_by_when_it_fires(self):
        tz = localtime.operator_tz()
        tomorrow = localtime.today() + dt.timedelta(days=1)
        def once(hour, minute, sid):
            at = dt.datetime.combine(tomorrow, dt.time(hour, minute), tzinfo=tz)
            return {"version": 1, "id": sid, "kind": "once", "at": at.isoformat(), "enabled": True,
                    "created_at": at.isoformat(), "command": {"kind": "notify_operator", "text": "wake up"}}
        rows = [once(7, 0, "r7"), once(6, 30, "r630")]
        with mock.patch("aletheia.scheduler.all_schedules", return_value=rows):
            found, why = intercom._one_reminder("6:30")
            self.assertEqual((found or {}).get("id"), "r630", why)
            found, why = intercom._one_reminder("7")
            self.assertEqual((found or {}).get("id"), "r7", why)
            found, why = intercom._one_reminder("9")
        self.assertIsNone(found)
        self.assertIn("None of your reminders is about 9", why)


if __name__ == "__main__":
    unittest.main()
