""""Text mom happy birthday" - the person and the message with no "that".

Found 2026-10-07: "I don't have a phone number for mom happy." The send
still goes through the same approval as every message.
"""
import unittest
from unittest import mock

from aletheia import contacts, quick, voice


class TheNameEndsWhereTheMessageStarts(unittest.TestCase):
    def test_a_relation(self):
        with mock.patch.object(contacts, "all_contacts", return_value=[]):
            self.assertEqual(voice._interpret("text mom happy birthday")["command"],
                             {"kind": "message_send", "to": "mom", "body": "happy birthday"})

    def test_a_contact_with_two_words(self):
        dana = {"id": "dana-cole", "display_name": "Dana Cole", "aliases": [], "emails": [],
                "phones": ["+16055550123"]}
        with mock.patch.object(contacts, "all_contacts", return_value=[dana]), \
                mock.patch.object(contacts, "validate"):
            self.assertEqual(voice._interpret("text dana cole running late")["command"]["to"], "dana cole")

    def test_a_stranger_is_not_guessed(self):
        with mock.patch.object(contacts, "all_contacts", return_value=[]):
            self.assertEqual(voice._interpret("text bob happy birthday")["command"]["kind"], "intent")

    def test_what_version(self):
        self.assertEqual(quick.match("what version are you")[0], "version")


if __name__ == "__main__":
    unittest.main()
