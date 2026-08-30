import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import portfolio


NOW = dt.datetime(2026, 8, 30, 3, 0, tzinfo=dt.timezone.utc)


class PortfolioCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        patch = mock.patch.object(portfolio, "LATEST", self.root / "latest.json")
        patch.start(); self.addCleanup(patch.stop)
        self.fleet = {
            "owner": "caleb",
            "repos": {
                "known": {"github": "Known", "default_branch": "main", "summary": "known"}
            },
        }

    def request(self, method, path):
        self.assertEqual(method, "GET")
        if path.startswith("/users/caleb/repos"):
            return [
                {"name": "Known", "full_name": "caleb/Known", "private": False,
                 "archived": False, "default_branch": "main",
                 "updated_at": "2026-08-29T00:00:00Z", "description": "live"},
                {"name": "New", "full_name": "caleb/New", "private": False,
                 "archived": False, "default_branch": "main",
                 "updated_at": "2026-08-28T00:00:00Z", "description": "new"},
                {"name": "Old", "full_name": "caleb/Old", "private": False,
                 "archived": False, "default_branch": "main",
                 "updated_at": "2024-01-01T00:00:00Z", "description": "old"},
            ]
        if path.startswith("/repos/caleb/Known/commits/"):
            return {"commit": {"author": {"date": "2026-08-29T00:00:00Z"}}}
        if path.startswith("/repos/caleb/New/commits/"):
            return {"commit": {"author": {"date": "2026-06-01T00:00:00Z"}}}
        if path == "/repos/caleb/Known":
            return {"private": False, "default_branch": "main", "updated_at": "2026-08-29T00:00:00Z"}
        if path == "/repos/caleb/New":
            return {"private": False, "default_branch": "main", "updated_at": "2026-08-28T00:00:00Z"}
        if path.startswith("/repos/caleb/Known/pulls"):
            return []
        if path.startswith("/repos/caleb/New/pulls"):
            return [{"created_at": "2026-08-01T00:00:00Z"}]
        if path.startswith("/repos/caleb/Known/issues"):
            return []
        if path.startswith("/repos/caleb/New/issues"):
            return [{"number": 1}]
        if path.startswith("/repos/caleb/Known/actions/runs"):
            return {"workflow_runs": []}
        if path.startswith("/repos/caleb/New/actions/runs"):
            return {"workflow_runs": [
                {"status": "completed", "conclusion": "failure", "name": "ci",
                 "updated_at": "2026-08-29T02:00:00Z"}
            ]}
        return []

    def test_discovers_fleet_and_recent_owner_repos_but_not_abandoned_history(self):
        with mock.patch.object(portfolio.gh, "token", return_value=None):
            rows = portfolio.discover(fleet=self.fleet, request=self.request, now=NOW)
        self.assertEqual({r["name"] for r in rows}, {"Known", "New"})

    def test_scan_marks_failed_ci_red_and_persists_private_local_snapshot(self):
        with mock.patch.object(portfolio.gh, "token", return_value=None):
            snap = portfolio.scan_all(fleet=self.fleet, request=self.request, now=NOW)
        rows = {r["name"]: r for r in snap["repos"]}
        self.assertEqual(rows["Known"]["health"], "GREEN")
        self.assertEqual(rows["New"]["health"], "RED")
        self.assertEqual(rows["New"]["recent_failed_runs"], 1)
        self.assertTrue(portfolio.LATEST.exists())

    def test_private_repo_name_never_appears_in_public_summary(self):
        snap = {"counts": {"total": 2, "red": 1, "yellow": 0, "green": 1}, "repos": [
            {"name": "Public", "private": False, "health": "GREEN", "health_score": 100, "problems": []},
            {"name": "SecretProject", "private": True, "health": "RED", "health_score": 10,
             "problems": [{"detail": "private failure"}]},
        ]}
        text = portfolio.public_summary(snap)
        self.assertNotIn("SecretProject", text)
        self.assertNotIn("private failure", text)
        self.assertIn("1 private project", text)

    def test_github_failures_degrade_to_partial_snapshot_instead_of_inventing(self):
        def broken(method, path):
            raise OSError("offline")
        with mock.patch.object(portfolio.gh, "token", return_value=None):
            snap = portfolio.scan_all(fleet=self.fleet, request=broken, now=NOW)
        self.assertEqual(snap["counts"]["total"], 1)
        row = snap["repos"][0]
        self.assertEqual(row["name"], "Known")
        self.assertEqual(row["open_prs"], 0)
        self.assertEqual(row["recent_failed_runs"], 0)


if __name__ == "__main__":
    unittest.main()
