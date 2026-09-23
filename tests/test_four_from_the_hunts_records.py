"""From the 2026-09-23 night sweep with every frontier off: "why didn't the
Datadog one go", "anything I need to answer", "how many jobs have you found"
and "show me the fleet" each waited two minutes on her own model for a
store she holds."""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest import mock

from aletheia import pulse, quick


class WhyNotCase(unittest.TestCase):
    def test_the_record_says_why(self):
        rec = {"id": "apply-1", "state": "FAILED", "company": "Datadog", "job_title": "GTM Ops",
               "failure": "the Submit button would not take a click - a CAPTCHA challenge was in front of it"}
        with mock.patch("aletheia.apply_run.find", return_value=[rec]), \
             mock.patch("aletheia.apply_run.describe", return_value="GTM Ops at Datadog"):
            said = quick.answer("why didn't the Datadog one go")
        self.assertTrue(said.startswith("GTM Ops at Datadog: it would not send - "), said)
        self.assertIn("CAPTCHA", said)
        rec2 = {"id": "apply-2", "state": "NEEDS_YOU", "company": "Ramp", "job_title": "AM",
                "not_filled": [{"label": "What is your percentage attainment to goal?"}]}
        with mock.patch("aletheia.apply_run.find", return_value=[rec2]), \
             mock.patch("aletheia.apply_run.describe", return_value="AM at Ramp"):
            said = quick.answer("why did the Ramp application fail")
        self.assertIn("stopped on a question only you can answer: What is your percentage", said)
        with mock.patch("aletheia.apply_run.find", return_value=[]):
            # "the Nowhere ONE" names an application; no record is a fact
            self.assertIn("no application matching 'Nowhere'", quick.answer("why didn't the Nowhere one go"))
            # "the meeting" names nothing of hers, so a model may have it
            self.assertIsNone(quick.answer("why didn't the meeting go"))


class ToAnswerCase(unittest.TestCase):
    def test_the_questions_waiting_on_him(self):
        rows = [{"kind": "application", "what": "Ramp asks: What is your percentage attainment to goal?"},
                {"kind": "approval", "what": "x"}]
        with mock.patch("aletheia.needs_you.items", return_value=rows):
            said = quick.answer("anything I need to answer")
        self.assertEqual(said, "1 question waiting on you: Ramp asks: What is your percentage attainment to goal?.")
        with mock.patch("aletheia.needs_you.items", return_value=[]):
            self.assertIn("Nothing to answer", quick.answer("what questions do you have for me"))


class FoundCase(unittest.TestCase):
    def test_openings_found_today(self):
        with mock.patch("aletheia.current_state.job_hunt", return_value={"today": {"discovered": 17, "qualified": 12, "sent": 3}}):
            self.assertEqual(quick.answer("how many jobs have you found today"),
                             "17 openings found today, 12 worth applying to, 3 sent.")
        with mock.patch("aletheia.current_state.job_hunt", return_value={"today": {}}):
            self.assertIn("No openings found today", quick.answer("how many jobs have you found"))


class FleetCase(unittest.TestCase):
    def test_the_fleet_in_one_breath(self):
        fleet = {"repos": {"a": {"github": "Aletheia", "status": "active"}, "s": {"github": "Shorts-pipeline", "status": "active"},
                           "e": {"github": "etsy_maker", "status": "stub"}},
                 "alerts": [{"repo": "s", "failing": ["daily.yml"]}]}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(pulse, "PULSE_DIR", pathlib.Path(tmp)):
            (pathlib.Path(tmp) / "latest.json").write_text(json.dumps(fleet), encoding="utf-8")
            self.assertEqual(quick.answer("show me the fleet"), "2 projects active, 1 dormant; 1 fault: Shorts-pipeline (daily failing).")
            self.assertEqual(quick.answer("any faults"), "2 projects active, 1 dormant; 1 fault: Shorts-pipeline (daily failing).")
            (pathlib.Path(tmp) / "latest.json").write_text(json.dumps({"repos": {}}), encoding="utf-8")
            self.assertIn("No fleet reading", quick.answer("how's the fleet"))
            (pathlib.Path(tmp) / "latest.json").unlink()
            self.assertIn("No fleet reading yet", quick.answer("how's the fleet"))


if __name__ == "__main__":
    unittest.main()
