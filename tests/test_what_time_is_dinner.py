""""What time is dinner Saturday" went to a model a turn after dinner with Sam
was pencilled in for Saturday at 7; a renamed task was journaled as
"description corrected — was: ..." and read out in the morning (2026-10-14)."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, quick, voice


class DinnerSaturday(unittest.TestCase):
    def _rows(self):
        tz = localtime.operator_tz()
        day = dt.date.fromisoformat(voice._spoken_day("saturday"))
        at = dt.datetime.combine(day, dt.time(19, 0), tzinfo=tz).astimezone(dt.timezone.utc)
        return [(at, "dinner with Sam", "calendar")]

    def test_the_meal_on_that_day(self):
        with mock.patch.object(quick, "_coming", return_value=self._rows()):
            said = quick.answer("what time is dinner saturday")
        self.assertTrue(said.startswith("Your dinner with Sam is "), said)
        self.assertIn("7 pm", said)

    def test_another_day_is_not_that_dinner(self):
        with mock.patch.object(quick, "_coming", return_value=self._rows()):
            self.assertIsNone(quick.answer("what time is dinner " + ("monday" if dt.date.today().weekday() != 0 else "tuesday")))

    def test_with_nobody_thinking_she_says_what_she_checked(self):
        said = quick.when_nobody_can_think("what time is lunch tomorrow")
        self.assertTrue(said.startswith("Nothing on your calendar mentions lunch tomorrow."), said)


class RenamedTask(unittest.TestCase):
    def test_the_morning_reads_a_reminder_as_set(self):
        self.assertEqual(quick._as_done("I'll remind you today at 6 pm: call the bank"),
                         "Set a reminder for today at 6 pm: call the bank")


if __name__ == "__main__":
    unittest.main()
