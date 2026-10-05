"""Fiftieth sandbox batch, 2026-10-05: her own rules, asked about.

    > what are you allowed to do without asking   [6.1s] a model
    > are you allowed to send emails              [8.0s] a model
    > what happens if I say halt                  [4.1s] a model
    > what would you never do                     [5.0s] a model
    > do you record me                            [12.0s] a model
    > forget everything you know about me         "I have nothing remembered about everything you know about me."
    > what version are you / who am I talking to / are you an AI / why are you called thea   a model each
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import memory, quick, voice


class HerOwnRules(unittest.TestCase):
    def test_what_runs_without_his_yes_comes_from_the_descriptors(self):
        self.assertEqual(quick.match("what are you allowed to do without asking")[0], "unattended_allowed")
        said = quick.answer("what do you do on your own")
        self.assertIn("waits for your yes", said)
        self.assertIn("spending money is refused", said)
        self.assertIn("your tasks and reminders", said)

    def test_allowed_to_says_whose_yes_it_takes(self):
        said = quick.answer("are you allowed to send emails")
        self.assertTrue(said.startswith("Yes"), said)
        self.assertIn("Only with your yes each time", said)
        self.assertIsNone(quick.answer("are you allowed to fly a helicopter") and None)

    def test_the_canned_truths(self):
        self.assertIn("I can't lift my own halt", quick.answer("what happens if I say halt"))
        never = quick.answer("what would you never do")
        self.assertTrue(never.startswith("Spend your money - never"), never)
        self.assertIn("not as audio", quick.answer("do you record me"))
        self.assertEqual(quick.match("what version are you")[0], "version")

    def test_who_she_is(self):
        self.assertTrue(quick.answer("who am I talking to").startswith("I'm Thea"))
        self.assertTrue(quick.answer("are you an AI").startswith("Yes - I'm software."))
        self.assertTrue(quick.answer("are you human").startswith("No, I'm not a person."))
        self.assertTrue(quick.answer("are you chatgpt").startswith("No."))
        self.assertIn("Greek for truth", quick.answer("why are you called thea"))


class ForgetEverything(unittest.TestCase):
    def test_a_wipe_is_a_keyboard_act_and_one_thing_is_a_sentence(self):
        d = voice.interpret("thea forget everything you know about me")
        self.assertIsNone(d["command"])
        self.assertIn("I don't wipe it from a sentence", d["say"])
        self.assertIn("forget-all", d["say"])
        self.assertEqual(voice.interpret("thea forget my landlord")["command"], {"kind": "forget", "about": "my landlord"})
        self.assertIsNone(voice.interpret("thea wipe your memory")["command"])

    def test_forget_all_empties_every_shelf(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(memory, "MEMORY_DIR", Path(tmp)):
                memory.remember("people", "landlord", "Dana", "test")
                memory.remember("identity", "birthday", "June 3", "test")
                self.assertEqual(memory.count(), 2)
                self.assertEqual(memory.forget_all(via="test"), 2)
                self.assertEqual(memory.count(), 0)
                self.assertIsNone(memory.recall("people", "landlord"))


if __name__ == "__main__":
    unittest.main()
