"""A place she may write, and a hard edge around it.

Two gaps closed together, because the second is only safe because of the
first. She could think but not produce: no document, no spreadsheet, no
file of any kind. "Open my resume and fix the formatting" compiled to
nothing at all. And most of what sounds like desktop control is really a
FILE operation wearing a GUI — driving Word to edit a document is the
dangerous way to do something a text edit does safely.

So: one directory she owns, and a boundary that holds.

THE BOUNDARY, and why each rule is here rather than assumed:

- **One root, everything under it.** Default `~/Aletheia`, overridable by
  the operator. Every path is resolved to its real location and checked
  against the resolved root, so `../` escapes, absolute paths, and
  SYMLINKS pointing out of the workspace are all refused by the same
  check. Resolving first is the point: a symlink is how a confinement
  built on string prefixes gets walked out of.
- **Nothing is overwritten without a copy of what was there.** Every
  write to an existing file keeps the previous version in `.versions/`
  first. She will get something wrong eventually; the question is whether
  that costs him a paragraph or an afternoon.
- **Never his whole disk.** The root may not BE or CONTAIN his home
  directory, Desktop, Documents, or a system path — a workspace that
  resolves to `C:\\Users\\him` is not a workspace, it is everything.
- **Bounded.** A file has a size ceiling and the workspace has a file
  count, so a loop that writes forever fills a directory rather than a
  disk.

Reading is deliberately WIDER than writing: she may read a file he names
anywhere, because "look at my resume in Downloads" is a reasonable thing
to say and reading cannot destroy it. Writing is workspace-only, always,
with no argument that widens it.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import shutil
import sys
from pathlib import Path

from aletheia import journal, policy, stateio

ACTOR = "aletheia-workspace"

# Her own directory under his Documents — NOT ~/Aletheia, which on the
# operator's PC is this repository's checkout. A workspace inside the repo
# put every file she produced into `git status` (which makes the Core's
# sync refuse to touch "a person's uncommitted work"), and counted the
# 2,000+ tracked files against her own ceiling, so the very first real
# write was refused as "the workspace already holds 2000 files" (found
# live 2026-09-02). root() now refuses a repository outright.
DEFAULT_ROOT = Path.home() / "Documents" / "Aletheia"
MAX_FILE_BYTES = 5_000_000
MAX_READ_BYTES = 2_000_000
MAX_FILES = 2_000
VERSIONS = ".versions"

# Text-shaped things she may author. A binary format she cannot write
# correctly is a corrupted file with a confident receipt attached.
TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".yaml", ".yml",
    ".html", ".htm", ".css", ".js", ".py", ".sh", ".ps1", ".sql", ".ini",
    ".cfg", ".toml", ".rst", ".log", ".srt", ".vtt", ".xml", ".tex",
}


class WorkspaceError(RuntimeError):
    pass


class OutsideWorkspace(PermissionError):
    """A path that is not hers to write."""


def root() -> Path:
    """The workspace root, refusing a root that is too big to be one."""
    raw = os.environ.get("ALETHEIA_WORKSPACE")
    path = Path(raw).expanduser() if raw else DEFAULT_ROOT
    path.mkdir(parents=True, exist_ok=True)
    resolved = path.resolve()
    home = Path.home().resolve()
    forbidden = [home] + [home / n for n in
                          ("Desktop", "Documents", "Downloads", "Pictures")]
    forbidden += [Path(p) for p in ("/", "/etc", "/usr", "/bin", "C:\\", "C:\\Windows")]
    for bad in forbidden:
        try:
            if resolved == bad.resolve():
                raise WorkspaceError(
                    f"{resolved} is not a workspace, it is everything under it. "
                    "Point ALETHEIA_WORKSPACE at a directory of its own.")
        except (OSError, ValueError):
            continue
    _refuse_repository(resolved)
    return resolved


def _refuse_repository(resolved: Path) -> None:
    """A source repository is not a workspace, and neither is anything
    inside one. Files she writes there land in `git status`, the Core's
    sync then refuses to rebase past "a person's uncommitted work", and the
    repository's own files count against her ceiling."""
    from aletheia.fleet import REPO_ROOT
    try:
        repo = Path(REPO_ROOT).resolve()
    except OSError:
        repo = None
    inside_repo = repo is not None and (resolved == repo or repo in resolved.parents)
    if inside_repo or (resolved / ".git").exists():
        raise WorkspaceError(
            f"{resolved} is a source repository (or inside one), not a "
            "workspace: what she writes there would sit in git status and "
            "block the Core's sync. Point ALETHEIA_WORKSPACE at a directory "
            "of its own — the default is ~/Documents/Aletheia.")


