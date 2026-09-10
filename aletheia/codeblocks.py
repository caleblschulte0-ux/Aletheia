"""A program is a file, not a sentence.

    > write me a python script that renames files
      [18.6s] Here's a general-purpose rename script — handles find/replace,
      adding a prefix or suffix, and sequential renumbering, with a dry-run
      so you can preview before it touches anything. import os. import
      argparse. def rename_files(folder, mode, find=None, replace=None,
      prefix=None, suffix=None, start_num=1, pad=3, ext_filter=None,
      dry_run=True): files = sorted(os.listdir(folder)). if ext_filter:
      files = [f for f in files if f.lower.endswith(ext_filter.lower)]...

Sixty lines of Python, read out in a room. The first sentence was
perfect and everything after it was unusable — not merely awkward:
useless, and two minutes long, with no way to stop it and nothing to keep
at the end.

The cause is one line doing exactly what it says and precisely the wrong
thing. `speech.unmarkdown` strips ``` fence MARKERS, because markdown is
page formatting and an asterisk is silence out loud. A fence is not
formatting. Removing it does not tidy the code — it PROMOTES the code
into prose, which is the one transformation that must never happen to it.

So a fenced block is lifted out before anything is said, and then the
thing he actually wanted happens: it is WRITTEN. `file.author` has been
AVAILABLE this whole time, keeping a version of anything it replaces,
inside a workspace with a hard edge around it. She had the capability to
produce the file and no path from a model's answer to it, so the program
was composed, spoken, and thrown away.

What she says instead names the file, the language and the size — the
three things that let him decide whether to open it — and nothing else.
He can ask her to read it, or open it himself. `talking is not doing`
cuts both ways: an answer containing a program that nobody saved is a
promise, not a deliverable.

WHAT THIS IS NOT. It does not RUN anything. `script.run` is the sandbox,
with its import whitelist and no network, and it stays the only thing
that executes. A file on disk that he chose to open is his decision;
`.py` is not marked executable and nothing here launches an interpreter.
"""
from __future__ import annotations

import re

#: A fenced block, with its language tag if the model gave one. Non-greedy
#: so two blocks in one answer stay two blocks, and tolerant of a missing
#: closing fence, which a truncated answer will have.
FENCE = re.compile(
    r"```([a-zA-Z0-9_+#.-]*)[ \t]*\r?\n(.*?)(?:\r?\n```|\Z)", re.DOTALL)

#: What to call the file, by what the model said it was. The value is the
#: suffix; the KEY is what she says out loud.
LANGUAGES = {
    "python": ".py", "py": ".py", "python3": ".py",
    "javascript": ".js", "js": ".js", "typescript": ".ts", "ts": ".ts",
    "bash": ".sh", "sh": ".sh", "shell": ".sh", "zsh": ".sh",
    "powershell": ".ps1", "ps1": ".ps1", "batch": ".bat",
    "json": ".json", "yaml": ".yml", "yml": ".yml", "toml": ".toml",
    "html": ".html", "css": ".css", "sql": ".sql", "csv": ".csv",
    "markdown": ".md", "md": ".md", "text": ".txt", "": ".txt",
}

#: Said the way a person says it, for the sentence.
SPOKEN_LANGUAGE = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
    ".sh": "a shell script", ".ps1": "PowerShell", ".bat": "a batch file",
    ".json": "JSON", ".yml": "YAML", ".toml": "TOML", ".html": "HTML",
    ".css": "CSS", ".sql": "SQL", ".csv": "CSV", ".md": "Markdown",
    ".txt": "text",
}

#: Below this a "block" is an inline example, not a program — three lines
#: of illustration belong in the sentence, where he can hear them.
MIN_LINES = 4
#: And above this it is not going in a spoken answer at all.
MAX_BLOCK_BYTES = 200_000
#: Where she puts them, inside the workspace she already owns.
SUBDIR = "code"


def blocks(text: str) -> list[dict]:
    """Every fenced block in a model's answer, longest-lived first.

    Returns dicts rather than tuples because a caller wants the language
    AND the body AND how long it is, and a three-tuple at a call site
    reads as nothing.
    """
    found = []
    for match in FENCE.finditer(str(text or "")):
        body = match.group(2).strip("\r\n")
        if not body.strip():
            continue
        found.append({
            "language": (match.group(1) or "").strip().casefold(),
            "code": body,
            "lines": len(body.splitlines()),
            "span": match.span(),
        })
    return found


