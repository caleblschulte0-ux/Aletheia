"""Two questions that went to her own model for minutes with every frontier
off (2026-09-22), and are a file read and a machine reading away."""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import quick

GB = 1024 ** 3


class WhatSheDidOnHerOwnCase(unittest.TestCase):
    def test_the_honesty_question_reads_the_ledger_not_a_model(self):
        for sentence in ("what did you do without asking me", "what have you done on your own today",
                         "did you do anything without telling me", "what did you do unattended"):
            with self.subTest(sentence=sentence):
                with mock.patch("aletheia.autonomy.spoken", return_value="Nothing in the last day.") as said:
                    self.assertEqual(quick.answer(sentence), "Nothing in the last day.")
                self.assertEqual(said.call_args.kwargs["hours"], 24.0)

    def test_it_does_not_swallow_other_did_you_questions(self):
        self.assertIsNone(quick.match("what did you do to my resume"))


class TheMachinesMemoryCase(unittest.TestCase):
    def test_free_memory_is_a_reading_not_a_refusal(self):
        with mock.patch("aletheia.machine.memory",
                        return_value={"total": 16 * GB, "available": 7 * GB, "load_percent": 55}):
            said = quick.answer("how much memory is free")
        self.assertEqual(said, "7.0 GB of 16 GB is free; 9.0 GB in use.")
        for sentence in ("how much ram do I have free", "is this computer low on memory",
                         "how much memory is free on this laptop", "how's my computer's memory"):
            with self.subTest(sentence=sentence):
                self.assertEqual(quick.match(sentence)[0], "machine")

    def test_tight_memory_says_what_it_means_for_her(self):
        with mock.patch("aletheia.machine.memory",
                        return_value={"total": 16 * GB, "available": 2 * GB, "load_percent": 90}):
            said = quick.answer("how much memory is free")
        self.assertIn("tight", said)
        self.assertIn("my own model", said)

    def test_an_unreadable_machine_is_said_plainly(self):
        with mock.patch("aletheia.machine.memory", return_value={}):
            self.assertIn("can't read", quick.answer("how much memory is free"))


if __name__ == "__main__":
    unittest.main()