def resolve(relative: str) -> Path:
    """A path inside the workspace, or a refusal.

    Resolution happens BEFORE the containment check, which is what makes a
    symlink out of the workspace fail here rather than succeed quietly. A
    check written against the raw string would pass `notes/../../../etc`
    and follow a planted link straight out.
    """
    raw = str(relative or "").strip()
    if not raw:
        raise OutsideWorkspace("a path is required")
    # An ABSOLUTE path is refused outright, never quietly made relative.
    # Stripping the leading slash turned "/etc/passwd" into
    # "<workspace>/etc/passwd" — contained, but not what he said, and a
    # confident write to a path nobody named is worse than a refusal.
    # (Caught by this module's own boundary test.) Windows drive letters
    # and UNC shares count as absolute even on a POSIX runner, because the
    # check must mean the same thing on the machine this actually runs on.
    normalized = raw.replace("\\", "/")
    if (normalized.startswith("/") or normalized.startswith("//")
            or (len(normalized) > 1 and normalized[1] == ":")):
        raise OutsideWorkspace(
            f"{relative!r} is an absolute path. She writes inside her own "
            "workspace, and a path relative to it is what she needs — a "
            "leading slash is not quietly ignored.")
    value = normalized.strip("/")
    if not value:
        raise OutsideWorkspace("a path is required")
    base = root()
    candidate = (base / value)
    # resolve(strict=False): the file need not exist yet, but every existing
    # component of the path — including symlinks — is followed first.
    real = candidate.resolve()
    try:
        real.relative_to(base)
    except ValueError:
        raise OutsideWorkspace(
            f"{relative!r} lands outside the workspace ({real}). She writes "
            "inside her own directory and nowhere else.") from None
    if VERSIONS in real.parts:
        raise OutsideWorkspace(
            "the version history is hers to keep, not to edit — it is the "
            "copy of your work that exists when she gets something wrong")
    return real


def _text_ok(path: Path) -> None:
    if path.suffix.casefold() not in TEXT_SUFFIXES:
        raise WorkspaceError(
            f"{path.suffix or 'that'} is not a text format she can author "
            f"correctly. Writable: {', '.join(sorted(TEXT_SUFFIXES))}")


def _count() -> int:
    base = root()
    return sum(1 for p in base.rglob("*") if p.is_file() and VERSIONS not in p.parts)


def read(path: str, *, anywhere: bool = False) -> dict:
    """Read a file. Reading is wider than writing — she may read what he
    names, because "look at my resume in Downloads" is reasonable and
    reading destroys nothing."""
    target = Path(path).expanduser().resolve() if anywhere else resolve(path)
    if not target.is_file():
        raise WorkspaceError(f"{path} is not a file")
    size = target.stat().st_size
    if size > MAX_READ_BYTES:
        raise WorkspaceError(f"{path} is {size:,} bytes; the read ceiling is "
                             f"{MAX_READ_BYTES:,}")
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise WorkspaceError(f"{path} is not UTF-8 text — she cannot read it "
                             "honestly, so she does not guess") from None
    journal.append("action", "workspace:read", f"read {target.name} ({size:,} bytes)",
                   actor=ACTOR)
    return {"path": str(target), "bytes": size, "text": text}


def _keep_previous(target: Path) -> str | None:
    """Copy what is there before replacing it. She will get something wrong
    eventually; this decides whether that costs a paragraph or an afternoon."""
    if not target.exists():
        return None
    base = root()
    stamp = stateio.utcnow().replace(":", "").replace("-", "")
    kept = base / VERSIONS / target.relative_to(base).parent / f"{target.stem}-{stamp}{target.suffix}"
    kept.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, kept)
    return str(kept.relative_to(base))


def write(path: str, text: str, *, why: str = "") -> dict:
    """Create or replace a file in the workspace, keeping the old version."""
    policy.ensure_not_halted()
    target = resolve(path)
    _text_ok(target)
    data = str(text)
    if len(data.encode("utf-8")) > MAX_FILE_BYTES:
        raise WorkspaceError(f"that is over the {MAX_FILE_BYTES:,}-byte file ceiling")
    if not target.exists() and _count() >= MAX_FILES:
        raise WorkspaceError(
            f"the workspace already holds {MAX_FILES} files — clear some out "
            "rather than letting a loop fill the disk")
    previous = _keep_previous(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".partial")
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(target)          # atomic: no half-written file survives a crash
    journal.append(
        "action", "workspace:write",
        f"wrote {target.name} ({len(data):,} chars)"
        + (f" — {why[:120]}" if why else "")
        + (f" [previous kept: {previous}]" if previous else " [new file]"),
        actor=ACTOR)
    return {"path": str(target), "chars": len(data), "previous": previous,
            "created": previous is None}


