""""My goal is to read 20 books this year", "I finished a book", then "how
many books have I read this year" and "how close am I to my reading goal"
(2026-10-14): an untitled book counted as nothing, and the finish said
"that wasn't on your task list"."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import lists, quick


class ReadingGoal(unittest.TestCase):
    def test_untitled_books_count_against_the_goal(self):
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        rows = [{"text": "i finished another book", "ts": now}, {"text": "i finished a book", "ts": now},
                {"text": "my goal is to read 20 books this year", "ts": now}]
        with mock.patch.object(quick, "_notes", return_value=rows), mock.patch.object(lists, "all_lists", return_value=[]):
            want = "2 books this year, from what you've told me - 18 to go on your goal of 20."
            self.assertEqual(quick.answer("how many books have i read this year"), want)
            self.assertEqual(quick.answer("how close am i to my reading goal"), want)
            self.assertEqual(quick.answer("what books have i read"), "You've told me you finished 2 books, but not which.")


if __name__ == "__main__":
    unittest.main()
