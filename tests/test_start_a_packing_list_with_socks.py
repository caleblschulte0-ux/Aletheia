""""Start a packing list with socks and a charger" (2026-10-28) went to the
planner: a new list with its first things on it is adding them."""
import unittest

from aletheia import voice


class StartAListWithThings(unittest.TestCase):
    def test_the_things_go_on_the_list(self):
        cmd = voice.interpret("start a packing list with socks and a charger")["command"]
        self.assertEqual((cmd["kind"], cmd["list"], cmd["item"]), ("list_add", "packing", "socks and a charger"))

    def test_a_grocery_list_is_the_shopping_list(self):
        cmd = voice.interpret("start a shopping list with milk and eggs")["command"]
        self.assertEqual((cmd["kind"], cmd["item"]), ("shopping_add", "milk and eggs"))
        self.assertEqual(voice.interpret("create a grocery list with milk")["command"]["kind"], "shopping_add")

    def test_a_list_for_something_is_still_just_a_list(self):
        self.assertEqual(voice.interpret("make a packing list for my trip")["command"],
                         {"kind": "list_new", "list": "packing"})


if __name__ == "__main__":
    unittest.main()
