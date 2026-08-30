import json
import unittest
from unittest import mock

from aletheia import brain, local_brain, local_model_pool, model_pool_config, training_data


VALID = {
    "intent": "answer",
    "summary": "ok",
    "required_capabilities": [],
    "references": [],
    "confidence": 0.8,
}


class TestLocalModelPool(unittest.TestCase):
    def setUp(self):
        self.capture = mock.patch.object(training_data, "record_turn", return_value="turn")
        self.record_turn = self.capture.start()
        self.addCleanup(self.capture.stop)
        self.base = mock.patch.object(
            local_brain.OllamaConfig,
            "from_env",
            return_value=local_brain.OllamaConfig(
                base_url="http://127.0.0.1:11434", model="ignored", timeout_seconds=1
            ),
        )
        self.base.start(); self.addCleanup(self.base.stop)

    def profiles(self, role):
        if role == "fast":
            return {"role": "fast", "model": "qwen3:8b", "think": False, "source": "default"}
        return {"role": "deep", "model": "qwen3.6:27b", "think": True, "source": "default"}

    def test_fast_uses_8b_with_thinking_off(self):
        response = {"message": {"content": json.dumps(VALID)}}
        with mock.patch.object(model_pool_config, "resolve_profile", side_effect=self.profiles), \
             mock.patch.object(local_brain, "_request_json", return_value=response) as request:
            result = local_model_pool.run_fast("hello")
        self.assertEqual(result, VALID)
        payload = request.call_args.args[2]
        self.assertEqual(payload["model"], "qwen3:8b")
        self.assertFalse(payload["think"])
        self.assertEqual(self.record_turn.call_args.kwargs["provider"], "ollama:fast")

    def test_deep_uses_27b_with_thinking_on(self):
        response = {"message": {"content": json.dumps(VALID)}}
        with mock.patch.object(model_pool_config, "resolve_profile", side_effect=self.profiles), \
             mock.patch.object(local_brain, "_request_json", return_value=response) as request:
            result = local_model_pool.run_deep("review the architecture")
        self.assertEqual(result, VALID)
        payload = request.call_args.args[2]
        self.assertEqual(payload["model"], "qwen3.6:27b")
        self.assertTrue(payload["think"])
        self.assertEqual(self.record_turn.call_args.kwargs["provider"], "ollama:deep")

    def test_auto_defaults_to_fast(self):
        with mock.patch.object(local_model_pool, "run_fast", return_value=VALID) as fast, \
             mock.patch.object(local_model_pool, "run_deep") as deep:
            route, result = local_model_pool.run_auto("what time is the meeting?")
        self.assertEqual(route.role, "fast")
        self.assertEqual(result, VALID)
        fast.assert_called_once()
        deep.assert_not_called()

    def test_auto_routes_architecture_to_deep(self):
        with mock.patch.object(local_model_pool, "run_deep", return_value=VALID) as deep, \
             mock.patch.object(local_model_pool, "run_fast") as fast:
            route, result = local_model_pool.run_auto("review the architecture of this system")
        self.assertEqual(route.role, "deep")
        self.assertEqual(result, VALID)
        deep.assert_called_once()
        fast.assert_not_called()

    def test_selected_role_failure_gets_one_local_failover(self):
        with mock.patch.object(local_model_pool, "run_fast", side_effect=local_brain.LocalBrainUnavailable("off")), \
             mock.patch.object(local_model_pool, "run_deep", return_value=VALID):
            route, result = local_model_pool.run_auto("simple request")
        self.assertEqual(route.role, "deep")
        self.assertIn("failover", route.reason)
        self.assertEqual(result, VALID)

    def test_both_local_failures_end_in_deterministic_fallback(self):
        with mock.patch.object(local_model_pool, "run_fast", side_effect=local_brain.LocalBrainUnavailable("off")), \
             mock.patch.object(local_model_pool, "run_deep", side_effect=local_brain.LocalBrainUnavailable("off")):
            route, result = local_model_pool.run_auto("do magic")
        self.assertEqual(route.role, "fallback")
        self.assertEqual(result["intent"], "clarify")
        self.assertEqual(result["confidence"], 0.0)


if __name__ == "__main__":
    unittest.main()
