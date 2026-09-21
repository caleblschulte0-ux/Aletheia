"""Read-only tools over her own repository: list, search, read, symbol,
status, diff, log.

The brief (docs/JARVIS_BRIEF.md §2): "Reading her own code is normal;
changing her running code stays a different privilege." This module is the
reading half and nothing else. There is no write here, no `repo.change`,
no `repo.propose_patch`, and no subprocess except read-only git.

CONFINEMENT IS BY GIT, NOT BY PATH ARITHMETIC. A path is readable only if
git TRACKS it (`git ls-files`). That one rule keeps out, without a list
anybody has to maintain:

- private state (`state/private/` is ignored), so his answers, his mail
  and his resume never reach a model through a code-reading tool;
- `.git/` itself, untracked secrets, `.env` files, caches;
- anything outside the repository (`..`, absolute paths, symlinks out):
  a path that does not normalise to a tracked name is not a tracked name.

Committed files are public by construction (CLAUDE.md: no secrets in
committed files), so a tracked file is by definition safe to read back.

READING MUST NOT WRITE. `git status` refreshes the index when it can;
`GIT_OPTIONAL_LOCKS=0` tells it not to, so a status read from a loop can
never collide with the Core's own git sync. Every call is hidden
(`proc.hidden_flags`): an unhidden subprocess in a loop is a console-window
storm on his screen.
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from aletheia import tools

#: Bounds on what one observation can carry. An observation goes back into
#: a prompt whose whole budget is a few thousand characters.
MAX_LIST = 80
MAX_HITS = 30
MAX_LINE = 200
MAX_READ_LINES = 160
MAX_READ_CHARS = 9_000
MAX_DIFF_CHARS = 6_000
MAX_LOG = 30
MAX_FILE_BYTES = 512 * 1024
GIT_TIMEOUT_S = 20
#: `git ls-files` changes when a commit lands, not between two tool calls.
LS_CACHE_S = 30.0
_LS: dict[str, Any] = {"at": 0.0, "root": None, "files": None}
_SYMBOLS: dict[str, Any] = {"key": None, "index": None}

#: A ref a model may name. No leading dash (an option), no spaces, no
#: `..` range tricks beyond what git itself calls a revision.
_REF = re.compile(r"^(?!-)[A-Za-z0-9._/~^@{}-]{1,80}$")


class RepoError(ValueError):
    """A request the repo tools refuse, in words a model can repair from."""


def root() -> Path:
    """The repository she is running from. A function, not a module
    constant, so tests can point it at a scratch repository."""
    from aletheia.fleet import REPO_ROOT
    return Path(REPO_ROOT)


def _git(*args: str, cwd: Path | None = None) -> str:
    from aletheia.proc import hidden_flags
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    try:
        done = subprocess.run(["git", "--no-pager", *args], capture_output=True,
                              cwd=str(cwd or root()), timeout=GIT_TIMEOUT_S, env=env,
                              creationflags=hidden_flags())
    except subprocess.TimeoutExpired:
        raise RepoError(f"git {args[0]} took longer than {GIT_TIMEOUT_S} seconds") from None
    except OSError as exc:
        raise RepoError(f"git could not run ({type(exc).__name__})") from None
    out = done.stdout.decode("utf-8", "replace")
    if done.returncode not in (0, 1):      # grep answers 1 for "no match"
        err = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RepoError(f"git {args[0]} failed: {(err[-1] if err else 'no detail')[:160]}")
    return out


def tracked(*, fresh: bool = False) -> list[str]:
    """Every path git tracks, forward-slashed, cached briefly."""
    here = str(root())
    now = time.monotonic()
    if (not fresh and _LS["files"] is not None and _LS["root"] == here
            and now - _LS["at"] < LS_CACHE_S):
        return list(_LS["files"])
    files = [line for line in _git("ls-files", "-z").split("\0") if line]
    _LS.update({"at": now, "root": here, "files": files})
    return list(files)


def _norm(path: object) -> str:
    """A model's path, as git would name it. Never resolves the filesystem:
    the answer is a NAME, checked against the tracked list."""
    text = str(path or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    parts = []
    for part in text.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise RepoError("paths are relative to the repository and may not climb out of it")
        parts.append(part)
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise RepoError("paths are relative to the repository root, never absolute")
    return "/".join(parts)


def _tracked_file(path: object) -> str:
    name = _norm(path)
    if not name:
        raise RepoError("name a file")
    files = tracked()
    if name in set(files):
        return name
    near = [f for f in files if f.endswith("/" + name) or f.rsplit("/", 1)[-1] == name]
    if len(near) == 1:
        return near[0]
    if near:
        raise RepoError(f"{name!r} is ambiguous: " + ", ".join(near[:6]))
    raise RepoError(f"{name!r} is not a tracked file in the repository "
                    "(untracked files and private state are never readable here)")


def _int(value: object, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(int(value), high))
    except (TypeError, ValueError):
        return default


def _clip(line: str, limit: int = MAX_LINE) -> str:
    line = line.rstrip("\r\n")
    return line if len(line) <= limit else line[:limit] + "..."


# ---- the handlers ---------------------------------------------------------

def repo_list(args: dict, **_ignored) -> dict:
    """Tracked files and folders directly under a folder."""
    base = _norm(args.get("path"))
    prefix = base + "/" if base else ""
    pattern = str(args.get("pattern") or "").strip().casefold()
    files, folders = [], {}
    for name in tracked():
        if not name.startswith(prefix):
            continue
        rest = name[len(prefix):]
        if "/" in rest:
            top = rest.split("/", 1)[0]
            folders[top] = folders.get(top, 0) + 1
        elif not pattern or pattern in rest.casefold():
            files.append(rest)
    if base and not files and not folders:
        raise RepoError(f"{base!r} is not a tracked folder")
    return {"path": base or ".", "folders": {k: folders[k] for k in sorted(folders)[:MAX_LIST]},
            "files": sorted(files)[:MAX_LIST], "file_count": len(files),
            "truncated": len(files) > MAX_LIST or len(folders) > MAX_LIST}


def repo_search(args: dict, **_ignored) -> dict:
    """Literal, case-insensitive text search over tracked files (git grep)."""
    query = " ".join(str(args.get("query") or "").split())
    if not query:
        raise RepoError("query is required")
    if len(query) > 200:
        raise RepoError("query is too long")
    base = _norm(args.get("path"))
    limit = _int(args.get("limit"), MAX_HITS, 1, MAX_HITS)
    pathspec = [base] if base else []
    out = _git("grep", "-n", "-I", "-i", "-F", "--full-name", "-e", query, "--", *pathspec)
    hits, total = [], 0
    for line in out.splitlines():
        match = re.match(r"^(.*?):(\d+):(.*)$", line)
        if not match:
            continue
        total += 1
        if len(hits) < limit:
            hits.append({"path": match.group(1), "line": int(match.group(2)),
                         "text": _clip(match.group(3).strip())})
    result = {"query": query, "path": base or ".", "matched": total, "hits": hits}
    if not total:
        result["note"] = ("no tracked file contains that text. That is a fact about this "
                          "search, not proof the behaviour does not exist under another name.")
    return result


def repo_read(args: dict, **_ignored) -> dict:
    """Numbered lines of one tracked file."""
    name = _tracked_file(args.get("path"))
    full = root() / name
    try:
        if full.stat().st_size > MAX_FILE_BYTES:
            raise RepoError(f"{name} is larger than {MAX_FILE_BYTES // 1024} KB; search it instead")
        raw = full.read_bytes()
    except OSError as exc:
        raise RepoError(f"{name} could not be read ({type(exc).__name__})") from None
    if b"\0" in raw[:4096]:
        raise RepoError(f"{name} is a binary file")
    lines = raw.decode("utf-8", "replace").splitlines()
    start = _int(args.get("start"), 1, 1, max(1, len(lines)))
    count = _int(args.get("lines"), 80, 1, MAX_READ_LINES)
    shown, size = [], 0
    for number in range(start, min(len(lines), start + count - 1) + 1):
        text = f"{number}: {_clip(lines[number - 1], 300)}"
        if size + len(text) > MAX_READ_CHARS:
            break
        shown.append(text)
        size += len(text) + 1
    last = start + len(shown) - 1
    return {"path": name, "start": start, "end": last, "total_lines": len(lines),
            "text": "\n".join(shown), "more": last < len(lines)}


def _symbol_index() -> dict[str, list[dict]]:
    """name -> where it is defined, over every tracked Python file. Rebuilt
    when any of those files changes size or mtime."""
    files = [f for f in tracked() if f.endswith(".py")]
    base = root()
    stamps = []
    for name in files:
        try:
            st = (base / name).stat()
            stamps.append((name, st.st_mtime_ns, st.st_size))
        except OSError:
            continue
    key = (str(base), tuple(stamps))
    if _SYMBOLS["key"] == key and _SYMBOLS["index"] is not None:
        return _SYMBOLS["index"]
    index: dict[str, list[dict]] = {}
    for name, _mtime, size in stamps:
        if size > MAX_FILE_BYTES:
            continue
        try:
            tree = ast.parse((base / name).read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, ValueError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                kind = "class" if isinstance(node, ast.ClassDef) else "def"
                doc = (ast.get_docstring(node) or "").strip().splitlines()
                index.setdefault(node.name, []).append({
                    "path": name, "line": node.lineno, "kind": kind,
                    "end": getattr(node, "end_lineno", node.lineno),
                    "doc": _clip(doc[0], 160) if doc else ""})
            elif isinstance(node, ast.Assign) and node in getattr(tree, "body", []):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.isupper():
                        index.setdefault(target.id, []).append({
                            "path": name, "line": node.lineno, "kind": "constant",
                            "end": getattr(node, "end_lineno", node.lineno), "doc": ""})
    _SYMBOLS.update({"key": key, "index": index})
    return index


def repo_symbol(args: dict, **_ignored) -> dict:
    """Where a function, class or module constant is defined."""
    wanted = str(args.get("name") or "").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,100}", wanted):
        raise RepoError("name must be a Python identifier, optionally module.name")
    module = ""
    if "." in wanted:
        module, wanted = wanted.rsplit(".", 1)
    found = list(_symbol_index().get(wanted, []))
    if module:
        tail = module.replace(".", "/") + ".py"
        found = [f for f in found if f["path"].endswith(tail)] or found
    out = {"name": wanted, "definitions": found[:MAX_HITS], "matched": len(found)}
    if not found:
        out["note"] = "no tracked Python file defines that name"
    return out


def repo_status(args: dict, **_ignored) -> dict:
    """Branch, commit, and changed files, from git."""
    head = _git("log", "-1", "--format=%h%n%s%n%cI").splitlines()
    branch = _git("rev-parse", "--abbrev-ref", "HEAD").strip()
    porcelain = _git("status", "--porcelain", "--untracked-files=no").splitlines()
    changed = [line[3:].strip() for line in porcelain if line.strip()]
    return {"repo": root().name, "branch": branch,
            "commit": head[0] if head else "", "subject": head[1][:120] if len(head) > 1 else "",
            "committed_at": head[2] if len(head) > 2 else "",
            "dirty": bool(changed), "changed": changed[:MAX_LIST], "changed_count": len(changed)}


def _ref(value: object, default: str) -> str:
    text = str(value or "").strip() or default
    if not _REF.match(text) or ".." in text.replace("...", ""):
        raise RepoError(f"{text!r} is not a revision name")
    return text


def repo_diff(args: dict, **_ignored) -> dict:
    """What changed: the working tree against a revision (default HEAD),
    or one revision against another. Stat first, then a bounded patch."""
    against = _ref(args.get("against"), "HEAD")
    revs = [against]
    if args.get("to"):
        revs.append(_ref(args.get("to"), "HEAD"))
    base = _norm(args.get("path"))
    pathspec = ["--", base] if base else ["--"]
    stat = _git("diff", "--stat=120", *revs, *pathspec)
    patch = _git("diff", "--no-color", "-U2", *revs, *pathspec)
    return {"against": against, "to": revs[1] if len(revs) > 1 else "working tree",
            "path": base or ".", "stat": _clip(stat, MAX_DIFF_CHARS // 3),
            "patch": patch[:MAX_DIFF_CHARS], "truncated": len(patch) > MAX_DIFF_CHARS,
            "empty": not patch.strip()}


def repo_log(args: dict, **_ignored) -> dict:
    """Recent commits, optionally only those touching a path or matching words."""
    count = _int(args.get("n") or args.get("limit"), 10, 1, MAX_LOG)
    base = _norm(args.get("path"))
    extra = []
    grep = " ".join(str(args.get("grep") or "").split())
    if grep:
        extra += ["-i", "-F", f"--grep={grep[:120]}"]
    out = _git("log", f"-{count}", "--format=%h%x1f%cI%x1f%an%x1f%s", *extra,
               "--", *([base] if base else []))
    commits = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            commits.append({"commit": parts[0], "at": parts[1], "author": parts[2],
                            "subject": _clip(parts[3], 160)})
    return {"path": base or ".", "commits": commits}


def _guarded(handler):
    """A refusal comes back as an observation, not an exception: a model
    repairs a bad path from a sentence, and learns nothing from a crash."""
    def run(args: dict, **kwargs) -> dict:
        try:
            return handler(dict(args or {}), **kwargs)
        except RepoError as exc:
            return {"error": str(exc)}
    run.__name__ = handler.__name__
    return run


_PATH = {"type": "string", "description": "relative to the repository root"}

TOOLS = (
    tools.declare(
        "repo.list",
        description=("List the tracked files and folders directly under a folder of your own "
                     "repository (path, default the root; pattern filters file names)."),
        input_schema={"properties": {"path": _PATH, "pattern": {"type": "string"}}},
        handler=_guarded(repo_list), capability="repo.read", reads=("repository",)),
    tools.declare(
        "repo.search",
        description=("Search your own code and docs for literal text, case-insensitive "
                     "(query; path narrows to a folder or file; limit at most 30). Returns "
                     "path, line number and the line."),
        input_schema={"properties": {"query": {"type": "string"}, "path": _PATH,
                                     "limit": {"type": ["integer", "string"]}},
                      "required": ["query"]},
        handler=_guarded(repo_search), capability="repo.read", reads=("repository",)),
    tools.declare(
        "repo.read",
        description=("Read numbered lines of one tracked file of your own repository (path; "
                     "start line, default 1; lines, default 80, at most 160)."),
        input_schema={"properties": {"path": _PATH,
                                     "start": {"type": ["integer", "string"]},
                                     "lines": {"type": ["integer", "string"]}},
                      "required": ["path"]},
        handler=_guarded(repo_read), capability="repo.read", reads=("repository",)),
    tools.declare(
        "repo.symbol",
        description=("Find where a Python function, class or UPPER_CASE constant is defined "
                     "in your own code (name, or module.name). Returns path, line and the "
                     "first docstring line; read it with repo.read."),
        input_schema={"properties": {"name": {"type": "string"}}, "required": ["name"]},
        handler=_guarded(repo_symbol), capability="repo.read", reads=("repository",)),
    tools.declare(
        "repo.status",
        description="Your own repository's branch, latest commit and uncommitted changes.",
        input_schema={"properties": {}},
        handler=_guarded(repo_status), capability="repo.read", reads=("repository",)),
    tools.declare(
        "repo.diff",
        description=("What changed in your own code: the working tree against a revision "
                     "(against, default HEAD), or against..to between two revisions; path "
                     "narrows it. A stat and a bounded patch."),
        input_schema={"properties": {"against": {"type": "string"}, "to": {"type": "string"},
                                     "path": _PATH}},
        handler=_guarded(repo_diff), capability="repo.read", reads=("repository",)),
    tools.declare(
        "repo.log",
        description=("Recent commits to your own code (n at most 30; path narrows to a file or "
                     "folder; grep matches words in the commit message)."),
        input_schema={"properties": {"n": {"type": ["integer", "string"]}, "path": _PATH,
                                     "grep": {"type": "string"}}},
        handler=_guarded(repo_log), capability="repo.read", reads=("repository",)),
)
