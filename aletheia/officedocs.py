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


# ---- PowerPoint ----------------------------------------------------------
#
# A deck needs a master, a layout and a theme or PowerPoint refuses to
# open it. None of the three ever vary here, so they are written once as
# the smallest valid form rather than generated.

_A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
_P = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
_R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'

_THEME = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<a:theme {_A} name="Office"><a:themeElements>'
    '<a:clrScheme name="Office"><a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>'
    '<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>'
    '<a:dk2><a:srgbClr val="44546A"/></a:dk2><a:lt2><a:srgbClr val="E7E6E6"/></a:lt2>'
    '<a:accent1><a:srgbClr val="4472C4"/></a:accent1><a:accent2><a:srgbClr val="ED7D31"/></a:accent2>'
    '<a:accent3><a:srgbClr val="A5A5A5"/></a:accent3><a:accent4><a:srgbClr val="FFC000"/></a:accent4>'
    '<a:accent5><a:srgbClr val="5B9BD5"/></a:accent5><a:accent6><a:srgbClr val="70AD47"/></a:accent6>'
    '<a:hlink><a:srgbClr val="0563C1"/></a:hlink>'
    '<a:folHlink><a:srgbClr val="954F72"/></a:folHlink></a:clrScheme>'
    '<a:fontScheme name="Office">'
    '<a:majorFont><a:latin typeface="Calibri Light"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>'
    '<a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont>'
    '</a:fontScheme>'
    '<a:fmtScheme name="Office">'
    '<a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>'
    '<a:lnStyleLst><a:ln><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>'
    '<a:ln><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>'
    '<a:ln><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>'
    '<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle>'
    '<a:effectStyle><a:effectLst/></a:effectStyle>'
    '<a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>'
    '<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst>'
    '</a:fmtScheme></a:themeElements></a:theme>')

_SLIDE_MASTER = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<p:sldMaster {_A} {_P} {_R}><p:cSld><p:spTree>'
    '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
    '<p:grpSpPr/></p:spTree></p:cSld>'
    '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" '
    'accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" '
    'accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
    '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
    '</p:sldMaster>')

_SLIDE_LAYOUT = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<p:sldLayout {_A} {_P} {_R} type="titleOnly"><p:cSld><p:spTree>'
    '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
    '<p:grpSpPr/></p:spTree></p:cSld><p:clrMapOvr><a:overrideClrMapping '
    'bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" '
    'accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" '
    'hlink="hlink" folHlink="folHlink"/></p:clrMapOvr></p:sldLayout>')


def _shape(shape_id: int, name: str, x: int, y: int, cx: int, cy: int,
           paragraphs: list[str], size: int) -> str:
    body = "".join(
        f'<a:p><a:r><a:rPr lang="en-US" sz="{size}" dirty="0"/>'
        f'<a:t>{_x(line)}</a:t></a:r></a:p>' for line in paragraphs) or "<a:p/>"
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="{_x(name)}"/>'
        '<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr/></p:nvSpPr>'
        f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/>'
        '</a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
        f'<p:txBody><a:bodyPr wrap="square"/><a:lstStyle/>{body}</p:txBody></p:sp>')


def _slide_xml(title: str, bullets: list[str]) -> str:
    shapes = _shape(2, "Title", 838200, 685800, 10515600, 1325563,
                    [title] if title else [], 4000)
    if bullets:
        shapes += _shape(3, "Content", 838200, 2130425, 10515600, 3602038,
                         list(bullets), 2000)
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<p:sld {_A} {_P} {_R}><p:cSld><p:spTree>'
            '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/>'
            '</p:nvGrpSpPr><p:grpSpPr/>'
            + shapes +
            '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>'
            '</p:sld>')


