"""Talked to her, 2026-10-12: with the city comparison written into the mission, "what cities are
you looking at", "what's on the shortlist", "compare Tampa and Austin" and "what's the cost of
living in Tampa" all went to a model that has never read a mission's results ("what's the
shortlist" even answered "I have nothing about the shortlist on file"). What she found answers."""

from tests import test_his_mission_rehearsed as rehearsed

FOUND = ("I read bestplaces.net and two tax tables. "
         "Tampa: cost of living index 102, median rent $1,850, no state income tax. "
         "Austin: cost of living index 119, median rent $1,700, no state income tax. "
         "Nashville: cost of living index 106, no state tax on wages.")


class WhatCitiesSheIsLookingAt(rehearsed.HisMissionRunsWithoutHim):

    def _found(self, said=FOUND, outcome="ok", state=rehearsed.ws.DONE):
        def change(record):
            t6 = next(t for t in record["tasks"] if t["key"] == "t6")
            t6.update(state=state, results=[{"at": "2026-10-11T17:07:00Z", "step": 0, "tool": "research",
                                             "outcome": outcome, "said": said}])
        rehearsed.pg.update(self.pid, change)

    def test_the_cities_are_the_comparison(self):
        from aletheia import quick
        self._found()
        for asked in ("what cities are you looking at", "Which cities are on the shortlist?",
                      "what's on the shortlist", "where should I move", "what did the comparison say",
                      "which cities made the shortlist"):
            said = quick.answer(asked) or ""
            self.assertIn("Tampa: cost of living index 102", said, asked)
            self.assertIn("Compare a shortlist of warm red-state cities", said, asked)
            self.assertNotIn("I read bestplaces", said, asked)

    def test_a_named_city_is_the_sentences_that_name_it(self):
        from aletheia import quick
        self._found()
        said = quick.answer("what's the cost of living in Tampa") or ""
        self.assertTrue(said.startswith("From what I've found so far: Tampa: cost of living index 102"), said)
        self.assertNotIn("Nashville", said)
        both = quick.answer("compare tampa and austin") or ""
        self.assertIn("Tampa:", both)
        self.assertIn("Austin:", both)
        self.assertIn("Austin", quick.answer("how does austin compare to nashville") or "")

    def test_nothing_found_hands_the_question_on(self):
        from aletheia import quick
        self._found()
        # A place she never read about is not settled by what she found.
        self.assertIsNone(quick.answer("compare denver and boise"))
        # A look that failed is not a finding, and an unfinished comparison says so.
        self._found(said="I can't give you a sourced comparison from what I was handed.", outcome="failed",
                    state=rehearsed.ws.RETRY_LATER)
        said = quick.answer("what cities are you looking at") or ""
        self.assertIn("haven't finished", said)
        self.assertIn("Project Reboot", said)
        self.assertIsNone(quick.answer("what's the cost of living in tampa"))

    def test_the_weather_is_still_the_weather(self):
        from aletheia import quick
        self._found()
        self.assertNotEqual((quick.match("what's the weather in tampa") or ("",))[0], "mission_found")

    def test_the_voice_layer_leaves_them_to_what_she_found(self):
        from aletheia import voice
        self._found()
        for asked in ("what's on the shortlist", "what's the cost of living in tampa", "what cities are you looking at"):
            self.assertNotEqual(((voice._interpret(asked) or {}).get("command") or {}).get("kind"), "missions", asked)
        # With nothing found that settles it, the mission's status still answers.
        self._found(said="I can't give you a sourced comparison from what I was handed.", outcome="failed",
                    state=rehearsed.ws.RETRY_LATER)
        self.assertEqual(voice._interpret("what's the cost of living in tampa")["command"]["kind"], "missions")
