""""Clear my calendar on Monday" and "clear Friday" (2026-10-28) went to the
planner, though "clear my calendar Friday" named her holds. And "move focus
time to Monday afternoon" said she can't move calendar things - about a hold
she had pencilled in herself."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import calendar, localtime, voice


def hold(title, day, hour, *, mine=True):
    tz = localtime.operator_tz()
    start = dt.datetime.combine(day, dt.time(hour), tzinfo=tz)
    return {"title": title, "start": start.isoformat(), "end": (start + dt.timedelta(hours=3)).isoformat(),
            "status": "TENTATIVE" if mine else "CONFIRMED", "source": "hold:x" if mine else "ics"}


def next_weekday(n):
    today = dt.datetime.now(localtime.operator_tz()).date()
    return today + dt.timedelta(days=(n - today.weekday()) % 7 or 7)


class ClearADay(unittest.TestCase):
    def test_on_monday_and_a_bare_day_are_the_same_ask(self):
        friday = next_weekday(4)
        with mock.patch.object(calendar, "all_events", return_value=[hold("Focus time", friday, 14)]):
            for said in ("clear my calendar on friday", "clear friday"):
                got = voice.interpret(said)
                self.assertIsNone(got["command"], said)
                self.assertIn("I pencilled in Focus time at 2 pm", got["say"], said)


class MoveToAPartOfTheDay(unittest.TestCase):
    def test_monday_morning_is_the_morning(self):
        friday = next_weekday(4)
        with mock.patch.object(calendar, "all_events", return_value=[hold("Focus time", friday, 14)]):
            cmd = voice.interpret("move focus time to tuesday morning")["command"]
        start = dt.datetime.fromisoformat(cmd["start"]).astimezone(localtime.operator_tz())
        self.assertEqual((cmd["kind"], start.strftime("%A"), start.hour), ("calendar_hold", "Tuesday", 9))
        self.assertEqual(cmd["minutes"], 180)

    def test_an_afternoon_hold_keeps_its_hour_in_the_afternoon(self):
        friday = next_weekday(4)
        with mock.patch.object(calendar, "all_events", return_value=[hold("Focus time", friday, 14)]):
            cmd = voice.interpret("move focus time to monday afternoon")["command"]
        self.assertEqual(dt.datetime.fromisoformat(cmd["start"]).astimezone(localtime.operator_tz()).hour, 14)


if __name__ == "__main__":
    unittest.main()
