"""Talked to her, 2026-10-12, every model off: "anything I'm forgetting" went to the planner while
"what should I work on today" was answered from her stores, and "what time is it in Tampa" went to
a model while Nashville and Austin - two other places on his move shortlist - were answered."""

import unittest

from aletheia import quick


class WhatAmIForgettingIsTheDay(unittest.TestCase):

    def test_the_forgetting_phrasings_are_the_focus_question(self):
        for asked in ("anything i'm forgetting", "is there anything im forgetting", "am i forgetting anything",
                      "what am i forgetting today", "did i forget anything"):
            self.assertEqual((quick.match(asked) or ("",))[0], "focus", asked)


class TheShortlistedPlacesHaveAClock(unittest.TestCase):

    def test_every_place_on_his_shortlist_tells_the_time(self):
        for place in ("tampa", "charleston", "austin", "nashville", "orlando", "raleigh", "memphis"):
            said = quick.answer(f"what time is it in {place}")
            self.assertIsNotNone(said, place)
            self.assertIn(place.title(), said)


if __name__ == "__main__":
    unittest.main()
