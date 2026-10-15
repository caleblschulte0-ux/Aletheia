"""2026-10-15, every model off: "remember the password for netflix is
hunter22" and "note that the wifi password at mom's is bluebird22" both came
back "Noted." and went into the journal and the conversation word for word -
while her refusal elsewhere says anything that looks like a password is
blanked out of everything she writes down. The scrubber only knew "password
is X"; what it opens may sit in between. And "what's left on my to do list"
reached a model."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import converse, quick, sensitivity, voice


class WhatItOpensMaySitBetween(unittest.TestCase):
    def test_the_value_is_blanked(self):
        for said, kept in (("the wifi password at mom's is bluebird22", "the wifi password at mom's [redacted]"),
                           ("the password for netflix is hunter22", "the password for netflix [redacted]"),
                           ("the password to the shed is 1234", "the password to the shed [redacted]")):
            self.assertEqual(sensitivity.clean(said), kept)

    def test_where_it_is_kept_is_not_a_password(self):
        for said in ("the wifi password is on the fridge",
                     "the password for the wifi at the cabin is on the fridge",
                     "reset the password for my bank", "the password field was empty"):
            self.assertEqual(sensitivity.clean(said), said)

    def test_noting_one_is_refused(self):
        for said in ("remember the password for netflix is hunter22",
                     "note that the wifi password at mom's is bluebird22"):
            got = voice.interpret(said)
            self.assertIsNone(got["command"], said)
            self.assertIn("I don't keep passwords", got["say"])

    def test_asking_for_one_is_answered_the_same_way(self):
        self.assertIn("I don't keep passwords", quick.answer("what's the wifi password at mom's") or "")


class TheConversationDoesNotKeepItEither(unittest.TestCase):
    def test_the_turn_is_kept_blanked(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(converse, "THREAD_PATH", Path(d) / "recent.json"), \
                mock.patch.object(converse, "_journal_his_ask"):
            converse.remember_exchange("remember the password for netflix is hunter22", "I don't keep passwords.")
            kept = (Path(d) / "recent.json").read_text()
        self.assertNotIn("hunter22", kept)
        self.assertIn("[redacted]", kept)


class WhatsLeftOnTheToDoList(unittest.TestCase):
    def test_the_ways_he_asks(self):
        for said in ("what's left on my to do list", "anything left on my to do list",
                     "what else is on my to do list", "what's still on my to do list",
                     "is there anything else on my to do list"):
            self.assertEqual(voice._interpret(said)["command"], {"kind": "tasks"}, said)


if __name__ == "__main__":
    unittest.main()
