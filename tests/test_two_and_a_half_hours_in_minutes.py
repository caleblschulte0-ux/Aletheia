"""A spoken half in a duration conversion is the number.

2026-10-28, talking to her with the models off:

    > what's 2.5 hours in minutes
      150 minutes.
    > how many minutes in 2 and a half hours
      I can't think just now: ...
"""
import unittest

from aletheia import quick


class SpokenHalves(unittest.TestCase):
    def test_every_way_he_says_it(self):
        for q, said in (("how many minutes in 2 and a half hours", "150 minutes."),
                        ("what's 2 and a half hours in minutes", "150 minutes."),
                        ("how many minutes is an hour and a half", "90 minutes."),
                        ("convert an hour and a half to minutes", "90 minutes."),
                        ("what's half an hour in seconds", "1,800 seconds.")):
            self.assertEqual(quick.answer(q), said, q)

    def test_the_digits_are_unchanged(self):
        self.assertEqual(quick.answer("what's 2.5 hours in minutes"), "150 minutes.")
        self.assertEqual(quick._direct("what time will it be in half an hour"), "what time will it be in half an hour")


if __name__ == "__main__":
    unittest.main()
