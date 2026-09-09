"""Three placeholders, read out loud, for something she can already do.

    > email dana the quarterly numbers
      no address known for 'Dana' - add them privately first:
      python -m aletheia.contacts new <id> 'Dana' --email <address>

CLAUDE.md names this shape: "a command with a placeholder in it answers
'what do I type' and not 'which URL'". It was worse than that here,
because `contact_add` already existed as a routine kind - she could save
the contact herself and was reading him a shell command instead.

Texting could not be fixed the same way, because `contact_add` REQUIRED
an email and had no phone field at all, while `contacts.create` had
supported phones from the start. So the capability he has asked for most
- sending a text - had no way to learn a number by voice.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from aletheia import intercom, mail, messages


class ItAsksRatherThanPrescribesCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ,
                            {"ALETHEIA_PRIVATE_STATE": self.tmp.name})
        p.start(); self.addCleanup(p.stop)

    def _refusal(self, call):
        with self.assertRaises(ValueError) as caught:
            call()
        return str(caught.exception)

    def test_a_missing_email_asks_for_the_email(self):
        said = self._refusal(lambda: mail.draft("Dana", "subject", "body"))
        self.assertIn("Dana", said)
        self.assertIn("email", said.lower())

    def test_a_missing_number_asks_for_the_number(self):
        said = self._refusal(lambda: messages.draft("Brant", "running late"))
        self.assertIn("Brant", said)
        self.assertIn("number", said.lower())

    def test_neither_refusal_is_a_command(self):
        """It is read out in a room. A shell command is not a sentence."""
        for call in (lambda: mail.draft("Dana", "s", "b"),
                     lambda: messages.draft("Brant", "late")):
            said = self._refusal(call)
            with self.subTest(said=said):
                self.assertNotIn("python -m", said)
                self.assertNotIn("--", said)
                self.assertNotIn("<", said)
                self.assertTrue(said.strip().endswith("."), said)


class SavingAContactCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ,
                            {"ALETHEIA_PRIVATE_STATE": self.tmp.name})
        p.start(); self.addCleanup(p.stop)

    def _add(self, **cmd):
        return intercom.execute_command({"kind": "contact_add", **cmd}, {},
                                        quote="he said so")

    def test_a_phone_number_alone_is_enough(self):
        """The gap that blocked texting: email used to be required."""
        said = self._add(name="Brant", phone="555-123-4567")
        self.assertIn("Brant", said)
        self.assertIn("5551234567", said)

    def test_an_email_alone_is_still_enough(self):
        said = self._add(name="Dana", email="dana@example.com")
        self.assertIn("dana@example.com", said)

    def test_both_are_kept(self):
        said = self._add(name="Sam", email="sam@example.com", phone="5551230000")
        self.assertIn("sam@example.com", said)
        self.assertIn("5551230000", said)

    def test_a_contact_she_cannot_reach_is_refused(self):
        said = self._add(name="Nobody")
        self.assertIn("email address or a phone number", said)

    def test_a_number_that_is_not_a_number_is_refused(self):
        """Ten digits or more; "12" is a house number or a mishearing."""
        self.assertIn("didn't sound like a phone number", self._add(
            name="Bad", phone="12"))

    def test_the_grammar_requires_only_a_name(self):
        problems = intercom.validate_kind_args(
            {"kind": "contact_add", "name": "Dana", "phone": "5551234567"}, {})
        self.assertEqual(problems, [])

    def test_saving_one_makes_her_able_to_reach_them(self):
        """The point of all of it: the refusal stops happening."""
        self._add(name="Brant", phone="555-123-4567")
        number, name = messages.resolve_number("Brant")
        self.assertTrue(number, f"still cannot reach {name}")


if __name__ == "__main__":
    unittest.main()
