"""Live 2026-09-23, 17:34 on his PC: a pull's rebase failed on an index.lock
another git process held, the abort that followed failed on the same lock,
and `.git/rebase-merge/` was left holding one file, `autostash`. `git
status` said "You are currently rebasing"; the sync said "leaving it alone
until whoever started it is finished"; every merge for six hours sat on the
remote, seven commits behind, while the page said everything was running.

Every case here is against a real local bare repo: no mocks, no network.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from aletheia import sync
from aletheia.sync import GitSync

SNAP = "state/pulse/latest.json"


def run(args, cwd):
    return subprocess.run(args, cwd=str(cwd), check=True, capture_output=True, text=True)


class HuskCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.origin = base / "origin.git"
        run(["git", "init", "--bare", "-b", "main", str(self.origin)], base)
        self.relay, self.pc = base / "relay", base / "pc"
        for clone in (self.relay, self.pc):
            run(["git", "clone", str(self.origin), str(clone)], base)
            run(["git", "config", "user.email", "test@test"], clone)
            run(["git", "config", "user.name", "test"], clone)
        (self.relay / SNAP).parent.mkdir(parents=True, exist_ok=True)
        (self.relay / SNAP).write_text('{"n": 1}\n', encoding="utf-8")
        run(["git", "add", "."], self.relay)
        run(["git", "commit", "-m", "seed"], self.relay)
        run(["git", "push", "origin", "main"], self.relay)
        run(["git", "pull", "origin", "main"], self.pc)
        self.sync = GitSync(repo_root=self.pc, branch="main")
        self.git_dir = self.pc / ".git"

    def tearDown(self):
        self.tmp.cleanup()

    def relay_moves_on(self):
        (self.relay / SNAP).write_text('{"n": 2}\n', encoding="utf-8")
        run(["git", "add", "."], self.relay)
        run(["git", "commit", "-m", "relay: pulse"], self.relay)
        run(["git", "push", "origin", "main"], self.relay)

    def husk(self, name="rebase-merge"):
        d = self.git_dir / name
        d.mkdir()
        (d / "autostash").write_text("0" * 40 + "\n", encoding="utf-8")
        return d

    def test_the_husk_reads_as_a_rebase_until_it_is_cleared(self):
        self.husk()
        self.assertTrue(self.sync.merge_in_progress(), "exactly what git status says")
        self.assertIn("in progress", self.sync.blocking_reason() or "")
        notes = self.sync.heal_stale_git_state()
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("husk of an aborted rebase", notes[0])
        self.assertFalse((self.git_dir / "rebase-merge").exists())
        self.assertFalse(self.sync.merge_in_progress())

    def test_the_pull_lands_through_the_husk(self):
        self.relay_moves_on()
        self.husk()
        ok, detail = self.sync.pull()
        self.assertTrue(ok, detail)
        self.assertIn("husk", detail)
        self.assertEqual((self.pc / SNAP).read_text(encoding="utf-8"), '{"n": 2}\n')
        self.assertFalse(self.sync.merge_in_progress())

    def test_a_real_rebase_is_left_alone(self):
        d = self.husk()
        (d / "head-name").write_text("refs/heads/main\n", encoding="utf-8")
        self.assertEqual(self.sync.heal_stale_git_state(), [])
        self.assertTrue(d.exists(), "somebody's rebase, or her own mid-flight")
        self.assertTrue(self.sync.merge_in_progress())

    def test_a_lock_nobody_holds_is_removed_and_a_fresh_one_is_kept(self):
        lock = self.git_dir / "index.lock"
        lock.write_text("", encoding="utf-8")
        self.assertEqual(self.sync.heal_stale_git_state(), [], "a lock a moment old may be a live git")
        self.assertTrue(lock.exists())
        old = time.time() - sync.LOCK_STALE_S - 120
        os.utime(lock, (old, old))
        notes = self.sync.heal_stale_git_state()
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("index.lock nobody had held", notes[0])
        self.assertFalse(lock.exists())

    def test_the_checkpoint_is_not_skipped_for_a_husk(self):
        self.husk()
        (self.pc / SNAP).write_text('{"n": 3}\n', encoding="utf-8")
        ok, detail = self.sync.commit([SNAP], "core: state checkpoint")
        self.assertTrue(ok, detail)
        self.assertEqual(detail, "committed")


if __name__ == "__main__":
    unittest.main()
