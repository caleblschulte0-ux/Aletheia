"""His words, 2026-09-23: "it's saying Schwab Trader is broken ... I've had a
different Claude chat fix it ... I don't need that being read all night";
"when I go to it, it just says Schwab Trader, guardrail, paper trading
system, etc. It's like the readme. I want it to tell me what the fault is."

The trader's red was `signals/paper_account.json` missing - a file its
rebuild renamed to `sim_account.json`; every workflow had passed."""
import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import agenda, faults, intercom, journal, notifications, quick, tools

NOW = dt.datetime(2026, 9, 24, 0, 30, tzinfo=dt.timezone.utc)
PULSE = {
    "generated_at": "2026-09-23T21:33:46Z",
    "repos": {
        "schwab_trader": {"github": "schwab-trader", "status": "active", "health": "red",
                          "summary": "Guardrailed paper-trading system.",
                          "workflows": {"sell-brain.yml": {"status": "completed", "conclusion": "success",
                                                           "updated_at": "2026-09-22T18:37:07Z"}},
                          "state_files": {"signals/paper_account.json": {"exists": False}}},
        "shorts_pipeline": {"github": "Shorts-pipeline", "status": "active", "health": "red",
                            "workflows": {"daily.yml": {"status": "completed", "conclusion": "failure",
                                                        "updated_at": "2026-09-23T22:30:00Z"},
                                          "story_forge.yml": {"status": "completed", "conclusion": "failure",
                                                              "updated_at": "2026-09-23T20:30:00Z"}}},
    },
    "alerts": [
        {"repo": "schwab_trader", "github": "schwab-trader", "health": "red",
         "missing": ["signals/paper_account.json"]},
        {"repo": "shorts_pipeline", "github": "Shorts-pipeline", "health": "red",
         "failing": ["daily.yml", "story_forge.yml"]},
    ],
}


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(root / "private")})
        env.start(); self.addCleanup(env.stop)
        p = mock.patch.object(journal, "JOURNAL_PATH", root / "journal.jsonl")
        p.start(); self.addCleanup(p.stop)
        from aletheia import pulse
        (root / "pulse").mkdir()
        (root / "pulse" / "latest.json").write_text(json.dumps(PULSE), encoding="utf-8")
        q = mock.patch.object(pulse, "PULSE_DIR", root / "pulse")
        q.start(); self.addCleanup(q.stop)


class TheFaultInWords(unittest.TestCase):
    def test_a_missing_file_says_so_and_names_the_registry(self):
        said = faults.said(PULSE["alerts"][0], PULSE["repos"]["schwab_trader"], now=NOW)
        self.assertEqual(said, "The pulse expects signals/paper_account.json and the repository does not have it "
                               "- if it was renamed, that is a fix to the fleet registry, not to the project.")

    def test_failing_workflows_say_which_and_when(self):
        said = faults.said(PULSE["alerts"][1], PULSE["repos"]["shorts_pipeline"], now=NOW)
        self.assertEqual(said, "Daily failed 2 hours ago; story_forge failed 4 hours ago.")

    def test_unreadable_and_unsaid(self):
        self.assertEqual(faults.said({"repo": "x", "error": "HTTP 403"}), "It could not be read: HTTP 403.")
        self.assertEqual(faults.said({"repo": "x"}), "The pulse marks it red and does not say why.")

    def test_the_registry_no_longer_expects_the_renamed_file(self):
        from aletheia.fleet import REPO_ROOT
        text = (REPO_ROOT / "config" / "fleet.json").read_text(encoding="utf-8")
        self.assertNotIn("paper_account.json", text)
        self.assertIn("signals/sim_account.json", text)


class Handled(Isolated):
    def test_his_ack_quiets_the_same_fault_and_not_a_different_one(self):
        self.assertIsNone(faults.is_handled(PULSE["alerts"][0]))
        said = faults.ack("schwab-trader", quote="had another chat fix it")
        self.assertIn("stop calling schwab-trader broken", said)
        self.assertTrue(faults.is_handled(PULSE["alerts"][0]))
        self.assertIsNone(faults.is_handled(PULSE["alerts"][1]))
        changed = {**PULSE["alerts"][0], "failing": ["watchdog.yml"]}
        self.assertIsNone(faults.is_handled(changed), "a different fault on the same project is shouted again")
        with self.assertRaises(ValueError):
            faults.ack("nothing-red")
        self.assertIn("marked handled by him", journal.JOURNAL_PATH.read_text(encoding="utf-8"))

    def test_the_fleet_payload_carries_the_sentence_and_the_ack(self):
        out = faults.decorate(json.loads(json.dumps(PULSE)), now=NOW)
        self.assertIn("expects signals/paper_account.json", out["alerts"][0]["said"])
        self.assertFalse(out["alerts"][0]["handled"])
        faults.ack("schwab_trader")
        out = faults.decorate(json.loads(json.dumps(PULSE)), now=NOW)
        self.assertTrue(out["alerts"][0]["handled"])
        self.assertFalse(out["alerts"][1]["handled"])

    def test_the_room_says_handled_not_red(self):
        self.assertIn("2 repos red:", quick.answer("is anything broken"))
        faults.ack("schwab-trader")
        said = quick.answer("is anything broken")
        self.assertIn("1 repo red: Shorts-pipeline - daily failed", said)
        self.assertIn("schwab-trader you've marked handled", said)
        fleet = quick.answer("how is the fleet")
        self.assertIn("schwab-trader marked handled by you", fleet)
        faults.ack("Shorts-pipeline")
        self.assertIn("Nothing red that you haven't handled", quick.answer("is anything broken"))

    def test_the_kind_is_his_tap_only(self):
        self.assertEqual(intercom.KIND_ARGS["fault_ack"], ({"repo"}, set()))
        self.assertIn("fault_ack", intercom.ROUTINE_KINDS)
        self.assertIn("fault_ack", intercom.PLANNER_FORBIDDEN)
        self.assertIn("fault_ack", agenda.FORBIDDEN_KINDS)
        self.assertIn("fault_ack", notifications.HIS_TAP_KINDS)
        self.assertIn("fault_ack", tools.INTERNAL_KINDS)
        with mock.patch("aletheia.intercom.rehearsing", return_value=False):
            self.assertIn("stop calling schwab-trader broken",
                          intercom.execute_command({"kind": "fault_ack", "repo": "schwab_trader"}, {}))


class ThePageLeadsWithTheFault(unittest.TestCase):
    def test_the_page_renders_the_sentence_and_the_button(self):
        from aletheia.fleet import REPO_ROOT
        js = (REPO_ROOT / "interface" / "thea-app.js").read_text(encoding="utf-8")
        self.assertIn("a.said", js)
        self.assertIn('kind: "fault_ack"', js)
        self.assertIn("handled, waiting for the next reading", js)
        self.assertLess(js.index("faultLine +"), js.index('(r.summary ? "<p>"'), "the fault before the README")


if __name__ == "__main__":
    unittest.main()
