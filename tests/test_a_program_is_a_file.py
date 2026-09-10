"""Sixty lines of Python, read out loud in a room.

    > write me a python script that renames files
      [18.6s] Here's a general-purpose rename script - handles find/replace,
      adding a prefix or suffix, and sequential renumbering, with a dry-run
      so you can preview before it touches anything. import os. import
      argparse. def rename_files(folder, mode, find=None, replace=None,
      prefix=None, suffix=None, start_num=1, pad=3, ext_filter=None,
      dry_run=True): files = sorted(os.listdir(folder)). if ext_filter:
      files = [f for f in files if f.lower.endswith(ext_filter.lower)]...

The first sentence was perfect and everything after it was two minutes of
nothing, with no way to stop it and nothing to keep at the end.

One line, doing exactly what it says and precisely the wrong thing.
`speech.unmarkdown` strips ``` fence MARKERS, because markdown is page
formatting and an asterisk is silence out loud. A FENCE IS NOT
FORMATTING. Removing it does not tidy the code, it PROMOTES the code into
prose - the one transformation that must never happen to it.

And underneath that, a capability with no path to it: `file.author` has
been AVAILABLE the whole time, keeping a version of anything it replaces,
inside a workspace with a hard edge around it. She could produce the file
and had no way to get from a model's answer to one, so every program she
wrote was composed, spoken, and thrown away.

What this holds:

- a program is written, not said; two lines he would type are said
- the file is called what the ANSWER calls it - she told him to run
  `python rename.py` and filed it as `renames-files.py`
- the offer is keepable: "say read rename.py" has to work
- reading it back does not recite it either, which is the same defect
  arriving through the other door
- and the two sentences agree about how long it is
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import codeblocks, voice

SCRIPT = '''Here's a renamer. Run it with python rename.py "C:\\folder" old new.

```python
import os
import sys


def rename(folder, old, new, apply=False):
    for name in sorted(os.listdir(folder)):
        if old in name:
            print(name, "->", name.replace(old, new))
            if apply:
                os.rename(os.path.join(folder, name),
                          os.path.join(folder, name.replace(old, new)))


if __name__ == "__main__":
    rename(sys.argv[1], sys.argv[2], sys.argv[3], "--apply" in sys.argv)
```
'''

ONE_LINER = """Type dir or ls. For hidden files:

```
get-childitem -force
```

That's it."""


class _InAWorkspace(unittest.TestCase):
    """Her real workspace is never touched by a test."""

    def setUp(self):
        self._was = os.environ.get("ALETHEIA_WORKSPACE")
        self._tmp = tempfile.mkdtemp(prefix="aletheia-ws-")
        os.environ["ALETHEIA_WORKSPACE"] = self._tmp

    def tearDown(self):
        if self._was is None:
            os.environ.pop("ALETHEIA_WORKSPACE", None)
        else:
            os.environ["ALETHEIA_WORKSPACE"] = self._was


class AFenceIsNotFormattingCase(unittest.TestCase):
    def test_a_program_is_lifted_out_of_the_prose(self):
        said = codeblocks.prose_only(SCRIPT)
        self.assertIn("Here's a renamer", said)
        self.assertNotIn("os.listdir", said)
        self.assertNotIn("def rename", said)

    def test_two_lines_he_would_type_stay_in_the_sentence(self):
        """"Run it with get-childitem -force" IS the answer."""
        said = codeblocks.prose_only(ONE_LINER)
        self.assertIn("get-childitem -force", said)

    def test_the_dividing_line_is_one_predicate(self):
        """A block is never both spoken AND filed, and never neither."""
        for text in (SCRIPT, ONE_LINER):
            with self.subTest(text=text[:20]):
                for block in codeblocks.blocks(text):
                    spoken = block["code"] in codeblocks.prose_only(text)
                    self.assertEqual(spoken, not codeblocks.worth_saving(block))

    def test_an_unclosed_fence_is_still_a_block(self):
        """A truncated answer has no closing fence."""
        found = codeblocks.blocks("here:\n```python\nimport os\nx = 1\ny = 2\nz = 3")
        self.assertEqual(len(found), 1)
        self.assertIn("import os", found[0]["code"])

    def test_an_answer_with_no_code_is_untouched(self):
        said = "Type dir or ls, both are aliases for Get-ChildItem."
        self.assertEqual(codeblocks.prose_only(said), said)
        self.assertEqual(codeblocks.blocks(said), [])


