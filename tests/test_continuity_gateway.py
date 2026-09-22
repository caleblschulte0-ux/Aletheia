"""The gateway's continuity seams, and the browser deciding locally first."""
import os
import unittest
from unittest import mock

from aletheia import (browser_loop, local_model_pool, model_pool_config, page_state as ps,
                      reasoner, reasoning_gateway as gw)


def page():
    return {"url": "https://clinic.example", "title": "Clinic", "state": ps.CONTENT,
            "text": "Welcome to the clinic. Book a checkup online.",
            "targets": [{"id": "t1", "role": "link", "label": "Our services"},
                        {"id": "t2", "role": "link", "label": "Book an appointment"},
                        {"id": "t3", "role": "button", "label": "Sign in"}]}


class FrontierOff(unittest.TestCase):
    def test_the_switch_refuses_every_frontier_rung(self):
        with mock.patch.dict(os.environ, {gw.FRONTIER_OFF_ENV: "1"}), \
                mock.patch.object(reasoner, "subscription_json") as sub, \
                mock.patch.object(reasoner, "_subscription_json_with_provider") as subp:
            self.assertTrue(gw.frontier_off())
            self.assertFalse(gw.frontier_available())
            with self.assertRaises(reasoner.ReasonerUnavailable):
                gw.frontier_json("s", "t")
            with self.assertRaises(reasoner.ReasonerUnavailable):
                gw.reason_json("s", "t", policy="critical")
        sub.assert_not_called()
        subp.assert_not_called()

    def test_standard_falls_to_her_own_model_when_frontier_is_off(self):
        run = local_model_pool.LocalRun("fast", "qwen3:8b", False, {"a": 1}, None, 5)
        with mock.patch.dict(os.environ, {gw.FRONTIER_OFF_ENV: "1"}), \
                mock.patch.object(model_pool_config, "enabled", return_value=True), \
                mock.patch.object(local_model_pool, "reachable", return_value=True), \
                mock.patch.object(local_model_pool, "auto_json", return_value=run):
            result = gw.reason_json("s", "t", policy="standard")
        self.assertEqual(result.provider, "ollama:qwen3:8b")
        self.assertIn("subscriptions unavailable", result.degraded)

    def test_off_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(gw.FRONTIER_OFF_ENV, None)
            self.assertFalse(gw.frontier_off())

    def test_a_resting_claude_is_not_available(self):
        import datetime as dt
        with mock.patch.object(reasoner, "resting_until",
                               return_value=dt.datetime.now(dt.timezone.utc)):
            self.assertFalse(gw.frontier_available())


class TheThinkerAsksForAClass(unittest.TestCase):
    def test_it_passes_the_policy_and_the_old_seams_arguments(self):
        seen = {}

        def fake(system, text, **kw):
            seen.update(kw)
            return gw.GatewayResult({"ok": True}, "p", kw["policy"])
        with mock.patch.object(gw, "reason_json", side_effect=fake):
            out = gw.thinker("routine")("s", "t", model="haiku", validator=None, context={"x": 1})
        self.assertEqual(out, {"ok": True})
        self.assertEqual(seen["policy"], "routine")
        self.assertEqual(seen["context"], {"x": 1})

    def test_the_seam_carries_attention_and_a_work_budget(self):
        # research said BACKGROUND through this seam and the word was dropped
        # (2026-09-22): her own model got the attended 300 s and the report
        # died at 299.8 s beside a running batch.
        seen = {}
        def fake(system, text, **kw):
            seen.update(kw)
            return gw.GatewayResult({"ok": True}, "p", kw["policy"])
        with mock.patch.object(gw, "reason_json", side_effect=fake):
            gw.thinker("standard", attention=gw.BACKGROUND)("s", "t", validator=None)
        self.assertEqual(seen["attention"], gw.BACKGROUND)

    def test_an_unknown_class_is_refused(self):
        with self.assertRaises(ValueError):
            gw.thinker("whatever")

    def test_the_local_slice_is_bounded_by_the_routine_total(self):
        self.assertEqual(gw._local_slice(None), gw.ROUTINE_LOCAL_TIMEOUT_S)
        self.assertEqual(gw._local_slice(1e9), gw.ROUTINE_TOTAL_TIMEOUT_S)
        self.assertEqual(gw._local_slice(0), 0.5)


