import unittest
from unittest import mock

from aletheia import brain, local_model_pool, reasoning_gateway, training_data


VALID = {
    "intent": "answer",
    "summary": "ok",
    "required_capabilities": [],
    "references": [],
    "confidence": 0.8,
}


class TestReasoningGateway(unittest.TestCase):
    def role_run(self, role="fast", model="qwen3:8b", think=False, turn_id="turn-123"):
        return local_model_pool.RoleRun(
            role=role, model=model, think=think, turn_id=turn_id, output=VALID)

    def test_interpret_returns_exact_brain_shape_for_canonical_callers(self):
        pool_run = local_model_pool.PoolRun(
            route=local_model_pool.RouteDecision("fast", "default low-latency route"),
            role_run=self.role_run(),
            output=VALID,
        )
        with mock.patch.object(local_model_pool, "run_auto_traced", return_value=pool_run):
            result = reasoning_gateway.interpret("hello")
        self.assertEqual(result, VALID)
        self.assertEqual(set(result), set(VALID))

    def test_metadata_exposes_route_model_and_training_turn(self):
        pool_run = local_model_pool.PoolRun(
            route=local_model_pool.RouteDecision("deep", "explicit deep-reasoning cue"),
            role_run=self.role_run(
                role="deep", model="qwen3.6:27b", think=True, turn_id="turn-deep"),
            output=VALID,
        )
        with mock.patch.object(local_model_pool, "run_auto_traced", return_value=pool_run):
            result = reasoning_gateway.interpret_with_meta("review the architecture")
        data = result.as_dict()
        self.assertEqual(data["route"]["role"], "deep")
        self.assertEqual(data["provider"]["model"], "qwen3.6:27b")
        self.assertTrue(data["provider"]["think"])
        self.assertEqual(data["training"]["turn_id"], "turn-deep")
        self.assertEqual(data["output"], VALID)

    def test_explicit_fast_uses_traced_fast_role(self):
        run = self.role_run()
        with mock.patch.object(local_model_pool, "run_fast_traced", return_value=run) as fast:
            result = reasoning_gateway.interpret_with_meta("hello", mode="fast")
        self.assertEqual(result.role, "fast")
        self.assertEqual(result.turn_id, "turn-123")
        fast.assert_called_once_with("hello", {})

    def test_fallback_never_calls_local_pool(self):
        with mock.patch.object(local_model_pool, "run_auto_traced") as auto:
            result = reasoning_gateway.interpret_with_meta("do magic", mode="fallback")
        self.assertEqual(result.role, "fallback")
        self.assertIsNone(result.model)
        self.assertIsNone(result.turn_id)
        self.assertEqual(result.output["intent"], "clarify")
        auto.assert_not_called()

    def test_feedback_attaches_to_exact_turn(self):
        with mock.patch.object(training_data, "record_feedback", return_value="fb-1") as record:
            result = reasoning_gateway.feedback("turn-123", verdict="good", note="useful")
        self.assertEqual(result["feedback_id"], "fb-1")
        record.assert_called_once_with(
            "turn-123", verdict="good", corrected_result=None, note="useful")

    def test_status_wraps_pool_health_without_inference(self):
        expected = {"profiles": {"fast": {"online": True}}}
        with mock.patch.object(local_model_pool, "status", return_value=expected):
            result = reasoning_gateway.status()
        self.assertEqual(result["gateway_version"], reasoning_gateway.GATEWAY_VERSION)
        self.assertEqual(result["pool"], expected)
        self.assertIn("auto", result["modes"])

    def test_context_must_be_object(self):
        with self.assertRaises(ValueError):
            reasoning_gateway.interpret_with_meta("hello", ["not", "object"])


if __name__ == "__main__":
    unittest.main()
