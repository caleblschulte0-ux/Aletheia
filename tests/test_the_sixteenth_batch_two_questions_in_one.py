"""Sixteenth sandbox batch, 2026-10-05.

    > what's on my calendar tomorrow and am I free at 2   [6.0s] a model with
                                   neither answer in front of it
    > any news                     "No replies from employers today." - about
                                   employers only
    > what should I know           [5.5s] a model
    > what did you do while I was out   [4.5s] a model
"""
import unittest
from unittest import mock

from aletheia import quick


class TwoQuestionsInOneSentence(unittest.TestCase):
    def test_both_halves_are_fast_so_both_are_said(self):
        def fake_match(text):
            return {"what's on my calendar tomorrow": ("agenda", "tomorrow"),
                    "am i free at 2": ("free", "at 2")}.get(text.casefold())
        with mock.patch("aletheia.quick.match", side_effect=fake_match), \
             mock.patch.dict(quick.ANSWERS, {"agenda": lambda r: "Tomorrow: dentist at 10 am.",
                                             "free": lambda r: "Free at 2 pm."}):
            self.assertEqual(quick.answer("what's on my calendar tomorrow and am I free at 2"),
                             "Tomorrow: dentist at 10 am. Free at 2 pm.")

    def test_half_a_question_is_never_answered(self):
        def fake_match(text):
            return {"what's on my calendar tomorrow": ("agenda", "tomorrow")}.get(text.casefold())
        with mock.patch("aletheia.quick.match", side_effect=fake_match), \
             mock.patch.dict(quick.ANSWERS, {"agenda": lambda r: "Tomorrow: dentist."}), \
             mock.patch("aletheia.quick._follow_up", return_value=None):
            self.assertIsNone(quick.answer("what's on my calendar tomorrow and can you fly a helicopter"))


class TheRundownWords(unittest.TestCase):
    def test_news_and_what_should_i_know_are_the_rundown(self):
        with mock.patch.dict(quick.ANSWERS, {"status": lambda r: "Nothing needs you."}):
            for q in ("any news", "what should I know", "what have I missed"):
                self.assertEqual(quick.answer(q), "Nothing needs you.", q)

    def test_while_i_was_out_is_today(self):
        with mock.patch.dict(quick.ANSWERS, {"today": lambda r: "Today: two things."}):
            self.assertEqual(quick.answer("what did you do while I was out"), "Today: two things.")


if __name__ == "__main__":
    unittest.main()
