import contextlib
import io
import json
import unittest
from unittest import mock

from aletheia import local_ai_bridge, local_model_pool, model_pool_config


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
             mock.patch.object(local_model_pool, "run_auto") as run:
            result = self.run_cli("route", "hello")
        self.assertEqual(result["role"], "fast")
        choose.assert_called_once()
        run.assert_not_called()

    def test_explicit_fast_is_exposed_without_canonical_assistant(self):
        with mock.patch.object(local_model_pool, "run_fast", return_value=VALID) as run:
            result = self.run_cli("ask", "hello", "--mode", "fast")
        self.assertEqual(result["route"]["role"], "fast")
        self.assertEqual(result["output"], VALID)
        run.assert_called_once()

    def test_auto_returns_route_provenance(self):
        decision = local_model_pool.RouteDecision("deep", "explicit deep-reasoning cue")
        with mock.patch.object(local_model_pool, "run_auto", return_value=(decision, VALID)):
            result = self.run_cli("ask", "review the architecture")
        self.assertEqual(result["route"]["role"], "deep")
        self.assertEqual(result["output"], VALID)

    def test_profiles_are_read_only_view(self):
        expected = {"fast": {"model": "qwen3:8b"}, "deep": {"model": "qwen3.6:27b"}}
        with mock.patch.object(model_pool_config, "show", return_value=expected):
            result = self.run_cli("profiles")
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
