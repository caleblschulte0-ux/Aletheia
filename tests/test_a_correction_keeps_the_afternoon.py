"""A follow-up keeps what the first ask already settled.

    > remind me at 5 to stretch   -> tomorrow at 5 pm
    > make that 6                 -> tomorrow at 6 AM
    > what time is it in london
    > and in tokyo?               -> filed for a model
    > what's the weather
    > how about tomorrow          -> "I can't think just now"
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, quick, voice


def at(hour):
    tz = localtime.operator_tz()
    day = dt.datetime.now(tz).date() + dt.timedelta(days=1)
    return dt.datetime.combine(day, dt.time(hour, 0), tzinfo=tz).isoformat()


class MakeThat(unittest.TestCase):
    def moved(self, first_at, said):
        with mock.patch.object(voice, "_previous_ask", return_value="remind me at 5 to stretch"), \
             mock.patch.object(voice, "interpret",
                               side_effect=lambda t: {"command": {"kind": "remind_at", "at": first_at,
                                                                  "text": "stretch"}}):
            return voice._moved_reminder(said, said.split()[-1])["command"]

    def test_an_afternoon_reminder_stays_in_the_afternoon(self):
        cmd = self.moved(at(17), "make that 6")
        self.assertEqual(dt.datetime.fromisoformat(cmd["at"]).hour, 18)
        self.assertEqual(cmd["replaces"], "stretch")

    def test_a_morning_reminder_stays_in_the_morning(self):
        cmd = self.moved(at(9), "make that 10")
        self.assertEqual(dt.datetime.fromisoformat(cmd["at"]).hour, 10)

    def test_a_said_am_or_pm_still_wins(self):
        with mock.patch.object(voice, "_previous_ask", return_value="remind me at 5 to stretch"), \
             mock.patch.object(voice, "interpret",
                               side_effect=lambda t: {"command": {"kind": "remind_at", "at": at(17),
                                                                  "text": "stretch"}}):
            cmd = voice._moved_reminder("make that 6 am", "6 am")["command"]
        self.assertEqual(dt.datetime.fromisoformat(cmd["at"]).hour, 6)


class AndInTokyo(unittest.TestCase):
    def test_the_preposition_is_not_said_twice(self):
        with mock.patch.object(quick, "_previous_ask", return_value="what time is it in london"):
            said = quick._follow_up("and in tokyo")
        self.assertIn("Tokyo", said)

    def test_a_day_is_added_when_the_first_ask_named_none(self):
        with mock.patch.object(quick, "_previous_ask", return_value="what's the weather"), \
             mock.patch.object(quick, "_weather", side_effect=lambda when="": f"weather for {when or 'now'}"):
            self.assertEqual(quick._follow_up("how about tomorrow"), "weather for tomorrow")


if __name__ == "__main__":
    unittest.main()
