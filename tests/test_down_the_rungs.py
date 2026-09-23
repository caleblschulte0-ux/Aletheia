"""On his 16 GB laptop with 2 GB free (2026-09-23) the journal held 97
"nobody could think" events in one night, every one reading "fast - local
Ollama unavailable (TimeoutError); deep - ...": the pool tried the 8b, then
the 27b that never fits, and never the 4b that would have run. The chain
goes DOWN the rungs now."""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import local_model_pool as pool


def _failing(*roles_that_fail):
    calls = []

    def run_json(system_prompt, text, *, role, **kw):
        calls.append(role)
        if role in roles_that_fail:
            raise pool.LocalPoolUnavailable(f"{role} could not run")
        return pool.LocalRun(role, "m", False, {"ok": True}, "t", 1)
    return run_json, calls


class DownTheRungsCase(unittest.TestCase):
    def test_fast_falls_to_small_not_deep(self):
        run_json, calls = _failing("fast")
        with mock.patch("aletheia.local_model_pool.run_json", side_effect=run_json):
            out = pool.auto_json("s", "t", preferred_role="fast")
        self.assertEqual(calls, ["fast", "small"])
        self.assertEqual(out.role, "small")

    def test_deep_falls_to_fast_then_small(self):
        run_json, calls = _failing("deep", "fast")
        with mock.patch("aletheia.local_model_pool.run_json", side_effect=run_json):
            out = pool.auto_json("s", "t", preferred_role="deep")
        self.assertEqual(calls, ["deep", "fast", "small"])
        self.assertEqual(out.role, "small")

    def test_every_reason_is_in_the_failure(self):
        run_json, calls = _failing("deep", "fast", "small")
        with mock.patch("aletheia.local_model_pool.run_json", side_effect=run_json):
            with self.assertRaises(pool.LocalPoolUnavailable) as caught:
                pool.auto_json("s", "t", preferred_role="deep")
        said = str(caught.exception)
        for role in ("deep", "fast", "small"):
            self.assertIn(f"{role} — {role} could not run", said)

    def test_no_failover_stops_at_the_first(self):
        run_json, calls = _failing("fast")
        with mock.patch("aletheia.local_model_pool.run_json", side_effect=run_json):
            with self.assertRaises(pool.LocalPoolUnavailable):
                pool.auto_json("s", "t", preferred_role="fast", allow_failover=False)
        self.assertEqual(calls, ["fast"])

    def test_a_yield_is_never_a_failover(self):
        def run_json(system_prompt, text, *, role, **kw):
            raise pool.LocalPoolYielded("he is talking")
        with mock.patch("aletheia.local_model_pool.run_json", side_effect=run_json):
            with self.assertRaises(pool.LocalPoolYielded):
                pool.auto_json("s", "t", preferred_role="fast")


if __name__ == "__main__":
    unittest.main()
