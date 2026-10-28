"""An alarm named by how it repeats.

2026-10-28, talking to her with the models off:

    > set an alarm for 6:30 tomorrow
    > set an alarm for 7 on weekdays
    > turn off my weekday alarm
      Which one — tomorrow at 6:30 am or weekdays at 7 am?
"""
import unittest
from unittest import mock

from aletheia import intercom, voice

ONCE = {"id": "a1", "kind": "once", "at": "2026-10-29T11:30:00Z", "enabled": True,
        "command": {"kind": "notify_operator", "text": "wake up"}}
WEEKDAYS = {"id": "a2", "kind": "weekly", "weekdays": [0, 1, 2, 3, 4], "time": "07:00", "enabled": True,
            "command": {"kind": "notify_operator", "text": "wake up"}}
STANDUP = {"id": "s1", "kind": "weekly", "weekdays": [0, 1, 2, 3, 4], "time": "09:00", "enabled": True,
           "command": {"kind": "notify_operator", "text": "daily standup"}}


class BySort(unittest.TestCase):
    def test_voice_keeps_the_sort(self):
        self.assertEqual(voice.interpret("turn off my weekday alarm")["command"],
                         {"kind": "reminder_off", "which": "wake up weekday"})
        self.assertEqual(voice.interpret("cancel my weekend alarm")["command"]["which"], "wake up weekend")
        self.assertEqual(voice.interpret("cancel my alarm")["command"]["which"], "wake up")

    def test_the_sort_picks_the_one(self):
        with mock.patch.object(intercom, "_reminder_schedules", return_value=[ONCE, WEEKDAYS]):
            self.assertEqual(intercom._one_reminder("wake up weekday")[0]["id"], "a2")

    def test_no_alarm_of_that_sort_says_so(self):
        with mock.patch.object(intercom, "_reminder_schedules", return_value=[ONCE]), \
                mock.patch.object(intercom, "_reminder_words", return_value="wake up — tomorrow at 6:30 am"):
            found, why = intercom._one_reminder("wake up daily")
        self.assertIsNone(found)
        self.assertTrue(why.startswith("You don't have a daily alarm."), why)

    def test_words_that_say_daily_are_still_words(self):
        with mock.patch.object(intercom, "_reminder_schedules", return_value=[ONCE, STANDUP]):
            self.assertEqual(intercom._one_reminder("daily standup")[0]["id"], "s1")


if __name__ == "__main__":
    unittest.main()
