import io
import json
import unittest
import urllib.error
from unittest import mock

from aletheia import brain, local_brain, training_data


class FakeResponse:
    def __init__(self, value):
        self.payload = json.dumps(value).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, limit=-1):
        return self.payload if limit < 0 else self.payload[:limit]


class TestLocalBrain(unittest.TestCase):
    def setUp(self):
        self.cfg = local_brain.OllamaConfig(
            base_url="http://127.0.0.1:11434",
            model="qwen3:8b",
            timeout_seconds=1,
        )
        self.capture = mock.patch.object(training_data, "record_turn", return_value="turn-1")
        self.record_turn = self.capture.start()
        self.addCleanup(self.capture.stop)

    def test_local_provider_uses_existing_brain_contract(self):
        proposal = {
            "intent": "answer",
            "summary": "All good.",
            "required_capabilities": [],
            "references": [],
            "confidence": 0.9,
        }
        response = FakeResponse({"message": {"role": "assistant", "content": json.dumps(proposal)}})
        with mock.patch.object(local_brain.urllib.request, "urlopen", return_value=response) as opened:
            result = local_brain.run_local("status?", {"pulse": "ok"}, config=self.cfg)
        self.assertEqual(result, proposal)
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/chat")
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["model"], "qwen3:8b")
        self.assertFalse(body["stream"])
        self.assertFalse(body["think"])
        self.assertEqual(body["options"]["temperature"], 0)
        self.assertEqual(body["format"]["type"], "object")
        captured = self.record_turn.call_args.kwargs
        self.assertEqual(captured["status"], "validated")
        self.assertEqual(captured["request_payload"], body)
        self.assertEqual(captured["result"], proposal)
        self.assertEqual(captured["model"], "qwen3:8b")

    def test_invalid_model_output_is_rejected_and_retained_as_failure(self):
        bad = {
            "intent": "execute_everything",
            "summary": "done",
            "required_capabilities": [],
            "references": [],
            "confidence": 1,
        }
        response = FakeResponse({"message": {"content": json.dumps(bad)}})
        with mock.patch.object(local_brain.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(brain.BrainOutputError):
                local_brain.run_local("do it", config=self.cfg)
        captured = self.record_turn.call_args.kwargs
        self.assertEqual(captured["status"], "error")
        self.assertEqual(captured["error_type"], "BrainOutputError")

    def test_auto_falls_back_when_ollama_is_offline(self):
        with mock.patch.object(
            local_brain.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            result = local_brain.run_auto("do magic", config=self.cfg)
        self.assertEqual(result["intent"], "clarify")
        self.assertEqual(result["confidence"], 0.0)
        self.assertEqual(self.record_turn.call_args.kwargs["status"], "error")

    def test_auto_falls_back_on_protocol_failure(self):
        response = FakeResponse({"unexpected": True})
        with mock.patch.object(local_brain.urllib.request, "urlopen", return_value=response):
            result = local_brain.run_auto("do magic", config=self.cfg)
        self.assertEqual(result["intent"], "clarify")

    def test_status_reports_pulled_model(self):
        response = FakeResponse({"models": [{"name": "qwen3:8b"}, {"name": "gemma3:4b"}]})
        with mock.patch.object(local_brain.urllib.request, "urlopen", return_value=response), \
             mock.patch.object(training_data, "stats", return_value={"turns": 0}):
            result = local_brain.status(config=self.cfg)
        self.assertTrue(result["online"])
        self.assertTrue(result["model_available"])
        self.assertIn("qwen3:8b", result["models"])
        self.assertEqual(result["model_source"], "explicit")

    def test_status_reports_offline_without_throwing(self):
        with mock.patch.object(
            local_brain.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError("offline"),
        ), mock.patch.object(training_data, "stats", return_value={"turns": 0}):
            result = local_brain.status(config=self.cfg)
        self.assertFalse(result["online"])
        self.assertFalse(result["model_available"])

    def test_non_loopback_endpoint_is_refused(self):
        cfg = local_brain.OllamaConfig(base_url="https://example.com", model="qwen3:8b")
        with self.assertRaises(ValueError):
            cfg.validated()

    def test_context_is_bounded(self):
        raw = local_brain._context_text({"huge": "x" * (local_brain.MAX_CONTEXT_CHARS * 2)})
        self.assertLessEqual(len(raw), local_brain.MAX_CONTEXT_CHARS + 20)
        self.assertIn("[truncated]", raw)


if __name__ == "__main__":
    unittest.main()
