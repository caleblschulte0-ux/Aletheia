"""Measured on his PC, 2026-09-23: with the frontier "available" but answering
nothing, every background local run died at ~15 s - the leftover of a
frontier-shaped budget after Claude and the ChatGPT browser had spent it -
while the same runs answered in 145-511 s earlier in the night. The last
rung of background work gets the background ceiling, whatever the frontier
spent first."""
from __future__ import annotations

import time
import unittest
from unittest import mock

from aletheia import local_model_pool, reasoning_gateway
from aletheia.work_states import ATTENDED, BACKGROUND


class TheLastRungCase(unittest.TestCase):
    def _run(self, attention, spend_s):
        seen = {}

        def slow_frontier(*a, **kw):
            # The frontier eats most of the budget and then fails.
            reasoning_gateway_started = kw.get("timeout_s")
            del reasoning_gateway_started
            time.sleep(0)
            raise reasoning_gateway.reasoner.ReasonerUnavailable("neither Claude nor the ChatGPT browser could answer")

        def fake_auto(system, text, **kwargs):
            seen.update(kwargs)
            raise local_model_pool.LocalPoolUnavailable("not today")

        with mock.patch.object(reasoning_gateway.model_pool_config, "enabled", return_value=True), \
             mock.patch.object(reasoning_gateway.local_model_pool, "reachable", return_value=True), \
             mock.patch.object(reasoning_gateway, "frontier_available", return_value=True), \
             mock.patch.object(reasoning_gateway, "_subscription_json", side_effect=slow_frontier), \
             mock.patch.object(reasoning_gateway.local_model_pool, "auto_json", side_effect=fake_auto), \
             mock.patch.object(reasoning_gateway.time, "monotonic",
                               side_effect=[0.0, 0.0, spend_s, spend_s, spend_s, spend_s, spend_s, spend_s, spend_s, spend_s]):
            with self.assertRaises(reasoning_gateway.reasoner.ReasonerUnavailable):
                reasoning_gateway.reason_json("s", "t", policy="standard", attention=attention,
                                              timeout_s=180.0)
        return seen

    def test_background_gets_the_ceiling_after_the_frontier_spent_the_budget(self):
        seen = self._run(BACKGROUND, spend_s=165.0)
        self.assertAlmostEqual(seen["timeout_s"], reasoning_gateway.local_ceiling_s(BACKGROUND), delta=1.0)
        self.assertEqual(seen["attention"], BACKGROUND)

    def test_attended_still_gets_only_what_is_left(self):
        seen = self._run(ATTENDED, spend_s=165.0)
        self.assertLessEqual(seen["timeout_s"], 16.0)


if __name__ == "__main__":
    unittest.main()
