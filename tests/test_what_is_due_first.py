"""Talked to her, 2026-10-12, every model off: "which is due first" and "what's due soonest" after
two tasks went to a model, while "which of those is most urgent" named the nearest deadline."""

import unittest
from unittest import mock

from aletheia import quick


class WhatIsDueFirst(unittest.TestCase):

    def test_the_due_first_phrasings_name_the_one(self):
        with mock.patch.object(quick, "_task_top", return_value="TOP") as top:
            for asked in ("which is due first", "what's due soonest", "what's due next", "which one is due first"):
                self.assertEqual((quick.match(asked) or ("",))[0], "focus", asked)
                self.assertIn("TOP", quick.answer(asked), asked)
        self.assertTrue(top.called)


if __name__ == "__main__":
    unittest.main()
