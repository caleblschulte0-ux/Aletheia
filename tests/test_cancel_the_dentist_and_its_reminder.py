""""Cancel the dentist" takes its reminder with it (2026-10-12).

"I have a dentist appointment Thursday at 3", "remind me an hour before",
"cancel the dentist": the appointment came off the calendar and the 2 pm
reminder still went off for it.
"""
import unittest
from unittest import mock

from aletheia import intercom

START = "2030-10-17T20:00:00+00:00"


def row(rid, text, at, kind="once"):
    return {"id": rid, "kind": kind, "at": at, "enabled": True, "command": {"kind": "notify", "text": text}}


class RemindersBefore(unittest.TestCase):
    def test_the_one_set_ahead_of_it(self):
        rows = [row("r1", "dentist appointment Thursday at 3 pm", "2030-10-17T19:00:00+00:00"),
                row("r2", "dentist appointment Thursday at 3 pm", "2030-10-16T14:00:00+00:00"),
                row("r3", "call the dentist", "2030-10-17T15:00:00+00:00"),
                row("r4", "dentist appointment next year", "2030-11-30T15:00:00+00:00"),
                row("r5", "dentist appointment every week", "2030-10-17T19:00:00+00:00", kind="weekly")]
        with mock.patch.object(intercom, "_reminder_schedules", return_value=rows):
            got = intercom._reminders_before("Dentist appointment", START)
        self.assertEqual([r["id"] for r in got], ["r1", "r2"])

    def test_nothing_when_no_title(self):
        with mock.patch.object(intercom, "_reminder_schedules", return_value=[row("r1", "x", START)]):
            self.assertEqual(intercom._reminders_before("", START), [])


if __name__ == "__main__":
    unittest.main()
