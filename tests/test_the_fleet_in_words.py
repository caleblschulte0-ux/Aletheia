"""Night sweep 2026-09-23, every frontier off: "what's wrong with the
trader", "is the trader running", "which project has a fault" and "when was
the fleet last checked" each went to a model for the pulse she writes."""
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from aletheia import pulse, quick

PULSE = {"generated_at": "2026-09-23T04:51:00Z",
         "repos": {"schwab_trader": {"github": "schwab-trader", "status": "active", "health": "red",
                                     "commit": {"sha": "e239f4bea87a", "message": "bot: daily snapshot"},
                                     "workflows": {"sell-brain.yml": {"conclusion": "success"}}},
                   "shorts_pipeline": {"github": "Shorts-pipeline", "status": "active", "health": "red",
                                       "workflows": {"daily.yml": {"conclusion": "failure"}}}},
         "alerts": [{"repo": "schwab_trader", "github": "schwab-trader", "missing": ["signals/paper_account.json"]},
                    {"repo": "shorts_pipeline", "github": "Shorts-pipeline", "failing": ["daily.yml"]}]}


class TheFleetInWords(unittest.TestCase):
    def test_the_shapes_are_claimed(self):
        for said, shape in (("what's wrong with the trader", "repo_wrong"),
                            ("what did the shorts pipeline do today", "repo_wrong"),
                            ("which project has a fault", "alerts"),
                            ("which ones are failing", "alerts"),
                            ("when was the fleet last checked", "fleet_read_at"),
                            ("how fresh is the fleet reading", "fleet_read_at"),
                            ("is the trader running", "status_of")):
            with self.subTest(said=said):
                found = quick.match(said)
                self.assertIsNotNone(found, said)
                self.assertEqual(found[0], shape)

    def test_with_a_pulse_the_answers_are_the_pulses(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(pulse, "PULSE_DIR", pathlib.Path(tmp)):
            (pathlib.Path(tmp) / "latest.json").write_text(json.dumps(PULSE), encoding="utf-8")
            self.assertIn("schwab-trader", quick.answer("which project has a fault"))
            said = quick.answer("when was the fleet last checked")
            self.assertTrue(said.startswith("The fleet was last read"), said)
            self.assertIn("every six hours", said)
            wrong = quick.answer("what's wrong with the trader")
            self.assertIsNotNone(wrong)

    def test_with_no_pulse_nothing_is_guessed(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(pulse, "PULSE_DIR", pathlib.Path(tmp)):
            for said in ("what's wrong with the trader", "is the trader running", "when was the fleet last checked",
                         "which project has a fault"):
                with self.subTest(said=said):
                    out = quick.answer(said)
                    self.assertIsNotNone(out, said)
                    self.assertIn("No fleet reading", out)


if __name__ == "__main__":
    unittest.main()
