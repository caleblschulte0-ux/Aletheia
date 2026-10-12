""""Never mind" straight after something she did takes it back (2026-10-12).

"Add paper towels" - "never mind" answered "Okay - nothing was waiting" and
the paper towels stayed on the list.
"""
import unittest
from unittest import mock

from aletheia import policy, voice


def said(sentence, previous):
    with mock.patch.object(policy, "all_approvals", return_value=[]), \
            mock.patch("aletheia.voice._previous_ask", return_value=previous), \
            mock.patch("aletheia.voice._previous_turn", return_value=(previous, "")), \
            mock.patch("aletheia.converse.recent", return_value=[{"he_asked": previous, "she_answered": ""}]):
        return voice.interpret(f"thea {sentence}")


class NeverMind(unittest.TestCase):
    def test_after_an_add_it_is_undo(self):
        self.assertEqual(said("never mind", "add paper towels to my shopping list")["command"], {"kind": "undo"})

    def test_dont_do_that_after_a_reminder_is_undo(self):
        self.assertEqual(said("don't do that", "remind me to call bob at 5pm")["command"], {"kind": "undo"})

    def test_after_a_question_nothing_is_taken_back(self):
        got = said("never mind", "what time is it")
        self.assertIsNone(got["command"])
        self.assertEqual(got["say"], "Okay - nothing was waiting.")

    def test_a_pending_approval_still_comes_first(self):
        pending = [{"id": "ap-1", "state": "PENDING", "requested_action": "x", "created_at": "2026-10-12T00:00:00Z"}]
        with mock.patch.object(policy, "all_approvals", return_value=pending), \
                mock.patch("aletheia.voice._previous_ask", return_value="add paper towels"):
            got = voice.interpret("thea never mind")
        self.assertNotEqual((got.get("command") or {}).get("kind"), "undo")


if __name__ == "__main__":
    unittest.main()
