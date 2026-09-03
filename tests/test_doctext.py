"""His resume is a PDF, and nothing in this system could open it.

Everything built on "read his resume" — the cover letters, "look at my
resume and tell me what's weak", the whole application packet — was
reading a `.md` file that existed only because a test wrote one.
`workspace.read` refuses a suffix it cannot author, and
`aletheia.documents` says so in its own docstring: it "does not pretend to
parse arbitrary PDFs/Office files without the corresponding parser". There
was no parser. The most important input in the system was the one input
she could not open.

Stdlib only, deliberately: `pip install pypdf` on his PC would make this
work on the machine of whoever remembered to run it, which is the same
shape as a capability that says AVAILABLE and is not.
"""
import os
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest import mock

from aletheia import doctext

LINES = [
    "Caleb Schulte", "caleblschulte0@gmail.com", "EXPERIENCE",
    "Built a multi-channel automated YouTube pipeline: discovery, scripting,",
    "render and upload, unattended, with a headless quality gate.",
    "Built Aletheia, a personal operating system with approval gates.",
    "Built an automated options trader with hard risk guardrails.",
    "SKILLS: Python, ffmpeg, GitHub Actions, Windows automation",
]


def make_pdf(path, lines, compress=True, pad=0):
    ops = ["BT", "/F1 12 Tf", "72 720 Td", "14 TL"]
    for line in lines:
        safe = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        ops += [f"({safe}) Tj", "T*"]
    ops.append("ET")
    content = "\n".join(ops).encode("latin-1")
    stream, extra = ((zlib.compress(content), b"/Filter /FlateDecode ")
                     if compress else (content, b""))
    objs = [b"<< /Type /Catalog >>", b"<< /Type /Pages >>", b"<< /Type /Page >>",
            b"<< " + extra + b"/Length " + str(len(stream)).encode()
            + b" >>\nstream\n" + stream + b"\nendstream"]
    out = bytearray(b"%PDF-1.4\n")
    for i, body in enumerate(objs, 1):
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    out += b"%" + b"padding " * pad + b"\ntrailer\n%%EOF\n"
    Path(path).write_bytes(bytes(out))


def make_docx(path, lines):
    paras = "".join(f"<w:p><w:r><w:t>{l}</w:t></w:r></w:p>" for l in lines)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml",
                   '<?xml version="1.0"?><w:document xmlns:w="x"><w:body>'
                   + paras + "</w:body></w:document>")


class DocCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)


class ItReadsWhatHeActuallyHAS(DocCase):
    def test_a_compressed_pdf(self):
        make_pdf(self.d / "r.pdf", LINES)
        got = doctext.extract(self.d / "r.pdf")
        self.assertEqual(got["kind"], doctext.PDF)
        self.assertIn("Caleb Schulte", got["text"])
        self.assertIn("headless quality gate", got["text"])

    def test_an_uncompressed_pdf(self):
        make_pdf(self.d / "r.pdf", LINES, compress=False)
        self.assertIn("options trader", doctext.extract(self.d / "r.pdf")["text"])

    def test_a_docx(self):
        make_docx(self.d / "r.docx", LINES)
        got = doctext.extract(self.d / "r.docx")
        self.assertEqual(got["kind"], doctext.DOCX)
        self.assertIn("approval gates", got["text"])

    def test_a_docx_keeps_its_line_breaks(self):
        """Paragraph ends become newlines BEFORE tags are stripped, or a
        resume arrives as one enormous line with every bullet run together."""
        make_docx(self.d / "r.docx", LINES)
        text = doctext.extract(self.d / "r.docx")["text"]
        self.assertGreater(len(text.split("\n")), 5)

    def test_plain_text_still_works(self):
        (self.d / "r.txt").write_text("\n".join(LINES))
        self.assertEqual(doctext.extract(self.d / "r.txt")["kind"], doctext.TEXT)

    def test_pdf_escapes_survive(self):
        make_pdf(self.d / "r.pdf", LINES + [
            r"Built (things) with \backslashes and 50% uptime"])
        text = doctext.extract(self.d / "r.pdf")["text"]
        self.assertIn("(things)", text)
        self.assertIn("50%", text)


