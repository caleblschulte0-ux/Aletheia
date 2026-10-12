""""The plumber is coming Wednesday", "remind me the day before" (2026-10-12).

The follow-up went to a model; "remind me a day before the plumber comes"
looked for a calendar event called "plumber comes"; and a note that named a
day and no time was never found for "the day before" at all. The reminder
said "your plumber", too.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import calendar as cal, localtime, quick, voice

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def in_three_days():
    tz = localtime.operator_tz()
    day = dt.datetime.now(tz).date() + dt.timedelta(days=3)
    return day, DAYS[day.weekday()]


class TheDayBefore(unittest.TestCase):
    def setUp(self):
        self.day, self.name = in_three_days()
        notes = [{"text": f"the plumber is coming {self.name}", "ts": "2026-10-12T17:00:00Z"}]
        self.patches = [mock.patch.object(quick, "_notes", return_value=notes),
                        mock.patch.object(cal, "all_events", return_value=[])]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def check(self, got):
        cmd = got["command"]
        self.assertEqual(cmd["kind"], "remind_at")
        at = dt.datetime.fromisoformat(cmd["at"]).astimezone(localtime.operator_tz())
        self.assertEqual(at.date(), self.day - dt.timedelta(days=1))
        self.assertTrue(cmd["text"].startswith("the plumber "), cmd["text"])
        self.assertNotIn("12 am", cmd["text"])

    def test_said_in_full_with_the_verb(self):
        self.check(voice._interpret("remind me a day before the plumber comes"))

    def test_the_follow_up_after_the_note(self):
        with mock.patch.object(voice, "_previous_ask", return_value=f"note that the plumber is coming {self.name}"):
            self.check(voice._interpret("remind me the day before"))

    def test_an_hour_before_still_needs_a_time(self):
        self.assertIsNone(voice._event_from_notes("the plumber"))
        self.assertTrue(voice._event_from_notes("the plumber", day_only=True)["all_day"])


if __name__ == "__main__":
    unittest.main()
