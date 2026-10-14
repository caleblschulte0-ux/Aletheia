""""Save a recipe for tacos: ground beef, tortillas, cheese" went to the
planner, "what do I need to make tacos" too, and "add the taco stuff to my
shopping list" put "the taco stuff" on it (2026-10-14)."""
import unittest
from unittest import mock

from aletheia import quick, voice

TACOS = [{"text": "the recipe for tacos: ground beef, tortillas, cheese"}]


class SaveARecipe(unittest.TestCase):
    def test_saved_as_a_recipe_note(self):
        self.assertEqual(voice._interpret("save a recipe for tacos: ground beef, tortillas, cheese")["command"],
                         {"kind": "note", "text": "the recipe for tacos: ground beef, tortillas, cheese"})
        self.assertEqual(voice._interpret("my recipe for chili is beans, beef and tomatoes")["command"],
                         {"kind": "note", "text": "the recipe for chili: beans, beef and tomatoes"})

    def test_read_back(self):
        with mock.patch.object(quick, "_notes", return_value=TACOS):
            for asked in ("what do i need to make tacos", "what goes in tacos", "what does the taco recipe need"):
                self.assertEqual(quick.answer(asked), "Your tacos recipe calls for ground beef, tortillas and cheese.", asked)

    def test_no_recipe_hands_on(self):
        with mock.patch.object(quick, "_notes", return_value=TACOS):
            self.assertFalse(quick._saved_recipe("lasagna"))


class AddTheTacoStuff(unittest.TestCase):
    def test_its_ingredients(self):
        with mock.patch.object(quick, "_notes", return_value=TACOS):
            self.assertEqual(voice._interpret("add the taco stuff to my shopping list")["command"],
                             {"kind": "shopping_add", "item": "ground beef, tortillas, cheese"})

    def test_no_recipe_asks(self):
        with mock.patch.object(quick, "_notes", return_value=[]):
            out = voice._interpret("add the ingredients for lasagna to the grocery list")
        self.assertIsNone(out["command"])
        self.assertTrue(out["say"].startswith("I don't have a recipe for lasagna."))

    def test_a_plain_item_is_still_an_item(self):
        self.assertEqual(voice._interpret("add eggs to my shopping list")["command"], {"kind": "shopping_add", "item": "eggs"})


if __name__ == "__main__":
    unittest.main()
