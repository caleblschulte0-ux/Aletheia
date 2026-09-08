"""Which kind of work is this, and does it still have to pass the gates.

The behaviour this locks down is one sentence: **producing words is not a
project, but delivering them is.** "Write me an email to Brant" is one
round trip and used to cost a 25-80s planner compile; "write and send
Brant an email" is work and still goes through the planner and the gates.

The dangerous direction is only ever one of these. A question misread as
a job costs him seconds. A JOB misread as a question means the work
silently does not happen and she says something agreeable instead - so
every test about delivery below is a safety test, not a speed test.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import asking, routing


class WhatKindOfWorkCase(unittest.TestCase):
    def test_producing_words_is_writing(self):
        for said in ("write me an email to Brant about my promotion",
                     "draft an email to Dana",
                     "draft a thank you note",
                     "compose a short toast for the wedding",
                     "write me a caption for this photo"):
            with self.subTest(said=said):
                self.assertEqual(routing.task_type(said), "writing")

    def test_changing_words_he_already_has_is_a_rewrite(self):
        for said in ("rewrite this to sound friendlier",
                     "make this sound better",
                     "polish this paragraph",
                     "tighten this up"):
            with self.subTest(said=said):
                self.assertEqual(routing.task_type(said), "rewrite")

    def test_a_short_fact_is_not_an_explanation(self):
        """They route to different providers, so the split has to hold."""
        self.assertEqual(routing.task_type("who wrote Dune"), "simple_qa")
        self.assertEqual(routing.task_type("what is the capital of Iceland"),
                         "simple_qa")
        self.assertEqual(routing.task_type("why does thunder happen"),
                         "explanation")
        self.assertEqual(routing.task_type("explain how a diesel engine works"),
                         "explanation")

    def test_asking_why_something_happens_is_not_debugging(self):
        """"why does thunder happen" was classified as a fault report.

        A bare "why does"/"why is" matches ordinary curiosity. Only the
        NEGATIVE forms and real failure words mean something broke.
        """
        self.assertEqual(routing.task_type("why does thunder happen"),
                         "explanation")
        self.assertEqual(routing.task_type("why is the build failing"),
                         "debugging")
        self.assertEqual(routing.task_type("why isn't my script working"),
                         "debugging")

    def test_asking_for_code_is_coding_even_when_phrased_as_writing(self):
        self.assertEqual(
            routing.task_type("write a python function to parse dates"),
            "coding")

    def test_a_project_is_planning(self):
        for said in ("go improve my repo", "overhaul Barkly",
                     "audit my systems", "take care of my inbox"):
            with self.subTest(said=said):
                self.assertEqual(routing.task_type(said), "planning")


class TheDeliveryLineCase(unittest.TestCase):
    """Everything here is a safety test: work must not become chat."""

    def test_writing_alone_delivers_nothing(self):
        for said in ("write me an email to Brant",
                     "draft an email to Dana",
                     "write me a text for Brant"):
            with self.subTest(said=said):
                self.assertFalse(routing.delivers(said))
                self.assertTrue(routing.answerable_directly(said))

    def test_a_delivery_verb_makes_it_work(self):
        for said in ("write and send Brant an email",
                     "draft an email to Dana and send it",
                     "write it and email her",
                     "text Brant that I'm running late",
                     "email Dana the report",
                     "save this to my desktop",
                     "post this to my blog",
                     "commit this and push it"):
            with self.subTest(said=said):
                self.assertTrue(routing.delivers(said), said)
                self.assertFalse(routing.answerable_directly(said), said)
                self.assertEqual(routing.task_type(said), "action")

    def test_the_noun_email_is_not_the_verb_email(self):
        """The bug that made this module necessary, kept caught.

        "Write me an email to Brant" contains the word "email" and
        delivers nothing. An earlier version matched the noun, called it
        an action, and sent the exact sentence this exists to rescue
        straight back to the planner.
        """
        self.assertFalse(routing.delivers("write me an email to Brant"))
        self.assertTrue(routing.delivers("email Brant"))

    def test_nothing_that_delivers_is_ever_answerable_directly(self):
        """The whole safety property, asserted as one rule."""
        for said in ("write and send it", "draft it then post it",
                     "summarise this and email it to Dana",
                     "rewrite this and publish it"):
            with self.subTest(said=said):
                self.assertFalse(routing.answerable_directly(said), said)


class ThreeSpeedsCase(unittest.TestCase):
    def test_a_stored_answer_is_still_instant(self):
        """The tier an earlier draft of this change silently deleted."""
        with mock.patch("aletheia.quick.answer", return_value="It is 4pm."):
            self.assertEqual(asking.expectation("what time is it"), "instant")

    def test_writing_is_quick_not_working(self):
        with mock.patch("aletheia.quick.answer", return_value=None):
            for said in ("write me an email to Brant",
                         "summarize this for me",
                         "rewrite this to sound friendlier"):
                with self.subTest(said=said):
                    self.assertEqual(asking.expectation(said), "quick")

    def test_delivering_is_working(self):
        with mock.patch("aletheia.quick.answer", return_value=None):
            for said in ("write and send Brant an email",
                         "text Brant that I'm late",
                         "go improve my repo"):
                with self.subTest(said=said):
                    self.assertEqual(asking.expectation(said), "working")

    def test_a_router_that_will_not_load_falls_back_to_working(self):
        """Fail toward the planner: slower, never wrong about the work."""
        with mock.patch("aletheia.quick.answer", return_value=None), \
             mock.patch("aletheia.routing.answerable_directly",
                        side_effect=RuntimeError("router broken")):
            self.assertEqual(asking.expectation("write me an email"), "working")


class ProviderPolicyCase(unittest.TestCase):
    def test_prose_prefers_chatgpt_and_code_prefers_claude(self):
        """His stated preference, in one table rather than scattered."""
        self.assertEqual(routing.providers_for("writing")[0], "chatgpt")
        self.assertEqual(routing.providers_for("rewrite")[0], "chatgpt")
        self.assertEqual(routing.providers_for("coding")[0], "claude")
        self.assertEqual(routing.providers_for("planning")[0], "claude")
        self.assertEqual(routing.providers_for("debugging")[0], "claude")

    def test_local_leads_only_where_it_measured_faster(self):
        """2.4s for a short fact; 12.1s for a paragraph of prose.

        Local is paid per token on this CPU-only machine and a
        subscription call is paid per round trip, so local can only win
        when the answer is short. Anything wordy must not prefer it.
        """
        self.assertEqual(routing.providers_for("simple_qa")[0], "local")
        for wordy in ("writing", "rewrite", "summarization", "explanation"):
            with self.subTest(task=wordy):
                self.assertNotEqual(routing.providers_for(wordy)[0], "local")

    def test_every_task_type_has_a_policy(self):
        """A type with no row would silently fall to the unknown default."""
        for kind in routing.TASK_TYPES:
            with self.subTest(task=kind):
                self.assertIn(kind, routing.TASK_PROVIDER_POLICY)

    def test_every_policy_names_a_real_provider(self):
        for kind, chain in routing.TASK_PROVIDER_POLICY.items():
            for name in chain:
                with self.subTest(task=kind, provider=name):
                    self.assertIn(name, {"local", "claude", "chatgpt"})

    def test_a_sentence_routes_as_well_as_a_type(self):
        self.assertEqual(routing.providers_for("write me an email")[0],
                         "chatgpt")

    def test_choosing_a_provider_grants_no_authority(self):
        """Routing decides who REASONS, never what may be DONE."""
        with open(routing.__file__, encoding="utf-8") as handle:
            source = handle.read()
        for forbidden in ("approve", "policy.", "execute", "intercom",
                          "webtask", "subprocess"):
            self.assertNotIn(forbidden, source,
                             f"{forbidden} would let routing touch authority")


if __name__ == "__main__":
    unittest.main()
