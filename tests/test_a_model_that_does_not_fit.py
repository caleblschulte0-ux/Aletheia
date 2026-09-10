"""A 17.8 GB model on a 16 GB laptop, reported as ready.

CLAUDE.md names this defect by name: *"INSTALLED is not WORKING, and a
readiness check that confuses them is the worst kind of lie — it is wrong
precisely where he is trusting it."* `browse.available()` returned True
from an import and a file on disk and reported a browser that could not
load a single page. This is the same shape, one lane over.

`local_model_pool.reachable()` returns True when Ollama answers
`/api/tags`. That proves Ollama is running. It says nothing about the
model, and the `deep` role resolves by default to `qwen3.6:27b` — 17.8 GB
on a machine with 16 GB of RAM, integrated graphics and no discrete GPU.
Anything `choose_role` sends to "deep" loads it: a question containing
"debug", "root cause", "architecture", "review the code", or simply
longer than 1,200 characters.

Measured live 2026-09-09 while it was resident:

    commit charge   32,329 MB of a 32,841 MB limit   (98.4%)
    free physical    1,026 MB of 16,176 MB
    sum of every process working set    4,156 MB

At that point Windows starts killing things. What it killed was this
repository's own test suite, mid-run.

So the check exists now, it runs BEFORE the model is loaded rather than
after, and it fails over to a role that fits — which is the honest
outcome: he has a Claude subscription and one laptop.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import local_model_pool as pool
from aletheia import machine

GB = 1024 ** 3


class WhatTheMachineHasCase(unittest.TestCase):
    def test_it_asks_rather_than_assuming(self):
        found = machine.memory()
        self.assertGreater(found["total"], 0)
        self.assertLessEqual(found["available"], found["total"])
        self.assertTrue(0 <= found["load_percent"] <= 100)

    def test_headroom_is_left_for_everything_he_has_open(self):
        self.assertEqual(machine.usable_for_a_model(),
                         machine.memory()["total"] - machine.RESERVE_BYTES)

    def test_a_model_bigger_than_the_machine_does_not_fit(self):
        with mock.patch.object(machine, "memory",
                               lambda: {"total": 16 * GB, "available": 10 * GB,
                                        "load_percent": 35}):
            self.assertFalse(machine.room_for(17 * GB)["fits"])
            self.assertTrue(machine.room_for(5 * GB)["fits"])

    def test_the_verdict_carries_the_arithmetic(self):
        """"It does not fit" is an assertion he cannot check."""
        with mock.patch.object(machine, "memory",
                               lambda: {"total": 16 * GB, "available": 10 * GB,
                                        "load_percent": 35}):
            verdict = machine.room_for(17 * GB)
        self.assertGreater(verdict["needed"], 17 * GB, "no overhead counted")
        self.assertEqual(verdict["total"], 16 * GB)
        self.assertTrue(verdict["known"])

    def test_a_machine_that_will_not_say_fails_open(self):
        """Ignorance is not evidence that the model is too big."""
        with mock.patch.object(machine, "memory",
                               side_effect=machine.UnknownMachine("no")):
            verdict = machine.room_for(900 * GB)
        self.assertTrue(verdict["fits"])
        self.assertFalse(verdict["known"])
        self.assertIn("no", verdict["why"])

    def test_the_refusal_is_a_sentence(self):
        with mock.patch.object(machine, "memory",
                               lambda: {"total": 16 * GB, "available": 10 * GB,
                                        "load_percent": 35}):
            said = machine.why_it_does_not_fit("qwen3.6:27b",
                                               machine.room_for(17 * GB))
        self.assertIn("qwen3.6:27b", said)
        self.assertIn("GB", said)
        self.assertNotIn("17179869184", said, "a byte count, read out loud")
        self.assertNotIn("_", said, "an identifier in a spoken sentence")

    def test_sizes_are_said_the_way_he_would(self):
        self.assertEqual(machine.gigabytes(16 * GB), "16 GB")
        self.assertEqual(machine.gigabytes(5 * GB + GB // 2), "5.5 GB")
        self.assertEqual(machine.gigabytes(500 * 1024 * 1024), "500 MB")


class TheModelIsRefusedBeforeItLoadsCase(unittest.TestCase):
    def _machine(self, total_gb):
        return mock.patch.object(
            machine, "memory",
            lambda: {"total": total_gb * GB, "available": 10 * GB,
                     "load_percent": 35})

    def _sizes(self, **by_name):
        return mock.patch.object(pool, "installed_sizes", lambda **k: by_name)

    def test_a_role_whose_model_is_too_big_is_refused(self):
        with self._machine(16), self._sizes(**{"qwen3.6:27b": 17 * GB}), \
             mock.patch.object(pool.model_pool_config, "resolve",
                               lambda role: {"model": "qwen3.6:27b"}):
            verdict = pool.room_for_role("deep")
        self.assertFalse(verdict["fits"])
        self.assertIn("qwen3.6:27b", verdict["why"])

    def test_a_role_that_fits_is_not_refused(self):
        with self._machine(16), self._sizes(**{"qwen3:8b": 5 * GB}), \
             mock.patch.object(pool.model_pool_config, "resolve",
                               lambda role: {"model": "qwen3:8b"}):
            self.assertTrue(pool.room_for_role("fast")["fits"])

    def test_a_model_that_is_not_installed_is_ollamas_error_not_ours(self):
        """A memory refusal wearing someone else's coat helps nobody."""
        with self._machine(16), self._sizes(), \
             mock.patch.object(pool.model_pool_config, "resolve",
                               lambda role: {"model": "never-pulled"}):
            verdict = pool.room_for_role("fast")
        self.assertTrue(verdict["fits"])
        self.assertFalse(verdict["known"])

    def test_run_json_stops_before_the_model_is_loaded(self):
        """The point of the whole exercise: not slower, not loaded."""
        loaded = []
        with self._machine(16), self._sizes(**{"big": 17 * GB}), \
             mock.patch.object(pool.model_pool_config, "resolve",
                               lambda role: {"model": "big", "think": False}), \
             mock.patch.object(pool.model_pool_config, "enabled", lambda: True), \
             mock.patch.object(pool.local_brain, "infer_json",
                               lambda *a, **k: loaded.append(1)):
            with self.assertRaises(pool.LocalPoolUnavailable):
                pool.run_json("system", "debug this root cause", role="deep")
        self.assertEqual(loaded, [], "the model was loaded anyway")

    def test_ollama_being_unreachable_does_not_refuse_everything(self):
        """`installed_sizes` must never turn a quiet Ollama into a ban.

        Stubbed, not live. The first version of this test called the real
        `/api/tags` and passed or failed depending on whether HIS Ollama
        happened to be running — the live-network test CLAUDE.md warns
        about, written into the file whose whole subject is checking
        things properly.
        """
        import urllib.request
        with mock.patch.object(pool, "_SIZES", {"at": 0.0, "by_name": {}}), \
             mock.patch.object(urllib.request, "urlopen",
                               side_effect=OSError("nothing listening")):
            self.assertEqual(pool.installed_sizes(now=1.0), {})

    def test_a_quiet_ollama_leaves_every_role_runnable(self):
        """Fails OPEN, all the way up: no sizes means no refusal."""
        with self._machine(16), self._sizes():
            for role in ("fast", "deep"):
                with self.subTest(role=role):
                    self.assertTrue(pool.room_for_role(role)["fits"])


