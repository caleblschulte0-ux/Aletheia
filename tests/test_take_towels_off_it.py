""""Start a packing list", "add sunscreen and towels", "take towels off it"
(2026-10-12: the last went to a model, while "add flip flops to it" worked).

"It" is the list he was just on: his named one, or the shopping list when that
was what the last turn was about. "The first one" stays the read-back rule's.
"""
import unittest
from unittest import mock

from aletheia import converse, lists, policy, voice


def said(sentence, turns):
    with mock.patch.object(policy, "all_approvals", return_value=[]), \
            mock.patch.object(converse, "recent", side_effect=lambda limit=3: turns[-limit:]), \
            mock.patch.object(lists, "exists", return_value=True):
        return voice.interpret(f"thea {sentence}")["command"]


PACKING = [{"he_asked": "add sunscreen and towels", "she_answered": "Added to your packing list: sunscreen and towels."}]
SHOPPING = [{"he_asked": "add milk to the shopping list", "she_answered": "Added to the shopping list: milk."}]


class TakeItOffIt(unittest.TestCase):
    def test_the_named_list_just_used(self):
        for sentence in ("take towels off it", "cross towels off the list", "remove towels from it",
                         "delete towels from that list"):
            self.assertEqual(said(sentence, PACKING), {"kind": "list_off", "list": "packing", "item": "towels"}, sentence)

    def test_the_shopping_list_just_used(self):
        self.assertEqual(said("take milk off it", SHOPPING), {"kind": "shopping_off", "item": "milk"})


if __name__ == "__main__":
    unittest.main()
