""""Log a 30 minute run", "I did a 45 minute workout", "I walked 2 miles", then
"how much did I exercise this week" said "45 minutes" (2026-10-16, every
model off): only a workout counted as exercise. And "what's the plan for
this weekend" went to a model."""
import unittest
from unittest import mock

from aletheia import quick


class ARunIsExercise(unittest.TestCase):
    def test_every_kind_counts_and_reads_cleanly(self):
        import datetime as dt
        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = [{"ts": ts, "text": t} for t in ("log a 30 minute run", "I did a 45 minute workout", "I walked 2 miles")]
        with mock.patch.object(quick, "_notes", return_value=rows):
            self.assertEqual(quick.answer("how much did I exercise this week"),
                             "1 hour and 15 minutes, plus 2 miles this week.")


class ThePlanForTheWeekend(unittest.TestCase):
    def test_it_is_the_weekend_agenda(self):
        for said in ("what's the plan for this weekend", "what's the plan this weekend",
                     "what are my plans for the weekend"):
            with self.subTest(said=said):
                self.assertEqual(quick._direct(quick._tidy(said)), "what am i doing this weekend")


if __name__ == "__main__":
    unittest.main()
