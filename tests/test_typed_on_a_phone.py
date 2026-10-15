"""2026-10-15, every model off: typed on a phone, "pls remind me 2morrow at 8
to walk the dog", "wats the time" and "whats on my todo" each went to a
model; and "add milk and remind me at 5 to buy it" set a reminder to "buy
it"."""
import unittest
from unittest import mock

from aletheia import voice


class TypedOnAPhone(unittest.TestCase):
    def test_the_shorthand_is_the_word(self):
        self.assertEqual(voice._texted("pls remind me 2morrow at 8 to walk the dog"),
                         "remind me tomorrow at 8 to walk the dog")
        self.assertEqual(voice._texted("thea plz add eggs"), "thea add eggs")
        self.assertEqual(voice._texted("remind me tonite to lock up"), "remind me tonight to lock up")
        self.assertEqual(voice._texted("wats the time"), "what's the time")
        self.assertEqual(voice._texted("whats on my todo"), "whats on my to do list")

    def test_a_texted_reminder_is_a_reminder(self):
        got = voice.interpret("thea pls remind me tmrw at 8 to walk the dog")["command"]
        self.assertEqual(got["kind"], "remind_at")
        self.assertEqual(got["text"], "walk the dog")

    def test_words_that_only_look_like_it_are_left(self):
        self.assertEqual(voice._texted("the pls file is on the desk"), "the pls file is on the desk")
        self.assertEqual(voice._texted("add a todo app to the list"), "add a todo app to the list")


class ItIsWhatWasAdded(unittest.TestCase):
    def test_it_is_the_item(self):
        self.assertEqual(voice._it_is_the_item("add milk", "remind me at 5 to buy it"), "remind me at 5 to buy milk")

    def test_a_half_that_added_nothing_leaves_it(self):
        self.assertEqual(voice._it_is_the_item("set a timer for 5 minutes", "remind me at 5 to check it"),
                         "remind me at 5 to check it")

    def test_the_split_carries_it(self):
        asks = voice.two_asks("add milk and remind me at 5 to buy it")
        self.assertEqual(asks, ["add milk", "remind me at 5 to buy milk"])


if __name__ == "__main__":
    unittest.main()
