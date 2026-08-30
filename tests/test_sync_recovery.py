"""Regression coverage for interrupted upstream-merge recovery."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from aletheia.sync import GitSync


def run(args, cwd):
    return subprocess.run(
        args, cwd=str(cwd), check=True, capture_output=True, text=True
    )


class UpstreamMergeRecoveryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.origin = base / "origin.git"
        run(["git", "init", "--bare", "-b", "main", str(self.origin)], base)
        self.relay = base / "relay"
        self.pc = base / "pc"
        for clone in (self.relay, self.pc):
            run(["git", "clone", str(self.origin), str(clone)], base)
            run(["git", "config", "user.email", "test@test"], clone)
            run(["git", "config", "user.name", "test"], clone)

        (self.relay / "seed.txt").write_text("seed\n", encoding="utf-8")
        run(["git", "add", "."], self.relay)
        run(["git", "commit", "-m", "seed"], self.relay)
        run(["git", "push", "origin", "main"], self.relay)
        run(["git", "pull", "origin", "main"], self.pc)
        self.sync = GitSync(repo_root=self.pc, branch="main")

    def tearDown(self):
        self.tmp.cleanup()

    def _diverge(self):
        state = self.pc / "state"
        state.mkdir(exist_ok=True)
        (state / "pc.json").write_text("pc\n", encoding="utf-8")
        run(["git", "add", "state/pc.json"], self.pc)
        run(["git", "commit", "-m", "core: state checkpoint"], self.pc)

        (self.relay / "remote-code.txt").write_text("remote\n", encoding="utf-8")
        run(["git", "add", "remote-code.txt"], self.relay)
        run(["git", "commit", "-m", "remote code"], self.relay)
        run(["git", "push", "origin", "main"], self.relay)
        run(["git", "fetch", "origin", "main"], self.pc)

    def _begin_clean_merge(self, message):
        run(["git", "merge", "--no-commit", "-m", message, "origin/main"], self.pc)
        self.assertTrue((self.pc / ".git" / "MERGE_HEAD").exists())

    def test_plain_pull_editor_merge_is_aborted_then_rebased(self):
        self._diverge()
        self._begin_clean_merge(
            "Merge branch 'main' of https://github.com/example/Aletheia"
        )

        ok, detail = self.sync.pull()

        self.assertTrue(ok, detail)
        self.assertIn("aborted editor-only upstream merge", detail)
        self.assertFalse((self.pc / ".git" / "MERGE_HEAD").exists())
        self.assertEqual(
            (self.pc / "state" / "pc.json").read_text(encoding="utf-8"), "pc\n"
        )
        self.assertEqual(
            (self.pc / "remote-code.txt").read_text(encoding="utf-8"), "remote\n"
        )
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", "origin/main", "HEAD"],
            cwd=str(self.pc), capture_output=True, text=True,
        )
        self.assertEqual(ancestor.returncode, 0)

    def test_manual_merge_is_still_left_alone(self):
        self._diverge()
        self._begin_clean_merge("Manual merge for deliberate operator work")

        ok, detail = self.sync.pull()

        self.assertFalse(ok)
        self.assertIn("not created by a plain upstream pull", detail)
        self.assertTrue((self.pc / ".git" / "MERGE_HEAD").exists())


class RecoveryScriptContractCase(unittest.TestCase):
    def test_script_is_bounded_and_never_hard_resets(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "recover_operator_checkout.ps1"
        ).read_text(encoding="utf-8")
        lower = script.lower()
        self.assertNotIn("reset --hard", lower)
        self.assertNotIn("checkout -f", lower)
        self.assertIn('merge", "--abort', script)
        self.assertIn("rebase --autostash origin/main", script)
        self.assertIn('config", "pull.rebase", "true', script)
        self.assertIn("Foreign-Working-Paths", script)
        self.assertIn('"AletheiaProjects"', script)


if __name__ == "__main__":
    unittest.main()