def worth_saving(block: dict) -> bool:
    """A program, as opposed to an example of a line.

    Three lines of illustration belong IN the sentence: "run it with
    python rename.py --go" is an answer, and turning it into a file he has
    to go open is worse than saying it.
    """
    return (block["lines"] >= MIN_LINES
            and len(block["code"].encode("utf-8")) <= MAX_BLOCK_BYTES)


def _suffix(block: dict) -> str:
    return LANGUAGES.get(block["language"], ".txt")


#: A filename the answer itself uses — "run it with python rename.py", or
#: a leading `# rename.py` comment. Bounded to a plain name so a URL, a
#: version number or `os.path` cannot masquerade as one.
_NAMED_IN_TEXT = re.compile(
    r"(?<![\w./\\-])([a-z][a-z0-9_-]{1,40})"
    r"(\.(?:py|js|ts|sh|ps1|bat|json|ya?ml|toml|html|css|sql|csv|md))"
    # Not `(?![\w/\\])`: that let `example.py.org/x` through as
    # "example.py", because the character after ".py" was a dot. Reject a
    # dot only when a word follows it, so a domain is refused and
    # "run it with python rename.py." at the end of a sentence is not.
    r"(?![\w/\\]|\.\w)", re.I)


def _named_in(text: str, suffix: str) -> str:
    """The name the ANSWER gave it, if the answer gave it one.

    She wrote a script and told him to "run it with `python rename.py`",
    then filed it as `renames-files.py`. Both sentences were hers, one
    turn apart, and the one he would act on was wrong. A file has to be
    called what its own instructions call it.

    The code block itself is searched first — a `# rename.py` header is
    the model being explicit — and then the prose around it.
    """
    for match in _NAMED_IN_TEXT.finditer(str(text or "")):
        if match.group(2).casefold() == suffix.casefold():
            return (match.group(1) + match.group(2)).casefold()
    return ""


def _name_for(block: dict, hint: str, *, answer: str = "") -> str:
    """A filename from what he ASKED for, not from what the code says.

    "rename-files.py" comes out of "write me a python script that renames
    files"; naming it after the first function in the body gives him
    `rename_files.py` for one script and `main.py` for the next four.

    Unless the answer named it, in which case that wins — see `_named_in`.
    """
    suffix = _suffix(block)
    said = _named_in(block["code"], suffix) or _named_in(answer, suffix)
    if said:
        return said
    words = [w for w in re.split(r"[^a-z0-9]+", str(hint or "").casefold()) if w]
    skip = {"write", "me", "a", "an", "the", "can", "you", "please", "make",
            "create", "give", "some", "script", "program", "code", "function",
            "for", "that", "which", "to", "in", "with", "and", "my", "python",
            "javascript", "bash", "shell", "powershell", "quick", "simple"}
    kept = [w for w in words if w not in skip][:4]
    stem = "-".join(kept) or "snippet"
    return f"{stem}{_suffix(block)}"


def prose_only(text: str) -> str:
    """The answer with every PROGRAM lifted out, and short examples kept.

    The two halves are different on purpose. A sixty-line script read
    aloud is two minutes of nothing, so it goes; "run it with `python
    rename.py --go`" is the answer to his question, so it stays. The
    dividing line is `worth_saving` — the same predicate that decides
    what gets written — so a block is never both spoken AND filed, and
    never neither.
    """
    said = str(text or "")
    out, last = [], 0
    for block in blocks(said):
        start, end = block["span"]
        out.append(said[last:start])
        if not worth_saving(block):
            # Short enough to be part of the sentence. The fence markers
            # go; the line itself is what he asked for.
            out.append(f" {block['code']} ")
        last = end
    out.append(said[last:])
    return " ".join("".join(out).split())


def save(text: str, *, asked: str = "", why: str = "") -> list[dict]:
    """Write every block worth keeping into her workspace.

    Returns one row per file with the name, language, lines and path. An
    empty list means there was nothing in the answer but prose, which is
    the ordinary case and not a failure.

    Never raises for the caller's sake: a spoken answer that fails because
    the workspace was full would replace a good sentence with a bad one.
    A block that could not be written is simply not claimed.
    """
    from aletheia import journal, workspace

    saved: list[dict] = []
    seen: set[str] = set()
    for index, block in enumerate(blocks(text)):
        if not worth_saving(block):
            continue
        name = _name_for(block, asked, answer=text)
        if name in seen:
            stem, _, ext = name.rpartition(".")
            name = f"{stem}-{index + 1}.{ext}"
        seen.add(name)
        relative = f"{SUBDIR}/{name}"
        try:
            written = workspace.write(relative, block["code"] + "\n",
                                      why=why or f"code she wrote for: {asked[:80]}")
        except Exception:
            # Rule zero's other half: name what failed rather than
            # pretending it did not happen — but not in the room. The
            # sentence simply will not claim a file that is not there.
            journal.append("event", "aletheia-codeblocks",
                           f"could not save a {block['language'] or 'text'} "
                           f"block for {asked[:60]!r}",
                           actor="aletheia-codeblocks")
            continue
        saved.append({
            "name": name,
            "path": written.get("path", relative),
            "lines": block["lines"],
            "language": SPOKEN_LANGUAGE.get(_suffix(block), "text"),
            "replaced": not written.get("created", True),
        })
    return saved


