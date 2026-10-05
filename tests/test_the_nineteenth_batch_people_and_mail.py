"""Nineteenth sandbox batch, 2026-10-05.

    > what's my dentist's number        "1 contact: dentist — 0005550100."
    > remember my sister's birthday is march 3rd
                                        "Remembered: sister s birthday is march 3rd."
    > when is my sister's birthday      [3.5s] a model
    > how many days until my sister's birthday
                                        [5.0s] a model, for a date on her shelf
    > who do you have numbers for       [4.1s] a model
    > any email from the bank           [4.0s] a model
    > text the dentist that I'm running late (rehearsal)
                                        "message_send is gated as world-touching"
"""
import os
import unittest
from unittest import mock

from aletheia import act, intercom, mail, memory, quick, speech, voice

SISTER = {"people": {"sister_birthday": {"value": "March 3rd", "about": "your sister's birthday"}}}
DENTIST = [{"id": "dentist", "display_name": "dentist", "phones": ["0005550100"], "emails": []}]


class ANumberIsReadOut(unittest.TestCase):
    def test_digits_are_grouped(self):
        self.assertEqual(speech.phone_words("0005550100"), "000 555 0100")
        self.assertEqual(speech.phone_words("+1 000 555 0100"), "1 000 555 0100")
        self.assertEqual(speech.phone_words("5550100"), "555 0100")
        self.assertEqual(speech.phone_words("ext 12"), "ext 12")

    def test_one_contact_is_a_sentence_and_the_list_is_short(self):
        with mock.patch("aletheia.contacts.all_contacts", return_value=DENTIST):
            self.assertEqual(intercom._contacts_answer("my dentist"), "Your dentist's number is 000 555 0100.")
            self.assertEqual(intercom._contacts_answer(""), "Just one: dentist, 000 555 0100.")
            self.assertEqual(quick.answer("who do you have numbers for"), "Just one: dentist, 000 555 0100.")


class ThePossessiveSurvives(unittest.TestCase):
    def test_the_key_and_the_phrase(self):
        self.assertEqual(memory.key_for("sister's birthday"), "sister_birthday")
        out = voice.interpret("remember my sister's birthday is March 3rd")["command"]
        self.assertEqual(out["key"], "sister_birthday")
        self.assertEqual(out["about"], "your sister's birthday")
        self.assertIn("about", intercom.KIND_ARGS["remember"][1])

    def test_the_phrase_is_kept_and_read_back(self):
        memory.remember("people", "sister_birthday", "March 3rd", source="test", about="your sister's birthday")
        self.addCleanup(lambda: memory.forget("people", "sister_birthday", via="test cleanup"))
        held = memory._load("people")["sister_birthday"]
        self.assertEqual(held["about"], "your sister's birthday")
        with mock.patch("aletheia.memory.everything", return_value=SISTER), \
             mock.patch("aletheia.quick._notes", return_value=[]):
            self.assertEqual(quick.answer("when is my sister's birthday"), "Your sister's birthday is March 3rd.")
            until = quick.answer("how many days until my sister's birthday")
        self.assertRegex(until, r"^(\d+ days|Tomorrow|That's today), \w+ \d+ March - your sister's birthday is March 3rd\.$")


class MailFromOneSender(unittest.TestCase):
    def test_the_sentence_carries_the_sender(self):
        self.assertEqual(voice.interpret("any email from the bank")["command"], {"kind": "email_check", "from": "bank"})
        self.assertEqual(voice.interpret("did the bank email me")["command"], {"kind": "email_check", "from": "bank"})
        self.assertEqual(voice.interpret("did anyone email me today")["command"], {"kind": "email_check"})
        self.assertIn("from", intercom.KIND_ARGS["email_check"][1])

    def test_unread_is_filtered_by_who_sent_it(self):
        class Fake:
            def fetch_unread(self, limit):
                return [{"subject": "Statement", "from": "First Bank <no-reply@bank.example>"},
                        {"subject": "Hi", "from": "Pat Example <pat@example.com>"}]
        with mock.patch("aletheia.journal.append"):
            self.assertEqual(mail.check_unread(transport=Fake(), sender="bank"), "One unread: Statement — from First Bank")
            self.assertEqual(mail.check_unread(transport=Fake(), sender="acme"), "Nothing unread from acme.")


class ARehearsalSpeaks(unittest.TestCase):
    def test_the_refusal_is_in_english(self):
        with mock.patch.dict(os.environ, {intercom.REHEARSAL: "1"}):
            with self.assertRaises(act.Refused) as caught:
                intercom.execute_command({"kind": "message_send", "to": "dentist", "body": "running late"}, {"repos": {}})
        said = str(caught.exception)
        self.assertIn("I didn't send the text", said)
        self.assertNotIn("message_send", said)
        self.assertNotIn("gated", said)


if __name__ == "__main__":
    unittest.main()


class ThePhraseReachesTheReader(unittest.TestCase):
    def test_everything_carries_his_phrase(self):
        # The live sandbox still said "Sister birthday: march 3rd" after the
        # phrase was stored: `memory.everything`, which every reader asks,
        # had dropped it on the way.
        memory.remember("people", "sister_birthday", "March 3rd", source="test", about="your sister's birthday")
        self.addCleanup(lambda: memory.forget("people", "sister_birthday", via="test cleanup"))
        held = memory.everything()["people"]["sister_birthday"]
        self.assertEqual(held.get("about"), "your sister's birthday")