def pptx_bytes(slides: list[dict]) -> dict[str, str]:
    """`slides` are {"title": ..., "bullets": [...]}."""
    if not slides:
        raise DocumentError("a deck with no slides is not a deck")
    if len(slides) > MAX_SLIDES:
        raise DocumentError(f"{len(slides)} slides is beyond what she will "
                            f"write ({MAX_SLIDES})")
    parts: dict[str, str] = {}
    ids, rels = [], []
    for n, slide in enumerate(slides, start=1):
        parts[f"ppt/slides/slide{n}.xml"] = _slide_xml(
            str(slide.get("title") or ""),
            [str(b) for b in (slide.get("bullets") or [])])
        parts[f"ppt/slides/_rels/slide{n}.xml.rels"] = _RELS.format(body=(
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/slideLayout" '
            'Target="../slideLayouts/slideLayout1.xml"/>'))
        ids.append(f'<p:sldId id="{255 + n}" r:id="rId{n + 1}"/>')
        rels.append(
            f'<Relationship Id="rId{n + 1}" Type="http://schemas.openxml'
            'formats.org/officeDocument/2006/relationships/slide" '
            f'Target="slides/slide{n}.xml"/>')

    overrides = "".join(
        f'<Override PartName="/ppt/slides/slide{n}.xml" ContentType='
        '"application/vnd.openxmlformats-officedocument.presentationml.slide'
        '+xml"/>' for n in range(1, len(slides) + 1))

    parts["[Content_Types].xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-'
        'package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/ppt/presentation.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
        '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType='
        '"application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
        '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType='
        '"application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
        '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.theme+xml"/>' + overrides + "</Types>")
    parts["_rels/.rels"] = _RELS.format(body=(
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/officeDocument" '
        'Target="ppt/presentation.xml"/>'))
    parts["ppt/presentation.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:presentation {_A} {_P} {_R}>'
        '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/>'
        "</p:sldMasterIdLst><p:sldIdLst>" + "".join(ids) + "</p:sldIdLst>"
        '<p:sldSz cx="12192000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/>'
        "</p:presentation>")
    parts["ppt/_rels/presentation.xml.rels"] = _RELS.format(body=(
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/slideMaster" '
        'Target="slideMasters/slideMaster1.xml"/>' + "".join(rels) +
        f'<Relationship Id="rId{len(slides) + 2}" Type="http://schemas.'
        'openxmlformats.org/officeDocument/2006/relationships/theme" '
        'Target="theme/theme1.xml"/>'))
    parts["ppt/slideMasters/slideMaster1.xml"] = _SLIDE_MASTER
    parts["ppt/slideMasters/_rels/slideMaster1.xml.rels"] = _RELS.format(body=(
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/slideLayout" '
        'Target="../slideLayouts/slideLayout1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>'))
    parts["ppt/slideLayouts/slideLayout1.xml"] = _SLIDE_LAYOUT
    parts["ppt/slideLayouts/_rels/slideLayout1.xml.rels"] = _RELS.format(body=(
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/slideMaster" '
        'Target="../slideMasters/slideMaster1.xml"/>'))
    parts["ppt/theme/theme1.xml"] = _THEME
    return parts


def deck_text(target) -> list[str]:
    """The words out of a deck, one string per slide.

    Twenty lines, and it is why the deck is provable: `doctext` reads a
    .docx by pulling `<w:t>` runs out of the zip and a .pptx is the same
    shape, `<a:t>` runs, one part per slide. I called this unverifiable
    once. It was not; I had not looked.
    """
    from xml.etree import ElementTree
    ns = "{http://schemas.openxmlformats.org/drawingml/2006/main}t"
    out = []
    with zipfile.ZipFile(Path(target)) as archive:
        names = sorted(n for n in archive.namelist()
                       if re.fullmatch(r"ppt/slides/slide\d+\.xml", n))
        for name in names:
            root = ElementTree.fromstring(archive.read(name))
            out.append("\n".join(node.text or "" for node in root.iter(ns)))
    return out


# ---- the door ------------------------------------------------------------

WRITABLE = {".docx": "a Word document", ".xlsx": "a spreadsheet",
            ".pptx": "a slide deck"}


def save(path: str, *, blocks=None, rows=None, slides=None,
         sheet_name: str = "Sheet1", why: str = "") -> dict:
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
    elif suffix == ".pptx":
        if not slides:
            raise DocumentError("a deck with no slides is not a deck")
        parts = pptx_bytes(list(slides))
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
        if target.suffix.casefold() == ".pptx":
            # Every part PowerPoint refuses a deck without, then the words
            # read back off the slides — the same round trip the .docx
            # gets, through a reader that turned out to be twenty lines.
            for needed in ("ppt/presentation.xml",
                           "ppt/slideMasters/slideMaster1.xml",
                           "ppt/slideLayouts/slideLayout1.xml",
                           "ppt/theme/theme1.xml"):
                if needed not in names:
                    return {"ok": False, "why": f"no {needed.rsplit('/', 1)[-1]}"}
            slides = deck_text(target)
            if not slides or not any(s.strip() for s in slides):
                return {"ok": False, "why": "no readable text on any slide"}
            return {"ok": True, "why": "", "slides": len(slides),
                    "text": " / ".join(s.replace("\n", " ")[:60]
                                       for s in slides[:3])}
        if "xl/worksheets/sheet1.xml" not in names:
            return {"ok": False, "why": "no worksheet part"}
        return {"ok": True, "why": ""}
    except Exception as exc:
        return {"ok": False, "why": f"{type(exc).__name__}: {exc}"}
