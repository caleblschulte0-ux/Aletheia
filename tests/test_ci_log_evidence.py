"""A CI repair needs the error, not the job's name (2026-09-02).

The first live sweeps declined every CI failure — correctly — because the
only evidence was "sell-brain: Run the sell brain". The failing job's log
is fetched (without forwarding the GitHub token to blob storage, which
answers 401 when it is), timestamps are stripped, and the window is
anchored on the last error-shaped line rather than the cleanup boilerplate
every log ends with.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import code_worker, journal, policy, project_loop


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d / "private")})
        env.start(); self.addCleanup(env.stop)
        for target, attr, value in (
                (journal, "JOURNAL_PATH", d / "journal.jsonl"),
                (policy, "HALT_PATH", d / "halt.json"),
                (code_worker, "RUNS_DIR", d / "runs")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)


REPO = {"full_name": "me/repo", "private": False, "observation_complete": True}


class ACiRepairSeesTheLog(Isolated):
    def test_the_failing_jobs_log_is_evidence(self):
        def request(method, path, body=None):
            if "/pulls?" in path or "/issues?" in path:
                return []
            if path.endswith("/actions/runs?per_page=20"):
                return {"workflow_runs": [{"id": 77, "status": "completed", "conclusion": "failure"}]}
            if "/actions/runs/77/jobs" in path:
                return {"jobs": [{"id": 900, "name": "test", "conclusion": "failure",
                                  "steps": [{"name": "Run tests", "conclusion": "failure"}]}]}
            raise AssertionError(path)

        lines = [f"2026-09-02T10:00:{i % 60:02d}.000Z line {i}" for i in range(200)]
        lines.append("2026-09-02T10:03:20.000Z AssertionError: expected 2 got 1")
        lines.append("2026-09-02T10:03:21.000Z ##[error]Process completed with exit code 1.")
        lines += ["2026-09-02T10:03:22.000Z Post job cleanup."] * 100

        def request_text(path):
            self.assertEqual(path, "/repos/me/repo/actions/jobs/900/logs")
            return "\n".join(lines)

        work = project_loop._ci_work(REPO, request=request, request_text=request_text)
        self.assertEqual(work["task_id"], "ci-77")
        self.assertIn("AssertionError: expected 2 got 1", work["evidence"])
        self.assertNotIn("2026-09-02T10:03:20", work["evidence"], "timestamps stripped")
        self.assertNotIn("line 5\n", work["evidence"], "only the window around the error")
        self.assertLessEqual(len(work["evidence"]), code_worker.MAX_EVIDENCE_CHARS)

    def test_the_window_is_anchored_on_the_error_not_the_cleanup(self):
        log = ["step %d ok" % i for i in range(150)]
        log += ["Traceback (most recent call last):", "  File x.py", "KeyError: 'price'",
                "##[error]Process completed with exit code 1."]
        log += ["Post job cleanup.", "Cleaning up orphan processes"] * 60
        tail = project_loop._job_log_tail("me%2Frepo", 1, request_text=lambda p: "\n".join(log))
        self.assertIn("KeyError: 'price'", tail)
        self.assertIn("exit code 1", tail)

    def test_a_declined_run_is_not_asked_again(self):
        code_worker._save_run("me/repo", "ci-77", {"version": 1, "status": "DECLINED",
                                                   "repo": "me/repo", "task_id": "ci-77"})

        def request(method, path, body=None):
            if "/pulls?" in path or "/issues?" in path:
                return []
            if path.endswith("/actions/runs?per_page=20"):
                return {"workflow_runs": [{"id": 77, "status": "completed", "conclusion": "failure"}]}
            raise AssertionError(path)
        self.assertIsNone(project_loop._ci_work(REPO, request=request, request_text=lambda p: ""))

    def test_a_withheld_log_costs_only_the_evidence(self):
        def boom(path):
            raise RuntimeError("410 gone")
        self.assertEqual(project_loop._job_log_tail("me%2Frepo", 1, request_text=boom), "")

    def test_the_token_is_not_forwarded_to_blob_storage(self):
        from aletheia import gh
        import urllib.request
        handler = gh._NoAuthOnRedirect()
        req = urllib.request.Request("https://api.github.com/x", headers={"Authorization": "Bearer t"})
        follow = handler.redirect_request(req, None, 302, "Found", {}, "https://blob.test/log")
        self.assertIsNotNone(follow)
        self.assertFalse(follow.has_header("Authorization"))


if __name__ == "__main__":
    unittest.main()
