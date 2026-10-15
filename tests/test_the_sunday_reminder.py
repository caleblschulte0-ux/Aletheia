"""2026-10-15, every model off: "change the sunday reminder to 7pm" said "I
don't see a reminder for sunday" with one every Sunday; "skip the rent
reminder this month" went to the planner; and "when's my next rent reminder"
said "on the 1st of every month" instead of the date."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import intercom, quick, scheduler, voice

SUNDAY = {"id": "w1", "kind": "weekly", "weekdays": [6], "time": "18:00", "enabled": True,
          "command": {"kind": "notify", "text": "plan the week"}}
RENT = {"id": "m1", "kind": "monthly", "monthday": 1, "time": "09:00", "enabled": True,
        "command": {"kind": "notify", "text": "pay rent"}}


class TheSundayReminder(unittest.TestCase):
    def one(self, needle):
        with mock.patch.object(intercom, "_reminder_schedules", return_value=[SUNDAY, RENT]):
            return intercom._one_reminder(needle)[0]

    def test_named_by_its_day(self):
        self.assertEqual(self.one("sunday")["id"], "w1")
        self.assertEqual(self.one("the sunday night")["id"], "w1")

    def test_named_by_how_often(self):
        self.assertEqual(self.one("weekly")["id"], "w1")
        self.assertEqual(self.one("monthly")["id"], "m1")

    def test_a_day_with_nothing_on_it_is_still_nothing(self):
        self.assertIsNone(self.one("monday"))


class SkipItThisMonth(unittest.TestCase):
    def test_this_month_is_its_coming_turn(self):
        got = voice._interpret("skip the rent reminder this month")["command"]
        self.assertEqual(got, {"kind": "reminder_off", "which": "rent", "once": "next"})


class TheNextOneIsADate(unittest.TestCase):
    def test_a_monthly_one_says_when(self):
        with mock.patch.object(intercom, "_one_reminder", return_value=(RENT, "")), \
                mock.patch.object(intercom, "_reminder_words", return_value="pay rent — on the 1st of every month at 9 am"), \
                mock.patch.object(scheduler, "next_occurrence",
                                  return_value=dt.datetime(2026, 11, 1, 14, 0, tzinfo=dt.timezone.utc)):
            said = quick._reminder_when("next rent")
        self.assertTrue(said.startswith("Your next rent reminder is "), said)
        self.assertNotIn("is on the 1st of every month at 9 am:", said)
        self.assertIn("It repeats on the 1st of every month", said)


if __name__ == "__main__":
    unittest.main()
