"""Production boundaries for Aletheia's hybrid local/subscription reasoning."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from aletheia import (
    local_brain, local_model_pool, model_pool_config, reasoner,
    reasoning_gateway, training_data,
)


class PrivateStateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {
            "ALETHEIA_PRIVATE_STATE": self.tmp.name,
            "ALETHEIA_TRAINING_CAPTURE": "1",
        }, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_default_roles_match_installed_staging_plan_and_are_swappable(self):
        self.assertEqual(model_pool_config.resolve("fast")["model"], "qwen3:8b")
        self.assertEqual(model_pool_config.resolve("deep")["model"], "qwen3.6:27b")
        model_pool_config.save("fast", model="future-fast:latest", think=False)
        self.assertEqual(model_pool_config.resolve("fast")["model"], "future-fast:latest")
        self.assertTrue(str(model_pool_config.config_path()).startswith(self.tmp.name))

    def test_training_store_redacts_secret_keys_and_known_token_shapes(self):
        turn = training_data.record_turn(
            provider="teacher", model="x", role="teacher",
            text="use sk-abcdefghijklmnopqrstuvwxyz123456 safely",
            context={"password": "hunter2", "nested": {"api_key": "abc"}},
            request_payload={"authorization": "Bearer secret"},
            result={"summary": "github_pat_abcdefghijklmnopqrstuvwxyz123456"},
            status="teacher_validated",
        )
        self.assertIsNotNone(turn)
        rows = training_data.iter_events()
        raw = json.dumps(rows)
        self.assertNotIn("hunter2", raw)
        self.assertNotIn("Bearer secret", raw)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz123456", raw)
        self.assertIn("REDACTED_SECRET", raw)


class LocalTransportCase(unittest.TestCase):
    def test_remote_ollama_endpoint_is_refused(self):
        with self.assertRaises(ValueError):
            local_brain.OllamaConfig(model="x", base_url="https://example.com").validated()
        with self.assertRaises(ValueError):
            local_brain.OllamaConfig(model="x", base_url="http://10.0.0.4:11434").validated()

    def test_loopback_endpoint_is_allowed(self):
        cfg = local_brain.OllamaConfig(model="x", base_url="http://127.0.0.1:11434")
        self.assertIs(cfg.validated(), cfg)


class GatewayRoutingCase(unittest.TestCase):
    def local_run(self, summary="local", role="fast"):
        return local_model_pool.LocalRun(
            role=role, model="local-model", think=(role == "deep"),
            output={"summary": summary}, turn_id="abc123", duration_ms=1,
        )

    def test_routine_is_local_first(self):
        with mock.patch.object(local_model_pool, "auto_json", return_value=self.local_run()) as local, \
             mock.patch.object(reasoner, "subscription_json", side_effect=AssertionError("cloud should not run")):
            result = reasoning_gateway.reason_json("sys", "simple", policy="routine")
        self.assertEqual(result.output["summary"], "local")
        self.assertTrue(result.provider.startswith("ollama:"))
        local.assert_called_once()
        self.assertNotIn("preferred_role", local.call_args.kwargs)

    def test_standard_is_subscription_first(self):
        with mock.patch.object(reasoner, "subscription_json", return_value={"summary": "teacher"}) as sub, \
             mock.patch.object(local_model_pool, "auto_json", side_effect=AssertionError("local fallback should not run")):
            result = reasoning_gateway.reason_json("sys", "normal", policy="standard")
        self.assertEqual(result.output["summary"], "teacher")
        self.assertEqual(result.provider, "subscription.auto")
        sub.assert_called_once()

    def test_standard_uses_local_deep_when_both_subscriptions_are_down(self):
        with mock.patch.object(reasoner, "subscription_json", side_effect=reasoner.ReasonerUnavailable("down")), \
             mock.patch.object(local_model_pool, "auto_json", return_value=self.local_run("offline", "deep")) as local:
            result = reasoning_gateway.reason_json("sys", "normal", policy="standard")
        self.assertEqual(result.output["summary"], "offline")
        self.assertEqual(result.local_role, "deep")
        self.assertIn("subscriptions unavailable", result.degraded)
        self.assertEqual(local.call_args.kwargs["preferred_role"], "deep")

    def test_critical_never_downgrades_to_local_answer(self):
        with mock.patch.object(reasoner, "subscription_json", side_effect=reasoner.ReasonerUnavailable("down")), \
             mock.patch.object(local_model_pool, "auto_json") as local:
            with self.assertRaises(reasoner.ReasonerUnavailable):
                reasoning_gateway.reason_json("sys", "production code", policy="critical")
        local.assert_not_called()

    def test_fast_compat_adapter_uses_routine_local_first_policy(self):
        fake = reasoning_gateway.GatewayResult(
            output={"intent": "answer", "summary": "ok"},
            provider="ollama:fast", policy="routine",
        )
        with mock.patch.object(reasoning_gateway, "reason_json", return_value=fake) as route:
            result = reasoner.CliReasoner(system_prompt="sys").infer("hello")
        self.assertEqual(result["summary"], "ok")
        self.assertEqual(route.call_args.kwargs["policy"], "routine")

    def test_deep_planner_adapter_remains_subscription_first_standard(self):
        fake = reasoning_gateway.GatewayResult(
            output={"intent": "plan", "summary": "ok"},
            provider="subscription.auto", policy="standard",
        )
        with mock.patch.object(reasoning_gateway, "reason_json", return_value=fake) as route:
            result = reasoner.CliReasoner(
                model=reasoner.PLAN_MODEL, system_prompt="sys"
            ).infer("plan this")
        self.assertEqual(result["summary"], "ok")
        self.assertEqual(route.call_args.kwargs["policy"], "standard")


class ShadowCase(unittest.TestCase):
    def test_subscription_answer_is_returned_unchanged_while_shadow_is_scheduled(self):
        teacher = {"summary": "strong answer"}
        with mock.patch.object(reasoner, "_subscription_json_with_provider",
                               return_value=(teacher, "claude.cli:sonnet")), \
             mock.patch.object(reasoner, "_schedule_local_shadow") as shadow:
            out = reasoner.subscription_json("sys", "task")
        self.assertIs(out, teacher)
        shadow.assert_called_once()
        self.assertIs(shadow.call_args.args[4], teacher)


if __name__ == "__main__":
    unittest.main()
