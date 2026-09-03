"""Deleting and moving — verbs she did not have.

Found by running sentences. "Delete summary.md" had no matching kind at
all: `file_write`, `file_edit`, `file_read` and `file_list` were the
whole vocabulary, so the planner claimed `file.author` was missing (the
registry said otherwise and the claim was refused) and then fell through
to the SCRIPT SANDBOX to do an ordinary file operation.

Deletion here is the same promise as overwriting: the previous version
goes to `.versions/` FIRST. She cannot destroy his work, only take it off
the shelf — which is exactly what makes these routine rather than things
that need an approval every time.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import intercom, journal, policy, workspace


class FileVerbCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.ws = d / "ws"
        self.ws.mkdir()
        env = mock.patch.dict(os.environ, {"ALETHEIA_WORKSPACE": str(self.ws),
                                           "ALETHEIA_PRIVATE_STATE": str(d)})
        env.start(); self.addCleanup(env.stop)
        for target, attr, value in ((journal, "JOURNAL_PATH", d / "j.jsonl"),
                                    (policy, "HALT_PATH", d / "halt.json")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)


class DeletingLosesNothing(FileVerbCase):
    def test_the_file_goes_and_the_version_stays(self):
        (self.ws / "summary.md").write_text("three bullets")
        out = workspace.remove("summary.md")
        self.assertFalse((self.ws / "summary.md").exists())
        self.assertTrue(out["kept"])
        self.assertEqual(len(workspace.versions("summary.md")), 1)

    def test_it_can_be_brought_back(self):
        """A delete that cannot lose anything is a shelf, not a shredder."""
        (self.ws / "summary.md").write_text("three bullets")
        workspace.remove("summary.md")
        workspace.restore(workspace.versions("summary.md")[0])
        self.assertEqual((self.ws / "summary.md").read_text(), "three bullets")

    def test_deleting_something_that_is_not_there_is_an_error(self):
        with self.assertRaises(workspace.WorkspaceError):
            workspace.remove("never-existed.md")

    def test_it_cannot_reach_outside_the_workspace(self):
        for escape in ("../outside.md", "/etc/passwd"):
            with self.assertRaises(workspace.OutsideWorkspace):
                workspace.remove(escape)

    def test_the_version_history_is_not_deletable(self):
        (self.ws / "x.md").write_text("v1")
        workspace.remove("x.md")
        kept = workspace.versions("x.md")[0]
        with self.assertRaises(workspace.OutsideWorkspace):
            workspace.remove(kept)

    def test_a_halt_stops_it(self):
        (self.ws / "x.md").write_text("v1")
        policy.halt("stopped", via="test")
        with self.assertRaises(Exception):
            workspace.remove("x.md")
        self.assertTrue((self.ws / "x.md").exists())


class MovingKeepsWhatItLandsOn(FileVerbCase):
    def test_a_rename_moves_the_content(self):
        (self.ws / "a.md").write_text("A")
        workspace.move("a.md", "notes/b.md")
        self.assertEqual((self.ws / "notes" / "b.md").read_text(), "A")
        self.assertFalse((self.ws / "a.md").exists())

    def test_landing_on_a_file_keeps_the_previous_version(self):
        """The same rule as write, for the same reason."""
        (self.ws / "a.md").write_text("new")
        (self.ws / "b.md").write_text("old")
        out = workspace.move("a.md", "b.md")
        self.assertTrue(out["replaced"])
        self.assertEqual((self.ws / "b.md").read_text(), "new")
        self.assertEqual(len(workspace.versions("b.md")), 1)

    def test_moving_a_file_onto_itself_is_refused(self):
        (self.ws / "a.md").write_text("A")
        with self.assertRaises(workspace.WorkspaceError):
            workspace.move("a.md", "a.md")

    def test_it_cannot_move_something_out_of_the_workspace(self):
        (self.ws / "a.md").write_text("A")
        with self.assertRaises(workspace.OutsideWorkspace):
            workspace.move("a.md", "../escaped.md")
        self.assertTrue((self.ws / "a.md").exists())

    def test_it_will_not_move_a_file_into_a_format_she_cannot_author(self):
        (self.ws / "a.md").write_text("A")
        with self.assertRaises(workspace.WorkspaceError):
            workspace.move("a.md", "a.exe")


class HeCanAskForThem(FileVerbCase):
    def test_both_kinds_exist_and_are_local_and_routine(self):
        for kind in ("file_delete", "file_move"):
            self.assertIn(kind, intercom.KIND_ARGS, kind)
            self.assertIn(kind, intercom.LOCAL_KINDS, kind)
            self.assertIn(kind, intercom.ROUTINE_KINDS, kind)

    def test_deleting_through_the_intercom_says_the_version_is_kept(self):
        (self.ws / "summary.md").write_text("three bullets")
        said = intercom.execute_command(
            {"kind": "file_delete", "path": "summary.md"}, fleet={}, quote="q")
        self.assertIn("previous version is kept", said)

    def test_moving_through_the_intercom_works(self):
        (self.ws / "a.md").write_text("A")
        said = intercom.execute_command(
            {"kind": "file_move", "path": "a.md", "to": "b.md"},
            fleet={}, quote="q")
        self.assertIn("moved", said)
        self.assertEqual((self.ws / "b.md").read_text(), "A")

    def test_the_planner_can_see_them(self):
        from aletheia import planner
        brief = planner.grammar_brief()
        self.assertIn("file_delete(", brief)
        self.assertIn("file_move(", brief)


class CurrentInformationIsResearchedNotRecalled(unittest.TestCase):
    """"What's the weather tomorrow" came back as intent=answer, which
    means a model writing from memory about a thing that changes daily —
    a guess wearing a fact's clothes. The rule is now about the ANSWER,
    not the phrasing: it does not have to say "look into"."""

    def test_the_prompt_says_so(self):
        from aletheia import planner
        flat = " ".join(planner.PROMPT_HEADER.split())
        self.assertIn("CURRENT INFORMATION", flat)
        self.assertIn("changes with the day", flat)
        self.assertIn("guess wearing a fact's clothes", flat)

    def test_it_names_the_kind_that_really_opens_pages(self):
        from aletheia import planner
        flat = " ".join(planner.PROMPT_HEADER.split())
        self.assertIn("RESEARCH kind", flat)


if __name__ == "__main__":
    unittest.main()
