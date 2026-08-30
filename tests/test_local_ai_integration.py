"""Production boundaries for Aletheia's hybrid local/subscription reasoning."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from aletheia import (
    local_ai, local_brain, local_model_pool, model_pool_config, reasoner,
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
        self.assertFalse(model_pool_config.enabled())
        self.assertFalse(model_pool_config.shadow_enabled())
        self.assertEqual(model_pool_config.resolve("fast")["model"], "qwen3:8b")
        self.assertEqual(model_pool_config.resolve("deep")["model"], "qwen3.6:27b")
        model_pool_config.save("fast", model="future-fast:latest", think=False)
        self.assertEqual(model_pool_config.resolve("fast")["model"], "future-fast:latest")
        self.assertTrue(str(model_pool_config.config_path()).startswith(self.tmp.name))

    def test_activation_settings_are_machine_local_and_disable_clears_shadow(self):
        model_pool_config.save_settings(enabled=True, shadow=True)
        self.assertTrue(model_pool_config.enabled())
        self.assertTrue(model_pool_config.shadow_enabled())
        model_pool_config.save_settings(enabled=False)
        self.assertFalse(model_pool_config.enabled())
        self.assertFalse(model_pool_config.shadow_enabled())

    def test_machine_local_deactivate_cannot_be_undone_by_environment(self):
        model_pool_config.save_settings(enabled=False, shadow=False)
        with mock.patch.dict(os.environ, {
            "ALETHEIA_LOCAL_AI_ENABLED": "1",
            "ALETHEIA_LOCAL_AI_SHADOW": "1",
        }):
            self.assertFalse(model_pool_config.enabled())
            self.assertFalse(model_pool_config.shadow_enabled())

    def test_training_store_redacts_secret_keys_and_known_token_shapes(self):
        turn = training_data.record_turn(
            provider="teacher", model="x", role="teacher",
            text="use sk-abcdefghijklmnopqrstuvwxyz123456 safely password: dont-store-me",
            context={"password": "hunter2", "nested": {"api_key": "abc"}},
            request_payload={"authorization": "Bearer verysecrettoken"},
            result={"summary": "github_pat_abcdefghijklmnopqrstuvwxyz123456"},
            status="teacher_validated",
        )
        self.assertIsNotNone(turn)
        rows = training_data.iter_events()
        raw = json.dumps(rows)
        for secret in ("hunter2", "dont-store-me", "Bearer verysecrettoken",
                       "abcdefghijklmnopqrstuvwxyz123456"):
            self.assertNotIn(secret, raw)
        self.assertIn("REDACTED_SECRET", raw)

    def test_teacher_pair_links_durable_teacher_and_student_turns(self):
        teacher = training_data.record_turn(
            provider="chatgpt.browser", model="chatgpt.browser", role="teacher",
            text="question", context={}, result={"summary": "teacher"},
            status="teacher_validated",
        )
        student = training_data.record_turn(
            provider="ollama", model="qwen3:8b", role="fast",
            text="question", context={}, result={"summary": "student"},
            status="validated",
        )
        pair = training_data.record_teacher_pair(
            teacher_turn_id=teacher, student_turn_id=student,
            teacher_provider="chatgpt.browser",
            teacher_result={"summary": "teacher"},
            student_result={"summary": "student"}, route="test",
        )
        self.assertIsNotNone(pair)
        pairs = [x for x in training_data.iter_events() if x.get("kind") == "teacher_pair"]
        self.assertEqual(pairs[-1]["teacher_turn_id"], teacher)
        self.assertEqual(pairs[-1]["student_turn_id"], student)

    def test_training_capture_stops_at_quota_without_deleting_old_data(self):
        with mock.patch.dict(os.environ, {"ALETHEIA_TRAINING_MAX_BYTES": "1024"}):
            old_turn = training_data.record_turn(
                provider="teacher", model="x", role="teacher",
                text="small", context={}, result={"summary": "keep me"},
                status="teacher_validated",
            )
            self.assertIsNotNone(old_turn)
            turn = training_data.record_turn(
                provider="teacher", model="x", role="teacher",
                text="x" * 4000, context={}, result={"summary": "large"},
                status="teacher_validated",
            )
            self.assertIsNone(turn)
            self.assertTrue(training_data.stats()["storage_saturated"])
            self.assertEqual(
                [row["id"] for row in training_data.iter_events()], [old_turn],
            )

    def test_activate_enables_only_after_real_smoke_contract_passes(self):
        with mock.patch.object(local_model_pool, "smoke", return_value={"ok": True}), \
             redirect_stdout(StringIO()):
            self.assertEqual(local_ai.main(["activate"]), 0)
        self.assertTrue(model_pool_config.enabled())
        self.assertFalse(model_pool_config.shadow_enabled())

    def test_failed_activation_leaves_local_routing_disabled(self):
        model_pool_config.save_settings(enabled=True, shadow=True)
        with mock.patch.object(local_model_pool, "smoke",
                               side_effect=local_model_pool.LocalPoolUnavailable("missing")), \
             redirect_stdout(StringIO()):
            self.assertEqual(local_ai.main(["activate"]), 1)
        self.assertFalse(model_pool_config.enabled())
        self.assertFalse(model_pool_config.shadow_enabled())

    def test_activation_reports_environment_forced_disable(self):
        with mock.patch.dict(os.environ, {"ALETHEIA_LOCAL_AI_ENABLED": "0"}), \
             mock.patch.object(local_model_pool, "smoke", return_value={"ok": True}), \
             redirect_stdout(StringIO()):
            self.assertEqual(local_ai.main(["activate"]), 1)
        self.assertFalse(model_pool_config.enabled())

    def test_shadow_enable_failure_does_not_leave_a_latent_opt_in(self):
        model_pool_config.save_settings(enabled=True, shadow=False)
        with mock.patch.dict(os.environ, {"ALETHEIA_LOCAL_AI_SHADOW": "0"}), \
             redirect_stdout(StringIO()):
            self.assertEqual(local_ai.main(["shadow", "on"]), 1)
        self.assertFalse(model_pool_config.shadow_enabled())


class LocalTransportCase(unittest.TestCase):
    def test_remote_ollama_endpoint_is_refused(self):
        with self.assertRaises(ValueError):
            local_brain.OllamaConfig(model="x", base_url="https://example.com").validated()
        with self.assertRaises(ValueError):
            local_brain.OllamaConfig(model="x", base_url="http://10.0.0.4:11434").validated()

    def test_loopback_endpoint_is_allowed(self):
        cfg = local_brain.OllamaConfig(model="x", base_url="http://127.0.0.1:11434")
        self.assertIs(cfg.validated(), cfg)

    def test_machine_timeout_cannot_expand_a_route_budget(self):
        with mock.patch.dict(os.environ, {"ALETHEIA_LOCAL_AI_TIMEOUT": "300"}):
            cfg = local_brain.OllamaConfig.for_model("x", timeout_s=5)
        self.assertEqual(cfg.timeout_s, 5)


class GatewayRoutingCase(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {
            "ALETHEIA_LOCAL_AI_ENABLED": "1",
            "ALETHEIA_LOCAL_AI_SHADOW": "0",
        }, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()

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
        self.assertFalse(local.call_args.kwargs["allow_failover"])
        self.assertLessEqual(
            local.call_args.kwargs["timeout_s"],
            reasoning_gateway.ROUTINE_LOCAL_TIMEOUT_S,
        )

    def test_invalid_route_timeout_is_rejected_before_any_provider(self):
        with mock.patch.object(local_model_pool, "auto_json") as local, \
             mock.patch.object(reasoner, "subscription_json") as subscription:
            with self.assertRaises(ValueError):
                reasoning_gateway.reason_json(
                    "sys", "simple", policy="routine", timeout_s=float("nan"),
                )
        local.assert_not_called()
        subscription.assert_not_called()

    def test_disabled_routine_skips_local_without_false_degradation(self):
        with mock.patch.dict(os.environ, {"ALETHEIA_LOCAL_AI_ENABLED": "0"}), \
             mock.patch.object(local_model_pool, "auto_json",
                               side_effect=AssertionError("disabled local must not run")), \
             mock.patch.object(reasoner, "subscription_json",
                               return_value={"summary": "teacher"}):
            result = reasoning_gateway.reason_json("sys", "simple", policy="routine")
        self.assertEqual(result.output["summary"], "teacher")
        self.assertIsNone(result.degraded)

    def test_broken_local_configuration_degrades_to_subscription(self):
        with mock.patch.dict(os.environ, {"ALETHEIA_LOCAL_AI_TIMEOUT": "broken"}), \
             mock.patch.object(reasoner, "subscription_json",
                               return_value={"summary": "teacher"}) as sub:
            result = reasoning_gateway.reason_json("sys", "simple", policy="routine")
        self.assertEqual(result.output["summary"], "teacher")
        self.assertIn("local routine path unavailable", result.degraded)
        sub.assert_called_once()

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
        self.assertFalse(local.call_args.kwargs["allow_failover"])

    def test_disabled_standard_never_silently_uses_local(self):
        with mock.patch.dict(os.environ, {"ALETHEIA_LOCAL_AI_ENABLED": "0"}), \
             mock.patch.object(reasoner, "subscription_json",
                               side_effect=reasoner.ReasonerUnavailable("down")), \
             mock.patch.object(local_model_pool, "auto_json") as local:
            with self.assertRaisesRegex(reasoner.ReasonerUnavailable,
                                        "local reasoning disabled"):
                reasoning_gateway.reason_json("sys", "normal", policy="standard")
        local.assert_not_called()

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


class LocalSmokeCase(unittest.TestCase):
    def test_smoke_proves_fast_response_and_both_tags_without_pre_enabling(self):
        observed_timeouts = {}
        observed_thinking = {}

        def status(config):
            return {"online": True, "model_available": True, "model": config.model}

        def infer(system, text, *, context, config):
            del system, text, context
            role = "fast" if config.model == "qwen3:8b" else "deep"
            observed_timeouts[role] = config.timeout_s
            observed_thinking[role] = config.think
            return {"ok": True, "role": role}

        with mock.patch.object(local_brain, "status", side_effect=status), \
             mock.patch.object(local_brain, "infer_json", side_effect=infer), \
             mock.patch.object(training_data, "record_turn", return_value="turn"):
            result = local_model_pool.smoke()
        self.assertTrue(result["ok"])
        self.assertEqual(result["required_response_role"], "fast")
        self.assertEqual(set(result["roles"]), {"fast", "deep"})
        self.assertEqual(
            observed_timeouts, {"fast": local_model_pool.FAST_SMOKE_TIMEOUT_S}
        )
        self.assertEqual(observed_thinking, {"fast": False})
        self.assertTrue(result["roles"]["fast"]["response_tested"])
        self.assertFalse(result["roles"]["deep"]["response_tested"])
        self.assertTrue(result["roles"]["deep"]["model_available"])
        self.assertTrue(local_model_pool._config("deep").think)

    def test_smoke_still_requires_the_configured_deep_tag(self):
        def status(config):
            if config.model == "qwen3.6:27b":
                return {
                    "online": True,
                    "model_available": False,
                    "detail": "configured model is not installed",
                }
            return {"online": True, "model_available": True}

        with mock.patch.object(local_brain, "status", side_effect=status), \
             mock.patch.object(local_brain, "infer_json") as infer:
            with self.assertRaisesRegex(
                local_model_pool.LocalPoolUnavailable,
                "local deep model is not ready",
            ):
                local_model_pool.smoke()
        infer.assert_not_called()

    def test_safe_transport_detail_survives_pool_wrapping(self):
        with mock.patch.object(
            local_brain, "infer_json",
            side_effect=local_brain.LocalBrainUnavailable(
                "local Ollama unavailable (TimeoutError)"
            ),
        ), mock.patch.object(training_data, "record_turn", return_value=None):
            with self.assertRaisesRegex(
                local_model_pool.LocalPoolUnavailable, "TimeoutError"
            ):
                local_model_pool.run_json(
                    "contract", "request", require_enabled=False,
                )

    def test_status_uses_short_non_inference_probes(self):
        with mock.patch.object(local_brain, "status",
                               return_value={"online": False}) as status, \
             mock.patch.object(training_data, "stats", return_value={}):
            local_model_pool.status()
        self.assertEqual(status.call_count, 2)
        self.assertTrue(all(
            call.args[0].timeout_s == 2.0 for call in status.call_args_list
        ))

    def test_windows_activation_is_main_only_and_smoke_gated(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "scripts" / "activate_local_ai.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn('$branch -ne "main"', script)
        self.assertIn("-m aletheia.local_ai activate", script)
        self.assertIn("local routing remains disabled", script)
        self.assertIn("Testing the fast route", script)
        self.assertIn("exit $activationCode", script)
        self.assertNotIn('throw "local model smoke test failed', script)
        self.assertNotIn("reset --hard", script.lower())
        self.assertNotIn("git pull", script.lower())


class ShadowCase(unittest.TestCase):
    def test_subscription_answer_is_teacher_recorded_and_returned_unchanged(self):
        teacher = {"summary": "strong answer"}
        with mock.patch.object(reasoner, "_subscription_json_with_provider",
                               return_value=(teacher, "claude.cli:sonnet")), \
             mock.patch.object(training_data, "record_turn", return_value="teacher123") as record, \
             mock.patch.object(reasoner, "_schedule_local_shadow") as shadow:
            out = reasoner.subscription_json("sys", "task")
        self.assertIs(out, teacher)
        self.assertEqual(record.call_args.kwargs["role"], "teacher")
        self.assertIs(record.call_args.kwargs["result"], teacher)
        shadow.assert_called_once()
        self.assertIs(shadow.call_args.args[4], teacher)
        self.assertEqual(shadow.call_args.args[6], "teacher123")


if __name__ == "__main__":
    unittest.main()
