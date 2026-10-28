"""His notes from a day, asked as "what did I ask you to remember".

2026-10-28, talking to her with the models off:

    > remember my car is parked on level 3
    > what did i ask you to remember today
      I can't think just now: Claude and ChatGPT are both out ...

"What have I asked you to remember" was a read of her notes already; the
same question with "today" on the end, and "what have you remembered for
me", went to a model that was not there.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import quick


def _now_notes():
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    return [{"text": "your car is parked on level 3", "ts": now}]


class AskedToRemember(unittest.TestCase):
    def test_a_day_on_the_end(self):
        with mock.patch.object(quick, "_notes", return_value=_now_notes()):
            for q in ("what did i ask you to remember today", "what did you note today",
                      "what have i told you to remember today", "what did you save for me today"):
                self.assertEqual(quick.answer(q), "1 note from today: your car is parked on level 3.", q)

    def test_no_day_is_all_of_them(self):
        with mock.patch.object(quick, "_notes", return_value=_now_notes()):
            for q in ("what have you remembered for me", "what did you save for me"):
                self.assertIn("your car is parked on level 3", quick.answer(q) or "", q)

    def test_a_named_thing_is_still_a_recall(self):
        self.assertNotIn((quick.match("what do you remember about the plumber") or ("",))[0],
                         ("notes_list", "notes_day"))


if __name__ == "__main__":
    unittest.main()
