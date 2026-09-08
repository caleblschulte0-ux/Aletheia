"""A team is only worth its minutes if it cannot quietly lose a worker.

Every test here replaces the model. A primitive whose tests need a live
subscription is a primitive whose tests nobody runs, and this one is
supposed to be exercised on every change.
"""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from aletheia import agents, journal, policy, teams


class TeamCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d)})
        env.start()
        self.addCleanup(env.stop)
        for patch in (mock.patch.object(journal, "JOURNAL_PATH", d / "j.jsonl"),
                      mock.patch.object(policy, "HALT_PATH", d / "halt.json"),
                      mock.patch.object(policy, "APPROVALS_DIR", d / "approvals")):
            patch.start()
            self.addCleanup(patch.stop)

    def three(self):
        return [teams.Assignment("researcher", "q"),
                teams.Assignment("builder", "q"),
                teams.Assignment("critic", "q")]


class NoWorkerIsLostCase(TeamCase):
    def test_every_assignment_comes_back_even_when_one_explodes(self):
        """One broken worker must not take the team, or hide itself."""
        def worker(assignment, timeout_s=0):
            if assignment["role"] == "builder":
                raise RuntimeError("provider fell over")
            return {"verdict": "yes", "provider": "ollama:qwen"}

        results = teams.run(self.three(), worker=worker)
        self.assertEqual(len(results), 3, "a worker vanished")
        states = {r["role"]: r["state"] for r in results}
        self.assertEqual(states["builder"], "FAILED")
        self.assertEqual(states["researcher"], "COMPLETED")
        self.assertIn("provider fell over",
                      [r.get("why", "") for r in results if r["state"] == "FAILED"][0])

    def test_a_failed_worker_is_not_counted_as_agreement(self):
        """Two workers, one dead, is not consensus."""
        def worker(assignment, timeout_s=0):
            if assignment["role"] == "critic":
                raise RuntimeError("down")
            return {"verdict": "ship it", "provider": "claude"}

        out = teams.deliberate("should we", self.three(), worker=worker)
        self.assertEqual(out["summary"]["answered"], 2)
        self.assertEqual(len(out["summary"]["failed"]), 1)

    def test_disagreement_is_reported_rather_than_averaged(self):
        def worker(assignment, timeout_s=0):
            verdict = "no" if assignment["role"] == "critic" else "yes"
            return {"verdict": verdict, "provider": "claude"}

        out = teams.deliberate("should we", self.three(), worker=worker)
        found = out["summary"]["disagreements"]
        self.assertEqual(len(found), 2, found)
        self.assertEqual({d["verdict"] for d in found}, {"yes", "no"})

    def test_agreement_is_not_reported_as_disagreement(self):
        def worker(assignment, timeout_s=0):
            return {"verdict": "yes", "provider": "claude"}
        out = teams.deliberate("should we", self.three(), worker=worker)
        self.assertEqual(out["summary"]["disagreements"], [])


class HonestIndependenceCase(TeamCase):
    def test_the_same_model_reviewing_itself_is_not_independent(self):
        same = {"role": "builder", "provider": "claude"}
        also = {"role": "critic", "provider": "claude"}
        self.assertFalse(teams.independent(same, also))

    def test_a_different_role_AND_provider_is(self):
        self.assertTrue(teams.independent(
            {"role": "builder", "provider": "claude"},
            {"role": "critic", "provider": "ollama:qwen"}))

    def test_an_unknown_provider_is_never_called_independent(self):
        self.assertFalse(teams.independent(
            {"role": "builder", "provider": "claude"},
            {"role": "critic", "provider": None}))

    def test_the_same_role_twice_is_not_independent_either(self):
        self.assertFalse(teams.independent(
            {"role": "critic", "provider": "claude"},
            {"role": "critic", "provider": "ollama:qwen"}))


class BoundedCase(TeamCase):
    def test_never_more_than_the_measured_ceiling_at_once(self):
        """Two. A sixteen-way burst on this PC had half its calls refused."""
        live = []
        peak = []

        def worker(assignment, timeout_s=0):
            live.append(1)
            peak.append(len(live))
            time.sleep(0.05)
            live.pop()
            return {"verdict": "ok", "provider": "x"}

        teams.run([teams.Assignment(f"r{i}", "q") for i in range(6)],
                  worker=worker, parallel=99)
        self.assertLessEqual(max(peak), agents.MAX_PARALLEL,
                             f"ran {max(peak)} at once")

    def test_the_halt_switch_stops_a_team_before_it_starts(self):
        with mock.patch("aletheia.policy.halted", lambda: {"reason": "stop"}):
            with self.assertRaises(agents.NotPermitted):
                teams.run(self.three(),
                          worker=lambda *a, **k: self.fail("a halted team ran"))

    def test_an_empty_team_is_not_an_error(self):
        self.assertEqual(teams.run([], worker=lambda *a, **k: None), [])

    def test_a_team_that_runs_out_of_time_says_so(self):
        def slow(assignment, timeout_s=0):
            time.sleep(0.4)
            return {"verdict": "ok", "provider": "x"}

        results = teams.run([teams.Assignment(f"r{i}", "q") for i in range(4)],
                            worker=slow, deadline_s=0.01)
        self.assertEqual(len(results), 4)
        self.assertTrue(any(r["state"] == "CANCELLED" for r in results),
                        [r["state"] for r in results])


if __name__ == "__main__":
    unittest.main()
