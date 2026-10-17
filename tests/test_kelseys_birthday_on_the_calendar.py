""""Add Kelsey's birthday to my calendar" went to the planner, and "remind me
a week before Kelsey's birthday to buy a gift" came back "kelsey's birthday is
in 7 days" (2026-10-17, every model off)."""
import unittest
from unittest import mock

from aletheia import quick, voice


class HerBirthday(unittest.TestCase):
    def _cmd(self, said):
        with mock.patch.object(quick, "_birthday_notes", return_value=[("Kelsey", 3, 3)]), \
                mock.patch.object(quick, "_date_in_notes", side_effect=lambda what, today: __import__("datetime").date(today.year + 1, 3, 3)):
            return voice.interpret(said)["command"]

    def test_on_the_calendar_is_the_reminder_on_the_day(self):
        command = self._cmd("add Kelsey's birthday to my calendar")
        self.assertEqual(command["kind"], "remind_at")
        self.assertEqual(command["text"], "Kelsey's birthday is today")

    def test_a_week_before_keeps_her_name_and_says_a_week(self):
        command = self._cmd("remind me a week before Kelsey's birthday to buy a gift")
        self.assertIn("Kelsey's birthday is in a week", command["text"])

    def test_two_weeks(self):
        self.assertIn("in two weeks", self._cmd("remind me two weeks before Kelsey's birthday to plan a party")["text"])


if __name__ == "__main__":
    unittest.main()
