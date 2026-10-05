"""Forty-fourth sandbox batch, 2026-10-05: codes said plainly, notes asked
about, and a sum said the long way.

    > my wifi password is hunter2        [4.5s] a plan, an approval
    > what did I note about the car      [3.5s] a model
    > what have I told you about the car [5.0s] a model
    > split 120 three ways               [7.0s] a model
"""
import unittest
from unittest import mock

from aletheia import quick, voice


class CodesSaidPlainly(unittest.TestCase):
    def test_a_code_of_his_is_a_note_and_a_password_is_refused_out_loud(self):
        # the journal scrubs a password on the way in, so "Noted." would have
        # kept "my wifi password [redacted]" and read that back to him
        d = voice.interpret("thea my wifi password is hunter2")
        self.assertIsNone(d["command"])
        self.assertIn("I don't keep passwords", d["say"])
        self.assertNotIn("hunter2", d["say"])
        self.assertEqual(voice.interpret("thea the gate code is 4471")["command"],
                         {"kind": "note", "text": "the gate code is 4471"})
        self.assertEqual(voice.interpret("thea my locker combination is 12-34-56")["command"]["kind"], "note")
        # a complaint is not a code
        self.assertNotEqual(voice.interpret("thea my wifi password is wrong")["command"].get("kind"), "note")

    def test_and_it_is_read_back(self):
        rows = [{"text": "the gate code is 4471"}, {"text": "the car needs an oil change"}]
        with mock.patch.object(quick, "_notes", return_value=rows):
            self.assertIn("you told me: the gate code is 4471", quick.answer("what's the gate code"))
            for said in ("what did I note about the car", "what have I told you about the car",
                         "any notes about the car", "what did I write down about the car"):
                self.assertIn("the car needs an oil change", quick.answer(said) or "", said)


class SumsSaidTheLongWay(unittest.TestCase):
    def test_split_and_bare_operations(self):
        self.assertEqual(quick.answer("split 120 three ways"), "40 each.")
        self.assertEqual(quick.answer("split 100 dollars between 3"), "$33.33 each.")
        self.assertEqual(quick.answer("divide 90 by 4"), "22.5 each.")
        self.assertEqual(quick.answer("7 times 8"), "56.")
        self.assertEqual(quick.answer("120 divided by 3"), "40.")


if __name__ == "__main__":
    unittest.main()
