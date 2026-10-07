"""Coins, dice, spelling and "forget that" need no model."""
import unittest
from unittest import mock

from aletheia import voice


def say(said):
    out = voice._interpret(said) or {}
    return out.get("say"), out.get("command")


class SmallThings(unittest.TestCase):
    def test_a_coin(self):
        self.assertIn(say("flip a coin")[0], ("Heads.", "Tails."))

    def test_dice_and_numbers(self):
        self.assertIn(say("roll a die")[0], [f"{n}." for n in range(1, 7)])
        self.assertIn(say("pick a number between 3 and 4")[0], ("3.", "4."))
        self.assertRegex(say("roll two dice")[0], r"^\d and \d - \d+\.$")

    def test_spelling(self):
        self.assertEqual(say("spell rhythm")[0], "Rhythm: R, H, Y, T, H, M.")

    def test_spell_my_name_is_still_his_name(self):
        self.assertNotIn("M, Y", say("spell my name")[0] or "")


class ForgetThatMeansTheNote(unittest.TestCase):
    def test_forget_that_after_a_note_forgets_it(self):
        with mock.patch.object(voice, "_previous_ask", return_value="remember that my car is in spot 14"), \
                mock.patch("aletheia.policy.all_approvals", return_value=[]):
            self.assertEqual(say("forget that")[1], {"kind": "forget", "about": "my car is in spot 14"})

    def test_forget_that_after_anything_else_is_never_mind(self):
        with mock.patch.object(voice, "_previous_ask", return_value="what time is it"), \
                mock.patch("aletheia.policy.all_approvals", return_value=[]):
            self.assertEqual(say("forget that"), ("Okay - nothing was waiting.", None))


if __name__ == "__main__":
    unittest.main()
