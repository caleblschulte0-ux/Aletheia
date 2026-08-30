"""Regression coverage for interrupted upstream-merge recovery."""
from __future__ import annotations

import subprocess
import shutil
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
        self.assertIn('@("rebase", "--autostash", "origin/main")', script)
        self.assertIn('config", "pull.rebase", "true', script)
        self.assertIn("Foreign-Working-Paths", script)
        self.assertIn('"AletheiaProjects"', script)
        self.assertIn("Resolve-Legacy-Journal-Rebase", script)
        self.assertIn('"checkout-index", "--stage=all"', script)
        self.assertIn('"merge-file", "--union"', script)
        self.assertIn('core.editor=true', script)
        self.assertIn('"core: state checkpoint"', script)
        self.assertIn('$conflicts.Count -ne 1', script)
        self.assertIn('Invoke-GitCapture -GitArgs @("rebase", "--abort")', script)
        self.assertIn('"Applied autostash"', script)
        self.assertIn('$code = $LASTEXITCODE', script)


class LegacyJournalUnionCase(unittest.TestCase):
    """The exact Git plumbing used by the Windows recovery preserves both tails."""

    def test_union_resolution_preserves_cloud_and_legacy_pc_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            origin = root / "origin.git"
            run(["git", "init", "--bare", "-b", "main", str(origin)], root)
            cloud = root / "cloud"
            pc = root / "pc"
            for clone in (cloud, pc):
                run(["git", "clone", str(origin), str(clone)], root)
                run(["git", "config", "user.email", "test@test"], clone)
                run(["git", "config", "user.name", "test"], clone)

            journal = cloud / "state" / "journal" / "journal.jsonl"
            journal.parent.mkdir(parents=True)
            journal.write_text('{"text":"base"}\n', encoding="utf-8")
            run(["git", "add", "."], cloud)
            run(["git", "commit", "-m", "seed"], cloud)
            run(["git", "push", "origin", "main"], cloud)
            run(["git", "pull", "origin", "main"], pc)

            pc_journal = pc / "state" / "journal" / "journal.jsonl"
            with pc_journal.open("a", encoding="utf-8") as handle:
                handle.write('{"text":"legacy pc"}\n')
            run(["git", "add", str(pc_journal.relative_to(pc))], pc)
            run(["git", "commit", "-m", "core: state checkpoint"], pc)

            with journal.open("a", encoding="utf-8") as handle:
                handle.write('{"text":"cloud"}\n')
            run(["git", "add", str(journal.relative_to(cloud))], cloud)
            run(["git", "commit", "-m", "cloud journal"], cloud)
            run(["git", "push", "origin", "main"], cloud)
            run(["git", "fetch", "origin", "main"], pc)

            conflicted = subprocess.run(
                ["git", "rebase", "origin/main"], cwd=pc,
                capture_output=True, text=True,
            )
            self.assertNotEqual(conflicted.returncode, 0)
            # Match the PowerShell wrapper: it runs from outside the checkout
            # and relies on git -C to place/resolve the temporary stage files.
            stages = run([
                "git", "-C", str(pc), "checkout-index", "--stage=all", "--temp", "--",
                "state/journal/journal.jsonl",
            ], root).stdout.strip().split()
            self.assertGreaterEqual(len(stages), 3)
            merged, base, legacy = (pc / stages[1], pc / stages[0], pc / stages[2])
            union = subprocess.run(
                ["git", "merge-file", "--union", str(merged), str(base), str(legacy)],
                cwd=pc, capture_output=True, text=True,
            )
            self.assertLessEqual(union.returncode, 1)
            shutil.copyfile(merged, pc_journal)
            for path in (merged, base, legacy):
                path.unlink(missing_ok=True)
            run(["git", "add", "state/journal/journal.jsonl"], pc)
            run(["git", "-c", "core.editor=true", "rebase", "--continue"], pc)

            recovered = pc_journal.read_text(encoding="utf-8")
            self.assertIn('"legacy pc"', recovered)
            self.assertIn('"cloud"', recovered)
            ancestor = subprocess.run(
                ["git", "merge-base", "--is-ancestor", "origin/main", "HEAD"],
                cwd=pc,
            )
            self.assertEqual(ancestor.returncode, 0)


if __name__ == "__main__":
    unittest.main()
