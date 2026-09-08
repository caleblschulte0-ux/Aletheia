"""He asked whether she can make Excel, PowerPoint and Word files.

She could READ a .docx and could not write one — `workspace.write`
refuses any suffix outside `TEXT_SUFFIXES`, so everything she authored
was markdown. "Here is a markdown file, open it in something" is the
answer that makes a person go and do it themselves.

Stdlib only, for the reason `doctext` gives at the top of its own file:
`pip install python-docx openpyxl` makes the feature work on the machine
of whoever remembered to run it, which is the same shape as a capability
that says AVAILABLE and is not.
"""
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock
from xml.etree import ElementTree

from aletheia import intercom, journal, officedocs


class DocumentCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {
            "ALETHEIA_WORKSPACE": str(d / "ws"),
            "ALETHEIA_PRIVATE_STATE": str(d / "private")})
        env.start()
        self.addCleanup(env.stop)
        p = mock.patch.object(journal, "JOURNAL_PATH", d / "j.jsonl")
        p.start()
        self.addCleanup(p.stop)


class ItReallyIsADocumentCase(DocumentCase):
    def test_a_word_file_reads_back_through_the_repos_own_reader(self):
        """The proof that matters: `doctext` — the reader his resume goes
        through — gets the words out again. A file that only looks right
        in a hex dump is what fails in front of him."""
        made = officedocs.save("report.docx", blocks=[
            {"style": "heading", "text": "Barkly launch readiness"},
            {"style": "body", "text": "Prepared for Caleb."},
            {"style": "bullet", "text": "Onboarding bug still open"}])
        self.assertTrue(made["verified"]["ok"], made["verified"])
        self.assertIn("Barkly launch readiness", made["verified"]["text"])
        self.assertIn("Onboarding bug", made["verified"]["text"])

    def test_a_short_document_is_still_a_document(self):
        """`doctext.extract` refuses anything under MIN_ANY_CHARS because
        a resume that short is a scan. That gate is right for reading his
        documents and wrong for writing a two-line memo."""
        made = officedocs.save("memo.docx", blocks=[
            {"style": "heading", "text": "Q3"}, {"text": "Fine."}])
        self.assertTrue(made["verified"]["ok"], made["verified"])

    def test_every_part_of_a_spreadsheet_is_valid_xml(self):
        made = officedocs.save("budget.xlsx",
                               rows=[["Item", "Qty"], ["Widget", 12]])
        with zipfile.ZipFile(made["path"]) as archive:
            for name in archive.namelist():
                if name.endswith((".xml", ".rels")):
                    ElementTree.fromstring(archive.read(name))  # raises if not

    def test_numbers_are_numbers_so_they_add_up(self):
        """A spreadsheet whose numbers are text is a table, not a
        spreadsheet — SUM() over it returns zero."""
        made = officedocs.save("n.xlsx", rows=[["a", 12], ["b", 4.5],
                                               ["c", "twelve"]])
        with zipfile.ZipFile(made["path"]) as archive:
            sheet = archive.read("xl/worksheets/sheet1.xml").decode()
        self.assertIn("<v>12</v>", sheet)
        self.assertIn("<v>4.5</v>", sheet)
        self.assertIn("twelve", sheet)
        self.assertIn("inlineStr", sheet)

    def test_a_cell_reference_is_spreadsheet_shaped(self):
        self.assertEqual(officedocs._cell_ref(1, 1), "A1")
        self.assertEqual(officedocs._cell_ref(3, 26), "Z3")
        self.assertEqual(officedocs._cell_ref(2, 27), "AA2")


class ADeckIsProvableAfterAllCase(DocumentCase):
    """I registered PowerPoint as a ticket and called it unverifiable,
    because nothing here reads a deck back. That was wrong and I had not
    looked: `doctext` reads a .docx by pulling `<w:t>` runs out of the
    zip, and a .pptx is the same shape — `<a:t>` runs, one part per
    slide. The reader is twenty lines."""

    def test_the_words_come_back_slide_by_slide(self):
        made = officedocs.save("launch.pptx", slides=[
            {"title": "Barkly launch", "bullets": ["Readiness review"]},
            {"title": "Ask", "bullets": ["Two weeks", "One engineer"]}])
        self.assertTrue(made["verified"]["ok"], made["verified"])
        slides = officedocs.deck_text(made["path"])
        self.assertEqual(len(slides), 2)
        self.assertIn("Barkly launch", slides[0])
        self.assertIn("Readiness review", slides[0])
        self.assertIn("One engineer", slides[1])

    def test_every_part_powerpoint_insists_on_is_present(self):
        """It refuses a deck without a master, a layout and a theme."""
        made = officedocs.save("d.pptx", slides=[{"title": "One"}])
        with zipfile.ZipFile(made["path"]) as archive:
            names = set(archive.namelist())
        for needed in ("ppt/presentation.xml",
                       "ppt/slideMasters/slideMaster1.xml",
                       "ppt/slideLayouts/slideLayout1.xml",
                       "ppt/theme/theme1.xml",
                       "ppt/slides/slide1.xml"):
            self.assertIn(needed, names)

    def test_every_part_of_a_deck_is_valid_xml(self):
        made = officedocs.save("v.pptx", slides=[{"title": "One",
                                                  "bullets": ["a", "b"]}])
        with zipfile.ZipFile(made["path"]) as archive:
            for name in archive.namelist():
                if name.endswith((".xml", ".rels")):
                    ElementTree.fromstring(archive.read(name))

    def test_a_deck_with_no_slides_is_not_a_deck(self):
        with self.assertRaises(officedocs.DocumentError):
            officedocs.save("empty.pptx", slides=[])

    def test_slides_survive_characters_that_would_break_the_xml(self):
        made = officedocs.save("odd.pptx", slides=[
            {"title": "<b>Q3 & Q4</b>", "bullets": ["we\x08ird"]}])
        self.assertTrue(made["verified"]["ok"])
        text = officedocs.deck_text(made["path"])[0]
        self.assertIn("Q3 & Q4", text)
        # The control character is gone and the word survived — a raw
        # 0x08 is what makes PowerPoint call a file corrupt.
        self.assertNotIn("\x08", text)
        self.assertIn("weird", text)


