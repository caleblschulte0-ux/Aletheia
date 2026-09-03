"""GitSync against a real local bare repo — no mocks, no network.

The scenario under test is the Core's actual life: ChatGPT's relay pushes
a command from one clone, the Core pulls it in another, writes a receipt,
and pushes it back — including the race where both sides pushed.
"""
import subprocess
import tempfile
import unittest
from unittest import mock
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

    def test_a_persons_staged_work_is_not_swept_into_a_checkpoint(self):
        """Observed live 2026-09-02: a session had `git add`ed a day's work
        and was waiting on the suite; the Core's checkpoint committed the
        whole index under "core: state checkpoint". Its own paths, and only
        its own paths, go in the commit — what a person staged stays staged."""
        (self.pc / "receipt.json").write_text("{}\n")
        (self.pc / "aletheia_change.py").write_text("print('mine')\n")
        run(["git", "add", "aletheia_change.py"], self.pc)
        ok, detail = self.sync.commit(["receipt.json"], "core: state checkpoint")
        self.assertEqual((ok, detail), (True, "committed"))
        shown = subprocess.run(["git", "show", "--stat", "--name-only", "HEAD"],
                               cwd=str(self.pc), capture_output=True, text=True).stdout
        self.assertIn("receipt.json", shown)
        self.assertNotIn("aletheia_change.py", shown)
        staged = subprocess.run(["git", "diff", "--cached", "--name-only"],
                                cwd=str(self.pc), capture_output=True, text=True).stdout
        self.assertIn("aletheia_change.py", staged, "still theirs to commit")

    def test_nothing_to_commit_is_ok_not_error(self):
        ok, detail = self.sync.commit_push(["seed.txt"], "no-op")
        self.assertTrue(ok)
        self.assertEqual(detail, "nothing to commit")

    def test_absent_path_does_not_strand_the_other_paths(self):
        # exchange/commands does not exist until the first command lands
        # (git stores no empty dirs). One unmatched pathspec used to fail
        # the whole `git add`, and a failed commit() short-circuits
        # commit_push() -- so the Core pushed NOTHING on a fresh clone.
        (self.pc / "receipt.json").write_text("{}")
        ok, detail = self.sync.commit_push(
            ["exchange/commands", "receipt.json"], "core: receipt")
        self.assertTrue(ok, detail)
        run(["git", "pull", "origin", "main"], self.relay)
        self.assertTrue((self.relay / "receipt.json").exists())

    def test_all_paths_absent_is_nothing_to_commit(self):
        ok, detail = self.sync.commit_push(["exchange/commands"], "core: none")
        self.assertTrue(ok, detail)
        self.assertEqual(detail, "nothing to commit")

    def test_git_never_prompts_a_human(self):
        # the daemon's git must be non-interactive: a credential-manager
        # GUI prompt hung the PC sync loop forever on 2026-08-26
        from aletheia import sync as sync_mod
        captured = {}
        real_run = sync_mod.subprocess.run

        def spy(cmd, **kwargs):
            captured.update(kwargs.get("env") or {})
            return real_run(cmd, **kwargs)

        with mock.patch.object(sync_mod.subprocess, "run", side_effect=spy):
            self.sync.pull()
        self.assertEqual(captured.get("GIT_TERMINAL_PROMPT"), "0")
        self.assertEqual(captured.get("GCM_INTERACTIVE"), "never")

    def test_rejected_push_rebases_and_retries(self):
        # both sides commit; the PC's push is rejected, must rebase and win
        self.relay_pushes("relay-first.json")
        (self.pc / "receipt.json").write_text("{}\n")
        ok, detail = self.sync.commit_push(["receipt.json"], "core: receipt")
        self.assertTrue(ok, detail)
        run(["git", "pull", "origin", "main"], self.relay)
        self.assertTrue((self.relay / "receipt.json").exists())
        self.assertTrue((self.relay / "relay-first.json").exists())

    # --- the tree is not always the Core's to rewrite (2026-08-27) ---

    def test_a_foreign_uncommitted_edit_blocks_the_rebase(self):
        # A session editing this clone had its work swept into an unwatched
        # stash by `rebase --autostash`, once a minute, for an hour.
        self.relay_pushes("newer.txt")
        work = self.pc / "half_written.py"
        work.write_text("work in progress\n")
        ok, detail = self.sync.pull()
        self.assertFalse(ok)
        self.assertIn("does not own", detail)
        self.assertIn("half_written.py", detail)
        # and the person's work is exactly where they left it
        self.assertEqual(work.read_text(), "work in progress\n")

    def test_the_cores_own_state_never_blocks_it(self):
        self.relay_pushes("newer.txt")
        (self.pc / "state").mkdir(exist_ok=True)
        (self.pc / "state" / "journal.jsonl").write_text('{"ts": "now"}\n')
        (self.pc / "exchange" / "commands").mkdir(parents=True, exist_ok=True)
        (self.pc / "exchange" / "commands" / "c1.json").write_text("{}\n")
        self.assertIsNone(self.sync.blocking_reason())
        ok, detail = self.sync.pull()
        self.assertTrue(ok, detail)

    def test_a_different_checked_out_branch_blocks_the_rebase(self):
        run(["git", "checkout", "-b", "claude/somebodys-work"], self.pc)
        ok, detail = self.sync.pull()
        self.assertFalse(ok)
        self.assertIn("claude/somebodys-work", detail)
        self.assertIn("refusing to rebase someone else's branch", detail)
        # the branch is still checked out, and still not rebased
        proc = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                              cwd=str(self.pc), capture_output=True, text=True)
        self.assertEqual(proc.stdout.strip(), "claude/somebodys-work")

    def test_a_tree_mid_merge_is_left_alone(self):
        # Observed live: while a session resolved a conflict here, the Core
        # tried to checkpoint every 60s and logged "you have unmerged files"
        # each time. Staging a conflicted path would commit the markers.
        (self.pc / ".git" / "MERGE_HEAD").write_text("deadbeef\n")
        self.assertTrue(self.sync.merge_in_progress())
        ok, detail = self.sync.commit(["seed.txt"], "core: state checkpoint")
        self.assertTrue(ok)
        self.assertIn("merge in progress", detail)
        blocked = self.sync.blocking_reason()
        self.assertIn("merge or rebase is in progress", blocked)
        ok, detail = self.sync.pull()
        self.assertFalse(ok)

    def test_a_clean_tree_on_the_sync_branch_is_not_blocked(self):
        self.assertIsNone(self.sync.blocking_reason())

    def test_a_renamed_foreign_file_is_still_foreign(self):
        (self.pc / "seed.txt").rename(self.pc / "renamed.txt")
        run(["git", "add", "-A"], self.pc)
        self.assertIn("renamed.txt", self.sync.foreign_changes())

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