class ItIsCalledWhatTheAnswerCallsItCase(unittest.TestCase):
    def test_the_name_in_the_instruction_wins(self):
        """She said "run it with python rename.py" and filed
        "renames-files.py". Both sentences hers, one turn apart, and the
        one he would act on was wrong."""
        block = codeblocks.blocks(SCRIPT)[0]
        self.assertEqual(
            codeblocks._name_for(block, "write me a python script that "
                                        "renames files", answer=SCRIPT),
            "rename.py")

    def test_without_one_it_is_named_from_what_he_asked(self):
        block = codeblocks.blocks("```python\na = 1\nb = 2\nc = 3\nd = 4\n```")[0]
        self.assertEqual(
            codeblocks._name_for(block, "write me a script to tag photos"),
            "tag-photos.py")

    def test_a_suffix_that_does_not_match_is_not_borrowed(self):
        """"see rename.py" in a bash answer does not name the .sh file."""
        block = {"language": "bash", "code": "echo hi", "lines": 1}
        self.assertEqual(codeblocks._named_in("see rename.py", ".sh"), "")

    def test_a_url_is_not_a_filename(self):
        self.assertEqual(codeblocks._named_in("go to example.py.org/x", ".py"), "")
        self.assertEqual(codeblocks._named_in("import os.path here", ".py"), "")

    def test_a_full_stop_after_it_is_still_a_filename(self):
        """"Run it with python rename.py." is how a sentence ends."""
        self.assertEqual(
            codeblocks._named_in("Run it with python rename.py.", ".py"),
            "rename.py")


class TheFileActuallyLandsCase(_InAWorkspace):
    def test_it_is_written_and_readable(self):
        from aletheia import workspace
        saved = codeblocks.save(SCRIPT, asked="a python script that renames files")
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["name"], "rename.py")
        path = Path(saved[0]["path"])
        self.assertTrue(path.is_file())
        self.assertIn("def rename", path.read_text(encoding="utf-8"))
        self.assertEqual(path.parent.name, codeblocks.SUBDIR)
        self.assertIn(workspace.root(), path.parents)

    def test_a_one_liner_is_not_filed(self):
        self.assertEqual(codeblocks.save(ONE_LINER, asked="list files"), [])

    def test_a_workspace_that_refuses_does_not_break_the_sentence(self):
        """A good answer must not be replaced by a bad one."""
        from aletheia import workspace
        with mock.patch.object(workspace, "write",
                               side_effect=RuntimeError("full")):
            self.assertEqual(codeblocks.save(SCRIPT, asked="x"), [])

    def test_she_does_not_claim_a_file_she_did_not_write(self):
        self.assertEqual(codeblocks.spoken([]), "")


class TheOfferIsKeepableCase(_InAWorkspace):
    """An OFFER is a claim about ability."""

    def test_the_sentence_names_the_file(self):
        saved = codeblocks.save(SCRIPT, asked="a python script that renames files")
        said = codeblocks.spoken(saved)
        self.assertIn("rename.py", said)
        self.assertNotIn("Say read it", said, "a pronoun she cannot resolve")

    def test_the_sentence_it_tells_him_to_say_compiles(self):
        saved = codeblocks.save(SCRIPT, asked="a python script that renames files")
        said = codeblocks.spoken(saved)
        ask = said.split("Say ")[1].split(" and I'll")[0]
        command = (voice._interpret(ask) or {}).get("command") or {}
        self.assertEqual(command.get("kind"), "file_read", f"{ask!r} -> {command}")
        self.assertEqual(command.get("path"), "rename.py")

    def test_reading_a_filename_does_not_swallow_a_web_page(self):
        for said, kind in (("read example.com", "browse_read"),
                           ("read https://example.com/x", "browse_read"),
                           ("read me my tasks", "tasks"),
                           ("read notes.md", "file_read")):
            with self.subTest(said=said):
                got = (voice._interpret(said) or {}).get("command") or {}
                self.assertEqual(got.get("kind"), kind, said)


class ReadingItBackIsNotRecitingItCase(unittest.TestCase):
    def test_a_program_is_described_rather_than_read(self):
        said = codeblocks.describe(codeblocks.blocks(SCRIPT)[0]["code"],
                                   "rename.py")
        self.assertIn("rename.py", said)
        self.assertIn("Python", said)
        self.assertIn("It defines rename", said)
        self.assertIn("command line", said)
        self.assertNotIn("os.listdir", said)

    def test_both_sentences_agree_how_long_it_is(self):
        """Saving said 15 lines and reading it back said 11."""
        block = codeblocks.blocks(SCRIPT)[0]
        said = codeblocks.describe(block["code"], "rename.py")
        self.assertIn(f"{block['lines']} lines", said)

    def test_a_document_is_prose_and_is_read(self):
        self.assertFalse(codeblocks.is_code("notes.md"))
        self.assertFalse(codeblocks.is_code("resume.pdf"))
        self.assertTrue(codeblocks.is_code("rename.py"))
        self.assertTrue(codeblocks.is_code("deploy.sh"))

    def test_it_says_nothing_it_did_not_count(self):
        """Every claim is a thing matched, so there is nothing to invent."""
        said = codeblocks.describe("x = 1\ny = 2", "notes.py")
        self.assertNotIn("It defines", said)
        self.assertNotIn("command line", said)


if __name__ == "__main__":
    unittest.main()
