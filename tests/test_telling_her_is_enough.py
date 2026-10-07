"""She says "tell me and I'll remember it" - so telling her has to work."""
import unittest
from unittest import mock

from aletheia import quick, speech, voice


class TellingHerIsEnough(unittest.TestCase):
    def cmd(self, said):
        out = voice._interpret(said)
        return (out or {}).get("command")

    def test_my_name_is_remembers_his_name(self):
        c = self.cmd("my name is caleb schulte")
        self.assertEqual((c["kind"], c["domain"], c["key"], c["value"]),
                         ("remember", "identity", "full_name", "Caleb Schulte"))

    def test_one_word_is_what_he_goes_by(self):
        c = self.cmd("you can call me Cal")
        self.assertEqual((c["key"], c["value"]), ("operator_name", "Cal"))

    def test_sentences_that_are_not_his_name_are_not_saved(self):
        for said in ("call me back later", "my name is not caleb",
                     "call me tomorrow at 3", "my name is spelled wrong"):
            c = self.cmd(said)
            self.assertFalse(c and c.get("kind") == "remember", said)

    def test_the_confirmation_is_a_sentence(self):
        line = speech.spoken_receipt("remember", "remembered identity.full_name")
        self.assertEqual(line, "Got it - I'll remember your name.")

    def test_who_is_my_landlord_reads_his_note(self):
        notes = [{"text": "my landlord is Sam Ortiz"}]
        with mock.patch.object(quick, "_notes", return_value=notes), \
                mock.patch("aletheia.memory.recall", return_value=None):
            self.assertEqual(quick._person("landlord"), "Your landlord is Sam Ortiz.")

    def test_nothing_noted_still_says_so(self):
        with mock.patch.object(quick, "_notes", return_value=[]), \
                mock.patch("aletheia.memory.recall", return_value=None):
            self.assertIn("Tell me", quick._person("dentist"))


if __name__ == "__main__":
    unittest.main()
