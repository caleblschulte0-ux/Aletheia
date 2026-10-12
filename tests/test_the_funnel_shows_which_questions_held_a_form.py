"""The funnel says which questions held a form, in words that name nobody."""
import datetime as dt
import unittest

from aletheia import hunt_funnel


NOW = dt.datetime(2026, 10, 12, 1, 0, tzinfo=dt.timezone.utc)


class QuestionShapes(unittest.TestCase):
    def test_a_held_question_is_published_in_plain_words_only(self):
        rows = [{"state": "NEEDS_YOU", "url": "https://jobs.lever.co/acme/1",
                 "staged_at": "2026-10-11T20:00:00Z",
                 "questions": [{"label": "Why do you want to work at Acmecorp?", "type": "textarea"},
                               {"label": "Are you willing to relocate to Springfield?"}]}]
        shapes = hunt_funnel.question_shapes(rows, now=NOW)
        self.assertEqual(shapes, {
            "lever: textarea: why do you want to work at _": 1,
            "lever: field: are you willing to relocate to _": 1})
        self.assertNotIn("acmecorp", str(shapes).lower())
        self.assertNotIn("springfield", str(shapes).lower())

    def test_old_and_unheld_records_are_left_out(self):
        rows = [{"state": "NEEDS_YOU", "url": "https://x.example/1", "staged_at": "2026-09-01T00:00:00Z",
                 "questions": [{"label": "Pay?"}]},
                {"state": "SUBMITTED", "url": "https://x.example/2", "staged_at": "2026-10-11T00:00:00Z",
                 "questions": [{"label": "Pay?"}]},
                "junk"]
        self.assertEqual(hunt_funnel.question_shapes(rows, now=NOW), {})


if __name__ == "__main__":
    unittest.main()
