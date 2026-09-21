"""Her own code, readable and nothing more.

The brief (docs/JARVIS_BRIEF.md §2): repo.list / search / read / symbol /
status / diff / log are read-only, confined to the repository, and use no
subprocess beyond read-only git. These tests hold the confinement (only
TRACKED files, so private state, untracked secrets and anything outside
the repository are unreachable), the bounds, and the flags the descriptors
carry. They run against a scratch repository, never the real one.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import intercom, repo_tools, tools

HAVE_GIT = shutil.which("git") is not None


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class RepoToolsReadATrackedRepository(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="repo-tools-"))
        root = cls.tmp / "repo"
        (root / "pkg").mkdir(parents=True)
        (root / "state" / "private").mkdir(parents=True)
        (root / "pkg" / "mod.py").write_text(
            'LIMIT = 3\n\n\ndef widget(x):\n    """Make a widget."""\n    return x  # captcha wall\n\n\n'
            "class Gadget:\n    pass\n", encoding="utf-8")
        (root / "README.md").write_text("hello\nCaptcha handoff lives here\n", encoding="utf-8")
        (root / ".gitignore").write_text("state/private/\n", encoding="utf-8")
        (root / "state" / "private" / "answers.json").write_text('{"ssn": "captcha"}', encoding="utf-8")
        _git(root, "init", "-q")
        _git(root, "config", "user.email", "t@example.com")
        _git(root, "config", "user.name", "t")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "first commit")
        (root / "secret.env").write_text("TOKEN=captcha\n", encoding="utf-8")   # untracked
        (root / "README.md").write_text("hello\nCaptcha handoff lives here\nchanged\n", encoding="utf-8")
        cls.root = root

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        patcher = mock.patch.object(repo_tools, "root", lambda: self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        repo_tools._LS.update({"at": 0.0, "root": None, "files": None})
        repo_tools._SYMBOLS.update({"key": None, "index": None})

    def run_tool(self, name, args):
        return tools.get(name).handler(args)

    def test_list_shows_only_tracked_files(self):
        out = self.run_tool("repo.list", {})
        self.assertIn("README.md", out["files"])
        self.assertNotIn("secret.env", out["files"])
        self.assertIn("pkg", out["folders"])
        self.assertNotIn("state", out["folders"])      # only ignored files live there

    def test_search_never_reaches_private_or_untracked_files(self):
        out = self.run_tool("repo.search", {"query": "captcha"})
        paths = {h["path"] for h in out["hits"]}
        self.assertEqual(paths, {"pkg/mod.py", "README.md"})
        self.assertTrue(all(isinstance(h["line"], int) for h in out["hits"]))

    def test_search_that_finds_nothing_says_what_that_means(self):
        out = self.run_tool("repo.search", {"query": "no such words here"})
        self.assertEqual(out["matched"], 0)
        self.assertIn("not proof", out["note"])

    def test_read_is_numbered_and_bounded(self):
        out = self.run_tool("repo.read", {"path": "pkg/mod.py", "start": 4, "lines": 2})
        self.assertEqual(out["text"].splitlines(), ['4: def widget(x):', '5:     """Make a widget."""'])
        self.assertTrue(out["more"])

    def test_read_refuses_everything_outside_the_tracked_set(self):
        for path in ("state/private/answers.json", "secret.env", "../outside.txt",
                     "C:/Windows/win.ini", "/etc/passwd", ".git/config"):
            with self.subTest(path=path):
                out = self.run_tool("repo.read", {"path": path})
                self.assertIn("error", out)
                self.assertNotIn("text", out)

    def test_symbol_finds_functions_classes_and_constants(self):
        self.assertEqual(self.run_tool("repo.symbol", {"name": "widget"})["definitions"][0]["line"], 4)
        self.assertEqual(self.run_tool("repo.symbol", {"name": "Gadget"})["definitions"][0]["kind"], "class")
        self.assertEqual(self.run_tool("repo.symbol", {"name": "mod.LIMIT"})["definitions"][0]["kind"], "constant")
        self.assertIn("error", self.run_tool("repo.symbol", {"name": "x; rm -rf"}))

    def test_status_diff_and_log(self):
        status = self.run_tool("repo.status", {})
        self.assertTrue(status["dirty"])
        self.assertEqual(status["changed"], ["README.md"])
        diff = self.run_tool("repo.diff", {})
        self.assertIn("+changed", diff["patch"])
        log = self.run_tool("repo.log", {"n": 5})
        self.assertEqual(log["commits"][0]["subject"], "first commit")

    def test_a_revision_that_looks_like_an_option_is_refused(self):
        for ref in ("--output=x", "-p", "HEAD;echo", "a..b"):
            with self.subTest(ref=ref):
                self.assertIn("error", self.run_tool("repo.diff", {"against": ref}))

    def test_status_does_not_take_the_index_lock(self):
        with mock.patch.object(repo_tools.subprocess, "run", wraps=subprocess.run) as spy:
            self.run_tool("repo.status", {})
        for call in spy.call_args_list:
            self.assertEqual(call.kwargs["env"]["GIT_OPTIONAL_LOCKS"], "0")
            self.assertEqual(call.args[0][:2], ["git", "--no-pager"])
            self.assertNotIn(call.args[0][2], ("add", "commit", "checkout", "reset", "push",
                                               "stash", "apply", "rm", "mv", "clean"))


#: The brief's "propose" step: a record (runs) and a throwaway-worktree trial
#: (handed off). Held by their own test below, not by the read-only rule.
PROPOSING = {"repo.propose_patch", "repo.try_patch"}


class TheRepoDescriptorsAreReadOnly(unittest.TestCase):
    def test_every_repo_tool_reads_and_the_local_model_sees_it(self):
        catalog = tools.catalog(fresh=True)
        names = {n for n in catalog if n.startswith("repo.")} - PROPOSING
        self.assertEqual(names, {"repo.list", "repo.search", "repo.read", "repo.symbol",
                                 "repo.status", "repo.diff", "repo.log"})
        for name in names:
            tool = catalog[name]
            with self.subTest(tool=name):
                self.assertTrue(tool.read_only)
                self.assertFalse(tool.destructive)
                self.assertEqual(tool.risk, intercom.TIER_READ)
                self.assertEqual(tool.writes, ())
                self.assertEqual(tool.approval, "none")
                self.assertTrue(tool.local_model_visible)
                self.assertEqual(tool.provenance, tools.TRUSTED_LOCAL_STATE)
        shown = {t["name"] for t in tools.for_model("local")["tools"]}
        self.assertTrue(names <= shown)

    def test_no_change_or_pr_tool_exists_yet(self):
        """Proposing is here (wave 3b); CHANGING her running code and opening a
        pull request are still different privileges, and do not exist."""
        catalog = tools.catalog(fresh=True)
        self.assertFalse({"repo.change", "repo.open_pr"} & set(catalog))

    def test_proposing_never_runs_anything_but_a_record_inside_a_session(self):
        from aletheia import agent_session
        catalog = tools.catalog(fresh=True)
        propose, trial = catalog["repo.propose_patch"], catalog["repo.try_patch"]
        self.assertTrue(propose.record_only)
        self.assertEqual(propose.writes, ("patch-proposals",))
        self.assertFalse(trial.record_only)
        self.assertEqual(trial.approval, "operator_once")
        broker = agent_session.Broker(catalog, halted=lambda: False)
        self.assertEqual(broker.check(agent_session.ToolRequest(
            "repo.try_patch", {"proposal": "patch-x"})).verdict, agent_session.HANDOFF)


if __name__ == "__main__":
    unittest.main()
