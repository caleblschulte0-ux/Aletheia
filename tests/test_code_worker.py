import base64
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import code_worker, gh, journal


class FakeGitHub:
    def __init__(self, *, private=False):
        self.private = private
        self.posts = []
        self.files = {
            "src/app.py": "def answer():\n    return 1\n",
            "tests/test_app.py": "def test_answer():\n    assert True\n",
        }

    def __call__(self, method, path, body=None):
        if method == "POST":
            self.posts.append((path, body))
            if path.endswith("/git/blobs"):
                return {"sha": f"blob-{len(self.posts)}"}
            if path.endswith("/git/trees"):
                return {"sha": "tree-new"}
            if path.endswith("/git/commits"):
                return {"sha": "commit-new"}
            if path.endswith("/git/refs"):
                return {"ref": body["ref"]}
            if path.endswith("/pulls"):
                return {"number": 7, "html_url": "https://github.com/me/repo/pull/7"}
            raise AssertionError((method, path))
        if path == "/repos/me/repo":
            return {"private": self.private, "default_branch": "main"}
        if "/git/ref/heads/main" in path:
            return {"object": {"sha": "base-sha"}}
        if "/git/commits/base-sha" in path:
            return {"tree": {"sha": "tree-base"}}
        if "/git/trees/tree-base?recursive=1" in path:
            return {"truncated": False, "tree": [
                {"path": "src/app.py", "type": "blob", "size": 29, "mode": "100644"},
                {"path": "tests/test_app.py", "type": "blob", "size": 39, "mode": "100644"},
                {"path": ".github/workflows/ci.yml", "type": "blob", "size": 20, "mode": "100644"},
            ]}
        if "/contents/" in path:
            part = path.split("/contents/", 1)[1].split("?ref=", 1)[0]
            text = self.files[part]
            return {"encoding": "base64", "content": base64.b64encode(text.encode()).decode(),
                    "sha": "old-sha"}
        raise AssertionError((method, path, body))


class CodeWorkerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        patches = [
            mock.patch.object(code_worker, "RUNS_DIR", root / "runs"),
            mock.patch.object(journal, "JOURNAL_PATH", root / "journal.jsonl"),
            mock.patch.object(gh, "token", return_value="token"),
            mock.patch.object(code_worker.code_trust, "claim", return_value={"slot": 1}),
        ]
        for patch in patches:
            patch.start(); self.addCleanup(patch.stop)

    def proposal(self):
        return {"summary": "fix answer", "confidence": 0.9, "changes": [
            {"path": "src/app.py", "content": "def answer():\n    return 2\n", "why": "correct result"}
        ]}

    def review(self, approved=True):
        return {"approved": approved, "summary": "reviewed", "findings": [] if approved else ["bad"]}

    def test_protected_paths_are_static_refusals(self):
        self.assertTrue(code_worker.protected_path("me/repo", ".github/workflows/ci.yml"))
        self.assertTrue(code_worker.protected_path("me/Aletheia", "aletheia/policy.py"))
        self.assertFalse(code_worker.protected_path("me/repo", "src/app.py"))

    def test_private_repo_refuses_before_reasoning(self):
        api = FakeGitHub(private=True)
        with mock.patch.object(code_worker.reasoner, "subscription_json") as model:
            with self.assertRaises(code_worker.code_trust.CodeTrustRequired):
                code_worker.prepare_pr("me/repo", "fix it", task_id="issue-1", request=api)
        model.assert_not_called()
        self.assertEqual(api.posts, [])

    def test_rejected_independent_review_creates_no_git_objects(self):
        api = FakeGitHub()
        with mock.patch.object(code_worker.reasoner, "subscription_json",
                               side_effect=[self.proposal(), self.review(False)]):
            result = code_worker.prepare_pr("me/repo", "fix answer", task_id="issue-1", request=api)
        self.assertEqual(result["status"], "REVIEW_REJECTED")
        self.assertEqual(api.posts, [])

    def test_approved_review_creates_branch_and_pr_but_never_updates_default_ref(self):
        api = FakeGitHub()
        with mock.patch.object(code_worker.reasoner, "subscription_json",
                               side_effect=[self.proposal(), self.review(True)]):
            result = code_worker.prepare_pr("me/repo", "fix answer", task_id="issue-2", request=api)
        self.assertEqual(result["status"], "PR_OPEN")
        self.assertEqual(result["pr_number"], 7)
        refs = [body["ref"] for path, body in api.posts if path.endswith("/git/refs")]
        self.assertEqual(len(refs), 1)
        self.assertTrue(refs[0].startswith("refs/heads/thea-auto/"))
        self.assertNotIn("refs/heads/main", refs)
        self.assertTrue(any(path.endswith("/pulls") for path, _ in api.posts))

    def test_existing_pr_is_idempotent(self):
        api = FakeGitHub()
        with mock.patch.object(code_worker.reasoner, "subscription_json",
                               side_effect=[self.proposal(), self.review(True)]):
            first = code_worker.prepare_pr("me/repo", "fix answer", task_id="issue-3", request=api)
        posts = len(api.posts)
        second = code_worker.prepare_pr("me/repo", "fix answer", task_id="issue-3", request=api)
        self.assertEqual(first["pr_url"], second["pr_url"])
        self.assertEqual(len(api.posts), posts)


