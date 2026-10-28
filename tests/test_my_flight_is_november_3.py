"""A plan he told her about, on the day he asks about.

2026-10-28, talking to her with the models off:

    > my flight to denver is november 3 at 7 am      Noted.
    > what's on tuesday                              Nothing on your calendar Tuesday.
    > what am I doing november 3                     Nothing on your calendar on Tuesday 3 November.
    > what's happening next tuesday                  (to a model)
    > delete the 6 am alarm   (none set)             You have no reminders set.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import intercom, localtime, quick

NOW = dt.datetime.now(dt.timezone.utc).isoformat()


class TheDateHeNamed(unittest.TestCase):
    def test_the_date_is_said_his_ways_and_no_other(self):
        said = quick._date_said(dt.date(2026, 11, 3))
        for text in ("my flight is november 3 at 7 am", "nov 3rd", "the 3rd of november", "november 3, 2026"):
            self.assertTrue(said.search(text), text)
        for text in ("november 30", "november 13", "november 3 2025"):
            self.assertFalse(said.search(text), text)

    def test_a_note_naming_the_day_is_read_on_that_day(self):
        tz = localtime.operator_tz()
        day = dt.datetime.now(tz).date() + dt.timedelta(days=3)
        note = {"text": f"my flight to Denver is {day.strftime('%B')} {day.day} at 7 am", "ts": NOW}
        with mock.patch.object(quick, "_notes", return_value=[note, {"text": f"when is {day.strftime('%B')} {day.day}", "ts": NOW}]):
            self.assertEqual(quick._dated_notes(day), [f"your flight to Denver is {day.strftime('%B')} {day.day} at 7 am"])
            self.assertIn("your flight to Denver", quick._plans_told(day.strftime("%A").lower()))

    def test_happening_next_tuesday_is_the_agenda(self):
        self.assertEqual(quick.match("what's happening next tuesday"), ("agenda", "tuesday"))
        self.assertEqual(quick.match("what am i doing next friday"), ("agenda", "friday"))


class NoAlarmToDelete(unittest.TestCase):
    def test_an_alarm_by_its_time_is_still_an_alarm(self):
        with mock.patch.object(intercom, "_reminder_schedules", return_value=[]):
            self.assertEqual(intercom._one_reminder("wake up 6 am")[1], "You have no alarms set.")


if __name__ == "__main__":
    unittest.main()
