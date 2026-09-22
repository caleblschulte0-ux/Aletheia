""""Call the dentist" waited two minutes on her own model with every
frontier off (2026-09-22) for a verb nothing here owns. She has no way to
place a call, and three ways to reach somebody, so she says which - and
"call it a day", "call the shots" and "call the whole thing off" are
idioms, not people."""
from __future__ import annotations

import unittest

from aletheia import voice


class APhoneCallCase(unittest.TestCase):
    def test_a_person_gets_the_three_doors_she_does_have(self):
        for said, who in (("thea call the dentist", "dentist"),
                          ("thea call mom", "mom"),
                          ("thea ring the vet", "vet"),
                          ("thea call my sister", "sister"),
                          ("thea call the plumber back", "plumber")):
            with self.subTest(said=said):
                out = voice.interpret(said)
                self.assertIsNone(out["command"])
                self.assertIn("can't place phone calls", out["say"])
                self.assertIn(who, out["say"])
                self.assertIn("text or email", out["say"])

    def test_his_capitals_come_back(self):
        self.assertIn("Dana Ruiz", voice.interpret("thea phone Dana Ruiz")["say"])

    def test_an_idiom_is_not_a_person(self):
        for said in ("thea call it a day", "thea call the shots", "thea call a meeting",
                     "thea call the whole thing off", "thea call me at 6",
                     "thea recall my landlord"):
            with self.subTest(said=said):
                out = voice.interpret(said)
                self.assertNotIn("can't place phone calls", str(out.get("say") or ""))

    def test_the_helper_is_the_rule(self):
        for yes in ("dentist", "mom", "dana ruiz", "the vet"):
            self.assertTrue(voice._is_a_person_to_ring(yes), yes)
        for no in ("it a day", "the shots", "a meeting", "whole thing off", "me",
                   "the list", "the meeting", "", "a very long name with too many words"):
            self.assertFalse(voice._is_a_person_to_ring(no), no)


if __name__ == "__main__":
    unittest.main()
