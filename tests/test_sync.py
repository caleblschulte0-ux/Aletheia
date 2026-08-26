"""GitSync against a real local bare repo — no mocks, no network.

The scenario under test is the Core's actual life: ChatGPT's relay pushes
a command from one clone, the Core pulls it in another, writes a receipt,
and pushes it back — including the race where both sides pushed.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

from aletheia.sync import GitSync


def run(args, cwd):
    subprocess.run(args, cwd=str(cwd), check=True, capture_output=True, text=True)


class GitSyncCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.origin = base / "origin.git"
        run(["git", "init", "--bare", "-b", "main", str(self.origin)], base)
        self.relay = base / "relay"   # stands in for the Actions/ChatGPT side
        self.pc = base / "pc"         # stands in for the Core on the PC
        for clone in (self.relay, self.pc):
            run(["git", "clone", str(self.origin), str(clone)], base)
            run(["git", "config", "user.email", "test@test"], clone)
            run(["git", "config", "user.name", "test"], clone)
        (self.relay / "seed.txt").write_text("seed\n")
        run(["git", "add", "."], self.relay)
        run(["git", "commit", "-m", "seed"], self.relay)
        run(["git", "push", "origin", "main"], self.relay)
        run(["git", "pull", "origin", "main"], self.pc)
        self.sync = GitSync(repo_root=self.pc, branch="main")

    def tearDown(self):
        self.tmp.cleanup()

    def relay_pushes(self, name, content="x\n"):
        (self.relay / name).write_text(content)
        run(["git", "add", "."], self.relay)
        run(["git", "commit", "-m", f"relay: {name}"], self.relay)
        run(["git", "push", "origin", "main"], self.relay)

    def test_available_and_not_a_repo(self):
        ok, detail = self.sync.available()
        self.assertTrue(ok, detail)
        bad = GitSync(repo_root=Path(self.tmp.name) / "nowhere", branch="main")
        ok, detail = bad.available()
        self.assertFalse(ok)

    def test_pull_sees_a_new_command(self):
        self.relay_pushes("command.json")
        ok, detail = self.sync.pull()
        self.assertTrue(ok, detail)
        self.assertTrue((self.pc / "command.json").exists())

    def test_commit_push_roundtrip(self):
        (self.pc / "receipt.json").write_text("{}\n")
        ok, detail = self.sync.commit_push(["receipt.json"], "core: receipt")
        self.assertTrue(ok, detail)
        run(["git", "pull", "origin", "main"], self.relay)
        self.assertTrue((self.relay / "receipt.json").exists())

    def test_commit_push_stages_only_named_paths(self):
        (self.pc / "receipt.json").write_text("{}\n")
        (self.pc / "operator-scratch.txt").write_text("do not commit me\n")
        ok, detail = self.sync.commit_push(["receipt.json"], "core: receipt")
        self.assertTrue(ok, detail)
        out = subprocess.run(["git", "status", "--porcelain"], cwd=str(self.pc),
                             capture_output=True, text=True).stdout
        self.assertIn("operator-scratch.txt", out)

    def test_nothing_to_commit_is_ok_not_error(self):
        ok, detail = self.sync.commit_push(["seed.txt"], "no-op")
        self.assertTrue(ok)
        self.assertEqual(detail, "nothing to commit")

    def test_rejected_push_rebases_and_retries(self):
        # both sides commit; the PC's push is rejected, must rebase and win
        self.relay_pushes("relay-first.json")
        (self.pc / "receipt.json").write_text("{}\n")
        ok, detail = self.sync.commit_push(["receipt.json"], "core: receipt")
        self.assertTrue(ok, detail)
        run(["git", "pull", "origin", "main"], self.relay)
        self.assertTrue((self.relay / "receipt.json").exists())
        self.assertTrue((self.relay / "relay-first.json").exists())

    def test_rebase_conflict_aborts_cleanly(self):
        # same file, different content on both sides -> conflict, clean abort
        self.relay_pushes("clash.txt", "relay version\n")
        (self.pc / "clash.txt").write_text("pc version\n")
        run(["git", "add", "."], self.pc)
        run(["git", "commit", "-m", "pc: clash"], self.pc)
        ok, detail = self.sync.pull()
        self.assertFalse(ok)
        self.assertIn("aborted cleanly", detail)
        # tree must not be mid-rebase: normal git operations still work
        out = subprocess.run(["git", "status"], cwd=str(self.pc),
                             capture_output=True, text=True).stdout
        self.assertNotIn("rebase in progress", out)


if __name__ == "__main__":
    unittest.main()
