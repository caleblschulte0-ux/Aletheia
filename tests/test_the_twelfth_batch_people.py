"""Twelfth sandbox batch, 2026-10-05: people.

    > remember person Dana ...     "remembered Dana Example as dana@example.com
                                   — private contacts only, never the public
                                   repo" - a developer's aside, lowercase
    > add a contact for my dentist, 000 555 0100   [4.0s] a plan and an
                                   approval to save a phone number
    > forget dana                  "I have nothing remembered about dana."
                                   one turn after the contact was saved
    > call the dentist             "I can text or email dentist" - the article gone
    > what drafts are you holding  [5.5s] a model, beside "what have you
                                   drafted" at 0.0 s
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import contacts, intercom, quick, voice


class AContactByNumber(unittest.TestCase):
    def test_the_sentences(self):
        for said, name in (("add a contact for my dentist, 000 555 0100", "dentist"),
                           ("the plumber's number is 000 555 0199", "plumber"),
                           ("save Sam's number 000 555 0123", "Sam")):
            cmd = voice.interpret(said)["command"]
            self.assertEqual(cmd["kind"], "contact_add", said)
            self.assertEqual(cmd["name"], name, said)
            self.assertIn("555", cmd["phone"])


class SaveAndForgetARecord(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(contacts, "CONTACTS_DIR", Path(self.tmp.name), create=True)
        p.start(); self.addCleanup(p.stop)
        p2 = mock.patch.object(contacts, "_path", lambda cid: Path(self.tmp.name) / f"{cid}.json")
        p2.start(); self.addCleanup(p2.stop)
        p3 = mock.patch.object(contacts, "all_contacts",
                               lambda: [contacts.load(x.stem) for x in Path(self.tmp.name).glob("*.json")])
        p3.start(); self.addCleanup(p3.stop)

    def test_the_round_trip(self):
        with mock.patch("aletheia.journal.append"):
            said = intercom.execute_command(
                {"kind": "contact_add", "name": "Dana Example", "email": "dana@example.com"}, {}, quote="t")
            self.assertEqual(said, "Saved Dana Example: dana@example.com.")
            gone = intercom.execute_command({"kind": "forget", "about": "dana"}, {}, quote="t")
        self.assertEqual(gone, "Forgotten: Dana Example (dana@example.com).")
        self.assertEqual(contacts.all_contacts(), [])


class ThePhoneSentenceKeepsHisArticle(unittest.TestCase):
    def test_the_dentist(self):
        with mock.patch("aletheia.voice._is_a_person_to_ring", return_value=True):
            out = voice.interpret("call the dentist")
        self.assertIn("text or email the dentist", out["say"])


class DraftsHoweverHeAsks(unittest.TestCase):
    def test_phrasings(self):
        with mock.patch("aletheia.quick._drafts", return_value="No drafts waiting.", create=True):
            for q in ("what drafts are you holding", "are you holding any drafts", "what are you holding"):
                self.assertIsNotNone(quick.answer(q), q)


if __name__ == "__main__":
    unittest.main()
