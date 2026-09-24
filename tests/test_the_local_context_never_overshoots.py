"""The local planner's context never overshoots its budget (2026-09-24).

The "trimmed" note was added after the size check, so a context that just
fit went over by the note's own length - 1114 bytes against a budget of
1096 on a full-suite run. A local prompt over budget is one that times out
on his laptop, so the note is measured with everything else.
"""
from __future__ import annotations

import json
import unittest

from aletheia import local_planner


class TheNoteIsMeasuredToo(unittest.TestCase):
    def _fits(self, context: dict, budget: int) -> dict:
        cut = local_planner.compact_context(context, budget=budget)
        self.assertLessEqual(len(json.dumps(cut, default=str).encode("utf-8")), budget, cut)
        return cut

    def test_a_context_that_just_fits_still_fits_with_the_note(self):
        keys = list(local_planner.CONTEXT_KEYS)[:3]
        context = {k: "x" * 40 for k in keys}
        context["something_else"] = "y"        # forces the trimmed note
        whole = len(json.dumps({k: context[k] for k in keys}).encode("utf-8"))
        for budget in range(whole - 5, whole + len(local_planner.TRIMMED_NOTE) + 40):
            with self.subTest(budget=budget):
                self._fits(context, budget)

    def test_everything_fits_when_there_is_room(self):
        keys = list(local_planner.CONTEXT_KEYS)[:2]
        context = {k: "z" for k in keys}
        cut = self._fits(context, 10_000)
        self.assertEqual({k: "z" for k in keys}, cut)


if __name__ == "__main__":
    unittest.main()
