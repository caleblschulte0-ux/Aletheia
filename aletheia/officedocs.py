"""Making the documents he actually has to hand people.

He asked whether she can make Excel, PowerPoint and Word files. She
could read a `.docx` and could not write one: `workspace.write` refuses
any suffix outside `TEXT_SUFFIXES`, so everything she authored was
markdown or plain text. A spreadsheet is not a nice-to-have — half of
what a person is asked to produce is a `.xlsx` or a `.docx`, and "here
is a markdown file, open it in something" is the answer that makes
somebody go and do it themselves.

STDLIB ONLY, for the reason `doctext` gives at the top of its own file
and which applies exactly: `pip install python-docx openpyxl` makes the
feature work on the machine of whoever remembered to run it, "which is
the same shape as a capability that says AVAILABLE and is not". All
three formats are ZIP archives of XML, and `zipfile` is stdlib. Nothing
here imports anything that is not.

WHAT IS DELIBERATELY SMALL. These are plain documents: headings,
paragraphs, tables of values, slides with a title and bullets. No
styling beyond what the format needs to be valid, no charts, no images.
A document she cannot make correctly she should not make at all, and a
half-styled spreadsheet is worse than a clean one — he can format it in
Excel in ten seconds and cannot un-corrupt a file.

PROVEN BY READING IT BACK. Every `.docx` written here is re-opened with
`doctext.extract` — the repo's own reader, the one his resume goes
through — and the words have to come back. A file that only "looks
right" in a hex dump is exactly the kind of thing that fails in front of
him at the moment he needs it.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

# What a document may contain before something has gone wrong. Generous
# for a report, small enough that a runaway loop cannot fill his disk.
MAX_PARAGRAPHS = 5_000
MAX_ROWS = 50_000
MAX_COLUMNS = 256
MAX_SLIDES = 200
MAX_TEXT = 20_000


class DocumentError(RuntimeError):
    """She could not make that document, and says why."""


def _x(text) -> str:
    """XML-escaped, control characters dropped.

    A raw 0x08 in a cell is what makes Excel call a file corrupt, and
    this repo has already lost an afternoon to an invisible backspace
    (see `test_encoding_is_never_the_locale`).
    """
    clean = "".join(c for c in str(text if text is not None else "")
                    if c >= " " or c in "\t\n")
    return escape(clean[:MAX_TEXT])


def _zip(target: Path, parts: dict[str, str]) -> Path:
    """Write the archive atomically. A half-written .xlsx is a corrupt one."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".partial")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, body in parts.items():
                archive.writestr(name, body)
        tmp.replace(target)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    return target


_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
         'relationships">{body}</Relationships>')


# ---- Word ----------------------------------------------------------------

