""""My car needs an oil change every 5000 miles", "I'm at 42000 miles", "I
changed the oil today", "when is my next oil change" (2026-10-14: the
interval note read back with no number, and "how many miles until" said it
did not know when it was due).
"""
import unittest
from unittest import mock

from aletheia import quick


ROWS = [{"text": "i changed the oil today"}, {"text": "i'm at 42000 miles"},
        {"text": "my car needs an oil change every 5000 miles"}]


class TheNextOne(unittest.TestCase):
    def test_the_interval_past_the_mileage(self):
        with mock.patch.object(quick, "_notes", return_value=ROWS):
            self.assertEqual(quick.answer("when is my next oil change"),
                             "At 47,000 miles - about 5,000 more than the 42,000 you told me the car has.")
            self.assertTrue(quick.answer("how many miles until my next oil change").startswith("About 5,000 miles"))

    def test_a_due_mileage_said_outright_still_wins(self):
        rows = [{"text": "my car has 43000 miles"}, {"text": "my oil change is due at 45000 miles"}]
        with mock.patch.object(quick, "_notes", return_value=rows):
            self.assertTrue(quick.answer("how many miles until my oil change").startswith("About 2,000 miles"))

    def test_nothing_known_hands_the_question_on(self):
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIsNone(quick._miles_until("when is my next oil change"))


if __name__ == "__main__":
    unittest.main()
