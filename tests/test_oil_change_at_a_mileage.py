""""I got an oil change today at 42000 miles" and "every 5000 miles": "when
is my next oil change" read the note back, and with the car at 44,000 it
said 49,000 (2026-10-21, every model off)."""
import unittest
from unittest import mock

from aletheia import quick

EVERY = {"text": "my car needs an oil change every 5000 miles"}
DONE = {"text": "I got an oil change today at 42000 miles"}


class NextOilChange(unittest.TestCase):
    def ask(self, said, *rows):
        with mock.patch.object(quick, "_notes", return_value=list(rows)):
            return quick.answer(said)

    def test_from_the_mileage_it_was_done_at(self):
        self.assertEqual(self.ask("when is my next oil change", DONE, EVERY),
                         "At 47,000 miles - your last oil change was at 42,000, and you said every 5,000.")

    def test_how_far_with_the_cars_mileage(self):
        said = self.ask("how many miles until my next oil change", {"text": "my car has 44000 miles"}, DONE, EVERY)
        self.assertEqual(said, "About 3,000 miles: it's due at 47,000 and you told me the car has 44,000.")

    def test_how_far_without_it_asks_for_it(self):
        said = self.ask("how many miles until my next oil change", DONE, EVERY)
        self.assertIn("due at 47,000", said)
        self.assertIn("mileage", said)


if __name__ == "__main__":
    unittest.main()
