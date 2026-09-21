"""The checkout that stayed stuck for three days (2026-09-18 to 09-21).

An autostash replay left conflict markers inside the legacy journal on the
operator's PC. Nothing writes that file any more, so nothing rewrote it
clean; the healer refused a file holding markers; every rebase after that
refused "you have unmerged files"; a recovery left a second clone INSIDE
the checkout, which read as a person's uncommitted work and blocked the
pull a second way. The Core ran code 85 commits old — every merge of that
week — and the page said everything was running.

Every case here is against a real local bare repo: no mocks, no network.
"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from aletheia import sync
from aletheia.sync import GitSync, resolve_conflict_markers

LOG = "state/journal/journal.jsonl"
SNAP = "state/pulse/latest.json"


def run(args, cwd):
    return subprocess.run(args, cwd=str(cwd), check=True,
                          capture_output=True, text=True)


def git_out(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True).stdout.strip()


class TheMarkersThemselvesCase(unittest.TestCase):
    """`resolve_conflict_markers` on the exact shapes git leaves."""

    LIVE = ("<<<<<<< Updated upstream\n"
            "=======\n"
            '{"ts": "2026-09-18T17:07:00Z", "kind": "event"}\n'
            '{"ts": "2026-09-18T19:06:35Z", "kind": "task"}\n'
            ">>>>>>> Stashed changes\n")

    def test_the_live_shape_keeps_the_lines_that_were_only_on_the_pc(self):
        # The first side was EMPTY on his PC: upstream had nothing there,
        # the Core's own copy had twenty-six lines. Union keeps them.
        settled = resolve_conflict_markers('{"base": 1}\n' + self.LIVE, keep_both=True)
        self.assertEqual(settled, '{"base": 1}\n'
                         '{"ts": "2026-09-18T17:07:00Z", "kind": "event"}\n'
                         '{"ts": "2026-09-18T19:06:35Z", "kind": "task"}\n')

    def test_a_log_keeps_both_halves_upstream_first(self):
        text = "a\n<<<<<<< HEAD\nb\n=======\nc\n>>>>>>> 1234 (core: state checkpoint)\nd\n"
        self.assertEqual(resolve_conflict_markers(text, keep_both=True), "a\nb\nc\nd\n")

    def test_a_snapshot_keeps_the_cores_own_copy(self):
        text = '<<<<<<< Updated upstream\n{"n": 2}\n=======\n{"n": 3}\n>>>>>>> Stashed changes\n'
        self.assertEqual(resolve_conflict_markers(text, keep_both=False), '{"n": 3}\n')

    def test_a_file_without_markers_comes_back_unchanged(self):
        self.assertEqual(resolve_conflict_markers("x\ny\n", keep_both=True), "x\ny\n")

    def test_a_shape_git_did_not_leave_is_refused(self):
        # Missing end, doubled start, a lone separator: never guessed at.
        for text in ("<<<<<<< a\nb\n=======\nc\n",
                     "<<<<<<< a\n<<<<<<< b\n=======\nc\n>>>>>>> d\n",
                     "<<<<<<< a\nb\n=======\n=======\nc\n>>>>>>> d\n"):
            self.assertIsNone(resolve_conflict_markers(text, keep_both=True), text)

    def test_only_a_log_keeps_both(self):
        self.assertTrue(sync._keeps_both_sides("state/journal/journal.jsonl"))
        self.assertFalse(sync._keeps_both_sides("state/pulse/latest.json"))


class StuckCheckoutCase(unittest.TestCase):
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
        for rel, text in ((LOG, '{"base": 1}\n'), (SNAP, '{"n": 1}\n')):
            path = self.relay / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        run(["git", "add", "."], self.relay)
        run(["git", "commit", "-m", "seed"], self.relay)
        run(["git", "push", "origin", "main"], self.relay)
        run(["git", "pull", "origin", "main"], self.pc)
        self.sync = GitSync(repo_root=self.pc, branch="main")

    def tearDown(self):
        self.tmp.cleanup()

    def relay_writes(self, rel, text):
        (self.relay / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.relay / rel).write_text(text, encoding="utf-8")
        run(["git", "add", "."], self.relay)
        run(["git", "commit", "-m", f"relay: {rel}"], self.relay)
        run(["git", "push", "origin", "main"], self.relay)

    def assert_clean_and_current(self):
        self.assertEqual(git_out(["diff", "--name-only", "--diff-filter=U"], self.pc), "")
        self.assertFalse(self.sync.merge_in_progress())
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", "origin/main", "HEAD"], cwd=str(self.pc))
        self.assertEqual(ancestor.returncode, 0, "the pull did not land")

    # --- the autostash replay, the way it went on his PC ---

    def test_its_own_dirty_log_clashing_with_upstream_keeps_both_halves(self):
        self.relay_writes(LOG, '{"base": 1}\n{"cloud": 2}\n')
        (self.pc / LOG).write_text('{"base": 1}\n{"pc": 3}\n', encoding="utf-8")
        ok, detail = self.sync.pull()
        self.assertTrue(ok, detail)
        self.assertIn("kept the Core's own copy of " + LOG, detail)
        text = (self.pc / LOG).read_text(encoding="utf-8")
        self.assertNotIn("<<<<<<<", text)
        self.assertEqual(text, '{"base": 1}\n{"cloud": 2}\n{"pc": 3}\n')
        self.assert_clean_and_current()

    def test_its_own_dirty_snapshot_clashing_with_upstream_keeps_its_copy(self):
        self.relay_writes(SNAP, '{"n": 2}\n')
        (self.pc / SNAP).write_text('{"n": 3}\n', encoding="utf-8")
        ok, detail = self.sync.pull()
        self.assertTrue(ok, detail)
        self.assertEqual((self.pc / SNAP).read_text(encoding="utf-8"), '{"n": 3}\n')
        self.assert_clean_and_current()

    def test_markers_already_sitting_in_its_log_are_settled_before_the_pull(self):
        # The state the PC was found in: the replay had already failed, the
        # markers were on disk, the index held the file unmerged, and the
        # remote had moved on again since.
        self.relay_writes(LOG, '{"base": 1}\n{"cloud": 2}\n')
        (self.pc / LOG).write_text('{"base": 1}\n{"pc": 3}\n', encoding="utf-8")
        old = GitSync.heal_owned_conflicts
        GitSync.heal_owned_conflicts = lambda self: []   # the old healer: refuses
        try:
            ok, detail = self.sync.pull()
        finally:
            GitSync.heal_owned_conflicts = old
        self.assertFalse(ok)
        self.assertIn("autostash conflict", detail)
        self.assertIn("<<<<<<<", (self.pc / LOG).read_text(encoding="utf-8"))
        self.assertEqual(git_out(["diff", "--name-only", "--diff-filter=U"], self.pc), LOG)
        self.relay_writes("code.py", "print('newer')\n")

        ok, detail = self.sync.pull()

        self.assertTrue(ok, detail)
        text = (self.pc / LOG).read_text(encoding="utf-8")
        self.assertNotIn("<<<<<<<", text)
        self.assertIn('{"cloud": 2}', text)
        self.assertIn('{"pc": 3}', text)
        self.assertTrue((self.pc / "code.py").exists(), "the code did not arrive")
        self.assert_clean_and_current()

    def test_a_checkpoint_of_its_own_log_that_clashes_is_rebased_through(self):
        (self.pc / LOG).write_text('{"base": 1}\n{"pc": 3}\n', encoding="utf-8")
        run(["git", "add", LOG], self.pc)
        run(["git", "commit", "-m", "core: state checkpoint"], self.pc)
        self.relay_writes(LOG, '{"base": 1}\n{"cloud": 2}\n')
        ok, detail = self.sync.pull()
        self.assertTrue(ok, detail)
        self.assertIn("kept the Core's own copy of " + LOG, detail)
        text = (self.pc / LOG).read_text(encoding="utf-8")
        self.assertEqual(text, '{"base": 1}\n{"cloud": 2}\n{"pc": 3}\n')
        self.assert_clean_and_current()
        self.assertEqual(git_out(["log", "-1", "--format=%s"], self.pc),
                         "core: state checkpoint")

    def test_a_persons_file_in_the_conflict_is_still_aborted_clean(self):
        (self.pc / "clash.txt").write_text("pc\n", encoding="utf-8")
        run(["git", "add", "."], self.pc)
        run(["git", "commit", "-m", "pc: clash"], self.pc)
        self.relay_writes("clash.txt", "relay\n")
        ok, detail = self.sync.pull()
        self.assertFalse(ok)
        self.assertIn("aborted cleanly", detail)
        self.assertFalse(self.sync.merge_in_progress())
        self.assertEqual((self.pc / "clash.txt").read_text(encoding="utf-8"), "pc\n")

    def test_markers_it_cannot_make_sense_of_are_left_alone(self):
        self.relay_writes(LOG, '{"base": 1}\n{"cloud": 2}\n')
        (self.pc / LOG).write_text('{"base": 1}\n{"pc": 3}\n', encoding="utf-8")
        old = GitSync.heal_owned_conflicts
        GitSync.heal_owned_conflicts = lambda self: []
        try:
            self.sync.pull()
        finally:
            GitSync.heal_owned_conflicts = old
        (self.pc / LOG).write_text("<<<<<<< Updated upstream\nhalf a marker block\n",
                                   encoding="utf-8")
        self.assertEqual(self.sync.heal_owned_conflicts(), [])
        self.assertEqual(git_out(["diff", "--name-only", "--diff-filter=U"], self.pc), LOG)

    # --- its own untracked file, which upstream has since added too ---

    TASK = "state/tasks/verify-message-send.json"

    def test_its_own_untracked_file_that_upstream_also_added_keeps_its_copy(self):
        # The second thing in the way on his PC: the Core had filed a task,
        # a session had committed the same task, and "untracked working tree
        # files would be overwritten by checkout" stopped the rebase before
        # it began — autostash never carries untracked files.
        (self.pc / self.TASK).parent.mkdir(parents=True, exist_ok=True)
        (self.pc / self.TASK).write_text('{"state": "BLOCKED_USER"}\n', encoding="utf-8")
        self.relay_writes(self.TASK, '{"state": "QUEUED"}\n')
        self.relay_writes("code.py", "print('newer')\n")
        ok, detail = self.sync.pull()
        self.assertTrue(ok, detail)
        self.assertIn(self.TASK, detail)
        self.assertTrue((self.pc / "code.py").exists(), "the code did not arrive")
        self.assertEqual((self.pc / self.TASK).read_text(encoding="utf-8"),
                         '{"state": "BLOCKED_USER"}\n')
        self.assert_clean_and_current()

    def test_its_own_untracked_log_that_upstream_also_added_keeps_both(self):
        rel = "state/journal/2026-09-19.jsonl"
        (self.pc / rel).write_text('{"pc": 1}\n', encoding="utf-8")
        self.relay_writes(rel, '{"cloud": 1}\n')
        ok, detail = self.sync.pull()
        self.assertTrue(ok, detail)
        self.assertEqual((self.pc / rel).read_text(encoding="utf-8"),
                         '{"cloud": 1}\n{"pc": 1}\n')
        self.assert_clean_and_current()

    def test_a_persons_untracked_file_in_the_way_still_stops_it(self):
        (self.pc / "notes.txt").write_text("mine\n", encoding="utf-8")
        self.relay_writes("notes.txt", "theirs\n")
        ok, detail = self.sync.pull()
        self.assertFalse(ok)
        self.assertEqual((self.pc / "notes.txt").read_text(encoding="utf-8"), "mine\n")
        self.assertFalse(self.sync.merge_in_progress())

    def test_a_rebase_head_git_left_behind_is_not_a_rebase_in_progress(self):
        # git 2.55 leaves REBASE_HEAD in place after a rebase finishes.
        # Reading it as "in progress" refused every pull on a clean tree.
        (self.pc / ".git" / "REBASE_HEAD").write_text("0" * 40 + "\n", encoding="utf-8")
        self.assertFalse(self.sync.merge_in_progress())
        self.assertIsNone(self.sync.blocking_reason())
        (self.pc / ".git" / "rebase-merge").mkdir()
        self.assertTrue(self.sync.merge_in_progress())

    def test_a_rebase_that_never_started_is_not_called_finished(self):
        finished, why = self.sync.finish_owned_rebase()
        self.assertFalse(finished)
        self.assertIn("never started", why)

    def test_the_complaint_is_read_from_gits_own_words(self):
        out = ("Created autostash: 356a9160\n"
               "error: The following untracked working tree files would be overwritten by checkout:\n"
               "\tstate/tasks/verify-message-send.json\n"
               "\tstate/tasks/other.json\n"
               "Please move or remove them before you switch branches.\n"
               "Aborting\nApplied autostash.\nerror: could not detach HEAD")
        self.assertEqual(sync.untracked_in_the_way(out),
                         ["state/tasks/verify-message-send.json", "state/tasks/other.json"])
        self.assertEqual(sync.untracked_in_the_way("Successfully rebased"), [])

    # --- the second clone inside the checkout ---

    def test_a_stray_clone_inside_the_checkout_is_not_a_persons_work(self):
        stray = self.pc / "Aletheia-new-20260919-190329"
        run(["git", "clone", str(self.origin), str(stray)], self.pc)
        self.assertEqual(self.sync.foreign_changes(), [])
        self.assertIsNone(self.sync.blocking_reason())
        self.relay_writes("code.py", "print('newer')\n")
        ok, detail = self.sync.pull()
        self.assertTrue(ok, detail)
        self.assertTrue(stray.exists(), "the stray clone must not be touched")

    def test_an_untracked_folder_that_is_not_a_repository_is_still_foreign(self):
        (self.pc / "notes").mkdir()
        (self.pc / "notes" / "draft.md").write_text("mine\n", encoding="utf-8")
        self.assertIn("notes/draft.md", self.sync.foreign_changes())


if __name__ == "__main__":
    unittest.main()
