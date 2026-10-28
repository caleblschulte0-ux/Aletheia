"""A flight he told her about, read back.

2026-10-28, talking to her with the models off:

    > my flight to denver is on november 3 on united
    > when is my flight
      Nothing on your calendar or in your reminders mentions your flight.
    > what airline am I flying            (to a model)
"""
import unittest
from unittest import mock

from aletheia import quick

NOTE = [{"text": "my flight to denver is on november 3 on united", "ts": "2026-10-28T14:00:00+00:00"}]


class TheFlight(unittest.TestCase):
    def ask(self, q, notes=NOTE):
        with mock.patch.object(quick, "_notes", return_value=notes), \
                mock.patch.object(quick, "_coming", return_value=[]):
            return quick.answer(q)

    def test_when_reads_a_month_and_day(self):
        self.assertEqual(self.ask("when is my flight"),
                         "You told me: your flight to denver is on November 3 on united.")

    def test_the_airline(self):
        for q in ("what airline am i flying", "which airline is my flight", "what airline am i flying to denver"):
            self.assertTrue(self.ask(q).startswith("United - you told me: your flight to denver"), q)

    def test_a_flight_somewhere_else_is_not_this_one(self):
        self.assertIsNone(self.ask("what airline am i flying to tokyo"))
        self.assertIsNone(self.ask("what airline am i flying", [{"text": "united won the game", "ts": NOTE[0]["ts"]}]))


if __name__ == "__main__":
    unittest.main()