class ItSaysWhenItCannotREAD(DocCase):
    def test_a_scan_is_refused_with_the_fix(self):
        """A picture of words has no words in it, and no amount of stream
        parsing changes that."""
        make_pdf(self.d / "scan.pdf", [], pad=20_000)
        with self.assertRaises(doctext.UnreadableDocument) as caught:
            doctext.extract(self.d / "scan.pdf")
        said = str(caught.exception)
        self.assertIn("scan or an image", said)
        self.assertIn(".docx", said)

    def test_a_short_document_is_not_treated_as_a_scan(self):
        """"Did extraction work" is not "is this document long". A
        three-word PDF is legitimately three words."""
        make_pdf(self.d / "note.pdf",
                 ["Remember to call the landlord about the boiler on Tuesday"])
        self.assertIn("landlord", doctext.extract(self.d / "note.pdf")["text"])

    def test_a_format_she_cannot_read_names_what_to_do(self):
        (self.d / "r.pages").write_bytes(b"apple")
        with self.assertRaises(doctext.UnreadableDocument) as caught:
            doctext.extract(self.d / "r.pages")
        self.assertIn("Save it as PDF", str(caught.exception))

    def test_a_missing_file_is_not_a_crash(self):
        with self.assertRaises(doctext.UnreadableDocument):
            doctext.extract(self.d / "nope.pdf")

    def test_a_docx_that_is_not_one(self):
        with zipfile.ZipFile(self.d / "r.docx", "w") as z:
            z.writestr("nothing.txt", "hi")
        with self.assertRaises(doctext.UnreadableDocument):
            doctext.extract(self.d / "r.docx")


class ItNeedsNothingINSTALLED(DocCase):
    def test_it_imports_only_the_standard_library(self):
        import re as _re
        body = (Path(__file__).parent.parent / "aletheia" / "doctext.py"
                ).read_text(encoding="utf-8")
        top = body.split("def ")[0]
        for line in _re.findall(r"^\s*(?:from|import)\s+([\w.]+)", top,
                                _re.MULTILINE):
            self.assertIn(line.split(".")[0],
                          {"argparse", "json", "re", "sys", "zipfile", "zlib",
                           "pathlib", "__future__"}, line)

    def test_a_broken_optional_parser_does_not_take_it_down(self):
        """Caught live: pypdf pulls in `cryptography`, whose Rust bindings
        raise pyo3_runtime.PanicException — a BaseException — when the
        native module is broken. `except Exception` does not catch that, so
        an optional dependency crashed a document the stdlib path reads
        perfectly well. "Optional" has to mean optional even when it is
        installed and broken."""
        make_pdf(self.d / "r.pdf", LINES)

        class Panic(BaseException):
            pass

        with mock.patch.object(doctext, "_pdf_via_pypdf",
                               side_effect=Panic("native module broken")):
            with self.assertRaises(Panic):
                doctext.extract(self.d / "r.pdf")   # the mock itself raises
        body = (Path(__file__).parent.parent / "aletheia" / "doctext.py"
                ).read_text(encoding="utf-8")
        self.assertIn("except BaseException", body)

    def test_the_better_parser_is_used_when_it_works(self):
        make_pdf(self.d / "r.pdf", LINES)
        with mock.patch.object(doctext, "_pdf_via_pypdf",
                               return_value="x" * 500) as better:
            self.assertEqual(doctext.extract(self.d / "r.pdf")["text"],
                             "x" * 500)
        better.assert_called_once()


class TheWorkspaceReadsThemNow(DocCase):
    def setUp(self):
        super().setUp()
        from aletheia import journal
        self.ws = self.d / "ws"
        self.ws.mkdir()
        env = mock.patch.dict(os.environ, {"ALETHEIA_WORKSPACE": str(self.ws),
                                           "ALETHEIA_PRIVATE_STATE": str(self.d)})
        env.start(); self.addCleanup(env.stop)
        p = mock.patch.object(journal, "JOURNAL_PATH", self.d / "j.jsonl")
        p.start(); self.addCleanup(p.stop)

    def test_reading_a_pdf_in_the_workspace(self):
        from aletheia import workspace
        make_pdf(self.ws / "resume.pdf", LINES)
        self.assertIn("Caleb Schulte", workspace.read("resume.pdf")["text"])

    def test_reading_a_pdf_he_named_anywhere(self):
        from aletheia import workspace
        make_pdf(self.d / "resume.pdf", LINES)
        got = workspace.read(str(self.d / "resume.pdf"), anywhere=True)
        self.assertIn("options trader", got["text"])

    def test_an_unreadable_pdf_becomes_a_workspace_refusal_not_a_crash(self):
        from aletheia import workspace
        make_pdf(self.ws / "scan.pdf", [], pad=20_000)
        with self.assertRaises(workspace.WorkspaceError) as caught:
            workspace.read("scan.pdf")
        self.assertIn("scan or an image", str(caught.exception))

    def test_writing_a_pdf_is_still_refused(self):
        """Reading is wider than writing, on purpose. She cannot author a
        PDF correctly, so she does not pretend to."""
        from aletheia import workspace
        with self.assertRaises(workspace.WorkspaceError):
            workspace.write("out.pdf", "some text")

    def test_conversation_notices_a_pdf_he_names(self):
        from aletheia import converse
        self.assertIn("resume.pdf",
                      converse._candidates("look at my resume.pdf and tell me "
                                           "what is weak"))


if __name__ == "__main__":
    unittest.main()
