"""Reading the resume he actually has.

His resume is a PDF. Everything built on top of "read his resume" — the
cover letters, "look at my resume and tell me what's weak", the whole
application packet — was reading a `.md` file that only exists because I
made one up for a test. `workspace.read` refuses a suffix it cannot
author, and `aletheia.documents` says so in its own docstring: it "does
not pretend to parse arbitrary PDFs/Office files without the
corresponding parser". There was no parser.

So the most important input in the system was the one input she could not
open.

STDLIB ONLY, deliberately. The obvious fix is `pip install pypdf` on his
PC and a new line in requirements — and then the feature works on the
machine of whoever remembered to run it, which is the same shape as a
capability that says AVAILABLE and is not. A resume is not an exotic
document. `.docx` is a zip of XML and `zipfile` is stdlib; a PDF's text
lives in content streams and `zlib` is stdlib. If `pypdf` happens to be
installed it is used first because it handles more, but nothing here
depends on it.

WHAT IT REFUSES TO DO. A scanned resume is a picture of words, and no
amount of stream parsing turns a picture into text. When extraction comes
back too short, or mostly unreadable, it says exactly that and names the
fix — export a .docx or paste it into a .txt — instead of handing back
forty characters of ligature soup that would become a cover letter about
nobody.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
import zlib
from pathlib import Path

MAX_BYTES = 20_000_000
MAX_CHARS = 200_000
# "Did extraction work" is not the same question as "is this document
# long". A three-word PDF is legitimately three words; a 300 KB PDF that
# yields forty characters is a photograph of a page. So the floor is
# proportional: almost nothing is always a failure, and a little out of a
# lot is a failure too.
MIN_ANY_CHARS = 30
MIN_USEFUL_CHARS = 200
BIG_ENOUGH_TO_EXPECT_WORDS = 50_000
# Fraction of characters that must be ordinary text for the result to be
# trustworthy. Below it we are reading font tables, not prose.
MIN_READABLE_RATIO = 0.85

PDF, DOCX, TEXT = "pdf", "docx", "text"
TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json",
                 ".yaml", ".yml", ".html", ".htm", ".xml", ".log", ".tex"}


class UnreadableDocument(RuntimeError):
    """The file exists and its words could not be got out of it."""


def kind_of(path: Path) -> str | None:
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        return PDF
    if suffix in (".docx", ".dotx"):
        return DOCX
    if suffix in TEXT_SUFFIXES:
        return TEXT
    return None


def handles(path: str | Path) -> bool:
    return kind_of(Path(path)) is not None


# ---- docx: a zip of XML, and zipfile is stdlib ---------------------------

_TAG = re.compile(r"<[^>]+>")
_BREAK = re.compile(r"</w:p>|<w:br\s*/>|</w:tr>")


def _docx_text(data: bytes) -> str:
    import io
    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
        try:
            xml = bundle.read("word/document.xml").decode("utf-8", "replace")
        except KeyError:
            raise UnreadableDocument(
                "that .docx has no word/document.xml — it may be a template "
                "or a renamed file") from None
    # Paragraph and row ends become newlines BEFORE tags are stripped, or a
    # resume arrives as one enormous line and every bullet runs together.
    xml = _BREAK.sub("\n", xml)
    text = _TAG.sub("", xml)
    for entity, char in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                         ("&quot;", '"'), ("&apos;", "'"), ("&#8217;", "’")):
        text = text.replace(entity, char)
    return text


# ---- pdf: content streams, and zlib is stdlib ----------------------------

_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
_SHOW = re.compile(rb"\((?:\\.|[^\\()])*\)\s*(?:Tj|TJ|'|\")|"
                   rb"\[(?:[^\[\]\\]|\\.)*\]\s*TJ|"
                   rb"(?:Td|TD|T\*|ET)")
_PIECE = re.compile(rb"\((?:\\.|[^\\()])*\)")
_KERN = re.compile(rb"(-?\d+(?:\.\d+)?)")

_ESCAPES = {b"n": "\n", b"r": "\n", b"t": "\t", b"b": "", b"f": "",
            b"(": "(", b")": ")", b"\\": "\\"}


def _pdf_string(raw: bytes) -> str:
    """One PDF literal string, with its escapes resolved."""
    body = raw[1:-1]
    out, i = [], 0
    while i < len(body):
        char = body[i:i + 1]
        if char != b"\\":
            out.append(char.decode("latin-1"))
            i += 1
            continue
        nxt = body[i + 1:i + 2]
        if nxt in _ESCAPES:
            out.append(_ESCAPES[nxt])
            i += 2
        elif nxt.isdigit():
            octal = body[i + 1:i + 4]
            while octal and not octal.isdigit():
                octal = octal[:-1]
            try:
                out.append(chr(int(octal, 8)))
            except ValueError:
                pass
            i += 1 + len(octal)
        elif nxt == b"\n":
            i += 2                      # a line continuation inside a string
        else:
            out.append(nxt.decode("latin-1"))
            i += 2
    return "".join(out)


def _pdf_stream_text(content: bytes) -> str:
    out = []
    for match in _SHOW.finditer(content):
        token = match.group(0)
        if token in (b"Td", b"TD", b"T*", b"ET"):
            out.append("\n")            # a new line is positioned, not typed
            continue
        if token.startswith(b"["):
            # A TJ array: strings interleaved with kerning numbers. A big
            # negative number is how a PDF spells a space.
            for piece in re.finditer(rb"\((?:\\.|[^\\()])*\)|-?\d+(?:\.\d+)?",
                                     token):
                chunk = piece.group(0)
                if chunk.startswith(b"("):
                    out.append(_pdf_string(chunk))
                else:
                    try:
                        if float(chunk) <= -120:
                            out.append(" ")
                    except ValueError:
                        pass
            continue
        found = _PIECE.search(token)
        if found:
            out.append(_pdf_string(found.group(0)))
    return "".join(out)


def _pdf_text(data: bytes) -> str:
    pieces = []
    for match in _STREAM.finditer(data):
        raw = match.group(1)
        for attempt in (lambda: zlib.decompress(raw),
                        lambda: zlib.decompress(raw, -15),
                        lambda: raw):
            try:
                content = attempt()
            except zlib.error:
                continue
            if b"Tj" in content or b"TJ" in content:
                pieces.append(_pdf_stream_text(content))
            break
    return "\n".join(pieces)


def _pdf_via_pypdf(data: bytes) -> str | None:
    """Use the better parser when it is there, and never need it.

    `BaseException`, not `Exception`, and it is not laziness. An optional
    dependency can fail at IMPORT time in ways `except Exception` does not
    catch: pypdf pulls in `cryptography`, whose Rust bindings raise
    `pyo3_runtime.PanicException` — a BaseException — when the native
    module is broken. Caught live here, 2026-09-03: a resume that the
    stdlib path reads perfectly well took the whole extraction down with a
    panic from a library we do not need. "Optional" has to mean optional
    even when it is installed and broken.
    """
    try:
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except BaseException:
        return None


# ---- the honest bit ------------------------------------------------------

def _tidy(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def _readable_ratio(text: str) -> float:
    if not text:
        return 0.0
    ok = sum(1 for c in text if c.isprintable() or c in "\n\t")
    return ok / len(text)


def extract(path: str | Path) -> dict:
    """The words in a document. Raises UnreadableDocument with the fix."""
    target = Path(path).expanduser()
    if not target.is_file():
        raise UnreadableDocument(f"{path} is not a file")
    size = target.stat().st_size
    if size > MAX_BYTES:
        raise UnreadableDocument(f"{target.name} is {size:,} bytes, over the "
                                 f"{MAX_BYTES:,} ceiling")
    kind = kind_of(target)
    if kind is None:
        raise UnreadableDocument(
            f"she cannot read {target.suffix or 'that'} files. Save it as PDF, "
            ".docx, .txt or .md and point her at that.")
    data = target.read_bytes()
    if kind == TEXT:
        text = data.decode("utf-8", "replace")
    elif kind == DOCX:
        text = _docx_text(data)
    else:
        text = _pdf_via_pypdf(data)
        if text is None or len(_tidy(text)) < MIN_USEFUL_CHARS:
            text = _pdf_text(data)

    text = _tidy(text)[:MAX_CHARS]
    too_little = len(text) < MIN_ANY_CHARS or (
        len(text) < MIN_USEFUL_CHARS and size > BIG_ENOUGH_TO_EXPECT_WORDS)
    if too_little:
        raise UnreadableDocument(
            f"she got only {len(text)} characters out of {target.name} "
            f"({size:,} bytes). If it is a scan or an image it has no text in "
            "it to read — export a .docx from the original, or paste the text "
            "into a .txt, and point her at that. She will not write from a "
            "document she could not read.")
    if _readable_ratio(text) < MIN_READABLE_RATIO:
        raise UnreadableDocument(
            f"what came out of {target.name} is mostly unreadable characters, "
            "which usually means an embedded font she cannot map. Export a "
            ".docx or a .txt from the original and point her at that.")
    return {"path": str(target), "kind": kind, "chars": len(text), "text": text}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Get the words out of a document.")
    ap.add_argument("path")
    ap.add_argument("--full", action="store_true")
    args = ap.parse_args(argv)
    try:
        got = extract(args.path)
    except UnreadableDocument as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(got["text"] if args.full
          else json.dumps({k: v for k, v in got.items() if k != "text"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
