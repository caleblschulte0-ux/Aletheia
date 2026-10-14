""""My sister's name is Emma", "Emma likes lilies", then "what flowers does
my sister like" went to a model (2026-10-14): the relation was not turned
into her name, and lilies never say "flower"."""
import unittest
from unittest import mock

from aletheia import quick


class WhatFlowers(unittest.TestCase):
    ROWS = [{"text": "Emma likes lilies"}, {"text": "my sister's name is Emma"}, {"text": "Emma likes hiking"}]

    def test_by_relation_and_by_name(self):
        with mock.patch.object(quick, "_notes", return_value=self.ROWS), \
                mock.patch.object(quick, "_name_for_relation", side_effect=lambda rel: "Emma" if rel == "sister" else None):
            for asked in ("what flowers does my sister like", "what kind of flowers does emma like"):
                self.assertEqual(quick.answer(asked), "You told me Emma likes lilies.", asked)

    def test_a_like_of_another_kind_is_not_it(self):
        with mock.patch.object(quick, "_notes", return_value=[{"text": "Emma likes hiking"}]), \
                mock.patch.object(quick, "_name_for_relation", return_value=None):
            self.assertIsNone(quick._their_kind("what flowers does emma like"))


if __name__ == "__main__":
    unittest.main()
