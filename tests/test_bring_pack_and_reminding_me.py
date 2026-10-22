""""What do I need to bring tomorrow", "what are you reminding me about
tomorrow" and "pack a toothbrush for my trip" went to a model, and "did I
take my allergy pill" said "you took allergy pill" (2026-10-21)."""
import unittest

from aletheia import quick, voice


class TheyAreQuestionsShesAnswered(unittest.TestCase):
    def test_rewrites(self):
        self.assertEqual(quick._direct("what do i need to bring tomorrow"), "what's due tomorrow")
        self.assertEqual(quick._direct("what are you reminding me about tomorrow"), "what reminders do i have tomorrow")
        self.assertEqual(quick._direct("what will you be reminding me of on friday"), "what reminders do i have on friday")

    def test_pack_for_the_trip(self):
        cmd = voice.interpret("pack a toothbrush for my trip")["command"]
        self.assertEqual((cmd["kind"], cmd["list"], cmd["item"]), ("list_add", "packing", "a toothbrush"))
        self.assertNotEqual(voice.interpret("pack my bags for the trip")["command"].get("kind"), "list_add")

    def test_a_kind_of_pill_is_yours(self):
        self.assertEqual(quick._yours_med("allergy pill"), "your ")
        self.assertEqual(quick._yours_med("ibuprofen"), "")


if __name__ == "__main__":
    unittest.main()
