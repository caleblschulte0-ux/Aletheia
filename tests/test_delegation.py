"""Mostly a test that she refuses to build a team.

A runtime that can assemble workers will assemble them for everything
unless something says no. The expensive mistake here is not too few
agents — it is four workers deliberating over what time it is.
"""
import unittest
from unittest import mock

from aletheia import agents, delegation, places


class ItRefusesFirstCase(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(places, "resolve", side_effect=KeyError("none"))
        p.start()
        self.addCleanup(p.stop)

    def test_a_question_the_fast_lane_answers_never_becomes_a_team(self):
        for said in ("what time is it", "are you halted", "what day is it"):
            with self.subTest(said=said):
                got = delegation.decide(said)
                self.assertFalse(got["delegate"], said)
                self.assertIn("already answers", got["why"])

    def test_a_deterministic_verb_never_becomes_a_team(self):
        for said in ("add milk to the shopping list",
                     "remind me at 3 to call the dentist",
                     "what are my tasks"):
            with self.subTest(said=said):
                got = delegation.decide(said)
                self.assertFalse(got["delegate"], said)

    def test_one_small_thing_is_one_worker_or_none(self):
        got = delegation.decide("summarise this paragraph for me")
        self.assertFalse(got["delegate"])
        self.assertIn("one small thing", got["why"])

    def test_a_hard_question_with_nothing_to_disagree_about_is_not_a_team(self):
        """Three copies of one answer, more slowly, is not independence."""
        got = delegation.decide(
            "explain in detail how the reasoning gateway chooses a provider "
            "when the local pool is configured but not answering")
        self.assertFalse(got["delegate"])
        self.assertIn("differ", got["why"])

    def test_nothing_at_all_is_refused_without_raising(self):
        for empty in ("", "   ", None):
            got = delegation.decide(empty)
            self.assertFalse(got["delegate"])

    def test_it_never_calls_a_model_to_decide_whether_to_call_a_model(self):
        from aletheia import reasoning_gateway
        with mock.patch.object(reasoning_gateway, "reason_json",
                               side_effect=AssertionError("asked a model")):
            delegation.decide("should we launch Barkly next month or wait")


class WhatIsActuallyATeamCase(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(places, "resolve", side_effect=KeyError("none"))
        p.start()
        self.addCleanup(p.stop)

    def test_asking_for_independent_views_gets_them(self):
        for said in ("get three different opinions on this database choice",
                     "have one agent build this and another tear it apart",
                     "I want a second opinion on the launch plan"):
            with self.subTest(said=said):
                got = delegation.decide(said)
                self.assertTrue(got["delegate"], said)
                self.assertGreaterEqual(len(got["roles"]), 2)

    def test_a_decision_with_sides_gets_workers_who_disagree(self):
        got = delegation.decide(
            "should we launch Barkly next month or wait until the onboarding "
            "bug is fixed")
        self.assertTrue(got["delegate"])
        # Roles chosen so they CANNOT produce the same answer.
        self.assertNotEqual(len(set(got["roles"])), 1)
        self.assertIn("decision", got["why"])

    def test_it_never_plans_more_workers_than_the_machine_will_run(self):
        got = delegation.decide(
            "get independent opinions on the architecture and also the "
            "security and also the cost and also the timeline")
        self.assertLessEqual(len(got["roles"]), agents.MAX_PARALLEL + 1)

    def test_the_reason_is_sayable_either_way(self):
        for said in ("what time is it",
                     "should we launch Barkly or wait a month"):
            with self.subTest(said=said):
                line = delegation.spoken(delegation.decide(said))
                self.assertTrue(line.endswith("."), line)
                for forbidden in ("{", "[", "_", "delegate="):
                    self.assertNotIn(forbidden, line)

    def test_he_is_told_it_will_take_minutes(self):
        said = delegation.spoken(delegation.decide(
            "get three different opinions on whether to rewrite the planner"))
        self.assertIn("minutes", said)


if __name__ == "__main__":
    unittest.main()
