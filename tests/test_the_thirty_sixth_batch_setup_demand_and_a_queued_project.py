"""Thirty-sixth sandbox batch, 2026-10-05: setup by its other names, the demand
ledger, and a project not drafted yet.

    > what's next on the recipe app        "I don't have an application to recipe"
    > what do you get asked for most       [5.5s] "I don't have a tally"
    > what do people ask you for that you can't do   [16.5s] a model
    > set up mail / how do I set up mail   [5.5s] [4.5s] models
    > what's not set up yet                [4.5s] a model
"""
import unittest
from unittest import mock

from aletheia import quick, voice


class SetupAndDemand(unittest.TestCase):
    def test_setup_by_its_other_names(self):
        for said in ("what's not set up yet", "what needs setting up"):
            self.assertEqual(voice.interpret(said)["command"], {"kind": "setup_status"}, said)
        for said in ("set up mail", "how do I set up mail"):
            self.assertEqual(voice.interpret(said)["command"], {"kind": "setup_status", "about": "mail"}, said)
        self.assertNotEqual(voice.interpret("set a timer for 5 minutes")["command"]["kind"], "setup_status")

    def test_the_demand_ledger_answers(self):
        with mock.patch("aletheia.demand.spoken", return_value="The thing you keep asking for and I cannot do is room.scene — 3 times."):
            self.assertEqual(quick.answer("what do you get asked for most"), "The thing you keep asking for and I cannot do is room.scene — 3 times.")
            self.assertEqual(quick.match("what do people ask you for that you can't do")[0], "demand")


class AProjectNotDraftedYet(unittest.TestCase):
    def test_it_is_named_as_still_to_draft(self):
        with mock.patch("aletheia.charters.pending", return_value=[{"kind": "new", "text": "a recipe app for my kitchen", "state": "pending"}]), \
             mock.patch("aletheia.apply_run.find", return_value=[]), \
             mock.patch("aletheia.pursuit.search", return_value=[]):
            said = quick.answer("what's next on the recipe app")
        self.assertTrue(said.startswith("A recipe app for my kitchen is still to draft"), said)
        with mock.patch("aletheia.charters.pending", return_value=[]), \
             mock.patch("aletheia.apply_run.find", return_value=[]), \
             mock.patch("aletheia.pursuit.search", return_value=[]), \
             mock.patch("aletheia.plans.find_charter", return_value=(None, "I don't have a project called recipe.")):
            self.assertEqual(quick.answer("what's next on the recipe app"), "I don't have an application to recipe.")


if __name__ == "__main__":
    unittest.main()
