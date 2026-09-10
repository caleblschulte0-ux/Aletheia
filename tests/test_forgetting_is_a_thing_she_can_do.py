"""She could forget, and could not be asked to.

    > forget my landlord
      [6.6s] 1 step ready - Forget what's remembered about your landlord.
      Approve it on your phone or at the keyboard to run it. I can't
      memory.forget yet. I've put it on the build list.

`memory.forget` has been a real function in `aletheia/memory.py` the
whole time. It had no intercom kind, no registry entry and no phrasing,
so the sentence reached the planner — which INVENTED the identifier
`memory.forget`, filed a build task for a thing that already existed, and
read the id out loud in a room.

That is three documented defects stacked on one unwired function: rule
zero (never build a capability and leave it unwired), the planner filling
a hole by inventing a capability id, and §145 saying that id aloud.

The design decisions worth holding:

- SAME TIER AS `remember`. It is the same act on the same private store,
  and it would be strange to be told something for free and need an
  approval to be told to drop it.
- IT SAYS WHAT WENT. This is the only act in the system with no undo —
  `workspace.write` keeps the version it replaced, `memory.remember`
  records what it overwrote, a reminder is disabled rather than deleted.
  "Forgotten" alone cannot be checked by ear.
- A MISS SAYS WHAT HE DOES HAVE. "I forgot it" about something she never
  held would leave him believing a fact is gone that is still there.
- "FORGET IT" IS NOT THIS. It means never mind, and already denies a
  pending approval — a different act, and the safer one to keep.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import capabilities, intercom, memory, voice


class _WithMemories(unittest.TestCase):
    def setUp(self):
        self._was = memory.MEMORY_DIR
        memory.MEMORY_DIR = Path(tempfile.mkdtemp(prefix="mem-"))
        memory.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        memory.remember("people", "landlord", "Dana Okafor", source="test")
        memory.remember("people", "plumber", "Ray", source="test")
        memory.remember("preferences", "coffee", "flat white", source="test")

    def tearDown(self):
        memory.MEMORY_DIR = self._was

    def run_forget(self, about):
        return intercom.execute_command({"kind": "forget", "about": about},
                                        {}, quote=f"forget {about}")


class TheWordsHeWouldUseCase(unittest.TestCase):
    def kind(self, said):
        return ((voice._interpret(said) or {}).get("command") or {}).get("kind")

    def test_forgetting_a_thing_is_reachable(self):
        for said in ("forget my landlord", "forget Dana",
                     "forget about my landlord",
                     "forget what you know about my landlord"):
            with self.subTest(said=said):
                self.assertEqual(self.kind(said), "forget", said)

    def test_forget_it_still_means_never_mind(self):
        """It denies what is pending. A different act, and the safer one."""
        for said in ("forget it", "forget that", "never mind"):
            with self.subTest(said=said):
                self.assertNotEqual(self.kind(said), "forget", said)

    def test_his_capitals_survive(self):
        got = (voice._interpret("forget Dana Okafor") or {})["command"]
        self.assertEqual(got["about"], "Dana Okafor")


class ItActuallyForgetsCase(_WithMemories):
    def test_it_goes_and_the_receipt_says_what_went(self):
        said = self.run_forget("my landlord")
        self.assertIn("landlord", said)
        self.assertIn("Dana Okafor", said, "no undo, so say what went")
        self.assertIsNone(memory.recall("people", "landlord"))

    def test_my_is_folded_because_it_is_stored_without_it(self):
        self.run_forget("my plumber")
        self.assertIsNone(memory.recall("people", "plumber"))

    def test_the_value_matches_as_well_as_the_key(self):
        """"Forget Dana" is as natural as "forget my landlord"."""
        self.run_forget("Dana")
        self.assertIsNone(memory.recall("people", "landlord"))

    def test_it_leaves_everything_else_alone(self):
        self.run_forget("my landlord")
        self.assertEqual(memory.recall("people", "plumber"), "Ray")
        self.assertEqual(memory.recall("preferences", "coffee"), "flat white")


class AMissIsStillAnAnswerCase(_WithMemories):
    def test_nothing_matching_says_what_he_does_have(self):
        said = self.run_forget("my accountant")
        self.assertIn("nothing remembered about my accountant", said)
        self.assertIn("landlord", said)

    def test_it_does_not_claim_to_have_forgotten_it(self):
        """Believing a fact is gone that is still there is the worst
        outcome this answer can produce."""
        said = self.run_forget("my accountant").lower()
        self.assertNotIn("forgot ", said)

    def test_an_empty_store_says_only_that(self):
        for domain in list(memory.DOMAINS):
            for key in list(memory._load(domain)):
                memory.forget(domain, key, via="test")
        said = self.run_forget("my landlord")
        self.assertIn("nothing remembered about my landlord", said)
        self.assertNotIn("What I do have", said)

    def test_two_matches_ask_which(self):
        memory.remember("people", "landlady", "Dana Smith", source="test")
        said = self.run_forget("Dana")
        self.assertIn("Which one", said)
        # and nothing was dropped while she was asking
        self.assertEqual(memory.recall("people", "landlord"), "Dana Okafor")
        self.assertEqual(memory.recall("people", "landlady"), "Dana Smith")


class ItIsWiredCase(unittest.TestCase):
    def test_the_kind_exists(self):
        self.assertIn("forget", intercom.KIND_ARGS)

    def test_it_sits_where_remember_sits(self):
        """Told for free, told to drop it for free."""
        self.assertEqual(intercom.tier("forget"), intercom.tier("remember"))

    def test_the_registry_knows_it(self):
        entry = capabilities.get("memory.forget")
        self.assertEqual(entry["status"], "AVAILABLE")
        self.assertEqual(entry["module"], "aletheia.memory")
        self.assertIn("forget", entry["caller"])

    def test_the_id_the_planner_invented_is_the_one_that_exists_now(self):
        """It guessed `memory.forget`, correctly, about a real function."""
        self.assertTrue(hasattr(memory, "forget"))


if __name__ == "__main__":
    unittest.main()
