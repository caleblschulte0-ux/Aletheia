""""Actually cancel that" and "cancel that reminder" are the same sentence as "cancel it".

Talking to her in a sandbox, 2026-10-06, with no model to fall back on:

    > add a task to call the plumber      Added a task: call the plumber.
    > actually cancel that                I could not plan that: neither Claude nor the
                                          ChatGPT browser could answer just now; ...
    > remind me tomorrow at 9 to email Sam
    > cancel that reminder                None of your reminders is about that. The one
                                          you have is email Sam - Thursday at 9 am.

"Cancel that" alone was already instant. The correction word in front of it hid it from
every pattern, and "that reminder" was searched for the word "that".
"""
import unittest
from unittest import mock

from aletheia import voice


def after(*said):
    return mock.patch("aletheia.converse.recent", return_value=[{"he_asked": s, "she_answered": "x"} for s in said])


class CancelThat(unittest.TestCase):
    def setUp(self):
        p = mock.patch("aletheia.policy.all_approvals", return_value=[])
        p.start()
        self.addCleanup(p.stop)

    def test_a_correction_word_in_front_changes_nothing(self):
        with after("add a task to call the plumber"):
            for said in ("actually cancel that", "oh cancel that", "sorry, cancel it", "oops cancel that"):
                self.assertEqual(voice.interpret(f"thea {said}")["command"], {"kind": "undo"}, said)

    def test_a_correction_is_not_the_thing_to_take_back(self):
        """The previous ask skips "actually cancel that" the way it skips "cancel that"."""
        with after("remind me at 3 to call the dentist", "actually make that 4"):
            self.assertEqual(voice._previous_ask(), "remind me at 3 to call the dentist")

    def test_that_reminder_is_the_one_he_just_set(self):
        with after("remind me tomorrow at 9 to email Sam"):
            for said in ("cancel that reminder", "delete the reminder", "cancel the new reminder", "stop that reminder"):
                self.assertEqual(voice.interpret(f"thea {said}")["command"], {"kind": "undo"}, said)

    def test_a_named_reminder_and_a_pronoun_with_no_reminder_behind_it_are_unchanged(self):
        with after("remind me tomorrow at 9 to email Sam"):
            self.assertEqual(voice.interpret("thea cancel the dentist reminder")["command"],
                             {"kind": "reminder_off", "which": "dentist"})
            self.assertEqual(voice.interpret("thea cancel the last reminder")["command"],
                             {"kind": "reminder_off", "which": "last"}, "an ordinal still counts down the list")
        with after("what time is it"):
            self.assertEqual(voice.interpret("thea cancel that reminder")["command"],
                             {"kind": "reminder_off", "which": "that"})

    def test_what_are_my_reminders_is_read_from_the_store(self):
        for said in ("what are my reminders", "show me my reminders", "read me my timers"):
            self.assertEqual(voice.interpret(f"thea {said}")["command"], {"kind": "reminders"}, said)

    def test_actually_is_still_dropped_only_from_the_front(self):
        self.assertEqual(voice._without_preamble("actually, what time is it"), "what time is it")
        self.assertEqual(voice._without_preamble("actually"), "actually")


if __name__ == "__main__":
    unittest.main()
