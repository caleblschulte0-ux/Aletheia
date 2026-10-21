""""I was born in 1999" and then "how old am I" answered "I don't have your
birthday" (2026-10-21, every model off)."""
import unittest
from unittest import mock

from aletheia import quick


class ABirthYearAlone(unittest.TestCase):
    def ask(self, said):
        with mock.patch.object(quick, "_birthday_on_file", return_value=None), \
                mock.patch.object(quick, "_birth_year_said", return_value=1999):
            return quick.answer(said)

    def test_how_old_am_i(self):
        said = self.ask("how old am I")
        self.assertRegex(said, r"^\d\d or \d\d - you were born in 1999")

    def test_how_old_in_a_year(self):
        self.assertTrue(self.ask("how old will I be in 2030").startswith("30 or 31 in 2030"))

    def test_when_is_my_birthday(self):
        self.assertIn("born in 1999, but not the date", self.ask("when is my birthday"))

    def test_nothing_said_is_still_nothing(self):
        with mock.patch.object(quick, "_birthday_on_file", return_value=None), \
                mock.patch.object(quick, "_birth_year_said", return_value=None):
            self.assertIn("I don't have your birthday", quick.answer("how old am I"))


if __name__ == "__main__":
    unittest.main()


class RunsAndWorkoutTimers(unittest.TestCase):
    def test_how_many_runs_is_the_count(self):
        self.assertEqual(quick._direct("how many runs this week"), "how many times did i run this week")
        self.assertEqual(quick._direct("how many workouts"), "how many times did i work out this week")

    def test_a_workout_timer_with_no_length_is_a_stopwatch(self):
        from aletheia import voice
        self.assertEqual(voice.interpret("start a workout timer")["command"], {"kind": "stopwatch", "action": "start"})
        self.assertNotEqual(voice.interpret("set a workout timer for 20 minutes")["command"]["kind"], "stopwatch")
