"""A birthday kept under a name is the relation's birthday too (2026-10-12).

"My sister's name is Jenna", "Jenna's birthday is March 3", "when is my
sister's birthday" - answered - then "remind me a week before": "I don't
know when your sister's birthday is."
"""
import unittest
from unittest import mock

from aletheia import quick, voice


def _days_before_march_3(at):
    """Counted, so a leap year moves the date and not the answer."""
    import datetime as dt
    when = dt.datetime.fromisoformat(at)
    assert when.hour == 9, at
    return (dt.date(when.year, 3, 3) - when.date()).days


class ThroughTheName(unittest.TestCase):
    def setUp(self):
        notes = [{"text": "my sister's name is Jenna"}, {"text": "Jenna's birthday is March 3"}]
        self.patches = [mock.patch.object(quick, "_notes", return_value=notes),
                        mock.patch.object(quick, "_birthday_notes", return_value=[("Jenna", 3, 3)])]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_the_relation_finds_the_named_birthday(self):
        got = voice.interpret("thea remind me the day before my sister's birthday")["command"]
        self.assertEqual(got["kind"], "remind_at")
        self.assertEqual(got["text"], "Jenna's birthday is tomorrow")
        self.assertEqual(_days_before_march_3(got["at"]), 1)

    def test_the_name_finds_it_too(self):
        got = voice.interpret("thea remind me a week before jenna's birthday")["command"]
        self.assertEqual(_days_before_march_3(got["at"]), 7)

    def test_somebody_else_is_still_not_known(self):
        got = voice.interpret("thea remind me the day before my brother's birthday")
        self.assertIsNone(got["command"])
        self.assertIn("I don't know when your brother's birthday is", got["say"])


if __name__ == "__main__":
    unittest.main()
