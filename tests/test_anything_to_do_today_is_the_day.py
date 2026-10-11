""""Anything I need to do today" is the day, not the planner (2026-10-11)."""

import unittest

from aletheia import quick


class AnythingToDoTodayIsTheDay(unittest.TestCase):
    def test_today_is_the_day(self):
        for said in ("anything I need to do today", "is there anything I have to do today?",
                     "do I have anything I need to get done today"):
            found = quick.match(said)
            self.assertIsNotNone(found, said)
            self.assertEqual(found[0], "focus", said)

    def test_without_today_it_is_what_needs_him(self):
        for said in ("anything I need to deal with", "is there anything I need to do"):
            found = quick.match(said)
            self.assertIsNotNone(found, said)
            self.assertEqual(found[0], "waiting", said)


if __name__ == "__main__":
    unittest.main()
