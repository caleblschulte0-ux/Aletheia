""""Remember to bring my ID to the dentist" was read as a question about her
notes ("I have nothing about to bring my id ... on file"), and "what do I
need for the Sarah meeting" went to a model with the note sitting there
(2026-10-14)."""
import unittest
from unittest import mock

from aletheia import quick, voice


class RememberToIsAnInstruction(unittest.TestCase):
    def test_not_a_recall(self):
        self.assertIsNone(quick._groups("recall", "remember to bring my id to the dentist") or None)
        self.assertTrue(quick._groups("recall", "do you remember my landlord"))

    def test_a_task(self):
        for said in ("remember to bring my id to the dentist", "don't forget to take out the trash tonight"):
            self.assertEqual(voice._interpret(said)["command"]["kind"], "task_new", said)


class WhatDoINeedForTheMeeting(unittest.TestCase):
    ROWS = [{"text": "the Sarah meeting: bring the budget"}, {"text": "my dentist is Dr. Patel"}]

    def test_the_note_answers(self):
        with mock.patch.object(quick, "_notes", return_value=self.ROWS):
            for asked in ("what do i need for the sarah meeting", "what should i bring to my meeting with sarah",
                          "what do i need to bring to the sarah meeting"):
                self.assertEqual(quick.answer(asked), "For the Sarah meeting, you noted: bring the budget.", asked)

    def test_no_note_hands_on(self):
        with mock.patch.object(quick, "_notes", return_value=self.ROWS):
            self.assertIsNone(quick._for_meeting("what do i need for the dentist appointment"))


if __name__ == "__main__":
    unittest.main()