class ItRefusesRatherThanCorruptsCase(DocumentCase):
    def test_a_format_she_cannot_make_is_refused_by_name(self):
        with self.assertRaises(officedocs.DocumentError) as caught:
            officedocs.save("notes.rtf", blocks=[{"text": "hello"}])
        self.assertIn("rtf", str(caught.exception))

    def test_an_empty_document_is_not_a_document(self):
        for path, kwargs in (("a.docx", {"blocks": []}),
                             ("b.xlsx", {"rows": []})):
            with self.subTest(path=path):
                with self.assertRaises(officedocs.DocumentError):
                    officedocs.save(path, **kwargs)

    def test_control_characters_never_reach_the_file(self):
        """A raw 0x08 in a cell is what makes Excel call a file corrupt —
        and this repo has already lost an afternoon to one."""
        made = officedocs.save("odd.xlsx", rows=[["we\x08ird", "fi\x00ne"]])
        with zipfile.ZipFile(made["path"]) as archive:
            sheet = archive.read("xl/worksheets/sheet1.xml").decode()
        self.assertNotIn("\x08", sheet)
        self.assertNotIn("\x00", sheet)
        self.assertIn("weird", sheet)

    def test_angle_brackets_do_not_break_the_xml(self):
        made = officedocs.save("x.xlsx", rows=[["<b>bold & bigger</b>"]])
        self.assertTrue(made["verified"]["ok"])

    def test_a_file_that_does_not_verify_is_deleted_not_left(self):
        """Never leave something he might send to somebody."""
        with mock.patch.object(officedocs, "verify",
                               return_value={"ok": False, "why": "broken"}):
            with self.assertRaises(officedocs.DocumentError):
                officedocs.save("bad.docx", blocks=[{"text": "hello"}])
        from aletheia import workspace
        self.assertFalse(workspace.resolve("bad.docx").exists())

    def test_it_cannot_write_outside_the_workspace(self):
        from aletheia import workspace
        with self.assertRaises(workspace.OutsideWorkspace):
            officedocs.save("../escape.docx", blocks=[{"text": "no"}])


class ThroughTheGrammarCase(DocumentCase):
    def test_the_suffix_picks_the_format(self):
        said = intercom.execute_command(
            {"kind": "doc_make", "path": "q3.docx",
             "content": [{"style": "heading", "text": "Q3"}, "It went fine."]},
            {}, quote="make me a doc")
        self.assertIn("Word document", said)
        self.assertIn("reads back correctly", said)

        said = intercom.execute_command(
            {"kind": "doc_make", "path": "b.xlsx",
             "content": [["Item", "Qty"], ["Widget", 12]]},
            {}, quote="make me a sheet")
        self.assertIn("spreadsheet", said)

    def test_a_deck_through_the_grammar(self):
        said = intercom.execute_command(
            {"kind": "doc_make", "path": "deck.pptx",
             "content": [{"title": "Q3", "bullets": ["Up 12%"]}, "Thank you"]},
            {}, quote="make me a deck")
        self.assertIn("slide deck", said)
        self.assertIn("reads back correctly", said)

    def test_plain_strings_are_paragraphs(self):
        """What a planner produces when nobody asked for headings."""
        said = intercom.execute_command(
            {"kind": "doc_make", "path": "p.docx",
             "content": ["one", "two"]}, {}, quote="")
        self.assertIn("Word document", said)

    def test_content_that_is_not_a_list_is_refused(self):
        with self.assertRaises(ValueError):
            intercom.execute_command(
                {"kind": "doc_make", "path": "a.docx", "content": "just text"},
                {}, quote="")

    def test_it_is_routine_not_world(self):
        """It writes one file inside her own workspace: reversible, and
        it reaches nobody."""
        self.assertEqual(intercom.tier("doc_make"), intercom.TIER_ROUTINE)


if __name__ == "__main__":
    unittest.main()
