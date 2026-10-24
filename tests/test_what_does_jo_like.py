""""What does Jo like" with nothing kept, "Jo is vegan", "is Jo vegan" and
"who is Jo" all went to a model, and with nobody to think each one was
"I can't think just now" (2026-10-24).
"""
import unittest
from unittest import mock

from aletheia import quick, voice


def _notes(*texts):
    return mock.patch.object(quick, "_notes", return_value=[{"text": t} for t in texts])


class WhatDoesJoLike(unittest.TestCase):
    def test_nothing_about_them_is_said_plainly(self):
        with _notes("Ann likes tea"):
            self.assertEqual(quick.answer("what does Jo like"),
                             "You haven't told me what Jo likes. Say \"Jo likes ...\" and I'll keep it.")
            self.assertIn("my sister likes", quick.answer("what does my sister like"))

    def test_a_note_naming_them_is_left_to_a_model(self):
        with _notes("Jo is vegan"):
            self.assertIsNone(quick.answer("what does Jo like"))

    def test_what_they_like_still_reads_back(self):
        with _notes("Jo likes tea"):
            self.assertEqual(quick.answer("what does Jo like"), "You told me: Jo likes tea.")

    def test_a_two_letter_name_is_a_name(self):
        with _notes("Jo is vegan"), mock.patch("aletheia.contacts.all_contacts", return_value=[]):
            self.assertEqual(quick.answer("who is Jo"), "You told me: Jo is vegan.")


class JoIsVegan(unittest.TestCase):
    def _cmd(self, sentence):
        return voice.interpret(sentence).get("command") or {}

    def test_a_diet_is_a_note(self):
        for sentence in ("Jo is vegan", "my wife is vegetarian", "Sam is lactose intolerant"):
            with self.subTest(sentence=sentence):
                self.assertEqual(self._cmd(sentence), {"kind": "note", "text": sentence})

    def test_but_not_food(self):
        for sentence in ("the soup is vegan", "this is vegan", "it is gluten free", "pizza is vegan"):
            with self.subTest(sentence=sentence):
                self.assertNotEqual(self._cmd(sentence).get("kind"), "note")

    def test_is_jo_vegan(self):
        with _notes("Jo is vegan", "Dana is allergic to shellfish"):
            self.assertEqual(quick.answer("is Jo vegan"), "Yes - you told me Jo is vegan.")
            self.assertEqual(quick.answer("is Jo vegetarian"), "You told me Jo is vegan.")
            self.assertEqual(quick.answer("is Dana allergic to peanuts"),
                             "You told me Dana is allergic to shellfish; nothing about peanuts.")
            self.assertTrue(quick.answer("is Dana allergic to anything").startswith("Yes"))
            self.assertIsNone(quick.answer("is Sam vegan"))


if __name__ == "__main__":
    unittest.main()