#: Suffixes whose contents are a program rather than a document. Reading
#: one out loud is the defect this module exists to stop; a .md or .txt
#: is prose and is read.
CODE_SUFFIXES = frozenset({".py", ".js", ".ts", ".sh", ".ps1", ".bat",
                           ".sql", ".css", ".html", ".json", ".yml",
                           ".yaml", ".toml"})

#: What a top-level thing is called, per language, for "it defines...".
_DEFINITIONS = (
    re.compile(r"(?m)^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)"),        # python
    re.compile(r"(?m)^\s*class\s+([A-Za-z_]\w*)"),                   # python/js
    re.compile(r"(?m)^\s*(?:export\s+)?function\s+([A-Za-z_]\w*)"),  # js/ts
    re.compile(r"(?m)^\s*(?:function\s+)?([A-Za-z_][\w-]*)\s*\(\)\s*\{"),  # sh
)


def is_code(name: str) -> bool:
    stem, _, ext = str(name or "").rpartition(".")
    return bool(stem) and f".{ext}".casefold() in CODE_SUFFIXES


def describe(code: str, name: str = "") -> str:
    """What a program IS, in a sentence, without reciting it.

    "Read rename.py" is a reasonable thing to say and reciting fifteen
    lines of Python back is not an answer to it — it is the same two
    minutes of nothing this module was written to prevent, arriving
    through the other door. What he means by "go through it" is what it
    does and what is in it.

    Deterministic: line count, language, the names it defines, and
    whether it runs from the command line. No model, no round trip, and
    nothing it can invent — every claim is a thing counted or matched.
    """
    from aletheia import speech

    body = str(code or "")
    # THE SAME COUNT BOTH TIMES. Saving it said "15 lines of Python" and
    # reading it back said 11, because one counted every line and the
    # other skipped the blank ones. Two numbers for one file, a turn
    # apart, and no way for him to tell which is the file.
    lines = len(body.splitlines())
    suffix = f".{str(name).rpartition('.')[2]}".casefold() if name else ""
    language = SPOKEN_LANGUAGE.get(suffix, "code")
    said = f"{name or 'It'} is {lines} lines of {language}."

    found: list[str] = []
    for pattern in _DEFINITIONS:
        for match in pattern.finditer(body):
            word = match.group(1)
            if word not in found and not word.startswith("_"):
                found.append(word)
    if found:
        shown = found[:5]
        more = (f", and {len(found) - len(shown)} more"
                if len(found) > len(shown) else "")
        said += f" It defines {speech.and_list(shown)}{more}."
    if re.search(r"__main__|argparse|process\.argv|\$@", body):
        said += " It runs from the command line."
    return said


def spoken(saved: list[dict]) -> str:
    """Where the files went, in a sentence.

    The name, the language and the size, because those are the three
    things that let him decide whether to open it. Not the path: a
    Windows path read aloud is unusable, and `file.find` will find it by
    name the moment he asks.
    """
    from aletheia import speech

    if not saved:
        return ""
    parts = []
    for row in saved:
        kept = " (your previous version is kept)" if row["replaced"] else ""
        parts.append(f"{row['name']}, {row['lines']} lines of "
                     f"{row['language']}{kept}")
    lead = "I saved it in my workspace as " if len(saved) == 1 else \
           "I saved them in my workspace as "
    # NAME THE FILE IN THE OFFER. "Say read it" needs a referent she does
    # not reliably have a turn later, and an offer she cannot keep is a
    # claim about ability — the same defect as "should I pull them from
    # your bank data?" when there is no bank data. Saying the name makes
    # the offer true with no state at all.
    ask = f"Say read {saved[0]['name']}" if len(saved) == 1 else \
          f"Say read {saved[0]['name']} for the first one"
    return (lead + speech.and_list(parts) + f". {ask} and I'll go through it.")
