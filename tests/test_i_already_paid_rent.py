""""I already paid rent" and "my wife bought tickets to the game" went to the
planner while "I paid rent" was a note (2026-10-24); with nobody to think
they were lost.
"""
import unittest

from aletheia import intents, voice


class IAlreadyPaidRent(unittest.TestCase):
    def _cmd(self, said):
        return voice.interpret(said).get("command") or {}

    def test_done_is_kept_in_his_words(self):
        for said in ("i already paid rent", "I've already booked the hotel", "we already paid the plumber",
                     "my wife bought tickets to the game", "Sam booked the hotel"):
            with self.subTest(said=said):
                self.assertEqual(self._cmd(said), {"kind": "note", "text": said})

    def test_not_a_person_not_a_question_not_an_instruction(self):
        for said in ("Pizza got cold", "who bought the tickets", "my wife should buy tickets", "order me a pizza"):
            with self.subTest(said=said):
                self.assertNotEqual(self._cmd(said).get("kind"), "note")
        self.assertTrue(intents._asks_to_spend("order me a pizza"))


if __name__ == "__main__":
    unittest.main()
