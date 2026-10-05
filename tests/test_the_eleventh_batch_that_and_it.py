"""Eleventh sandbox batch, 2026-10-05: what "that" and "it" mean.

    > actually cancel that            [5.6s] a plan and an approval to cancel a
                                      task she had just added for free
    > remind me about it tomorrow at 9   "I don't have anything remembered
                                      about 'it tomorrow at 9'" - a recall
    > what's left                     the setup checklist, after "mark the
                                      dentist one done"
    > move that to 10                 [7.5s] a reminder INVENTED from the
                                      thread, with nothing set to move
    > what day of the week is christmas  [3.5s] a model, for calendar arithmetic
"""
import unittest
from unittest import mock

from aletheia import quick, voice


class ActuallyCancelThat(unittest.TestCase):
    def test_a_breath_in_front_does_not_change_the_words(self):
        with mock.patch("aletheia.policy.all_approvals", return_value=[]), \
             mock.patch("aletheia.voice._last_ask_is_undoable", return_value=True):
            for said in ("actually cancel that", "no, cancel that", "cancel that"):
                self.assertEqual(voice.interpret(said)["command"], {"kind": "undo"}, said)


class RemindMeAboutIt(unittest.TestCase):
    def test_it_is_his_last_task_and_the_sentence_is_a_reminder(self):
        with mock.patch("aletheia.voice._last_task_words", return_value="call the dentist"):
            cmd = voice.interpret("remind me about it tomorrow at 9")["command"]
        self.assertEqual(cmd["kind"], "remind_at")
        self.assertEqual(cmd["text"], "call the dentist")

    def test_a_named_thing_with_a_time_is_a_reminder_too(self):
        cmd = voice.interpret("remind me about the bins tonight at 8")["command"]
        self.assertEqual(cmd["kind"], "remind_at")
        self.assertIn("bins", cmd["text"])

    def test_without_a_time_it_is_still_a_recall(self):
        cmd = voice.interpret("remind me about the landlord")["command"]
        self.assertEqual(cmd["kind"], "recall")


class WhatsLeftIsHisList(unittest.TestCase):
    def test_bare_is_tasks_and_to_set_up_is_setup(self):
        with mock.patch("aletheia.quick._tasks", return_value="1 task open. Next: call the dentist."):
            self.assertEqual(quick.answer("what's left"), "1 task open. Next: call the dentist.")
        self.assertEqual(voice.interpret("what's left to set up")["command"], {"kind": "setup_status"})


class MoveThatWithNothingToMove(unittest.TestCase):
    def test_it_says_so_instead_of_inventing_one(self):
        with mock.patch("aletheia.voice._previous_reminder_ask", return_value={}):
            out = voice.interpret("move that to 10")
        self.assertIsNone(out["command"])
        self.assertIn("haven't set a reminder", out["say"])

    def test_a_question_in_between_does_not_lose_the_reminder(self):
        turns = [{"he_asked": "remind me tomorrow at 9 to call the dentist", "she_answered": "ok"},
                 {"he_asked": "what reminders do I have", "she_answered": "1 reminder"}]
        with mock.patch("aletheia.converse.recent", return_value=turns):
            cmd = voice.interpret("move that to 10")["command"]
        self.assertEqual(cmd["kind"], "remind_at")
        self.assertEqual(cmd["text"], "call the dentist")
        self.assertEqual(cmd["replaces"], "call the dentist")


class WhatDayIsIt(unittest.TestCase):
    def test_the_weekday_is_arithmetic(self):
        said = quick.answer("what day of the week is christmas")
        self.assertIn("December", said)
        self.assertRegex(said, r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)")


if __name__ == "__main__":
    unittest.main()
