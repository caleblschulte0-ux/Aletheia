"""Twenty-eighth sandbox batch, 2026-10-05: what the hunt steers by.

    > how many have you applied to today        [4.7s] a model
    > set my interview window to weekdays 9 to 5  "I can try to book ... experimental"
    > what salary are you asking for            [5.0s] a model
    > raise my minimum to 110k                  the planner, and an approval
    > am I willing to relocate                  "I steer by when you could start" - a
                                                different question
    > I'll relocate for the right job           the planner, and an approval
    > only remote jobs                          the planner, and an approval
"""
import unittest
from unittest import mock

from aletheia import quick, voice


class TheSteering(unittest.TestCase):
    def test_the_sentences_compile_to_the_preference(self):
        self.assertEqual(voice.interpret("set my interview window to weekdays 9 to 5")["command"],
                         {"kind": "interview_window_set", "start": "09:00", "end": "17:00"})
        self.assertEqual(voice.interpret("raise my minimum to 110k")["command"],
                         {"kind": "preference_set", "field": "desired_pay", "value": "110k"})
        self.assertEqual(voice.interpret("I'll relocate for the right job")["command"],
                         {"kind": "preference_set", "field": "willing_to_relocate", "value": "yes - I'll relocate for the right job"})
        self.assertEqual(voice.interpret("I won't relocate")["command"]["value"], "no - I won't relocate")
        self.assertEqual(voice.interpret("only remote jobs")["command"],
                         {"kind": "preference_set", "field": "work_wanted", "value": "only remote jobs"})
        self.assertEqual(voice.interpret("remote only")["command"]["value"], "only remote")
        self.assertEqual(voice.interpret("remote jobs")["command"]["kind"], "intent")

    def test_the_questions_reach_the_profile(self):
        self.assertEqual(quick.status_of("how many have you applied to today"), ("count_window", "today"))
        self.assertEqual(quick.match("what salary are you asking for")[0], "asking_pay")
        with mock.patch("aletheia.profile.answer", side_effect=lambda f: {"willing_to_relocate": "yes - for the right job",
                                                                           "desired_pay": "$110,000 minimum"}.get(f, "")):
            self.assertEqual(quick.answer("am i willing to relocate"), "Relocation: yes - for the right job.")
            self.assertEqual(quick.answer("what salary are you asking for"), "You're asking $110,000 minimum.")
        with mock.patch("aletheia.profile.answer", return_value=""):
            self.assertTrue(quick.answer("would i relocate").startswith("You haven't told me whether you'd relocate."))


if __name__ == "__main__":
    unittest.main()
