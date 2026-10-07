""""Repeat that" reads the thread she actually keeps."""
import unittest
from unittest import mock

from aletheia import quick


class SayThatAgain(unittest.TestCase):
    def test_her_last_answer(self):
        turns = [{"you": "what time is it", "her": "8:45 pm."}]
        with mock.patch("aletheia.converse._thread", return_value=turns):
            self.assertEqual(quick.answer("repeat that"), "I said: 8:45 pm.")

    def test_twice_says_the_same_thing(self):
        turns = [{"you": "what time is it", "her": "8:45 pm."},
                 {"you": "repeat that", "her": "8:45 pm."},
                 {"you": "i didn't catch that", "her": "8:45 pm."}]
        with mock.patch("aletheia.converse._thread", return_value=turns):
            self.assertEqual(quick.answer("say that again"), "I said: 8:45 pm.")

    def test_nothing_said_yet(self):
        with mock.patch("aletheia.converse._thread", return_value=[]):
            self.assertIn("haven't said anything", quick.answer("repeat that"))


class TheBattery(unittest.TestCase):
    def test_battery_is_the_power_reading(self):
        state = {"known": True, "on_ac": False, "battery_percent": 42, "has_battery": True,
                 "charging": False, "low": False, "critical": False, "seconds_left": None}
        with mock.patch("aletheia.power.status", return_value=state):
            self.assertEqual(quick.answer("what's my battery"), "The PC is on battery at 42%.")

    def test_unknown_says_so(self):
        with mock.patch("aletheia.power.status", return_value={"known": False}):
            self.assertIn("can't read the battery", quick.answer("how much battery do i have"))


if __name__ == "__main__":
    unittest.main()


class TheListAndTheNotes(unittest.TestCase):
    def test_is_it_on_my_list(self):
        rows = [{"need": "milk"}, {"need": "eggs"}]
        with mock.patch("aletheia.intercom._shopping_items", return_value=rows):
            self.assertEqual(quick.answer("is milk on my list"), "Yes - milk is on your shopping list.")
            self.assertEqual(quick.answer("are there any bananas on the list"),
                             "No, bananas aren't on your shopping list.")

    def test_a_note_with_a_colon_is_a_note(self):
        from aletheia import voice
        self.assertEqual(voice._interpret("note: buy a birthday card for dana")["command"],
                         {"kind": "note", "text": "buy a birthday card for dana"})

    def test_notes_about_someone(self):
        self.assertEqual(quick.match("what notes do i have about dana"), ("recall", "dana"))
