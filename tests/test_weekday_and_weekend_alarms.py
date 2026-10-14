""""Set an alarm for 6 am every weekday", "and 8 on weekends", "change my
weekday alarm to 6:30" (2026-10-14: the second and third to a model, and "set
an alarm for 8 am on weekends" said whole went there too).
"""
import unittest
from unittest import mock

from aletheia import policy, scheduler, voice


def said(sentence):
    with mock.patch.object(policy, "all_approvals", return_value=[]):
        return voice.interpret(f"thea {sentence}")


WEEKDAY = {"id": "a", "enabled": True, "kind": "weekly", "time": "06:00", "weekdays": [0, 1, 2, 3, 4],
           "command": {"text": "wake up"}}
WEEKEND = {"id": "b", "enabled": True, "kind": "weekly", "time": "08:00", "weekdays": [5, 6],
           "command": {"text": "wake up"}}


class WeekendAlarms(unittest.TestCase):
    def test_said_whole(self):
        for sentence in ("set an alarm for 8 am on weekends", "set an alarm for 9 am every saturday and sunday"):
            got = said(sentence)["command"]
            self.assertEqual((got["kind"], got["days"], got["text"]), ("remind_weekly", ["weekend"], "wake up"), sentence)

    def test_and_8_on_weekends_after_a_weekday_alarm(self):
        with mock.patch.object(voice, "_her_last_answer", return_value="Alarm set for weekdays at 6 am."):
            got = said("and 8 on weekends")["command"]
        self.assertEqual((got["kind"], got["days"], got["time"]), ("remind_weekly", ["weekend"], "08:00"))


class TheWeekdayOne(unittest.TestCase):
    def test_the_named_one_moves_by_its_clock(self):
        with mock.patch.object(voice, "_running_once", return_value=[]), \
                mock.patch.object(scheduler, "all_schedules", return_value=[WEEKDAY, WEEKEND]):
            got = said("change my weekday alarm to 6:30")["command"]
            asked = said("change my alarm to 7")
        self.assertEqual((got["days"], got["time"], got["replaces"]), ([0, 1, 2, 3, 4], "06:30", "wake up at 6:00 am"))
        self.assertTrue(asked["say"].startswith("Which one - your weekday alarm or your weekend alarm?"))

    def test_the_answer_to_which_one(self):
        question = 'Which one - your weekday alarm or your weekend alarm? Say "change my weekday alarm to 7" or the weekend one.'
        with mock.patch.object(voice, "_running_once", return_value=[]), \
                mock.patch.object(voice, "_her_last_answer", return_value=question), \
                mock.patch.object(scheduler, "all_schedules", return_value=[WEEKDAY, WEEKEND]):
            got = said("the weekend one")["command"]
        self.assertEqual((got["days"], got["replaces"]), ([5, 6], "wake up at 8:00 am"))
        self.assertEqual(got["time"], "07:00")


if __name__ == "__main__":
    unittest.main()
