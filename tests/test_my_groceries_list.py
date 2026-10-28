""""My groceries list" is the shopping list, as "my grocery list" is.

2026-10-28, talking to her with the models off:

    > add milk to my grocery list
      Added to the shopping list: milk.
    > what's on my groceries list
      I can't think just now: ...
"""
import unittest

from aletheia import quick, voice


class GroceriesList(unittest.TestCase):
    def test_it_is_the_grocery_list(self):
        self.assertEqual(voice._apostrophes("what's on my groceries list"), "what's on my grocery list")
        self.assertEqual(voice._apostrophes("add eggs to the groceries list please"), "add eggs to the grocery list please")

    def test_the_list_is_read(self):
        self.assertEqual(quick.match("what's on my groceries list"), quick.match("what's on my grocery list"))
        self.assertIsNotNone(quick.match("what's on my groceries list"))

    def test_an_add_goes_on_the_shopping_list(self):
        cmd = (voice.interpret("add eggs to my groceries list").get("command") or {})
        self.assertEqual(cmd.get("kind"), "shopping_add")


if __name__ == "__main__":
    unittest.main()
