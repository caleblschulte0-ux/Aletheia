"""Live 2026-09-23: nine merges sat on the remote for six hours while the
page said everything was running. Two holes, both closed here: a pull the
sync refused ("a rebase is in progress") never fetched, so the Core never
learned it was behind; and `running.version()` cached "0 behind" against a
signature that cannot see a remote-tracking ref move (a fetch from a
worktree of the same repository moves the ref and nothing else).

Every case here is against a real local bare repo: no mocks, no network.
"""
from __future__ import annotations

import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from aletheia import running
from aletheia.sync import GitSync

SNAP = "state/pulse/latest.json"


def run(args, cwd):
    return subprocess.run(args, cwd=str(cwd), check=True, capture_output=True, text=True)


def git_out(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True).stdout.strip()


class BlockedButFetched(unittest.TestCase):
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

    def tearDown(self):
        self.tmp.cleanup()

    def relay_moves_on(self):
        (self.relay / SNAP).write_text('{"n": 2}\n', encoding="utf-8")
        run(["git", "add", "."], self.relay)
        run(["git", "commit", "-m", "relay: pulse"], self.relay)
        run(["git", "push", "origin", "main"], self.relay)

    def test_a_refused_pull_still_learns_it_is_behind(self):
        self.relay_moves_on()
        # A person's uncommitted file: the tree is not the Core's to rebase.
        (self.pc / "notes.md").write_text("mine\n", encoding="utf-8")
        ok, detail = self.sync.pull()
        self.assertFalse(ok)
        self.assertIn("refusing", detail)
        self.assertEqual(git_out(["rev-list", "--count", "HEAD..origin/main"], self.pc), "1",
                         "refused is refused; the fetch still happened, so behind is known")
        self.assertEqual((self.pc / SNAP).read_text(encoding="utf-8"), '{"n": 1}\n', "nothing was rebased")

    def test_the_version_signature_sees_a_remote_ref_move(self):
        before = running._git_signature(self.pc)
        time.sleep(0.05)
        self.relay_moves_on()
        run(["git", "fetch", "origin", "main"], self.pc)
        # Hold FETCH_HEAD, HEAD and packed-refs still: the ref is the only
        # thing that moved, exactly as a fetch from a worktree leaves it.
        for name in ("FETCH_HEAD", "HEAD", "packed-refs"):
            path = self.pc / ".git" / name
            if path.exists():
                stamp = dict(before).get(name)
                if stamp:
                    import os
                    os.utime(path, ns=(stamp, stamp))
        after = running._git_signature(self.pc)
        self.assertNotEqual(before, after, "a moved remote-tracking ref is a new answer")


if __name__ == "__main__":
    unittest.main()
