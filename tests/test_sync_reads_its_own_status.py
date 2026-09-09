"""The Core's sync was blocked by a lost space.

    /api/sync -> pull: ok=false
      "uncommitted changes the Core does not own: tate/pulse/latest.json
       - refusing to autostash a person's work"

`tate/pulse/latest.json`. The leading `s` was gone, and that was the
whole bug: `_git` ends with `.strip()`, which removes the leading space
of the FIRST porcelain line, so ` M state/...` arrived as `M state/...`
and a fixed `line[3:]` ate one character too many.

Not cosmetic. `state/` is in OWNED_PATHS - the Core writes the pulse and
may stash it freely - but `tate/pulse/latest.json` does not start with
`state/`, so the Core read its OWN file as a person's work and refused to
pull. Only the first changed path is ever affected, which is why it
looked intermittent rather than broken.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import sync


class ReadingOnePorcelainLineCase(unittest.TestCase):
    def test_the_line_git_actually_emits(self):
        self.assertEqual(sync._porcelain_path(" M state/pulse/latest.json"),
                         "state/pulse/latest.json")

    def test_the_line_after_strip_has_eaten_the_leading_space(self):
        """The bug. `_git` strips, so the first line arrives like this."""
        self.assertEqual(sync._porcelain_path("M state/pulse/latest.json"),
                         "state/pulse/latest.json")

    def test_two_status_characters(self):
        self.assertEqual(sync._porcelain_path("MM aletheia/voice.py"),
                         "aletheia/voice.py")

    def test_untracked(self):
        self.assertEqual(sync._porcelain_path("?? cache/new-thing.png"),
                         "cache/new-thing.png")

    def test_a_rename_names_what_exists_now(self):
        self.assertEqual(sync._porcelain_path("R  old.py -> aletheia/new.py"),
                         "aletheia/new.py")

    def test_a_quoted_path_is_unquoted(self):
        self.assertEqual(sync._porcelain_path(' M "state/a file.json"'),
                         "state/a file.json")

    def test_a_line_that_is_not_a_status_line_is_ignored(self):
        for line in ("", "   ", "fatal: not a git repository"):
            with self.subTest(line=line):
                self.assertEqual(sync._porcelain_path(line), "")


class TheCoreKnowsItsOwnFilesCase(unittest.TestCase):
    def _foreign(self, porcelain):
        with mock.patch.object(sync, "_git", return_value=(0, porcelain)):
            return sync.GitSync(branch="live").foreign_changes()

    def test_its_own_pulse_is_not_somebody_elses_work(self):
        """The exact line that blocked the pull, first in the list."""
        self.assertEqual(self._foreign("M state/pulse/latest.json"), [])

    def test_owned_paths_are_owned_wherever_they_appear(self):
        porcelain = ("M state/pulse/latest.json\n"
                     " M state/journal/journal.jsonl\n"
                     "?? cache/screen-captures/x.png\n"
                     " M exchange/receipts/r.json")
        self.assertEqual(self._foreign(porcelain), [])

    def test_a_persons_edit_is_still_theirs(self):
        porcelain = ("M state/pulse/latest.json\n"
                     " M aletheia/voice.py")
        self.assertEqual(self._foreign(porcelain), ["aletheia/voice.py"])

    def test_a_persons_edit_is_theirs_even_when_it_comes_first(self):
        """The first line is the one the old slice mangled."""
        self.assertEqual(self._foreign("M aletheia/voice.py"),
                         ["aletheia/voice.py"])

    def test_a_failed_git_reports_nothing_rather_than_guessing(self):
        with mock.patch.object(sync, "_git", return_value=(1, "fatal: nope")):
            self.assertEqual(sync.GitSync(branch="live").foreign_changes(), [])


if __name__ == "__main__":
    unittest.main()
