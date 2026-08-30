import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import training_data


class TestTrainingData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = mock.patch.dict(os.environ, {
            training_data.ENV_DATA_DIR: self.tmp.name,
            training_data.ENV_CAPTURE: "1",
        }, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_turn_retains_exact_request_and_result(self):
        payload = {"model": "model-a", "messages": [{"role": "user", "content": "hello"}]}
        result = {"intent": "answer", "summary": "hi", "required_capabilities": [],
                  "references": [], "confidence": 0.9}
        turn_id = training_data.record_turn(
            provider="ollama", model="model-a", text="hello", context={"x": 1},
            request_payload=payload, result=result, status="validated", duration_ms=12)
        self.assertIsNotNone(turn_id)
        path = Path(self.tmp.name) / "turns" / f"{turn_id}.json"
        row = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(row["request_payload"], payload)
        self.assertEqual(row["result"], result)
        self.assertEqual(row["input"]["context"], {"x": 1})
        self.assertEqual(row["model"], "model-a")

    def test_feedback_is_append_only_separate_event(self):
        turn_id = training_data.record_turn(
            provider="ollama", model="m", text="x", context={}, status="validated")
        feedback_id = training_data.record_feedback(
            turn_id, verdict="corrected", corrected_result={"intent": "clarify"}, note="too eager")
        self.assertTrue((Path(self.tmp.name) / "turns" / f"{turn_id}.json").exists())
        feedback_path = Path(self.tmp.name) / "feedback" / f"{feedback_id}.json"
        row = json.loads(feedback_path.read_text(encoding="utf-8"))
        self.assertEqual(row["turn_id"], turn_id)
        self.assertEqual(row["verdict"], "corrected")

    def test_export_jsonl_and_stats(self):
        training_data.record_turn(provider="ollama", model="a", text="1", context={}, status="validated")
        training_data.record_turn(provider="ollama", model="b", text="2", context={}, status="error")
        output = Path(self.tmp.name) / "dataset.jsonl"
        count = training_data.export_jsonl(output)
        self.assertEqual(count, 2)
        self.assertEqual(len(output.read_text(encoding="utf-8").splitlines()), 2)
        stats = training_data.stats()
        self.assertEqual(stats["turns"], 2)
        self.assertEqual(stats["by_model"], {"a": 1, "b": 1})

    def test_capture_can_be_disabled_without_breaking_callers(self):
        with mock.patch.dict(os.environ, {training_data.ENV_CAPTURE: "0"}, clear=False):
            turn_id = training_data.record_turn(
                provider="ollama", model="m", text="x", context={}, status="validated")
        self.assertIsNone(turn_id)
        self.assertFalse((Path(self.tmp.name) / "turns").exists())


if __name__ == "__main__":
    unittest.main()
