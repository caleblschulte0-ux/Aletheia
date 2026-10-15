""""What's on my lists" and "read me all my lists" went to the planner
(2026-10-15, every model off): every list, with what is on it."""
import unittest
from unittest import mock

from aletheia import intercom, lists, voice


class WhatsOnMyLists(unittest.TestCase):
    def test_the_sentences_reach_every_list(self):
        for said in ("what's on my lists", "read me all my lists", "what's on all of my lists"):
            with self.subTest(said=said):
                self.assertEqual(voice._interpret(said)["command"], {"kind": "list_read", "list": voice.EVERY_LIST})

    def test_each_list_with_what_is_on_it(self):
        with mock.patch.object(intercom, "_shopping_items", return_value=[{"need": "milk"}, {"need": "eggs"}]), \
                mock.patch.object(lists, "all_lists", return_value=[{"name": "packing", "open": 1}, {"name": "books", "open": 0}]), \
                mock.patch.object(lists, "items", side_effect=lambda n: ["toothbrush"] if n == "packing" else []):
            said = intercom._named_list("list_read", {"list": voice.EVERY_LIST})
        self.assertEqual(said, "Your shopping list has milk and eggs; your packing list has toothbrush; your books list is empty.")

    def test_nothing_anywhere(self):
        with mock.patch.object(intercom, "_shopping_items", return_value=[]), \
                mock.patch.object(lists, "all_lists", return_value=[]):
            said = intercom._named_list("list_read", {"list": voice.EVERY_LIST})
        self.assertTrue(said.startswith("You don't have anything on a list yet"), said)


if __name__ == "__main__":
    unittest.main()