class BothReasonsSurviveCase(unittest.TestCase):
    def test_a_double_failure_says_why_twice(self):
        """"Both local reasoning roles are unavailable" told him nothing.

        The two halves usually fail for different reasons — one model too
        big for the machine, the other Ollama not running — and those have
        different fixes.
        """
        def refuse(*a, **kw):
            raise pool.LocalPoolUnavailable(
                f"{kw.get('role')} says no because reason-{kw.get('role')}")

        with mock.patch.object(pool, "run_json", refuse):
            with self.assertRaises(pool.LocalPoolUnavailable) as caught:
                pool.auto_json("system", "hello")
        said = str(caught.exception)
        self.assertIn("reason-fast", said)
        self.assertIn("reason-deep", said)


class TheAuditSaysItCase(unittest.TestCase):
    """Stub the verifiers, keep the aggregation under test.

    The audit's own promise is "checked live rather than assumed", which
    is exactly why its TESTS must not be: a suite that answers differently
    depending on whether Ollama happens to be up is a suite nobody trusts
    on a train.
    """

    def _audit(self, *, cramped):
        from aletheia import reasoning_gateway, setup
        answering = {"local": {"enabled": True,
                               "profiles": {"fast": {"online": True},
                                            "deep": {"online": True}}}}
        rooms = {"fast": {"fits": True, "why": "", "model": "small"},
                 "deep": {"fits": True, "why": "", "model": "small"}}
        for role in cramped:
            rooms[role] = {"fits": False, "model": "huge",
                           "why": "huge needs about 19 GB and this machine "
                                  "has 16 GB in total."}
        with mock.patch.object(reasoning_gateway, "status", lambda: answering), \
             mock.patch.object(pool, "room_for_role", lambda role: rooms[role]):
            return setup._local_ai()

    def test_a_lane_that_mostly_works_is_not_shouted_at(self):
        """An audit that cries BROKEN gets read as noise by the next one."""
        from aletheia import setup
        state, why = self._audit(cramped=["deep"])
        self.assertEqual(state, setup.OK)
        self.assertIn("19 GB", why)
        self.assertIn("smaller model", why, "no fix in the sentence")

    def test_a_lane_where_nothing_fits_is_broken(self):
        from aletheia import setup
        state, why = self._audit(cramped=["fast", "deep"])
        self.assertEqual(state, setup.BROKEN)
        self.assertIn("19 GB", why)

    def test_a_lane_that_fits_says_so_without_hedging(self):
        from aletheia import setup
        state, why = self._audit(cramped=[])
        self.assertEqual(state, setup.OK)
        self.assertNotIn("needs about", why)

    def test_a_broken_room_check_never_breaks_the_audit(self):
        """A check that cannot run is not a finding about the model."""
        from aletheia import reasoning_gateway, setup
        answering = {"local": {"enabled": True,
                               "profiles": {"fast": {"online": True}}}}
        with mock.patch.object(reasoning_gateway, "status", lambda: answering), \
             mock.patch.object(pool, "room_for_role",
                               side_effect=RuntimeError("boom")):
            state, _why = setup._local_ai()
        self.assertEqual(state, setup.OK)


if __name__ == "__main__":
    unittest.main()