class TheBrowserDecidesLocallyFirst(unittest.TestCase):
    def test_the_default_decider_is_the_gateway(self):
        self.assertIs(browser_loop.model_decider(), browser_loop.gateway_decide)

    def test_the_compact_prompt_has_no_selectors_and_is_small(self):
        p = page()
        p["targets"] = p["targets"] * 30
        text = browser_loop.compact_page("book a checkup", p, [{"did": "followed 'Home'"}])
        self.assertIn("of 90 targets shown", text, "the model is told the page holds more")
        self.assertLess(len(text), 3500)
        self.assertIn("GOAL: book a checkup", text)

    def test_a_sure_local_answer_is_taken_without_escalating(self):
        calls = []

        def fake(system, text, **kw):
            calls.append(kw["policy"])
            validated = kw["validator"]({"target": "t2", "sure": True})
            return gw.GatewayResult(validated, "ollama:qwen3:8b", kw["policy"])
        with mock.patch.object(gw, "reason_json", side_effect=fake):
            said = browser_loop.gateway_decide("book a checkup", page(), [])
        self.assertEqual(said["target"], "t2")
        self.assertEqual(said["class"], "routine")
        self.assertEqual(calls, ["routine"])

    def test_an_unsure_answer_escalates_to_standard(self):
        calls = []

        def fake(system, text, **kw):
            calls.append(kw["policy"])
            if kw["policy"] == "routine":
                return gw.GatewayResult(kw["validator"]({"target": None, "sure": False}),
                                        "ollama:qwen3:8b", "routine")
            return gw.GatewayResult(kw["validator"]({"target": "t2"}), "subscription.auto", "standard")
        with mock.patch.object(gw, "reason_json", side_effect=fake), \
                mock.patch.object(gw, "frontier_available", return_value=True):
            said = browser_loop.gateway_decide("book a checkup", page(), [])
        self.assertEqual(calls, ["routine", "standard"])
        self.assertEqual(said["target"], "t2")
        self.assertTrue(said["escalated"])

    def test_no_escalation_when_nobody_stronger_could_answer(self):
        calls = []

        def fake(system, text, **kw):
            calls.append(kw["policy"])
            return gw.GatewayResult(kw["validator"]({"target": None, "sure": False}),
                                    "ollama:qwen3:8b", "routine")
        with mock.patch.object(gw, "reason_json", side_effect=fake), \
                mock.patch.object(gw, "frontier_available", return_value=False):
            said = browser_loop.gateway_decide("book a checkup", page(), [])
        self.assertEqual(calls, ["routine"])
        self.assertIsNone(said["target"])

    def test_a_routine_timeout_with_nobody_stronger_gives_her_model_more_time_on_the_small_prompt(self):
        calls = []

        def fake(system, text, **kw):
            calls.append((kw["policy"], system, len(text)))
            if kw["policy"] == "routine":
                raise reasoner.ReasonerUnavailable("the local model could not either")
            return gw.GatewayResult(kw["validator"]({"target": "t2", "sure": True}), "ollama:qwen3:8b", "standard")
        with mock.patch.object(gw, "reason_json", side_effect=fake),                 mock.patch.object(gw, "frontier_available", return_value=False):
            said = browser_loop.gateway_decide("book a checkup", page(), [])
        self.assertEqual([c[0] for c in calls], ["routine", "standard"])
        self.assertIs(calls[1][1], browser_loop.DECIDE_LOCAL_SYSTEM, "the same cached system prompt")
        self.assertLessEqual(calls[1][2], browser_loop.LOCAL_PROMPT_CHARS)
        self.assertEqual(said["target"], "t2")
        self.assertEqual(said["by"], "ollama:qwen3:8b")

    def test_a_long_page_is_shown_a_chunk_at_a_time_before_anything_escalates(self):
        p = page()
        p["targets"] = [{"id": f"t{i}", "role": "link", "label": f"Category {i}"} for i in range(1, 60)]
        p["targets"].append({"id": "t60", "role": "link", "label": "Meditations"})
        seen = []

        def fake(system, text, **kw):
            seen.append(text)
            if "t60 link Meditations" in text:
                return gw.GatewayResult(kw["validator"]({"target": "t60", "sure": True}), "ollama:qwen3:8b", "routine")
            return gw.GatewayResult(kw["validator"]({"target": None, "sure": False}), "ollama:qwen3:8b", "routine")
        with mock.patch.object(gw, "reason_json", side_effect=fake),                 mock.patch.object(gw, "frontier_available", return_value=False):
            said = browser_loop.gateway_decide("find the Marcus Aurelius book", p, [])
        self.assertEqual(said["target"], "t60")
        self.assertEqual(said["chunk"], 3)
        self.assertEqual(len(seen), 3)
        self.assertTrue(all(len(t) <= browser_loop.LOCAL_PROMPT_CHARS for t in seen))

    def test_a_target_not_on_the_page_is_refused_by_the_validator(self):
        check = browser_loop._decision_validator(page())
        with self.assertRaises(ValueError):
            check({"target": "t99", "sure": True})

    def test_nobody_able_to_think_is_an_empty_decision_not_a_crash(self):
        with mock.patch.object(gw, "reason_json",
                               side_effect=reasoner.ReasonerUnavailable("nobody")):
            self.assertEqual(browser_loop.gateway_decide("go", page(), []), {})

    def test_a_committing_target_is_still_refused_whoever_picked_it(self):
        obs = {**page(), "_refs": {"t1": "#a", "t2": "#b", "t3": "#c"}}

        def fake(system, text, **kw):
            return gw.GatewayResult(kw["validator"]({"target": "t3", "sure": True}),
                                    "ollama:qwen3:8b", kw["policy"])
        with mock.patch.object(gw, "reason_json", side_effect=fake):
            self.assertIsNone(browser_loop._ask_model(browser_loop.model_decider(), "go", obs,
                                                      {"history": []}))


if __name__ == "__main__":
    unittest.main()
