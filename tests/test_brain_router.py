import contextlib
import io
import json
import unittest
from unittest import mock

from aletheia import brain_router, local_brain


class TestBrainRouter(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = brain_router.main(list(argv))
        self.assertEqual(code, 0, out.getvalue())
        return json.loads(out.getvalue())

    def test_auto_uses_local_first(self):
        proposal = {
            "intent": "answer",
            "summary": "local",
            "required_capabilities": [],
            "references": [],
            "confidence": 0.8,
        }
        with mock.patch.object(local_brain, "run_auto", return_value=proposal) as run:
            result = self.run_cli("interpret", "hello")
        self.assertEqual(result["summary"], "local")
        run.assert_called_once()

    def test_fallback_never_calls_or_configures_local(self):
        with mock.patch.object(local_brain, "run_auto") as auto, \
             mock.patch.object(local_brain, "run_local") as local, \
             mock.patch.object(local_brain.OllamaConfig, "from_env", side_effect=ValueError("bad env")) as env:
            result = self.run_cli("interpret", "do magic", "--provider", "fallback")
        self.assertEqual(result["intent"], "clarify")
        auto.assert_not_called()
        local.assert_not_called()
        env.assert_not_called()

    def test_auto_bad_local_config_fails_closed(self):
        with mock.patch.object(local_brain.OllamaConfig, "from_env", side_effect=ValueError("bad env")), \
             mock.patch.object(local_brain, "run_auto") as auto:
            result = self.run_cli("interpret", "hello")
        self.assertEqual(result["intent"], "clarify")
        self.assertEqual(result["confidence"], 0.0)
        auto.assert_not_called()

    def test_status_is_read_only_adapter_status(self):
        expected = {
            "provider": "ollama",
            "url": "http://127.0.0.1:11434",
            "model": "qwen3:8b",
            "online": True,
            "model_available": True,
            "models": ["qwen3:8b"],
        }
        with mock.patch.object(local_brain, "status", return_value=expected) as status:
            result = self.run_cli("status")
        self.assertEqual(result, expected)
        status.assert_called_once()


if __name__ == "__main__":
    unittest.main()
