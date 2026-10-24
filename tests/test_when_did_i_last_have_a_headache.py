""""I had a migraine yesterday" went to the planner, and "when did I last
have a headache" and "how many migraines have I had" went to a model with
"I have a headache" sitting in his journal (2026-10-24).
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, quick, voice


def _notes(*rows):
    return mock.patch.object(quick, "_notes", return_value=[{"text": t, "ts": ts.isoformat()} for t, ts in rows])


class WhenDidILastHaveAHeadache(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime.now(localtime.operator_tz())

    def test_past_tense_is_journaled(self):
        for said in ("i had a migraine yesterday", "I had a bad headache last night", "i got a nosebleed on monday"):
            with self.subTest(said=said):
                self.assertEqual((voice.interpret(said).get("command") or {}).get("kind"), "note")
        self.assertNotEqual((voice.interpret("i had a cold drink").get("command") or {}).get("kind"), "note")

    def test_when_last(self):
        with _notes(("Journal: i have a headache", self.now - dt.timedelta(days=3)),
                    ("Journal: i had a migraine yesterday", self.now)):
            self.assertIn("days ago", quick.answer("when did i last have a headache"))
            self.assertEqual(quick.answer("when was my last migraine"), "The last migraine you told me about was yesterday.")
            self.assertEqual(quick.answer("when did i last have a cold"), "You haven't told me about a cold.")

    def test_how_many(self):
        with _notes(("Journal: i have a migraine", self.now), ("Journal: i had a migraine yesterday", self.now)):
            self.assertEqual(quick.answer("how many migraines have i had"), "2 migraines in the last 30 days, from what you've told me.")
            self.assertEqual(quick.answer("how many colds have i had this year"), "None you've told me about this year.")

    def test_not_a_feeling_goes_on(self):
        with _notes():
            self.assertIsNone(quick._symptom_when("when was my last dentist visit"))


if __name__ == "__main__":
    unittest.main()