if __name__ == "__main__":
    unittest.main()


class AuthoritySurfacesAreProtected(unittest.TestCase):
    """The autonomous coder must never be able to PROPOSE widening its own
    authority. Found open in the 2026-09-01 catch-up review: config/ (the
    fleet front-door grants and every capability's approval_policy), the
    constitution, and several authority modules were all editable.

    CLAUDE.md: authority "widens only by a reviewed registry edit — never a
    code path around the check". An unattended worker opening PRs against
    the registries IS such a path, even though a human merges: the loop's
    whole premise is that it runs while nobody is watching.
    """

    REPO = "caleblschulte0-ux/Aletheia"

    MUST_BE_PROTECTED = [
        # registries — grants and approval policies live here
        "config/fleet.json", "config/capabilities.json",
        # the rules it is judged by
        "CLAUDE.md", "docs/PLAYBOOK.md", "docs/ARCHITECTURE.md",
        # roots of trust and gates
        "aletheia/policy.py", "aletheia/machine_binding.py",
        "aletheia/work_trust.py", "aletheia/secret_trust.py",
        "aletheia/code_trust.py", "aletheia/work_session.py",
        "aletheia/work_direct.py", "aletheia/sealed_observe.py",
        "aletheia/secret_store.py", "aletheia/secret_browser.py",
        "aletheia/intercom.py", "aletheia/capabilities.py",
        # the loop's own machinery and credentials
        "aletheia/code_worker.py", "aletheia/project_loop.py",
        "aletheia/github_auth.py", "aletheia/portfolio.py",
        # the always-on host, its supervisor, and what pulls code to the PC
        "aletheia/core.py", "aletheia/supervisor.py", "aletheia/sync.py",
        # agent instructions
        ".claude/settings.json", ".github/workflows/ci.yml",
        # secrets by shape, wherever they appear
        ".env", "deploy/id_rsa", "certs/server.pem",
    ]

    def test_every_authority_surface_is_refused(self):
        open_paths = [p for p in self.MUST_BE_PROTECTED
                      if not code_worker.protected_path(self.REPO, p)]
        self.assertEqual(open_paths, [],
                         "the autonomous coder could proposeedits to these "
                         "authority surfaces: " + ", ".join(open_paths))

    def test_ordinary_code_is_still_workable(self):
        """Protection must not become 'nothing may be fixed'."""
        for path in ("aletheia/ics.py", "aletheia/calendar.py", "tests/test_ics.py"):
            self.assertFalse(code_worker.protected_path(self.REPO, path), path)

    def test_protection_survives_case_and_traversal_tricks(self):
        for trick in ("CONFIG/fleet.json", "Aletheia/Policy.py",
                      "./config/fleet.json", "config//fleet.json"):
            with self.subTest(trick=trick):
                try:
                    refused = code_worker.protected_path(self.REPO, trick)
                except Exception:
                    refused = True   # rejecting the path outright is fine too
                self.assertTrue(refused, f"{trick} slipped past protection")
