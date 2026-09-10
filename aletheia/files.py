"""She can read a file he names, and could not find one.

    > what's in my downloads folder
    > find that PDF the landlord sent
    > do I have anything called lease

`workspace.read(anywhere=True)` will open any file on the disk, and its
module docstring says why: *"reading is deliberately WIDER than writing,
because 'look at my resume in Downloads' is a reasonable thing to say and
reading cannot destroy it."* True — and it takes a PATH. He does not know
the path. Nobody knows the path. `workspace.listing()` lists the one
directory she owns, which is the one directory he never puts anything in.

So the honest shape of what she had was: she can open a file if he can
tell her exactly where it is. That is not a capability, that is a
precondition he cannot meet, and it is why `applications.py` grew its own
private resume-finder — RESUME_PLACES, RESUME_NAMES, an mtime sort — for
one caller, because the general thing did not exist. That finder is the
proof this belongs in the system rather than in a module about job
applications; it now calls in here (rule zero: one implementation).

THE BOUNDARY. Listing is read-only and still needs an edge, because "find
my stuff" over a whole disk is a different act than it sounds like:

- **Named places, not the whole disk.** `PLACES` is Desktop, Documents,
  Downloads, Pictures, their OneDrive mirrors, and her own workspace —
  where a person keeps things. Not `C:\\`, not AppData, not Program Files.
  A search that walks everything finds his browser cache and the answer
  becomes unreadable long before it becomes dangerous.
- **Bounded depth and bounded results.** `MAX_DEPTH` and `MAX_RESULTS`,
  because a node_modules under Documents is 40,000 files and a sentence
  that begins "I found 40,000 things" has answered nothing.
- **Never the contents.** This says a file EXISTS, its name, where, how
  big, when he last touched it. Reading it is `document.read_any`, which
  has its own ceilings. Two capabilities because they are two decisions.
- **Skips what he did not put there.** Dotfiles, `~$` Office lock files,
  `.versions/` (her own undo history), and anything inside a directory
  whose name starts with a dot or is `node_modules`/`__pycache__`/`venv`.

Newest first, always — the lesson `applications` already learned out
loud: the one he last touched is the one he means.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

#: Where a person keeps things. Order matters only for tie-breaking a
#: name that exists in two places; the results are sorted by time.
PLACES: tuple[str, ...] = (
    "Desktop", "Documents", "Downloads", "Pictures",
    "OneDrive/Desktop", "OneDrive/Documents", "OneDrive/Downloads",
    "OneDrive/Pictures",
    "OneDrive - Personal/Desktop", "OneDrive - Personal/Documents",
    "OneDrive - Personal/Downloads",
)

#: How deep to walk inside one of those. Two is "Documents/Taxes/2025".
MAX_DEPTH = 3
#: What a sentence can carry. He is being read a list out loud.
MAX_RESULTS = 40
#: What one walk may look at before giving up on that place, so a folder
#: someone pointed a build tool at cannot hang the room.
MAX_SCANNED = 20_000

#: Directories that are software, not his things.
SKIP_DIRS = frozenset({
    "node_modules", "__pycache__", "venv", ".venv", "env", "AppData",
    "Library", "site-packages", "dist-info", ".git", ".versions",
    "$RECYCLE.BIN", "System Volume Information",
})

#: Files that exist for a program's sake.
SKIP_SUFFIXES = frozenset({".tmp", ".crdownload", ".part", ".lnk", ".ini"})


class FilesError(RuntimeError):
    """Said in English, because it is going to be read out in a room."""


def home() -> Path:
    return Path(os.environ.get("ALETHEIA_HOME_OVERRIDE") or Path.home())


def places() -> list[tuple[str, Path]]:
    """The named places that actually exist on this machine.

    Her workspace is included by calling `workspace.root()` rather than
    guessing at `~/Documents/Aletheia`: the operator may have moved it,
    and a finder that looks where the default USED to be reports "no such
    file" about a file she wrote herself.
    """
    found: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    base = home()
    for name in PLACES:
        path = base / name
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen or not path.is_dir():
            continue
        seen.add(resolved)
        found.append((name, path))
    try:
        from aletheia import workspace
        ws = workspace.root()
        if ws.resolve() not in seen:
            # "my workspace", not "her": this string is READ OUT, and she
            # is the one saying it. Same defect the registry had in
            # fifteen descriptions, reintroduced here within the hour.
            found.append(("my workspace", ws))
    except Exception:
        # A workspace that refuses to exist is not a reason to stop
        # finding his own files, which is the whole point of this module.
        pass
    return found


def _named(raw: str) -> Path | None:
    """A place he named, if he named one she knows."""
    said = str(raw or "").strip().strip("/\\").casefold()
    if not said:
        return None
    for name, path in places():
        tail = name.split("/")[-1].casefold()
        if said in (name.casefold(), tail) or said == str(path).casefold():
            return path
    return None


def _skip_dir(path: Path) -> bool:
    name = path.name
    return name in SKIP_DIRS or name.startswith(".")


def _skip_file(path: Path) -> bool:
    name = path.name
    if name.startswith(".") or name.startswith("~$"):
        return True
    return path.suffix.casefold() in SKIP_SUFFIXES


def _walk(start: Path, depth: int, budget: list[int]):
    """Files under `start`, bounded in both directions.

    `budget` is a one-element list so the count is shared across the
    recursion without a class or a global: one place he pointed at a
    checkout must not spend the whole search.
    """
    if depth < 0 or budget[0] <= 0:
        return
    try:
        entries = sorted(start.iterdir())
    except (OSError, PermissionError):
        return
    for entry in entries:
        budget[0] -= 1
        if budget[0] <= 0:
            return
        try:
            if entry.is_dir():
                if not _skip_dir(entry):
                    yield from _walk(entry, depth - 1, budget)
            elif entry.is_file() and not _skip_file(entry):
                yield entry
        except OSError:
            continue


def _words(text: str) -> list[str]:
    out, current = [], []
    for ch in str(text):
        if ch.isalnum():
            current.append(ch.casefold())
        elif current:
            out.append("".join(current))
            current = []
    if current:
        out.append("".join(current))
    return out


def matches(name: str, terms: list[str]) -> bool:
    """Every word he said appears in the filename.

    ALL of them, not any: "lease pdf" should not return every PDF he
    owns. Substring within a word on purpose — "invoic" finds "Invoice",
    and he is typing or speaking, not writing a regex.
    """
    return rank(name, terms) is not None


def rank(name: str, terms: list[str]) -> int | None:
    """How well the name matches: 0 is a real match, 1 is a coincidence.

    None means no match at all.

    Substring matching earns its keep at the START of a word — "invoic"
    finds "Invoice" and he should not have to spell it out. In the MIDDLE
    of one it is mostly an accident: asked to find "lease" she came back
    with "Greek Release Appeal" three times, filling three of the five
    slots a spoken answer has with a coincidence and pushing the real
    lease off the end. Recall is still worth having, so the coincidences
    are kept and ranked BELOW the real matches rather than thrown away.
    """
    if not terms:
        return 0
    words = _words(name)
    if not words:
        return None
    worst = 0
    for term in terms:
        if any(w.startswith(term) for w in words):
            continue
        if any(term in w for w in words):
            worst = 1
            continue
        return None
    return worst


def _row(path: Path) -> dict:
    stat = path.stat()
    return {
        "name": path.name,
        "path": str(path),
        "folder": str(path.parent),
        "bytes": stat.st_size,
        "modified": stat.st_mtime,
    }


def search(query: str = "", *, place: str = "",
           limit: int = MAX_RESULTS) -> dict:
    """Files whose names carry his words, newest first, AND how many there are.

    An empty query with a place is "what's in my downloads"; a query with
    no place is "find my lease" and searches all of them.

    The total is separate from the list because the first version of this
    conflated them: `MAX_RESULTS` capped the list at 40 and the sentence
    then said "40 files in Downloads" about 648, followed by "the other 35
    are there too" - arithmetic on the cap. A number he cannot check is
    exactly the kind of confident wrongness this system exists to avoid,
    so the count is counted and the list is cut, and `capped` says whether
    even the COUNT hit its scan budget ("at least", not a figure).
    """
    terms = _words(query)
    named = _named(place) if place else None
    if place and named is None:
        from aletheia import speech
        raise FilesError(
            f"she does not know a folder called {place}. She can look in "
            + speech.or_list(place_names()) + ".")
    targets = [("", named)] if named else places()
    found: list[dict] = []
    ran_out = False
    for _name, path in targets:
        budget = [MAX_SCANNED]
        for entry in _walk(path, MAX_DEPTH, budget):
            how_well = rank(entry.name, terms)
            if how_well is not None:
                try:
                    row = _row(entry)
                except OSError:
                    continue
                row["rank"] = how_well
                found.append(row)
        if budget[0] <= 0:
            ran_out = True
    # Real matches before coincidences, then newest first: the one he
    # last touched is the one he means. Without the first key, "lease"
    # spent three of its five spoken slots on "Greek Release Appeal".
    found.sort(key=lambda row: (-row.get("rank", 0), row["modified"]),
               reverse=True)
    deduped: list[dict] = []
    seen: set[str] = set()
    for row in found:
        key = row["path"].casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    cut = max(1, int(limit or MAX_RESULTS))
    return {"files": deduped[:cut], "total": len(deduped), "capped": ran_out,
            "query": query, "place": place}


def find(query: str = "", *, place: str = "", limit: int = MAX_RESULTS) -> list[dict]:
    """Just the files, for a caller that does not need the count."""
    return search(query, place=place, limit=limit)["files"]


def folder_size(place: str) -> dict:
    """How much is in one of his folders, and how big it is.

    Asked "how big is my downloads folder" she spent 28 seconds compiling
    a two-step plan — open File Explorer, read the properties dialog —
    and asked for approval to run it. She was already holding every one of
    those numbers: `search` reads `st_size` for each file on the way past.
    A capability that exists and is not reachable from the sentence is the
    same as one that does not exist, except slower and with a prompt.
    """
    result = search("", place=place, limit=1)
    total = 0
    count = 0
    named = _named(place)
    budget = [MAX_SCANNED]
    for entry in _walk(named, MAX_DEPTH, budget):
        try:
            total += entry.stat().st_size
        except OSError:
            continue
        count += 1
    return {"place": place, "bytes": total, "files": count,
            "capped": budget[0] <= 0, "newest": result["files"][:1]}


def size_spoken(size: dict) -> str:
    from aletheia import speech

    where = size.get("place") or "that folder"
    head = "at least " if size.get("capped") else ""
    return (f"{where} holds {head}{speech.count_phrase(size['files'], 'file')}, "
            f"{size_words(size['bytes'])} in all.")


def newest(query: str = "", *, place: str = "") -> dict | None:
    """The single best match, or None. What a caller wanting ONE file wants."""
    found = find(query, place=place, limit=1)
    return found[0] if found else None


def when_words(modified: float, *, now: float | None = None) -> str:
    """"yesterday", not "1757203200.0".

    A timestamp in a spoken sentence is the same defect as `hours: 168`
    coming out as "the last 168 hours": the number is for arithmetic and
    the words are for him.
    """
    seconds = max(0.0, (now if now is not None else time.time()) - float(modified))
    days = seconds / 86400.0
    if days < 1:
        return "today"
    if days < 2:
        return "yesterday"
    if days < 7:
        return f"{int(days)} days ago"
    if days < 14:
        return "last week"
    if days < 60:
        return f"{max(1, int(days // 7))} weeks ago"
    if days < 365:
        return f"{max(1, int(days // 30))} months ago"
    years = max(1, int(days // 365))
    return "a year ago" if years == 1 else f"{years} years ago"


def size_words(size: int) -> str:
    """A size a person would say.

    The first version stopped at megabytes — a loop whose only exit for a
    large number was `unit == "MB"` — so his Downloads folder came back as
    "15347.9 MB in all" instead of "15 GB". Fifteen thousand of anything
    is not an answer to "how big is it".
    """
    value = float(max(0, int(size)))
    if value < 1024:
        return f"{int(value)} bytes"
    for unit in ("KB", "MB", "GB"):
        value /= 1024.0
        if value < 1024 or unit == "GB":
            # No decimal once the number is big enough to carry meaning on
            # its own: "15 GB", not "14.9 GB".
            if value >= 10:
                return f"{value:.0f} {unit}"
            return f"{value:.1f} {unit}".replace(".0 ", " ")
    return f"{value:.0f} GB"


def place_words(row: dict) -> str:
    """Where it is, as he would say it — the folder, not the full path."""
    folder = Path(row.get("folder") or "")
    base = home()
    try:
        relative = folder.resolve().relative_to(base.resolve())
        said = str(relative).replace("\\", "/")
        return said or "your home folder"
    except (OSError, ValueError):
        return folder.name or str(folder)


#: What a suffix IS, said the way he would say it. The extension itself
#: is punctuation out loud - "dot p d f" - and the kind is what he wants.
KINDS = {
    ".pdf": "a PDF", ".docx": "a Word document", ".doc": "a Word document",
    ".xlsx": "a spreadsheet", ".xls": "a spreadsheet", ".csv": "a spreadsheet",
    ".pptx": "a slide deck", ".ppt": "a slide deck",
    ".png": "a picture", ".jpg": "a picture", ".jpeg": "a picture",
    ".gif": "a picture", ".webp": "a picture", ".heic": "a picture",
    ".mp4": "a video", ".mov": "a video", ".mkv": "a video",
    ".mp3": "audio", ".wav": "audio", ".m4a": "audio",
    ".zip": "a zip file", ".txt": "a text file", ".md": "a text file",
    ".json": "a data file",
}

#: A word this long carrying both letters and digits is a machine's name
#: for something, not his.
TOKEN_LENGTH = 14
#: And a bare run of digits this long is an id, not a number he wants read
#: to him. `7645813995346708496` comes out as seven quintillion.
DIGIT_RUN = 9


def _sayable_word(word: str) -> str:
    if word.isdigit():
        return "a long number" if len(word) >= DIGIT_RUN else word
    if len(word) < TOKEN_LENGTH:
        return word
    if not any(c.isdigit() for c in word):
        return word
    return f"{word[:6]} and a long string of letters and numbers"


#: Letters whose NAME starts with a vowel sound, for an extension that is
#: spelled out rather than said. "a 8xp file" and "a f4v file" are both
#: wrong out loud, and the rule is the SOUND, not the letter: "an F", "an
#: 8", "a U", "a W" (double-you).
_SOUNDS_LIKE_A_VOWEL = frozenset("aefhilmnorsx8")


def _a_or_an(word: str) -> str:
    """The right article for something he will hear, not read."""
    first = str(word or "").strip().casefold()[:1]
    if not first:
        return "a"
    if first in _SOUNDS_LIKE_A_VOWEL:
        return "an"
    return "a"


def name_words(name: str) -> str:
    """A filename a person can hear.

    Live on his PC the first version read out
    `tiktok1fJfKZJSK3nexvlIlV0mIcsbcrre9YkL (2).txt` and
    `developers.tiktok.com_app_7645813995346708496_pending (1).png`. Both
    are real filenames and neither is a sentence: separators are silence
    out loud, and a download token is forty syllables of nothing.

    Separators become spaces, the extension becomes what the file IS, and
    a long alphanumeric token is shortened WITH THE SHORTENING SAID ALOUD
    - she is not allowed to quietly hand him a name that is not the name.
    """
    raw = str(name or "").strip()
    stem, suffix = raw, ""
    if "." in raw[1:]:
        stem, _, ext = raw.rpartition(".")
        suffix = f".{ext}".casefold()
    for separator in ("_", "-", ".", "(", ")", "[", "]"):
        stem = stem.replace(separator, " ")
    said = " ".join(_sayable_word(w) for w in stem.split())
    if not said:
        said = raw
    kind = KINDS.get(suffix)
    if kind:
        return f"{said}, {kind}"
    if suffix:
        ext = suffix.lstrip(".")
        return f"{said}, {_a_or_an(ext)} {ext} file"
    return said


def place_names() -> list[str]:
    """The places she looked, said once each.

    `PLACES` holds `Documents` and `OneDrive/Documents` - two real
    directories, one word when spoken. "I looked in Desktop, Documents,
    Downloads, Pictures, Documents, Pictures and her workspace" sounds
    like she lost her place. What she SEARCHES and what she SAYS are two
    questions, so only the second one deduplicates.
    """
    said: list[str] = []
    for name, _path in places():
        tail = name.split("/")[-1]
        if tail not in said:
            said.append(tail)
    return said


def spoken(result, *, query: str = "", place: str = "", limit: int = 5) -> str:
    """The list, said out loud.

    Never the full path: `C:/Users/caleb/OneDrive - Personal/Documents`
    read aloud is forty syllables of punctuation. The name, the folder,
    and when he last touched it, because that is how he recognises it.

    The folder is dropped when HE named the folder. "40 files in
    Downloads: x, in Downloads, last week, y, in Downloads, last week"
    says the one word he already knows six times.

    Takes the whole `search` result so the count can be the REAL count. A
    bare list is still accepted - a caller holding five rows and wanting a
    sentence should not have to invent a total - it just cannot then claim
    one.
    """
    from aletheia import speech

    if isinstance(result, dict):
        found = list(result.get("files") or [])
        total = int(result.get("total") or len(found))
        capped = bool(result.get("capped"))
        query = query or result.get("query") or ""
        place = place or result.get("place") or ""
    else:
        found, total, capped = list(result), len(list(result)), False

    where = f" in {place}" if place else ""
    about = f" matching {query}" if query else ""
    if not found:
        said = (f"I could not find anything{about}{where}. I looked in "
                + speech.and_list(place_names()) + ".")
        # "Find the PDF the landlord sent" is a reasonable sentence and an
        # impossible search: nothing about who sent a file is in its name.
        # Saying only "I could not find it" leaves him thinking the file
        # is gone. An OFFER is a claim about ability, and so is a silence
        # about what the search actually looked at.
        if len(_words(query)) > 2:
            said += (" I match the name of a file, not what is inside it or "
                     "who sent it — try a word that would be in the name.")
        return said
    shown = found[:max(1, int(limit))]
    lines = []
    for row in shown:
        # His folder, only when he did not say it himself.
        middle = "" if place else f", in {place_words(row)}"
        lines.append(f"{name_words(row['name'])}{middle}, "
                     f"{when_words(row['modified'])}")
    head = speech.count_phrase(total, "file")
    if capped:
        head = f"at least {head}"
    more = ""
    if total > len(shown):
        rest = total - len(shown)
        more = (f" That is the newest {len(shown)}; "
                f"{speech.count_phrase(rest, 'other')} "
                f"{'is' if rest == 1 else 'are'} there too.")
    return f"{head}{about}{where}: " + speech.and_list(lines) + f".{more}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Find his files.")
    parser.add_argument("query", nargs="*", help="words in the filename")
    parser.add_argument("--place", default="", help="Downloads, Desktop, ...")
    parser.add_argument("--limit", type=int, default=MAX_RESULTS)
    parser.add_argument("--say", action="store_true", help="as she would say it")
    args = parser.parse_args(argv)
    query = " ".join(args.query)
    try:
        result = search(query, place=args.place, limit=args.limit)
        found = result["files"]
    except FilesError as exc:
        print(exc)
        return 1
    if args.say:
        print(spoken(result))
        return 0
    if not found:
        print("nothing found")
        return 1
    for row in found:
        print(f"{when_words(row['modified']):>12}  {size_words(row['bytes']):>10}"
              f"  {row['path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
