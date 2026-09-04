"""Nothing marked a value as sensitive, and the journal is public.

`docs/ROADMAP.md` names information-flow labels as the review's best
idea and the correct answer to "I don't want it blackmailing me". This
is the first slice, aimed at the outbound channel nobody thinks of:
`state/journal/` and `exchange/` are committed to a public GitHub
repository, `CLAUDE.md` says "no secrets in committed files", and every
enforcement of that was a person remembering.

The journal records his own words. A web task journals its goal, and
"log into my bank, the password is hunter2" is a sentence a person says
to an assistant.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, sensitivity


class ItRedactsByShapeNotByUnderstanding(unittest.TestCase):
    def test_the_things_that_must_never_be_written_down(self):
        for text, kind, secret in (
                ("the password is hunter2", "a password", "hunter2"),
                ("passphrase: correct horse", "a password", "horse"),
                ("log in with password hunter2 then submit", "a password",
                 "hunter2"),
                ("my card is 4111 1111 1111 1111", "an account number", "4111"),
                ("account 4111111111111111", "an account number",
                 "4111111111111111"),
                ("ssn 123-45-6789", "a social security number", "123-45-6789"),
                ("api_key = sk-abc123def456ghi789", "a key",
                 "sk-abc123def456ghi789"),
                ("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345", "a key", "ABCDEF"),
                ("cvv: 123", "a card code", "123")):
            with self.subTest(text=text):
                out, found = sensitivity.scrub(text)
                self.assertEqual(found, [kind])
                self.assertNotIn(secret, out)

    def test_a_passphrase_is_more_than_one_word(self):
        """The first version took one word and left three quarters of it
        sitting in a public repository."""
        out, _ = sensitivity.scrub("passphrase: correct horse battery staple")
        for word in ("correct", "horse", "battery", "staple"):
            self.assertNotIn(word, out)

    def test_the_word_PASSWORD_in_an_ordinary_sentence_is_left_alone(self):
        """Catching "password hunter2" without a colon is worth having;
        mangling every sentence with the word in it is not."""
        for text in ("the password field was empty",
                     "reset the password screen",
                     "he asked about the password policy"):
            with self.subTest(text=text):
                self.assertEqual(sensitivity.scrub(text), (text, []))

    def test_a_private_key_block_goes_whole(self):
        text = ("-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n"
                "-----END RSA PRIVATE KEY-----")
        out, found = sensitivity.scrub("here it is " + text)
        self.assertEqual(found, ["a private key"])
        self.assertNotIn("MIIabc", out)

    def test_ordinary_sentences_are_left_completely_alone(self):
        """A scrubber that mangles normal text is one somebody turns off."""
        for text in ("applied for the systems job at Stripe",
                     "AWAITING_YOU after 5 step(s): cancel my gym membership",
                     "filled 3 from what I know: First name, Email, Phone",
                     "pressed 'Submit application' — confirmed",
                     "call me on 512-555-0134"):
            with self.subTest(text=text):
                self.assertEqual(sensitivity.scrub(text), (text, []))

    def test_it_is_blunt_on_purpose(self):
        """A sixteen-digit order id gets redacted too. In prose that costs
        nothing; the alternative costs a card number in a public repo."""
        out, found = sensitivity.scrub("order 4029183746152837 shipped")
        self.assertEqual(found, ["an account number"])
        self.assertIn("shipped", out)

    def test_it_says_WHAT_it_hid_and_never_the_value(self):
        out, found = sensitivity.scrub("the password is hunter2")
        self.assertEqual(found, ["a password"])
        self.assertNotIn("hunter2", json.dumps(found))
        self.assertNotIn("hunter2", out)

    def test_it_never_throws(self):
        """A scrubber that can fail is one that gets wrapped in a
        try/except and quietly skipped."""
        for value in ("", None, 12345, object()):
            with self.subTest(value=repr(value)):
                text, found = sensitivity.scrub(value)
                self.assertIsInstance(text, str)
                self.assertEqual(found, [])


class TheJOURNAL_IS_PUBLIC(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "j.jsonl"
        patch = mock.patch.object(journal, "JOURNAL_PATH", self.path)
        patch.start(); self.addCleanup(patch.stop)

    def test_a_secret_never_reaches_the_file(self):
        journal.append("note", "webtask",
                       "log into my bank, the password is hunter2")
        written = self.path.read_text(encoding="utf-8")
        self.assertNotIn("hunter2", written)
        self.assertIn("[redacted]", written)

    def test_the_entry_says_that_something_was_hidden(self):
        entry = journal.append("note", "webtask", "my card is 4111111111111111")
        self.assertEqual(entry["redacted"], ["an account number"])
        self.assertNotIn("4111111111111111", json.dumps(entry))

    def test_an_ordinary_entry_is_unchanged_and_unmarked(self):
        entry = journal.append("action", "webtask", "applied at Stripe")
        self.assertEqual(entry["text"], "applied at Stripe")
        self.assertNotIn("redacted", entry)

    def test_the_receipt_writer_scrubs_too(self):
        """`exchange/` is committed as well, and a receipt's detail is
        whatever the capability said — for a web task, text read off a
        page."""
        from aletheia import intercom
        source = Path(intercom.__file__).read_text(encoding="utf-8")
        writer = source[source.index("def _write_receipt_and_journal"):]
        writer = writer[:writer.index("\ndef ")]
        self.assertIn("sensitivity.scrub", writer)


if __name__ == "__main__":
    unittest.main()
