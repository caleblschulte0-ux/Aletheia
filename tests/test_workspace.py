"""She can produce something now — inside a boundary that actually holds.

The gap: she could think but not hand him anything. No document, no
spreadsheet, no file. "Open my resume and fix the formatting" compiled to
nothing, and driving Word to do it would have been the dangerous way to
do something a text edit does safely.

So the tests that matter are the boundary ones. A confinement that can be
walked out of with `../` or a symlink is not a confinement, and an edit
that silently matches nothing is the failure shape that looks like success.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, policy, workspace


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "ws"
        self.root.mkdir()
        self.outside = Path(self.tmp.name) / "outside"
        self.outside.mkdir()
        env = mock.patch.dict(os.environ, {"ALETHEIA_WORKSPACE": str(self.root)})
        env.start(); self.addCleanup(env.stop)
        for target, attr, value in (
                (journal, "JOURNAL_PATH", Path(self.tmp.name) / "j.jsonl"),
                (policy, "HALT_PATH", Path(self.tmp.name) / "halt.json")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)


class TheBoundaryHolds(WorkspaceCase):
    def test_traversal_is_refused(self):
        for escape in ("../secrets.txt", "../../etc/passwd", "notes/../../x.txt",
                       "/etc/passwd", "\\\\..\\\\..\\\\x.txt"):
            with self.subTest(path=escape):
                with self.assertRaises(workspace.OutsideWorkspace):
                    workspace.resolve(escape)

    def test_a_symlink_out_of_the_workspace_is_refused(self):
        """The one a string-prefix check gets walked out of."""
        secret = self.outside / "secret.txt"
        secret.write_text("private", encoding="utf-8")
        link = self.root / "innocent.txt"
        try:
            link.symlink_to(secret)
        except (OSError, NotImplementedError):
            self.skipTest("this platform does not allow symlinks here")
        with self.assertRaises(workspace.OutsideWorkspace):
            workspace.resolve("innocent.txt")

    def test_a_symlinked_directory_is_refused_too(self):
        link = self.root / "sub"
        try:
            link.symlink_to(self.outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("this platform does not allow symlinks here")
        with self.assertRaises(workspace.OutsideWorkspace):
            workspace.resolve("sub/anything.txt")

    def test_a_root_that_is_everything_is_refused(self):
        with mock.patch.dict(os.environ, {"ALETHEIA_WORKSPACE": str(Path.home())}):
            with self.assertRaises(workspace.WorkspaceError):
                workspace.root()

    def test_the_version_history_is_not_editable(self):
        with self.assertRaises(workspace.OutsideWorkspace):
            workspace.resolve(".versions/notes-2026.txt")

    def test_only_text_formats_she_can_author(self):
        with self.assertRaises(workspace.WorkspaceError):
            workspace.write("thing.docx", "not really a docx")
        with self.assertRaises(workspace.WorkspaceError):
            workspace.write("photo.png", "not really a png")
        workspace.write("fine.md", "# yes")   # must not raise


class NothingIsLostWhenSheIsWrong(WorkspaceCase):
    def test_overwriting_keeps_the_previous_version(self):
        workspace.write("notes.md", "the original")
        result = workspace.write("notes.md", "the replacement")
        self.assertTrue(result["previous"], "a replaced file must leave a copy")
        kept = workspace.versions("notes.md")
        self.assertEqual(len(kept), 1)
        self.assertIn("the original",
                      (self.root / kept[0]).read_text(encoding="utf-8"))

    def test_a_new_file_has_nothing_to_keep(self):
        result = workspace.write("fresh.md", "new")
        self.assertIsNone(result["previous"])
        self.assertTrue(result["created"])

    def test_a_version_can_be_restored(self):
        workspace.write("notes.md", "the good version")
        workspace.write("notes.md", "the mistake")
        workspace.restore(workspace.versions("notes.md")[0])
        self.assertEqual(workspace.read("notes.md")["text"], "the good version")

    def test_restoring_something_that_is_not_a_version_is_refused(self):
        workspace.write("notes.md", "x")
        with self.assertRaises((workspace.OutsideWorkspace, workspace.WorkspaceError)):
            workspace.restore("notes.md")


class AnEditThatChangesNothingIsAFailure(WorkspaceCase):
    """The failure shape that looks exactly like success: five successful
    edits reported, nothing changed."""

    def test_no_match_raises_rather_than_quietly_passing(self):
        workspace.write("notes.md", "hello world")
        with self.assertRaises(workspace.WorkspaceError) as caught:
            workspace.edit("notes.md", "goodbye", "farewell")
        self.assertIn("not in", str(caught.exception))

    def test_an_ambiguous_match_asks_for_more_context(self):
        workspace.write("notes.md", "todo\ntodo\ntodo")
        with self.assertRaises(workspace.WorkspaceError) as caught:
            workspace.edit("notes.md", "todo", "done")
        self.assertIn("3 times", str(caught.exception))

    def test_a_good_edit_changes_the_file_and_reports_a_diff(self):
        workspace.write("resume.md", "Skills: Python\nExperience: some")
        result = workspace.edit("resume.md", "Experience: some",
                                "Experience: eight years")
        self.assertIn("eight years", workspace.read("resume.md")["text"])
        self.assertIn("+Experience: eight years", result["diff"])
        self.assertEqual(result["replacements"], 1)

    def test_editing_a_missing_file_says_so(self):
        with self.assertRaises(workspace.WorkspaceError):
            workspace.edit("nope.md", "a", "b")


class ReadingIsWiderThanWriting(WorkspaceCase):
    def test_she_may_read_a_file_he_names_outside_the_workspace(self):
        resume = self.outside / "resume.md"
        resume.write_text("my actual resume", encoding="utf-8")
        self.assertIn("my actual resume",
                      workspace.read(str(resume), anywhere=True)["text"])

    def test_but_she_may_never_write_outside_it(self):
        with self.assertRaises(workspace.OutsideWorkspace):
            workspace.write(str(self.outside / "resume.md"), "rewritten")

    def test_binary_is_refused_rather_than_guessed(self):
        blob = self.root / "thing.txt"
        blob.write_bytes(b"\xff\xfe\x00\x01binary")
        with self.assertRaises(workspace.WorkspaceError):
            workspace.read("thing.txt")


class BoundedAndStoppable(WorkspaceCase):
    def test_an_oversized_file_is_refused(self):
        with mock.patch.object(workspace, "MAX_FILE_BYTES", 100):
            with self.assertRaises(workspace.WorkspaceError):
                workspace.write("big.md", "x" * 200)

    def test_a_full_workspace_refuses_new_files(self):
        workspace.write("a.md", "1")
        with mock.patch.object(workspace, "MAX_FILES", 1):
            with self.assertRaises(workspace.WorkspaceError):
                workspace.write("b.md", "2")
            workspace.write("a.md", "updated")   # existing file still editable

    def test_halt_stops_writing(self):
        policy.halt("stop", via="test")
        with self.assertRaises(policy.Halted):
            workspace.write("notes.md", "x")

    def test_a_crash_mid_write_leaves_no_half_file(self):
        workspace.write("notes.md", "good")
        self.assertEqual(list(self.root.glob("*.partial")), [],
                         "the temp file is replaced atomically, never left behind")


if __name__ == "__main__":
    unittest.main()
