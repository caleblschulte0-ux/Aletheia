""""3/4 of a cup doubled" and "3/4 cup times 2" went to a model, and
"double 3/4 cup" said "1 and a half cup" (2026-10-14)."""
import unittest

from aletheia import quick


class KitchenSumsTheOtherWayRound(unittest.TestCase):
    def test_said_after(self):
        self.assertEqual(quick.answer("what's 3/4 of a cup doubled"), "1 and a half cups.")
        self.assertEqual(quick.answer("1 1/2 cups halved"), "Three quarters of a cup.")
        self.assertEqual(quick.answer("what is 3/4 cup times 2"), "1 and a half cups.")
        self.assertEqual(quick.answer("2 cups divided by 3"), "Two thirds of a cup.")

    def test_more_than_one_is_plural(self):
        self.assertEqual(quick.answer("double 3/4 cup"), "1 and a half cups.")
        self.assertEqual(quick.answer("double 1/2 cup"), "1 cup.")
        self.assertEqual(quick.answer("triple 1 tbsp"), "3 tbsp.")

    def test_money_is_not_a_kitchen_sum(self):
        self.assertIsNone(quick._fractions("20 dollars times 3"))


if __name__ == "__main__":
    unittest.main()
