""""Remind me to call mom when I get home", then "what reminders do I have"
said "You have no reminders set" (2026-10-15, every model off)."""
import unittest
from unittest import mock

from aletheia import intercom, quick


class AReminderForHome(unittest.TestCase):
    def test_alone_it_is_still_listed(self):
        with mock.patch.object(intercom, "_reminder_schedules", return_value=[]), \
                mock.patch.object(quick, "_home_reminders", return_value=["call my mom"]):
            self.assertEqual(intercom._reminders_answer(), "Just the one for when you get home: call your mom.")

    def test_beside_the_clock_ones(self):
        rows = [{"kind": "once", "at": "2099-01-01T15:00:00+00:00", "command": {"kind": "notify", "text": "stretch"}}]
        with mock.patch.object(intercom, "_reminder_schedules", return_value=rows), \
                mock.patch.object(quick, "_home_reminders", return_value=["call mom"]):
            said = intercom._reminders_answer()
        self.assertTrue(said.startswith("1 reminder: stretch"), said)
        self.assertTrue(said.endswith(" And when you get home, call mom."), said)

    def test_a_filtered_question_is_not_padded(self):
        with mock.patch.object(intercom, "_reminder_schedules", return_value=[]), \
                mock.patch.object(quick, "_home_reminders", return_value=["call mom"]):
            self.assertEqual(intercom._reminders_answer("recurring"), "You have no repeating reminders set.")

    def test_none_is_none(self):
        with mock.patch.object(intercom, "_reminder_schedules", return_value=[]), \
                mock.patch.object(quick, "_home_reminders", return_value=[]):
            self.assertEqual(intercom._reminders_answer(), "You have no reminders set.")


if __name__ == "__main__":
    unittest.main()
