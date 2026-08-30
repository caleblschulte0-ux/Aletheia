import contextlib
import io
import json
import unittest
from unittest import mock

from aletheia import local_ai_bridge, local_model_pool, model_pool_config, reasoning_gateway


VALID = {
    "intent": "answer",
    "summary": "ok",
    "required_capabilities": [],
    "references": [],
    "confidence": 0.8,
}


class TestLocalAIBridge(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = local_ai_bridge.main(list(argv))
        self.assertEqual(code, 0)
        return json.loads(out.getvalue())

    def test_route_does_not_infer(self):
        decision = local_model_pool.RouteDecision("fast", "default low-latency route")
        with mock.patch.object(local_model_pool, "choose_role", return_value=decision) as choose, \
             mock.patch.object(reasoning_gateway, "interpret_with_meta") as run:
            result = self.run_cli("route", "hello")
        self.assertEqual(result["role"], "fast")
        choose.assert_called_once()
        run.assert_not_called()

    def test_ask_goes_through_gateway(self):
        gateway_result = reasoning_gateway.GatewayResult(
            requested_mode="fast", role="fast", reason="explicit fast role",
            model="qwen3:8b", think=False, turn_id="turn-1", output=VALID,
        )
        with mock.patch.object(
            reasoning_gateway, "interpret_with_meta", return_value=gateway_result
        ) as run:
            result = self.run_cli("ask", "hello", "--mode", "fast")
        self.assertEqual(result["route"]["role"], "fast")
        self.assertEqual(result["provider"]["model"], "qwen3:8b")
        self.assertEqual(result["training"]["turn_id"], "turn-1")
        self.assertEqual(result["output"], VALID)
        run.assert_called_once_with("hello", {}, mode="fast")

    def test_auto_returns_route_provenance_from_gateway(self):
        gateway_result = reasoning_gateway.GatewayResult(
            requested_mode="auto", role="deep", reason="explicit deep-reasoning cue",
            model="qwen3.6:27b", think=True, turn_id="turn-2", output=VALID,
        )
        with mock.patch.object(
            reasoning_gateway, "interpret_with_meta", return_value=gateway_result
        ):
            result = self.run_cli("ask", "review the architecture")
        self.assertEqual(result["route"]["role"], "deep")
        self.assertEqual(result["output"], VALID)

    def test_feedback_is_exposed_through_gateway(self):
        expected = {"turn_id": "turn-1", "feedback_id": "fb-1", "verdict": "good"}
        with mock.patch.object(reasoning_gateway, "feedback", return_value=expected) as feedback:
            result = self.run_cli("feedback", "turn-1", "--verdict", "good", "--note", "nice")
        self.assertEqual(result, expected)
        feedback.assert_called_once_with("turn-1", verdict="good", note="nice")

    def test_profiles_are_read_only_view(self):
        expected = {"fast": {"model": "qwen3:8b"}, "deep": {"model": "qwen3.6:27b"}}
        with mock.patch.object(model_pool_config, "show", return_value=expected):
            result = self.run_cli("profiles")
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
