"""A sentence that belongs to its moment is not kept for a model later.

With nothing able to think, "give me a pep talk", "I'm stressed" and
"tell me something interesting" were filed as work, and the overnight
answer read them back: "kept 'I'm stressed' for later, until a model is
back". Planned hours later, the moment would long be over. A need he
states ("I'm out of milk") is still an ask, and is still kept.
"""
import unittest

from aletheia import planner


class WhatBelongsToTheMoment(unittest.TestCase):
    def test_feelings_and_being_entertained_are_for_right_now(self):
        for said in ("I'm bored", "I'm stressed", "i feel awful", "give me a pep talk",
                     "tell me something interesting", "tell me a joke", "cheer me up",
                     "make me laugh", "say something nice", "Thea, I'm tired."):
            self.assertTrue(planner.for_right_now(said), said)

    def test_the_planner_asks_before_it_files(self):
        import inspect
        self.assertIn("for_right_now(request)", inspect.getsource(planner.compile))

    def test_a_need_or_a_plan_is_still_an_ask(self):
        for said in ("I'm out of milk", "I'm running low on coffee", "I'm meeting Sam friday",
                     "I'm going to need a ride to the airport", "book a table at nobu",
                     "tell me when the package arrives", "give me a list of plumbers near me",
                     "remind me to call mom"):
            self.assertFalse(planner.for_right_now(said), said)


if __name__ == "__main__":
    unittest.main()
