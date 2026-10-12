"""Two follow-ups that answered as if nothing had just happened (2026-10-12).

"Remember Sam's birthday is June 3" - "forget that" said "Okay - nothing was
waiting" and KEPT the birthday: a note reads as a question at its tier, so
the last thing he could take back was never found. And "put lunch with Sam
on my calendar" - "who is it with" waited for a model, with the answer in
the hold's own title.
"""
import unittest
from unittest import mock

from aletheia import voice


def turns(*pairs):
    return [{"he_asked": said, "she_answered": answered} for said, answered in pairs]


class ForgetThat(unittest.TestCase):
    def _said(self, recent, sentence="forget that"):
        with mock.patch("aletheia.converse.recent", return_value=recent):
            return voice.interpret(f"thea {sentence}")

    def test_a_note_just_made_is_taken_back(self):
        got = self._said(turns(("remember sam's birthday is june 3", "Noted.")))
        self.assertEqual(got["command"], {"kind": "undo"})

    def test_forget_it_too(self):
        got = self._said(turns(("remember my locker is 42", "Noted.")), "forget it")
        self.assertEqual(got["command"], {"kind": "undo"})

    def test_a_question_before_it_is_not_what_that_means(self):
        got = self._said(turns(("what time is it", "9 am.")))
        self.assertNotEqual((got.get("command") or {}).get("kind"), "undo")

    def test_a_note_counts_as_something_he_can_take_back(self):
        with mock.patch("aletheia.converse.recent", return_value=turns(("remember my locker is 42", "Noted."))):
            self.assertTrue(voice._last_ask_is_undoable())


class WhoIsItWith(unittest.TestCase):
    def _said(self, held, sentence="who is it with"):
        with mock.patch("aletheia.voice._recent_ask_of", return_value=held), \
                mock.patch("aletheia.voice._hold_as_it_is_now", side_effect=lambda h: h):
            return voice.interpret(f"thea {sentence}")

    def test_the_hold_names_who(self):
        got = self._said({"title": "lunch with Sam", "start": "2026-10-15T13:00:00-05:00"})
        self.assertIsNone(got["command"])
        self.assertTrue(got["say"].startswith("It's with Sam: lunch with Sam, "), got["say"])

    def test_a_hold_that_names_nobody_says_so(self):
        got = self._said({"title": "the tour", "start": "2026-10-16T10:00:00-05:00"}, "who's it with?")
        self.assertTrue(got["say"].startswith("It doesn't say"), got["say"])

    def test_with_no_hold_just_made_it_is_not_answered_here(self):
        got = self._said({})
        self.assertNotIn("It's with", str(got.get("say") or ""))


if __name__ == "__main__":
    unittest.main()
