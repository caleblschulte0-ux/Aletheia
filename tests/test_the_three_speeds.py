"""Three expectations, and each one has to be met by a different road.

The operator, on what this should feel like: *"if I ask what's the
capital of Iceland, it should come back within five seconds and tell me
Reykjavik. But if I ask it, hey, go do major work on my repos, then it
can be like, okay, I'm thinking, give me a sec."*

    instant   she already knows it            a file read
    quick     one model round trip            ~4s
    working   a plan, and she says so         minutes

Everything that was not `instant` used to be `working`, including
"what's the capital of Iceland" — which paid the PLANNER (a fifteen-
kilobyte grammar prompt, 25-80 seconds here) to conclude it was a
question, and then paid `converse` to answer it. The expensive call
existed only to classify.

No model runs in this file. What is asserted is which road a sentence
takes, and the roads are named by what he experiences rather than by
what executes.
"""
import unittest
from unittest import mock

from aletheia import asking, intents, places


class WhichSpeedCase(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(places, "resolve", side_effect=KeyError("none"))
        p.start()
        self.addCleanup(p.stop)

    def test_things_she_already_knows_are_instant(self):
        for said in ("what time is it", "are you halted", "what day is it"):
            with self.subTest(said=said):
                self.assertEqual(asking.expectation(said), "instant", said)

    def test_a_fact_about_the_world_is_one_round_trip(self):
        for said in ("what's the capital of Iceland", "who wrote Dune",
                     "how tall is Everest", "why is the sky blue",
                     "explain how a diesel engine works"):
            with self.subTest(said=said):
                self.assertEqual(asking.expectation(said), "quick", said)

    def test_real_work_is_working(self):
        for said in ("go do major work on my repos",
                     "email dana that the invoice is ready",
                     "research whether the boiler is under warranty",
                     "fix the onboarding bug",
                     "apply to ten jobs with my resume"):
            with self.subTest(said=said):
                self.assertEqual(asking.expectation(said), "working", said)


class ItRefusesToGuessCase(unittest.TestCase):
    """The bias, and why it points where it does.

    A question misread as a job costs him seconds. A JOB misread as a
    question costs him the work not happening, and he does not find out
    until he checks. So everything uncertain goes to the planner.
    """

    def test_a_doing_verb_anywhere_sends_it_to_the_planner(self):
        for said in ("what's the best way to email dana",
                     "how do I cancel my gym membership",
                     "what should I add to the shopping list",
                     "who should I send this to"):
            with self.subTest(said=said):
                self.assertFalse(asking.is_a_plain_question(said), said)

    def test_anything_about_her_or_his_own_things_is_not_this_lane(self):
        for said in ("what do you think of my plan",
                     "what is my car's mileage",
                     "how are your workers doing"):
            with self.subTest(said=said):
                self.assertFalse(asking.is_a_plain_question(said), said)

    def test_a_project_brief_is_not_a_question_however_it_opens(self):
        long_ask = ("what is the best approach to " + "rewriting " * 30)
        self.assertFalse(asking.is_a_plain_question(long_ask))

    def test_a_sentence_that_is_not_a_question_at_all(self):
        for said in ("", "   ", "dana called", "the boiler is broken"):
            self.assertFalse(asking.is_a_plain_question(said), said)

    def test_it_never_calls_a_model_to_decide(self):
        """Asking a model whether to ask a model is the round trip this
        exists to remove."""
        from aletheia import converse, planner
        with mock.patch.object(planner, "compile",
                               side_effect=AssertionError("planned")), \
             mock.patch.object(converse, "answer",
                               side_effect=AssertionError("conversed")):
            asking.is_a_plain_question("what's the capital of Iceland")
            asking.expectation("who wrote Dune")


class ThePlannerIsNotPaidToClassifyCase(unittest.TestCase):
    """The point of the whole change, asserted directly."""

    def answer_with(self, text):
        return mock.patch("aletheia.converse.answer",
                          return_value={"answer": text})

    def test_a_plain_question_never_reaches_the_planner(self):
        with mock.patch.object(intents.planner, "compile",
                               side_effect=AssertionError(
                                   "the planner was paid to classify a question")), \
             self.answer_with("Reykjavik."):
            record = intents.propose("what's the capital of Iceland")
        self.assertEqual(record["intent"], "answer")
        self.assertTrue(record["read_only"])
        self.assertIn("Reykjav", record["spoken"])

    def test_real_work_still_reaches_the_planner(self):
        reached = []

        def compile_it(*a, **kw):
            reached.append(a)
            raise RuntimeError("stop here")

        with mock.patch.object(intents.planner, "compile", compile_it):
            with self.assertRaises(RuntimeError):
                intents.propose("go do major work on my repos")
        self.assertTrue(reached, "real work skipped the planner")

    def test_the_fast_lane_still_wins_over_both(self):
        with mock.patch("aletheia.policy.halted", lambda: None), \
             mock.patch.object(intents.planner, "compile",
                               side_effect=AssertionError("planned")), \
             mock.patch("aletheia.converse.answer",
                        side_effect=AssertionError("conversed")):
            record = intents.propose("are you halted?")
        self.assertTrue(record.get("fast_path"))

    def test_an_unreachable_model_says_which_half_failed(self):
        """Silence and "I could not think" are different problems."""
        with mock.patch.object(intents.planner, "compile",
                               side_effect=AssertionError("planned")), \
             mock.patch("aletheia.converse.answer",
                        side_effect=RuntimeError("no CLI")):
            record = intents.propose("who wrote Dune")
        self.assertIn("couldn't reach a model", record["spoken"])


if __name__ == "__main__":
    unittest.main()
