"""Two answers that were true, useless, and blamed the wrong thing.

Both were found by talking to her (`python -m aletheia.talk --sandbox`),
and both are the shape a unit test cannot see on its own: correct data
arranged into a sentence he cannot act on.

  "what's on my calendar this week"
    -> `Not yet — that one needs setting up first: python -m aletheia.apply
       calendar "<paste the URL>".`
    Which URL? The line that answers that was sitting directly above the
    command in the setup checklist.

  "research the best air purifier under 200 dollars"
    -> `no readable sources were found for that question — say it
       differently, or it may be something the open web does not answer`
    The web was fine. The browser could not load a page. Blaming his
    question means he rephrases it forever and never fixes the network —
    which is the exact failure the comment above that guard says it fixed,
    left half-fixed because `available()` is installed, not working.
"""
import unittest
from unittest import mock

from aletheia import browse, intents, research, setup


class SetupAnswerIsActionable(unittest.TestCase):
    def _step(self, capability):
        for step in setup.steps():
            if step.capability == capability:
                return step
        self.fail(f"no setup step for {capability}")

    def test_it_says_where_the_thing_he_must_paste_comes_from(self):
        said = intents._cannot_yet([{"capability": "calendar.read"}], {})
        self.assertIn("Google Calendar", said)
        self.assertIn("aletheia.apply calendar", said)

    def test_a_prerequisite_is_a_sentence_not_a_heading(self):
        # A heading ends in a colon because the screen puts the substance
        # underneath it; read out it is a fragment.
        for step in setup.steps():
            prereq = intents._setup_prereq(step)
            if prereq:
                self.assertFalse(prereq.endswith(":"), step.capability)
                self.assertGreaterEqual(len(prereq.split()), 4, step.capability)

    def test_a_prerequisite_is_never_the_command_itself(self):
        for step in setup.steps():
            prereq = intents._setup_prereq(step)
            self.assertFalse(prereq.startswith("python "), step.capability)

    def test_a_condition_survives_because_it_is_the_whole_point(self):
        # "Only if you already run Home Assistant:" is the difference
        # between a five-minute task and installing a home automation
        # platform. Dropping it left her reciting a menu path he has no
        # menu for.
        prereq = intents._setup_prereq(self._step("room.scene"))
        self.assertTrue(prereq.lower().startswith("only if"), prereq)

    def test_a_step_with_no_prose_still_answers(self):
        # browser.read is two pip commands and nothing else. The old
        # single-line answer has to survive when there is no prose.
        said = intents._cannot_yet([{"capability": "browser.read"}], {})
        self.assertIn("playwright", said)
        self.assertTrue(said.startswith("Not yet"), said)


class ResearchBlamesTheRightThing(unittest.TestCase):
    def _run_with_no_sources(self, reachable):
        with mock.patch.object(research, "find_sources", return_value=[]), \
             mock.patch.object(research.policy, "ensure_not_halted"), \
             mock.patch.object(browse, "available", return_value=(True, "installed")), \
             mock.patch.object(browse, "reachable", return_value=reachable), \
             self.assertRaises(research.ResearchError) as caught:
            research.run("what is the best air purifier",
                         think=lambda *a, **k: {"queries": ["air purifier"]})
        return str(caught.exception)

    def test_an_unreachable_browser_is_not_an_unanswerable_question(self):
        said = self._run_with_no_sources((False, "ERR_CONNECTION_RESET"))
        self.assertIn("could not reach the web", said)
        self.assertNotIn("does not answer", said)

    def test_a_reachable_browser_that_finds_nothing_still_says_so(self):
        said = self._run_with_no_sources((True, "loaded https://example.com"))
        self.assertIn("no readable sources", said)

    def test_the_live_check_costs_nothing_on_the_happy_path(self):
        # It is a real browser launch. It may only ever run on the failure
        # path — a check that fires on every successful search would put
        # twenty seconds on every question he asks.
        with mock.patch.object(browse, "reachable") as never, \
             mock.patch.object(research, "find_sources", return_value=[]), \
             mock.patch.object(research.policy, "ensure_not_halted"), \
             mock.patch.object(browse, "available", return_value=(True, "installed")):
            # a stubbed reader means this is not the real browser at all
            with self.assertRaises(research.ResearchError):
                research.run("q", reader=lambda *a, **k: {},
                             think=lambda *a, **k: {"queries": ["q"]})
        never.assert_not_called()


if __name__ == "__main__":
    unittest.main()
