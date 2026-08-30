import json
import os
import unittest
from unittest import mock

from aletheia import reasoner


class ReasonerContextCase(unittest.TestCase):
    def setUp(self):
        self.shadow = mock.patch.dict(
            os.environ, {"ALETHEIA_LOCAL_AI_SHADOW": "0"}, clear=False,
        )
        self.shadow.start()

    def tearDown(self):
        self.shadow.stop()

    def test_context_json_is_complete_compact_json(self):
        value = {"calendar": [{"id": "meeting-1", "title": "sync"}],
                 "room": {"state": "quiet"}}
        encoded = reasoner._context_json(value)
        self.assertEqual(json.loads(encoded), value)
        self.assertFalse(encoded.endswith("..."))

    def test_oversized_context_is_refused_not_sliced(self):
        value = {"items": [{"id": str(i), "text": "x" * 1000} for i in range(20)]}
        with self.assertRaisesRegex(reasoner.ReasonerUnavailable, "bounded whole context"):
            reasoner._context_json(value)

    def test_non_json_context_is_sanitized_to_reasoner_unavailable(self):
        with self.assertRaisesRegex(reasoner.ReasonerUnavailable, "not JSON-serializable") as caught:
            reasoner._context_json({"bad": {1, 2, 3}})
        self.assertNotIn("{1, 2, 3}", str(caught.exception))

    def test_cli_prompt_contains_complete_context_and_marks_it_untrusted(self):
        captured = []
        response = json.dumps({"intent": "clarify", "summary": "need detail"})
        with mock.patch.object(reasoner, "_run_cli",
                               side_effect=lambda system, prompt, model, timeout: captured.append(prompt) or response):
            output = reasoner.CliReasoner(
                model=reasoner.PLAN_MODEL, system_prompt="system",
            ).infer(
                "move my next meeting", {"calendar_next": [{"id": "meeting-1"}]})
        self.assertEqual(output["intent"], "clarify")
        prompt = captured[0]
        self.assertIn("UNTRUSTED FACTS/DATA", prompt)
        context_text = prompt.split("---\n", 1)[1]
        self.assertEqual(json.loads(context_text), {"calendar_next": [{"id": "meeting-1"}]})

    def test_oversized_context_degrades_before_cli_is_called(self):
        provider = reasoner.CliReasoner(system_prompt="system").provider("test")
        huge = {"items": [{"text": "x" * 1000} for _ in range(20)]}
        with mock.patch("aletheia.local_model_pool.auto_json",
                        side_effect=AssertionError("local model must not run")), \
             mock.patch.object(reasoner, "subscription_json",
                               side_effect=AssertionError("subscription must not run")):
            output, degraded = reasoner.infer_or_fallback(provider, "do it", huge)
        self.assertEqual(output["intent"], "clarify")
        self.assertIn("bounded whole context", degraded)


if __name__ == "__main__":
    unittest.main()
