"""Several things for the shopping list are one sentence, not an approval."""
import unittest
from unittest import mock

from aletheia import intercom, voice


class AListIsOneBreath(unittest.TestCase):
    def cmd(self, said):
        return (voice._interpret(said) or {}).get("command") or {}

    def test_a_comma_list_goes_straight_on(self):
        c = self.cmd("add eggs, bread and butter to my shopping list")
        self.assertEqual(c.get("kind"), "shopping_add")
        self.assertEqual(intercom.shopping_items_of(c["item"]), ["eggs", "bread", "butter"])

    def test_a_dish_with_and_in_its_name_is_one_row(self):
        self.assertEqual(intercom.shopping_items_of("mac and cheese"), ["mac and cheese"])
        self.assertEqual(intercom.shopping_items_of("eggs, mac and cheese and milk"),
                         ["eggs", "mac and cheese", "milk"])
        self.assertEqual(self.cmd("add mac and cheese to the list").get("kind"), "shopping_add")

    def test_a_doubtful_shape_still_goes_to_the_planner(self):
        self.assertNotEqual(self.cmd("add eggs milk and bread to the shopping list").get("kind"),
                            "shopping_add")


class AnythingTomorrowIsHisCalendar(unittest.TestCase):
    def cmd(self, said):
        return (voice._interpret(said) or {}).get("command") or {}

    def test_anything_tomorrow_is_free_time(self):
        self.assertEqual(self.cmd("do I have anything tomorrow").get("kind"), "free_time")
        self.assertEqual(self.cmd("do I have anything on friday").get("kind"), "free_time")

    def test_this_weekend_is_a_stretch(self):
        c = self.cmd("do I have any plans this weekend")
        self.assertEqual((c.get("kind"), c.get("when")), ("calendar_find_free", "this weekend"))

    def test_a_file_is_still_a_file(self):
        self.assertEqual(self.cmd("do I have a file called taxes").get("kind"), "file_find")


if __name__ == "__main__":
    unittest.main()
