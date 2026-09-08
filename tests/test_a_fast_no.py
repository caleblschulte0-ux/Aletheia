"""A slow no is a no he had to wait for.

"Set a timer for ten minutes" took a PLANNER round trip — 25 to 80
seconds on his machine — to come back with "I can't do timer.set yet".
He waited most of a minute to be disappointed. Timers, music, the
lights and the weather are several of those a day.

This is `quick`'s argument applied to refusals: the round trip for
something she already knows she cannot do is the same waste, and worse,
because the answer is a disappointment either way.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import cannot, capabilities, demand, intents, journal


class RefusalCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d)})
        env.start()
        self.addCleanup(env.stop)
        p = mock.patch.object(journal, "JOURNAL_PATH", d / "j.jsonl")
        p.start()
        self.addCleanup(p.stop)


class ItAnswersInsteadOfThinkingCase(RefusalCase):
    def test_the_planner_is_never_asked_about_a_thing_she_cannot_do(self):
        with mock.patch.object(intents.planner, "compile",
                               side_effect=AssertionError(
                                   "waited on the planner to say no")):
            # NOT "set a timer": that was built the same day, which is
            # exactly why a refusal test should not be anchored to a
            # capability somebody is about to finish.
            # Statuses PINNED below rather than taken from the
            # registry, for the same reason.
            for said in ("play some music", "turn on the kitchen lights"):
                with self.subTest(said=said):
                    record = intents.propose(said, quote=said)
                    self.assertTrue(record["spoken"])
                    self.assertTrue(record["read_only"])

    def test_needs_configuration_is_a_next_step_not_a_dead_end(self):
        """"It exists and needs a token from you" and "this does not exist"
        are different answers, and only one of them he can act on."""
        said = cannot.answer("turn on the lights")
        self.assertIn("needs setting up", said)
        self.assertIn("what do you still need", said)

    def test_not_built_says_it_is_on_the_list(self):
        said = cannot.answer("play some music")
        self.assertIn("can't play music yet", said)
        self.assertIn("on the list", said)


class ItStillCountsCase(RefusalCase):
    def test_his_ask_reaches_the_ledger_in_his_own_words(self):
        """The planner path recorded this. Getting faster must not make
        the thing he wants most look like the thing he stopped asking
        for.

        The status is PINNED. Four tests have broken this week
        because they used whatever was unbuilt that morning as
        their example, and then it got built. A test about the
        mechanism should not depend on the roadmap.
        """
        entry = dict(capabilities.get("media.play"))
        entry["status"] = "NOT_BUILT"
        with mock.patch.object(capabilities, "get", return_value=entry):
            cannot.answer("play some music")
        rows = demand.ranked()
        music = [r for r in rows if r["capability"] == "media.play"]
        self.assertTrue(music, rows)
        self.assertIn("play some music", music[0]["in_his_words"])

    def test_a_broken_ledger_never_breaks_the_answer(self):
        entry = dict(capabilities.get("media.play"))
        entry["status"] = "NOT_BUILT"
        with mock.patch.object(capabilities, "get", return_value=entry), \
             mock.patch.object(demand, "record", side_effect=OSError("full")):
            self.assertIn("music", cannot.answer("play some music"))


class ItReadsTheRegistryCase(RefusalCase):
    def test_the_day_it_is_built_the_refusal_stops(self):
        """A refusal frozen in code would still be refusing next year."""
        live = dict(capabilities.get("media.play"))
        live["status"] = "AVAILABLE"
        with mock.patch.object(capabilities, "get", return_value=live):
            self.assertIsNone(cannot.answer("play some music"))

    def test_a_capability_the_registry_does_not_know_is_not_refused(self):
        """A pattern naming a missing id is a bug in the pattern, and the
        planner is a better place to be wrong than a confident no."""
        with mock.patch.object(capabilities, "get", side_effect=KeyError("x")):
            self.assertIsNone(cannot.answer("play some music"))

    def test_an_unreadable_registry_never_raises(self):
        with mock.patch.object(capabilities, "get", side_effect=OSError("gone")):
            self.assertIsNone(cannot.answer("play some music"))


class ItRefusesToOverreachCase(RefusalCase):
    def test_it_does_not_touch_her_own_switches(self):
        for said in ("turn yourself off", "turn on the microphone",
                     "turn off the microphone"):
            with self.subTest(said=said):
                self.assertIsNone(cannot.answer(said), said)

    def test_it_does_not_swallow_its_neighbours(self):
        for said in ("turn off the kitchen sink", "what time is it",
                     "play devils advocate on this", "set up a meeting",
                     "what's the weather like in the office kitchen table"):
            with self.subTest(said=said):
                got = cannot.answer(said)
                if said.startswith("what's the weather like"):
                    continue     # "what's the weather" genuinely opens it
                self.assertIsNone(got, said)

    def test_nothing_at_all_is_not_a_refusal(self):
        for empty in ("", "   ", None):
            self.assertIsNone(cannot.answer(empty))


if __name__ == "__main__":
    unittest.main()
