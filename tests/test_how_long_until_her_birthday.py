"""Talked to her, 2026-10-12: "my sister's birthday is November 3", then "when is her birthday"
answered and "how many days until her birthday" went to a model. "How old is she
turning" after it did too, while "how old is my sister turning" answered."""

import unittest
from unittest import mock

from aletheia import converse, voice


class HowLongUntilHerBirthday(unittest.TestCase):

    def _after(self, said, asked):
        with mock.patch.object(converse, "recent", lambda limit=3: [{"he_asked": said}]):
            return voice._with_the_person_named(asked)

    def test_her_is_the_person_just_named(self):
        self.assertEqual(self._after("my sister's birthday is november 3", "how many days until her birthday"),
                         "how many days until my sister's birthday")
        self.assertEqual(self._after("Dana's birthday is march 3", "how long until her birthday?"),
                         "how long until Dana's birthday?")
        self.assertEqual(self._after("Sam's birthday is may 1", "how many weeks till his next birthday"),
                         "how many weeks till Sam's birthday")

    def test_how_old_is_she_is_the_person_just_named(self):
        self.assertEqual(self._after("my sister's birthday is march 3", "how old is she turning"),
                         "how old is my sister turning")
        self.assertEqual(self._after("jake's birthday is june 2 1990", "how old will he be?"),
                         "how old will Jake be?")
        self.assertEqual(self._after("jake's birthday is june 2 1990", "how old is he"), "how old is Jake")
        self.assertEqual(self._after("what's the weather", "how old is she turning"), "how old is she turning")

    def test_nobody_named_leaves_it_as_said(self):
        self.assertEqual(self._after("what's the weather", "how many days until her birthday"),
                         "how many days until her birthday")


if __name__ == "__main__":
    unittest.main()
