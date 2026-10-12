""""What's my alarm for tomorrow" / "what's my reminder on Thursday" (2026-10-12).

The singular went to a model, and the alarm question was answered as
"1 reminder tomorrow: 6 am, wake up." - a reminder list, when he asked
about his alarm.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, quick


def _at(days: int, hour: int) -> dt.datetime:
    tz = localtime.operator_tz()
    day = dt.datetime.now(tz).date() + dt.timedelta(days=days)
    return dt.datetime.combine(day, dt.time(hour, 0), tzinfo=tz)


ROWS = [(_at(1, 6), "wake up", "reminder"), (_at(1, 9), "call the dentist", "reminder")]


class AlarmForADay(unittest.TestCase):
    def ask(self, sentence, rows=ROWS):
        with mock.patch.object(quick, "_coming", return_value=rows):
            return quick.answer(sentence)

    def test_the_alarm_question_names_the_alarm_only(self):
        self.assertEqual(self.ask("what's my alarm for tomorrow"), "Your alarm tomorrow is at 6 am.")

    def test_the_plural_alarm_question_too(self):
        self.assertEqual(self.ask("what are my alarms for tomorrow"), "Your alarm tomorrow is at 6 am.")

    def test_no_alarm_is_said_as_no_alarm(self):
        self.assertEqual(self.ask("what's my alarm for tomorrow", rows=ROWS[1:]), "No alarm set for tomorrow.")

    def test_the_singular_reminder_question_is_answered(self):
        got = self.ask("what's my reminder for tomorrow")
        self.assertTrue(got.startswith("2 reminders tomorrow"), got)
        self.assertIn("call the dentist", got)


if __name__ == "__main__":
    unittest.main()
