""""Add milk", "add eggs too", "actually take that off", "what did I just
add" said "You just added eggs" (2026-10-23) - eggs had just come off.
"""
import unittest
from unittest import mock

from aletheia import converse, quick


def thread(*hers):
    return [{"you": "x", "her": h} for h in hers]


class WhatDidIJustAddAfterUndo(unittest.TestCase):
    def ask(self, *hers):
        with mock.patch.object(converse, "_thread", return_value=thread(*hers)):
            return quick._just_added()

    def test_an_add_taken_back_off_is_not_what_he_just_added(self):
        said = self.ask("Added to the shopping list: milk.", "Added to the shopping list: eggs.",
                        "Undone: took eggs back off the shopping list.")
        self.assertIn("took it back off", said)
        self.assertIn("Before that, milk", said)
        self.assertNotIn("You just added eggs", said)

    def test_the_last_add_still_answers(self):
        self.assertEqual(self.ask("Added to the shopping list: milk.", "Added to the shopping list: bread."),
                         "You just added bread to your shopping list.")

    def test_nothing_left_still_says_what_happened(self):
        said = self.ask("Added to the shopping list: eggs.", "Undone: took eggs back off the shopping list.")
        self.assertEqual(said, "You added eggs to your shopping list and then took it back off.")


if __name__ == "__main__":
    unittest.main()