def edit(path: str, find: str, replace: str, *, count: int = 1,
         why: str = "") -> dict:
    """Replace exact text in an existing file.

    An edit that matches nothing is an ERROR, not a no-op. The silent
    version is how a run reports five successful edits having changed
    nothing at all — the shape of failure that looks exactly like success.
    """
    policy.ensure_not_halted()
    target = resolve(path)
    _text_ok(target)
    if not target.is_file():
        raise WorkspaceError(f"{path} does not exist — write it first")
    if not find:
        raise WorkspaceError("nothing to find; use write() to replace a whole file")
    original = target.read_text(encoding="utf-8")
    found = original.count(find)
    if found == 0:
        raise WorkspaceError(
            f"that text is not in {target.name}, so nothing was changed. "
            "An edit that matches nothing is a failure, not a no-op.")
    if count and found > count:
        raise WorkspaceError(
            f"that text appears {found} times in {target.name}; give more "
            "surrounding context so exactly the right one changes")
    updated = original.replace(find, replace)
    result = write(path, updated, why=why or f"edit: {find[:40]}…")
    result["replacements"] = found
    result["diff"] = "".join(difflib.unified_diff(
        original.splitlines(keepends=True), updated.splitlines(keepends=True),
        fromfile=f"a/{target.name}", tofile=f"b/{target.name}", n=1))[:4_000]
    return result


def listing(subdir: str = "") -> list[dict]:
    base = root()
    start = resolve(subdir) if subdir else base
    out = []
    for p in sorted(start.rglob("*")):
        if not p.is_file() or VERSIONS in p.parts:
            continue
        out.append({"path": str(p.relative_to(base)), "bytes": p.stat().st_size})
    return out


def versions(path: str) -> list[str]:
    """What she replaced, and when. The undo he never has to ask for."""
    base = root()
    target = resolve(path)
    folder = base / VERSIONS / target.relative_to(base).parent
    if not folder.is_dir():
        return []
    return sorted(str(p.relative_to(base)) for p in folder.glob(f"{target.stem}-*"))


def restore(version_path: str) -> dict:
    """Put a kept version back. The whole point of keeping them."""
    policy.ensure_not_halted()
    base = root()
    kept = (base / str(version_path).strip("/")).resolve()
    try:
        kept.relative_to(base / VERSIONS)
    except ValueError:
        raise OutsideWorkspace("that is not a kept version") from None
    if not kept.is_file():
        raise WorkspaceError(f"{version_path} is not a kept version")
    stem = kept.stem.rsplit("-", 1)[0]
    original = base / kept.parent.relative_to(base / VERSIONS) / f"{stem}{kept.suffix}"
    return write(str(original.relative_to(base)),
                 kept.read_text(encoding="utf-8"), why=f"restored {kept.name}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="The files Aletheia may write.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_read = sub.add_parser("read"); p_read.add_argument("path")
    p_read.add_argument("--anywhere", action="store_true")
    p_write = sub.add_parser("write")
    p_write.add_argument("path"); p_write.add_argument("text")
    p_edit = sub.add_parser("edit")
    p_edit.add_argument("path"); p_edit.add_argument("find"); p_edit.add_argument("replace")
    p_ls = sub.add_parser("list"); p_ls.add_argument("subdir", nargs="?", default="")
    p_v = sub.add_parser("versions"); p_v.add_argument("path")
    p_r = sub.add_parser("restore"); p_r.add_argument("version")
    sub.add_parser("where")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "read":
            print(read(args.path, anywhere=args.anywhere)["text"])
        elif args.cmd == "write":
            print(json.dumps(write(args.path, args.text), indent=2))
        elif args.cmd == "edit":
            print(json.dumps(edit(args.path, args.find, args.replace), indent=2))
        elif args.cmd == "list":
            for row in listing(args.subdir):
                print(f"{row['bytes']:>10,}  {row['path']}")
        elif args.cmd == "versions":
            for v in versions(args.path):
                print(v)
        elif args.cmd == "restore":
            print(json.dumps(restore(args.version), indent=2))
        else:
            print(root())
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
