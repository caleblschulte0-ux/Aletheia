"""Forty-sixth sandbox batch, 2026-10-05: the fleet, asked sideways.

    > anything go wrong today           [13.0s] a model
    > which repo had the last fault      [4.5s] a model
    > when was the last pulse / how old is the pulse   [4.0s] a model each
    > how many repos are you watching    [4.5s] a model
    > list the repos                     [5.5s] "No active projects." (the wrong store)
    > what's the shorts pipeline         [5.5s] a model, which had never heard of it
    > what's failing in CI               [4.5s] a model
"""
import unittest
from pathlib import Path
from unittest import mock

from aletheia import pulse, quick


class TheFleetSideways(unittest.TestCase):
    def test_the_registry_answers_what_the_fleet_is(self):
        self.assertEqual(quick.match("how many repos are you watching")[0], "repos")
        self.assertEqual(quick.match("how many projects are in the fleet")[0], "repos")
        with mock.patch.object(pulse, "PULSE_DIR", Path("/nonexistent")):
            said = quick.answer("list the repos")
        self.assertTrue(said.startswith("4 repositories being watched: "), said)
        self.assertIn("Shorts-pipeline", said)
        self.assertIn("not watched", said)
        self.assertNotIn("mores", said)
        self.assertTrue(quick.answer("what's the shorts pipeline").startswith("Shorts-pipeline: "))
        self.assertTrue(quick.answer("what does the trader do").startswith("schwab-trader: "))
        self.assertTrue(quick.answer("tell me about the money machine project").startswith("Money_Machine: "))

    def test_the_catch_all_is_last_and_answers_nothing_it_does_not_know(self):
        # "what's the time" and "what's the weather" keep their own answers
        self.assertNotEqual(quick.match("what's the time")[0], "repo_about")
        self.assertNotEqual(quick.match("what's the weather")[0], "repo_about")
        self.assertNotEqual(quick.match("what's my name")[0], "repo_about")
        self.assertIsNone(quick.match("what's the capital of france"))
        self.assertIsNone(quick.match("what about next week"))
        self.assertIsNone(quick.match("what did dana say today"))
        self.assertEqual([n for n, _p in quick.PATTERNS][-1], "repo_about")

    def test_the_pulse_answers_faults_and_ci(self):
        with mock.patch.object(pulse, "PULSE_DIR", Path("state/pulse")):
            self.assertRegex(quick.answer("which repo had the last fault"), r"^[A-Za-z_-]+: .+")
            self.assertTrue(quick.answer("when was the last pulse").startswith("The fleet was last read "))
            ci = quick.answer("is CI green")
            self.assertTrue(ci.startswith(("Green: ", "Red: ")), ci)
            self.assertEqual(quick.answer("what's failing in CI"), ci)
        with mock.patch.object(pulse, "PULSE_DIR", Path("/nonexistent")):
            for said in ("which repo had the last fault", "is CI green", "how old is the pulse"):
                self.assertIn("No fleet reading yet", quick.answer(said), said)

    def test_anything_go_wrong_is_the_wrong_question(self):
        self.assertEqual(quick.match("anything go wrong today")[0], "wrong")
        self.assertEqual(quick.match("anything wrong")[0], "wrong")


if __name__ == "__main__":
    unittest.main()
