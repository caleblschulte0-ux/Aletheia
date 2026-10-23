""""Add a work trip to Denver from November 3 to 5" went to the planner
(2026-10-23). It is one hold from the first morning to the last night,
and every reader says it as days, never "at 12 am".
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import calendar, localtime, quick, voice


class ATripIsDays(unittest.TestCase):
    def test_a_trip_from_one_date_to_another_is_one_hold_of_whole_days(self):
        got = voice.interpret("add a work trip to Denver from november 3 to 5")["command"]
        self.assertEqual(got["kind"], "calendar_hold")
        self.assertEqual(got["title"], "work trip to Denver")
        start, end = dt.datetime.fromisoformat(got["start"]), dt.datetime.fromisoformat(got["end"])
        self.assertEqual((start.month, start.day, start.hour), (11, 3, 0))
        self.assertEqual((end.month, end.day, end.hour), (11, 6, 0))

    def test_a_vacation_put_on_the_calendar(self):
        got = voice.interpret("put my vacation on the calendar from december 20 to december 27")["command"]
        self.assertEqual((got["kind"], got["title"]), ("calendar_hold", "vacation"))

    def events(self):
        # The coming 3 November, so the fixture moves with the calendar.
        tz = localtime.operator_tz()
        today = dt.datetime.now(tz).date()
        year = today.year if (today.month, today.day) <= (11, 3) else today.year + 1
        start = dt.datetime(year, 11, 3, tzinfo=tz)
        return start, [{"id": "t", "title": "work trip to Denver", "start": start.isoformat(),
                        "end": (start + dt.timedelta(days=3)).isoformat(), "status": "TENTATIVE"}]

    def test_the_middle_day_has_the_trip_on_it(self):
        start, events = self.events()
        with mock.patch.object(calendar, "all_events", return_value=events):
            said = quick._agenda_on("november 4")
        self.assertIn("work trip to Denver, all day", said)
        self.assertNotIn("12 am", said)

    def test_when_is_it_says_the_days(self):
        start, events = self.events()
        last = start + dt.timedelta(days=2)
        with mock.patch.object(calendar, "all_events", return_value=events):
            said = quick._calendar_when(calendar.parse_time(events[0]["start"]), "work trip to Denver")
        self.assertEqual(said, f"from {start.strftime('%A')} 3 November to {last.strftime('%A')} 5 November")

    def test_an_hour_long_event_is_not_days(self):
        tz = localtime.operator_tz()
        start = dt.datetime(2030, 1, 1, 10, tzinfo=tz)
        event = {"start": start.isoformat(), "end": (start + dt.timedelta(hours=1)).isoformat()}
        self.assertIsNone(quick._whole_days(event, tz))


if __name__ == "__main__":
    unittest.main()