def docx_bytes(blocks: list[dict]) -> dict[str, str]:
    """`blocks` are {"text": ..., "style": "heading"|"body"|"bullet"}."""
    if len(blocks) > MAX_PARAGRAPHS:
        raise DocumentError(f"a document of {len(blocks)} paragraphs is not a "
                            f"document; the limit is {MAX_PARAGRAPHS}")
    body = []
    for block in blocks:
        style = str(block.get("style") or "body").lower()
        text = _x(block.get("text"))
        if style == "heading":
            body.append(
                '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
                f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>')
        elif style == "bullet":
            body.append(
                '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/>'
                '<w:numId w:val="1"/></w:numPr></w:pPr>'
                f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>')
        else:
            body.append(
                f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>')
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml'
        '/2006/main"><w:body>' + "".join(body) +
        '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr>'
        '</w:body></w:document>')
    return {
        "[Content_Types].xml":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            'content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxml'
            'formats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.wordprocessingml.document.main'
            '+xml"/></Types>',
        "_rels/.rels": _RELS.format(body=(
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/>')),
        "word/document.xml": document,
    }


# ---- Excel ---------------------------------------------------------------

def _cell_ref(row: int, column: int) -> str:
    letters = ""
    n = column
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return f"{letters}{row}"


def _is_number(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    return bool(re.fullmatch(r"-?\d+(\.\d+)?", str(value).strip()))


def xlsx_bytes(rows: list[list], sheet_name: str = "Sheet1") -> dict[str, str]:
    """Rows of values. Numbers are written as numbers, so they add up.

    INLINE STRINGS rather than a shared-string table: one fewer part to
    keep consistent, and a mismatch between the table and the sheet is
    the classic way to produce a file Excel refuses to open.
    """
    if len(rows) > MAX_ROWS:
        raise DocumentError(f"{len(rows)} rows is beyond what she will write "
                            f"({MAX_ROWS})")
    body = []
    for r, row in enumerate(rows, start=1):
        if len(row) > MAX_COLUMNS:
            raise DocumentError(f"row {r} has {len(row)} columns; the limit "
                                f"is {MAX_COLUMNS}")
        cells = []
        for c, value in enumerate(row, start=1):
            ref = _cell_ref(r, c)
            if value is None or str(value) == "":
                continue
            if _is_number(value):
                cells.append(f'<c r="{ref}"><v>{_x(value)}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t '
                             f'xml:space="preserve">{_x(value)}</t></is></c>')
        body.append(f'<row r="{r}">' + "".join(cells) + "</row>")
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml'
             '/2006/main"><sheetData>' + "".join(body) +
             "</sheetData></worksheet>")
    safe_name = _x(sheet_name)[:31] or "Sheet1"
    return {
        "[Content_Types].xml":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            'content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxml'
            'formats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType='
            '"application/vnd.openxmlformats-officedocument.spreadsheetml.'
            'worksheet+xml"/></Types>',
        "_rels/.rels": _RELS.format(body=(
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/>')),
        "xl/workbook.xml":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/'
            '2006/main" xmlns:r="http://schemas.openxmlformats.org/office'
            'Document/2006/relationships"><sheets>'
            f'<sheet name="{safe_name}" sheetId="1" r:id="rId1"/>'
            "</sheets></workbook>",
        "xl/_rels/workbook.xml.rels": _RELS.format(body=(
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/>')),
        "xl/worksheets/sheet1.xml": sheet,
    }


# ---- the door ------------------------------------------------------------

WRITABLE = {".docx": "a Word document", ".xlsx": "a spreadsheet"}


def save(path: str, *, blocks=None, rows=None, sheet_name: str = "Sheet1",
         why: str = "") -> dict:
    """Write one document into her workspace, and prove it afterwards.

    The suffix decides the format, because that is what he says: "save it
    as budget.xlsx". An unsupported one is refused by name rather than
    written wrongly.
    """
    from aletheia import journal, workspace
    target = workspace.resolve(path)
    suffix = target.suffix.casefold()
    if suffix not in WRITABLE:
        raise DocumentError(
            f"{suffix or 'that'} is not a document she can make. She writes "
            + ", ".join(sorted(WRITABLE)) + ", and text files through the "
            "ordinary file verbs.")

    if suffix == ".docx":
        if not blocks:
            raise DocumentError("a document with no content is not a document")
        parts = docx_bytes(list(blocks))
    else:
        if not rows:
            raise DocumentError("a spreadsheet with no rows is not a spreadsheet")
        parts = xlsx_bytes([list(r) for r in rows], sheet_name=sheet_name)

    _zip(target, parts)
    check = verify(target)
    if not check["ok"]:
        # Never leave a file he might send to somebody.
        try:
            target.unlink()
        except OSError:
            pass
        raise DocumentError(f"she wrote {target.name} and it did not read "
                            f"back correctly ({check['why']}); it was removed")
    journal.append("action", "document",
                   f"wrote {target.name} ({WRITABLE[suffix]})"
                   + (f" — {why[:80]}" if why else ""),
                   actor="documents")
    return {"path": str(target), "kind": WRITABLE[suffix],
            "bytes": target.stat().st_size, "verified": check}


def verify(target: Path) -> dict:
    """Open it again and check the words are in it.

    A `.docx` goes through `doctext` — the same reader his resume goes
    through — because a file that only looks right in a hex dump is what
    fails in front of him at the moment he needs it. A `.xlsx` is checked
    structurally, since nothing here reads one back.
    """
    target = Path(target)
    try:
        if not zipfile.is_zipfile(target):
            return {"ok": False, "why": "not a valid archive"}
        with zipfile.ZipFile(target) as archive:
            names = set(archive.namelist())
            bad = archive.testzip()
        if bad:
            return {"ok": False, "why": f"corrupt member {bad}"}
        # EVERY XML PART MUST PARSE. A zip that is intact and contains
        # malformed XML is exactly the file Office calls corrupt, and
        # checking only the archive would have called it fine.
        from xml.etree import ElementTree
        with zipfile.ZipFile(target) as archive:
            for name in names:
                if not name.endswith(".xml") and not name.endswith(".rels"):
                    continue
                try:
                    ElementTree.fromstring(archive.read(name))
                except ElementTree.ParseError as exc:
                    return {"ok": False, "why": f"{name} is not valid XML ({exc})"}
        if target.suffix.casefold() == ".docx":
            if "word/document.xml" not in names:
                return {"ok": False, "why": "no document part"}
            # `doctext._docx_text` rather than `doctext.extract`: extract
            # also decides whether a document is USEFUL — it refuses
            # anything under MIN_ANY_CHARS, because a resume that comes
            # back as forty characters is a scan. That gate is right for
            # reading his documents and wrong here, where "Q3 report / It
            # went fine." is a perfectly good short memo. This is still
            # the repo's own docx reader, which is the point: the words
            # have to survive a real round trip.
            from aletheia import doctext
            # The WHOLE file: `_docx_text` opens the .docx as a zip
            # itself. Handing it the inner document.xml got "File is not
            # a zip file" out of a perfectly valid document.
            text = doctext._docx_text(target.read_bytes())
            words = len(text.split())
            if not words:
                return {"ok": False, "why": "no readable text came back"}
            return {"ok": True, "why": "", "words": words, "text": text[:400]}
        if "xl/worksheets/sheet1.xml" not in names:
            return {"ok": False, "why": "no worksheet part"}
        return {"ok": True, "why": ""}
    except Exception as exc:
        return {"ok": False, "why": f"{type(exc).__name__}: {exc}"}
