"""The rung under the fast model.

His words, 2026-09-22: it "really needs to be able to handle a lot when
there's no frontier model available." That night 4 GB was free, the fast
model wanted 6, and there was nothing beneath it: her own model loaded into
a starved machine and timed out. "Never make a fallback that only tries one
model" (CLAUDE.md), so the pool has a `small` role now, fetched once by her
own self-healing, and one function says which of her models may be asked.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import local_model_pool, local_planner, model_pool_config, reasoner

GB = 1024 ** 3


class WhichOfHerModelsMayBeAskedCase(unittest.TestCase):
    def room(self, free, *, installed=None, held=0, reachable=True):
        return [
            mock.patch("aletheia.model_pool_config.enabled", return_value=True),
            mock.patch.object(reasoner, "_free_memory_bytes", return_value=free),
            mock.patch.object(reasoner, "_ollama_holds_bytes", return_value=held),
            mock.patch.object(local_model_pool, "reachable", return_value=reachable),
            mock.patch.object(local_model_pool, "installed_sizes",
                              return_value=installed if installed is not None else {"qwen3:8b": 5 * GB}),
        ]

    def picked(self, free, **kw):
        patches = self.room(free, **kw)
        for p in patches:
            p.start()
        try:
            return reasoner.local_role_that_fits()
        finally:
            for p in patches:
                p.stop()

    def test_with_room_the_fast_model_is_the_answer(self):
        self.assertEqual(self.picked(8 * GB)[0], "fast")

    def test_memory_ollama_already_holds_counts(self):
        # the second ask of a batch: the model's own gigabytes are not "used"
        self.assertEqual(self.picked(2 * GB, held=5 * GB)[0], "fast")

    def test_with_room_for_only_the_small_model_it_is_the_answer(self):
        role, why = self.picked(4 * GB, installed={"qwen3:8b": 5 * GB, "qwen3:4b": int(2.6 * GB)})
        self.assertEqual(role, "small")
        self.assertIn("smaller", why)

    def test_the_small_model_not_on_disk_is_named_in_the_no(self):
        role, why = self.picked(4 * GB)
        self.assertIsNone(role)
        self.assertIn("qwen3:4b", why)
        self.assertIn("not on this machine yet", why)

    def test_too_little_for_either_is_a_plain_no(self):
        role, why = self.picked(2 * GB, installed={"qwen3:8b": 5 * GB, "qwen3:4b": int(2.6 * GB)})
        self.assertIsNone(role)
        self.assertIn("2.0 GB", why)

    def test_not_running_is_a_no_whatever_the_room(self):
        role, why = self.picked(8 * GB, reachable=False)
        self.assertIsNone(role)
        self.assertIn("not running", why)

    def test_local_allowed_is_the_same_answer_as_a_yes_or_no(self):
        with mock.patch.object(reasoner, "local_role_that_fits", return_value=("small", "why")):
            self.assertEqual(reasoner.local_allowed(), (True, "why"))
        with mock.patch.object(reasoner, "local_role_that_fits", return_value=(None, "no")):
            self.assertEqual(reasoner.local_allowed(), (False, "no"))


class TheRoleIsAFirstClassRoleCase(unittest.TestCase):
    def test_the_pool_resolves_it_and_the_show_lists_it(self):
        self.assertEqual(model_pool_config.resolve("small")["model"], "qwen3:4b")
        self.assertIn("small", model_pool_config.ROLES)
        with mock.patch.object(model_pool_config, "_saved", return_value={}):
            self.assertIn("small", model_pool_config.show())

    def test_the_pool_runs_it(self):
        run = local_model_pool.LocalRun("small", "qwen3:4b", False, {"ok": True}, None, 1)
        with mock.patch.object(local_model_pool, "run_json", return_value=run) as ran:
            out = local_model_pool.auto_json("s", "t", preferred_role="small", allow_failover=False)
        self.assertEqual(out.role, "small")
        self.assertEqual(ran.call_args.kwargs["role"], "small")

    def test_an_unknown_role_is_still_refused(self):
        with self.assertRaises(ValueError):
            local_model_pool.run_json("s", "t", role="huge")


class ThePlannerTriesTheOneWithRoomFirstCase(unittest.TestCase):
    def test_the_role_with_room_goes_first_and_deep_last(self):
        with mock.patch.object(reasoner, "local_role_that_fits", return_value=("small", "")):
            self.assertEqual(local_planner.local_roles_in_order(), ("small", "fast", "deep"))
        with mock.patch.object(reasoner, "local_role_that_fits", return_value=("fast", "")):
            self.assertEqual(local_planner.local_roles_in_order(), ("fast", "small", "deep"))

    def test_nothing_fitting_still_tries_them_all_fast_first(self):
        with mock.patch.object(reasoner, "local_role_that_fits", return_value=(None, "no room")):
            self.assertEqual(local_planner.local_roles_in_order(), ("fast", "small", "deep"))

    def test_a_check_that_explodes_does_not_stop_the_planner(self):
        with mock.patch.object(reasoner, "local_role_that_fits", side_effect=RuntimeError("x")):
            self.assertEqual(local_planner.local_roles_in_order(), ("fast", "small", "deep"))


if __name__ == "__main__":
    unittest.main()
