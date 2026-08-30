import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import code_worker, project_loop


class ProjectLoopCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        patch = mock.patch.object(project_loop, "LATEST", root / "latest.json")
        patch.start(); self.addCleanup(patch.stop)

    def test_no_grant_blocks_before_portfolio_scan(self):
        with mock.patch.object(project_loop.code_trust, "active", return_value=None), \
             mock.patch.object(project_loop.portfolio, "scan_all") as scan, \
             mock.patch.object(project_loop, "reconcile_prior") as rec:
            out = project_loop.cycle()
        self.assertEqual(out["status"], "BLOCKED")
        scan.assert_not_called(); rec.assert_not_called()

    def test_daily_limit_throttles_before_new_scan_but_reconciles_old_prs(self):
        with mock.patch.object(project_loop.code_trust, "active", return_value={"id": "g"}), \
             mock.patch.object(project_loop.code_trust, "claims_since", return_value=3), \
             mock.patch.object(project_loop, "reconcile_prior", return_value=[{"status": "CI_GREEN"}]), \
             mock.patch.object(project_loop.portfolio, "scan_all") as scan:
            out = project_loop.cycle(daily_limit=3)
        self.assertEqual(out["status"], "THROTTLED")
        self.assertEqual(out["reconciled"], 1)
        scan.assert_not_called()

    def test_issue_is_real_work_source_and_only_one_attempt_runs(self):
        snapshot = {"counts": {"total": 2}, "repos": [
            {"full_name": "me/one", "private": False, "observation_complete": True,
             "health": "GREEN", "open_issues": 1},
            {"full_name": "me/two", "private": False, "observation_complete": True,
             "health": "GREEN", "open_issues": 1},
        ]}
        with mock.patch.object(project_loop.code_trust, "active", return_value={"id": "g"}), \
             mock.patch.object(project_loop.code_trust, "claims_since", return_value=0), \
             mock.patch.object(project_loop, "reconcile_prior", return_value=[]), \
             mock.patch.object(project_loop.portfolio, "scan_all", return_value=snapshot), \
             mock.patch.object(project_loop, "choose_work", side_effect=[
                 {"task_id": "issue-4", "kind": "issue", "objective": "fix issue"},
                 {"task_id": "issue-5", "kind": "issue", "objective": "fix other"},
             ]), \
             mock.patch.object(project_loop.code_worker, "prepare_pr",
                               return_value={"status": "PR_OPEN", "pr_url": "https://x/pr/1"}) as work:
            out = project_loop.cycle()
        self.assertEqual(out["status"], "WORKED")
        self.assertEqual(work.call_count, 1)

    def test_private_and_unobserved_repos_are_not_work_sources(self):
        self.assertIsNone(project_loop.choose_work(
            {"full_name": "me/private", "private": True, "observation_complete": True}, request=mock.Mock()
        ))
        self.assertIsNone(project_loop.choose_work(
            {"full_name": "me/offline", "private": False, "observation_complete": False}, request=mock.Mock()
        ))

    def test_existing_auto_pr_prevents_parallel_pr(self):
        def request(method, path, body=None):
            self.assertEqual(method, "GET")
            if "/pulls?" in path:
                return [{"head": {"ref": "thea-auto/issue-1-abc"}}]
            raise AssertionError(path)
        repo = {"full_name": "me/repo", "private": False, "observation_complete": True}
        self.assertIsNone(project_loop.choose_work(repo, request=request))

    def test_issue_selection_skips_manual_labels(self):
        def request(method, path, body=None):
            if "/pulls?" in path:
                return []
            if "/issues?" in path:
                return [
                    {"number": 1, "title": "do by hand", "labels": [{"name": "manual-only"}]},
                    {"number": 2, "title": "small bug", "body": "breaks startup", "labels": []},
                ]
            return {"workflow_runs": []}
        repo = {"full_name": "me/repo", "private": False, "observation_complete": True}
        work = project_loop.choose_work(repo, request=request)
        self.assertEqual(work["task_id"], "issue-2")
        self.assertIn("small bug", work["objective"])

    def test_ci_failure_supplies_failed_job_names_without_editing_workflow(self):
        def request(method, path, body=None):
            if "/pulls?" in path: return []
            if "/issues?" in path: return []
            if path.endswith("/actions/runs?per_page=20"):
                return {"workflow_runs": [{"id": 9, "name": "ci", "status": "completed", "conclusion": "failure"}]}
            if "/actions/runs/9/jobs" in path:
                return {"jobs": [{"name": "test", "conclusion": "failure",
                                   "steps": [{"name": "pytest", "conclusion": "failure"}]}]}
            raise AssertionError(path)
        repo = {"full_name": "me/repo", "private": False, "observation_complete": True}
        work = project_loop.choose_work(repo, request=request)
        self.assertEqual(work["task_id"], "ci-9")
        self.assertIn("test: pytest", work["objective"])
        self.assertIn("Do not edit GitHub workflow files", work["objective"])

    def test_reconcile_uses_external_evidence_but_does_not_merge(self):
        with mock.patch.object(code_worker, "RUNS_DIR", Path(self.tmp.name) / "runs"):
            self.assertEqual(project_loop.reconcile_prior(request=mock.Mock()), [])


if __name__ == "__main__":
    unittest.main()
