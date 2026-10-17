""""What time is it", asked just after a reminder was set, answered with the
reminder ("That's today at 4:47 pm: check the oven"). "I need paper towels
too" put "paper towels too" on the list, and "what's tomorrow morning look
like" and "is next monday a holiday" went to a model (2026-10-17, every model
off)."""
import unittest
from unittest import mock

from aletheia import calendar as cal, quick, voice


class TheClockIsNotTheReminder(unittest.TestCase):
    def test_what_time_is_it_is_not_a_bare_when(self):
        self.assertIsNone(voice._BARE_WHEN.fullmatch("what time is it"))
        self.assertIsNone(voice._BARE_WHEN.fullmatch("what day is it"))

    def test_what_time_is_that_still_is(self):
        self.assertIsNotNone(voice._BARE_WHEN.fullmatch("what time is that"))
        self.assertIsNotNone(voice._BARE_WHEN.fullmatch("when is it"))


class TooIsAboutTheSentence(unittest.TestCase):
    def test_paper_towels_too(self):
        command = voice.interpret("I need paper towels too")["command"]
        self.assertEqual(command, {"kind": "shopping_add", "item": "paper towels"})


class ADayAndAPartLooksLike(unittest.TestCase):
    def test_the_phrasings(self):
        for said, label in (("what's tomorrow morning look like", "tomorrow morning"),
                            ("how's tomorrow afternoon looking", "tomorrow afternoon")):
            with self.subTest(said=said), mock.patch.object(cal, "all_events", return_value=[]), \
                    mock.patch.object(quick, "_reminders_in_part", return_value=""):
                self.assertEqual(quick.answer(said), f"Nothing on your calendar {label}.")


class NextMondayAHoliday(unittest.TestCase):
    def test_answered(self):
        said = quick.answer("is next monday a holiday")
        self.assertTrue(said and (said.startswith("No.") or said.startswith("Yes")), said)


if __name__ == "__main__":
    unittest.main()
