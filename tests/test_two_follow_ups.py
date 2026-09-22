"""Two follow-ups that waited two minutes on her own model with every
frontier off (2026-09-22): "say that again" (her own last sentence, held by
the thread) and "you're wrong" (nothing to guess at)."""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import quick, voice


class SayThatAgainCase(unittest.TestCase):
    def test_her_last_sentence_is_said_again(self):
        with mock.patch("aletheia.converse.recent", return_value=[{"he_asked": "x", "she_said": "Added a task."}]):
            for sentence in ("say that again", "what did you just say", "repeat that", "pardon"):
                with self.subTest(sentence=sentence):
                    self.assertEqual(quick.answer(sentence), "I said: Added a task.")
        with mock.patch("aletheia.converse.recent", return_value=[]):
            self.assertIn("haven't said anything yet", quick.answer("say that again"))


class YoureWrongCase(unittest.TestCase):
    def test_a_bare_correction_asks_for_the_correction(self):
        for sentence in ("thea you're wrong", "thea that's not right", "thea wrong"):
            with self.subTest(sentence=sentence):
                out = voice.interpret(sentence)
                self.assertIsNone(out["command"])
                self.assertIn("Tell me what's wrong", out["say"])

    def test_a_correction_with_content_still_goes_on(self):
        out = voice.interpret("thea you're wrong, my landlord is Dana")
        self.assertNotIn("Tell me what's wrong", str(out.get("say") or ""))


if __name__ == "__main__":
    unittest.main()
