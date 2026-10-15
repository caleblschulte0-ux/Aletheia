""""I like sushi", then "what food do I like" and "do I like sushi" went to
a model; "if I go to bed now how much sleep will I get" went to the planner;
and "call dr patel" offered to "text or email Dr patel" beside "Dr Patel's
number" (2026-10-15, every model off)."""
import unittest
from unittest import mock

from aletheia import quick, voice

NOTES = ["I like sushi", "I love tacos", "I don't like mushrooms"]


def ask(question):
    with mock.patch.object(quick, "_notes", return_value=[{"text": n} for n in NOTES]):
        return quick.answer(question)


class WhatFoodDoILike(unittest.TestCase):
    def test_the_food_he_likes(self):
        for q in ("what food do I like", "what foods do i like", "what do I like to eat",
                  "what kind of food do I like"):
            got = ask(q)
            self.assertIn("you like sushi", got, q)
            self.assertIn("you love tacos", got, q)

    def test_do_i_like_a_thing_he_likes(self):
        self.assertEqual(ask("do I like sushi"), "Yes - you told me: you like sushi.")

    def test_do_i_like_a_thing_he_does_not(self):
        self.assertEqual(ask("do I like mushrooms"), "No - you told me: you don't like mushrooms.")

    def test_nothing_said_is_still_a_models_question(self):
        self.assertIsNone(ask("do I like pizza"))


class SleepIfIGoToBedNow(unittest.TestCase):
    def test_the_condition_first_is_the_same_sum(self):
        for q in ("if I go to bed now how much sleep will I get",
                  "if i went to bed right now, how many hours would i get"):
            t = quick._tidy(q)
            self.assertTrue(any(name == "alarm_left" and p.search(t) for name, p in quick.PATTERNS), q)


class TheContactKnowsHowTheNameIsWritten(unittest.TestCase):
    def test_a_lowercase_name_is_offered_as_the_contact_writes_it(self):
        from aletheia import contacts
        one = {"display_name": "Dr Patel", "phones": ["555-123-4567"]}
        with mock.patch.object(contacts, "resolve", return_value=one):
            said = voice._interpret("call dr patel")["say"]
        self.assertIn("text or email Dr Patel,", said)
        self.assertNotIn("Dr patel", said)


if __name__ == "__main__":
    unittest.main()
