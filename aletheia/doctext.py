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

_ESCAPES = {b"n": "\n", b"r": "\n", b"t": "\t", b"b": "", b"f": "",
            b"(": "(", b")": ")", b"\\": "\\"}


def _read_string(body: bytes, i: int) -> tuple[str, int]:
    """One PDF literal string starting at `body[i] == '('`.

    A SCANNER, not a regex, because PDF strings nest: parentheses inside a
    string need no escaping as long as they balance. A phone number is
    written `(512) 555-0134`, so a resume line reading
    `(caleb@example.com | (512) 555-0134) Tj` is one perfectly legal
    string containing another pair — and the regex that had been doing
    this stopped at the inner `(`, failed to match, and DROPPED THE WHOLE
    LINE. Silently: the extraction succeeded, it was just missing his
    email address and his phone number, which is most of what a form wants
    from him. Found 2026-09-03 by watching a campaign learn seven things
    off a resume and not those two.
    """
    out = []
    depth = 1
    i += 1
    while i < len(body) and depth:
        char = body[i:i + 1]
        if char == b"\\":
            nxt = body[i + 1:i + 2]
            if nxt in _ESCAPES:
                out.append(_ESCAPES[nxt]); i += 2
            elif nxt.isdigit():
                octal = b""
                j = i + 1
                while j < len(body) and len(octal) < 3 and body[j:j + 1].isdigit():
                    octal += body[j:j + 1]; j += 1
                try:
                    out.append(chr(int(octal, 8)))
                except ValueError:
                    pass
                i = j
            elif nxt == b"\n":
                i += 2                       # a line continuation
            else:
                out.append(nxt.decode("latin-1")); i += 2
            continue
        if char == b"(":
            depth += 1
            out.append("(")
        elif char == b")":
            depth -= 1
            if depth:
                out.append(")")
        else:
            out.append(char.decode("latin-1"))
        i += 1
    return "".join(out), i


def _pdf_stream_text(content: bytes) -> str:
    """Walk a content stream, keeping the text and the line breaks.

    Also a scanner rather than a pattern, for the same reason: the show
    operators carry strings, and the strings are what the regex could not
    read.
    """
    out = []
    i, n = 0, len(content)
    pending: list[str] = []            # strings seen since the last operator
    while i < n:
        char = content[i:i + 1]
        if char == b"(":
            text, i = _read_string(content, i)
            pending.append(text)
            continue
        if char == b"[":
            # A TJ array: strings with kerning numbers between them. A big
            # negative number is how a PDF spells a space.
            depth, j, parts = 1, i + 1, []
            while j < n and depth:
                c = content[j:j + 1]
                if c == b"(":
                    text, j = _read_string(content, j)
                    parts.append(text)
                    continue
                if c == b"[":
                    depth += 1
                elif c == b"]":
                    depth -= 1
                elif c in b"-0123456789":
                    number = c
                    j += 1
                    while j < n and content[j:j + 1] in b"-.0123456789":
                        number += content[j:j + 1]; j += 1
                    try:
                        if float(number) <= -120:
                            parts.append(" ")
                    except ValueError:
                        pass
                    continue
                j += 1
            pending.append("".join(parts))
            i = j
            continue
        if char.isalpha() or char == b"'" or char == b'"':
            word = b""
            while i < n and (content[i:i + 1].isalpha() or
                             content[i:i + 1] in b"*'\""):
                word += content[i:i + 1]; i += 1
            if word in (b"Tj", b"TJ", b"'", b'"'):
                out.extend(pending)
            elif word in (b"Td", b"TD", b"T*", b"ET"):
                out.extend(pending)
                out.append("\n")
            pending = []
            continue
        i += 1
    out.extend(pending)
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
