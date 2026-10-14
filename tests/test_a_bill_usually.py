""""How much is my electric bill usually", with "my electric bill was 120
dollars" in his notes, came back "I can't think just now"; and her reminder
answer said "is next tomorrow at 8 am" (2026-10-14, every model off)."""
import unittest
from unittest import mock

from aletheia import quick


class Usually(unittest.TestCase):
    def test_the_word_usually_is_the_same_question(self):
        self.assertEqual(quick._direct("how much is my electric bill usually"), "how much is my electric bill")
        self.assertEqual(quick._direct("how much does my phone bill usually cost"), "how much is my phone bill")
        self.assertEqual(quick._direct("how much does my phone bill cost on average"), "how much is my phone bill")

    def test_read_from_his_note(self):
        with mock.patch.object(quick, "_notes", return_value=[{"text": "my electric bill was 120 dollars"}]):
            self.assertIn("120 dollars", quick.answer("how much is my electric bill usually"))


if __name__ == "__main__":
    unittest.main()
