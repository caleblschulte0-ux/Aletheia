import json
import tempfile
import unittest
from pathlib import Path

from aletheia.fleet import load_fleet
from aletheia.pulse import briefing, collect, write_pulse


class FakeSource:
    """Scriptable source: healthy by default, with injectable failures."""

    def __init__(self, dead_repos=(), failed_workflows=(), missing_files=()):
        self.dead_repos = set(dead_repos)
        self.failed_workflows = set(failed_workflows)
        self.missing_files = set(missing_files)

    def latest_commit(self, gh, branch):
        if gh in self.dead_repos:
            raise RuntimeError("repo unreachable")
        return {"sha": "abc123abc123", "date": "2026-08-25T00:00:00Z", "message": "hello"}

    def workflow_run(self, gh, workflow):
        conclusion = "failure" if workflow in self.failed_workflows else "success"
        return {"status": "completed", "conclusion": conclusion,
                "updated_at": "2026-08-25T00:00:00Z", "url": "https://example.invalid"}

    def state_file(self, gh, path, branch):
        return {"exists": path not in self.missing_files, "bytes": 10}


class TestCollect(unittest.TestCase):
    def setUp(self):
        self.fleet = load_fleet()

    def test_all_healthy_actives_are_green_and_stubs_dormant(self):
        pulse = collect(self.fleet, FakeSource())
        for rid, repo in self.fleet["repos"].items():
            expected = "dormant" if repo["status"] == "stub" else "green"
            self.assertEqual(pulse["repos"][rid]["health"], expected, rid)

    def test_failed_workflow_turns_repo_red(self):
        pulse = collect(self.fleet, FakeSource(failed_workflows={"trader.yml"}))
        self.assertEqual(pulse["repos"]["schwab_trader"]["health"], "red")
        self.assertEqual(pulse["repos"]["shorts_pipeline"]["health"], "green")

    def test_missing_state_file_turns_repo_red(self):
        pulse = collect(self.fleet, FakeSource(missing_files={"signals/holdings.json"}))
        self.assertEqual(pulse["repos"]["schwab_trader"]["health"], "red")

    def test_dead_repo_is_a_finding_not_a_crash(self):
        pulse = collect(self.fleet, FakeSource(dead_repos={"Shorts-pipeline"}))
        record = pulse["repos"]["shorts_pipeline"]
        self.assertEqual(record["health"], "unknown")
        self.assertIn("unreachable", record["error"])
        # every registry repo is still named in the pulse
        self.assertEqual(set(pulse["repos"]), set(self.fleet["repos"]))

    def test_briefing_names_the_unreachable(self):
        pulse = collect(self.fleet, FakeSource(dead_repos={"Shorts-pipeline"}))
        text = briefing(pulse)
        self.assertIn("Unreachable:", text)
        self.assertIn("Shorts-pipeline", text)

    def test_write_pulse_emits_latest_briefing_and_history(self):
        pulse = collect(self.fleet, FakeSource())
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_pulse(pulse, Path(tmp))
            names = {p.name for p in paths}
            self.assertIn("latest.json", names)
            self.assertIn("briefing.md", names)
            reread = json.loads((Path(tmp) / "latest.json").read_text())
            self.assertEqual(reread["fleet_revision"], self.fleet["revision"])


if __name__ == "__main__":
    unittest.main()
