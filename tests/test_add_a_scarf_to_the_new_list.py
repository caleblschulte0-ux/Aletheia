""""Make a list of gift ideas for mom", then "add a scarf", put the scarf on the
shopping list; "I packed the charger" and "what's left to pack" went to the
planner and a model with a packing list on file (2026-10-23).
"""
import unittest
from unittest import mock

from aletheia import converse, lists, voice


def _after(she_said):
    return mock.patch.object(converse, "recent", return_value=[{"he_asked": "x", "she_answered": she_said}])


class AddAScarfToTheNewList(unittest.TestCase):
    def _cmd(self, sentence):
        return voice.interpret(sentence).get("command") or {}

    def test_a_bare_add_follows_the_list_just_started(self):
        with _after('Started your gift ideas for mom list. Say "add ... to my gift ideas for mom list".'):
            cmd = self._cmd("add a scarf")
        self.assertEqual(cmd, {"kind": "list_add", "list": "gift ideas for mom", "item": "a scarf"})

    def test_and_the_list_just_added_to(self):
        with _after("Added to your packing list: socks."):
            self.assertEqual(self._cmd("add sunscreen").get("list"), "packing")

    def test_otherwise_it_is_still_shopping(self):
        with _after("Added to the shopping list: milk."):
            self.assertEqual(self._cmd("add eggs").get("kind"), "shopping_add")
        with _after("It's 7 pm."):
            self.assertEqual(self._cmd("add eggs").get("kind"), "shopping_add")

    def test_i_packed_it_crosses_it_off(self):
        with mock.patch.object(lists, "items", return_value=["socks", "phone charger"]):
            self.assertEqual(self._cmd("i packed the charger"),
                             {"kind": "list_off", "list": "packing", "item": "charger"})
            self.assertNotEqual(self._cmd("i packed my lunch").get("kind"), "list_off")

    def test_whats_left_to_pack(self):
        for sentence in ("what's left to pack", "what haven't i packed yet", "what else do i need to pack"):
            with self.subTest(sentence=sentence):
                self.assertEqual(self._cmd(sentence), {"kind": "list_read", "list": "packing"})


if __name__ == "__main__":
    unittest.main()
