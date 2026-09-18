"""How a project is installed, tested and read — whatever it is written in.

His brief's goal is "I should never not be able to work on my projects", and
until now the bounded LOCAL repair tier could only run ONE kind of project.
`investigation.test_command` returned `python -m pytest` or `python -m
unittest` for every directory it was ever handed, so a Node repository with a
perfectly ordinary failing unit test became an investigation packet whose
whole reason was, in Scenario A's own words, "its checks run under Node
(package.json), which the local repair tier does not run". Money_Machine
(Barkly, the holdco platform) and most of what he ships are JavaScript, so
that sentence covered most of his portfolio.

This module is the toolchain, made data. A project is asked what it IS from
its own files — `package.json` and its lockfile, `pyproject.toml` /
`setup.cfg` / a `tests/` folder, and the commands its CI workflow actually
runs — and the answer says four things:

    install        how to get its dependencies, or why she will not
    suite          how to run the whole test suite
    one            how to run ONE named test
    read           how to read that runner's failure output

The fourth is the one that matters. Every runner's output is parsed into the
SAME structured failure the tier already used for Python — a test id, the
files and lines of the stack frames that point into the project, and the
message — so the classifier, the evidence gathering, the "verify the original
failure is resolved" step and the investigation packet all work unchanged. A
JavaScript test id is `<path>::<full test name>`, the same `::` shape pytest
uses, so `investigation.test_file_for` and `repair_classifier._test_module`
already understand it.

ADDING A TOOLCHAIN is meant to be a data edit: one entry in `TOOLCHAINS` with
its detection evidence, its argv builders and its parsers, plus a lockfile row
in `PACKAGE_MANAGERS` if it installs anything. Nothing else in the tier names
a language.

WHAT IT NEVER DOES. It never installs anything anywhere but a throwaway
worktree the caller already guarded, never without a committed lockfile,
never with package scripts enabled (`--ignore-scripts`: a `postinstall` is
arbitrary code from the internet), never past its time or disk budget, and
never a command outside `CHECK_COMMANDS` when it is gathering evidence. An
install that fails or overruns is reported honestly so the caller can make an
investigation packet that SAYS SO, rather than guessing at a repair with no
dependencies present.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Any, Callable

PYTHON = "python"
NODE = "node"

#: Budgets. His laptop is 16 GB, CPU-only, and the live job loop shares it.
INSTALL_TIMEOUT_S = 300
INSTALL_MAX_MB = 400
INSTALL_MIN_FREE_MB = 1_500
CHECK_TIMEOUT_S = 180
MAX_CHECK_OUTPUT = 4_000

#: JavaScript/TypeScript sources a stack frame or an import may land in.
JS_SUFFIXES = (".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx", ".vue", ".svelte")

#: Directories that are NOT his code even though they sit inside the checkout:
#: installed packages and build output. A vitest failure frame points into
#: `node_modules/vite/dist/...` as readily as into `src/`, and a tier that let
#: that become an implicated source file would show a model a bundled
#: dependency and invite it to edit one. Nothing under these is ever a file a
#: repair may touch, and nothing under them is ever evidence about his code.
VENDOR_DIRS = ("node_modules/", "vendor/", "dist/", "build/", "out/", "coverage/", ".next/",
               ".nuxt/", ".svelte-kit/", "site-packages/", ".venv/", "venv/", "target/",
               "bower_components/", ".yarn/", "__pycache__/")


#: His credentials never reach a package manager, a test runner or a check.
#: (`investigation._SECRET_ENV` is this same pattern; it lives here because
#: this module runs subprocesses and `investigation` imports it, not the
#: other way round.)
SECRET_ENV = re.compile(r"(?:TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|ACCESS_?KEY|PRIVATE_?KEY|CREDENTIAL|"
                        r"COOKIE|SESSION)", re.I)


def scrubbed_env(extra: dict | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if not SECRET_ENV.search(k)}
    env.update(CI="1", NO_COLOR="1", FORCE_COLOR="0", npm_config_update_notifier="false")
    env.update(extra or {})
    return env


def is_vendor_path(path: str) -> bool:
    norm = str(path or "").replace("\\", "/").removeprefix("./")
    return norm.startswith(VENDOR_DIRS) or any(f"/{d}" in f"/{norm}" for d in VENDOR_DIRS)


class RunnerRefused(RuntimeError):
    """Said in a sentence: why this project cannot be installed or run here."""


# ---- finding the tools ---------------------------------------------------------------

def _tool(name: str) -> str | None:
    """The real executable, resolved through PATH and PATHEXT (npm is `npm.cmd`
    on his PC). None when this machine does not have it."""
    return shutil.which(name)


def node_available() -> bool:
    return bool(_tool("node"))


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def node_bin(where: Path, package: str) -> Path | None:
    """A locally installed runner's own entry script, from its `bin` field.

    Resolved through `node`, never `npx`: npx is a shell shim that may reach
    the network to fetch a package that is not installed, and a repair tier
    that silently downloads a test runner is not reproducing anything."""
    root = Path(where) / "node_modules" / package
    manifest = _read_json(root / "package.json")
    entry = manifest.get("bin")
    candidates: list[str] = []
    if isinstance(entry, str):
        candidates.append(entry)
    elif isinstance(entry, dict):
        candidates.append(str(entry.get(package) or ""))
        candidates.extend(str(v) for v in entry.values())
    candidates.extend([f"bin/{package}.js", f"{package}.mjs", "index.js"])
    for rel in candidates:
        if not rel:
            continue
        target = (root / str(rel).lstrip("./")).resolve()
        if root.resolve() in target.parents and target.is_file():
            return target
    return None


# ---- the failure shapes ---------------------------------------------------------------

_PY_FRAME = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')
_PY_UNITTEST_FAIL = re.compile(r"^(FAIL|ERROR): (\w+) \(([\w.]+)\)", re.M)
_PY_PYTEST_FAIL = re.compile(r"^(?:FAILED|ERROR) (\S+?)(?: - |\s*$)", re.M)

#: A JavaScript stack frame, in every shape the four runners print it:
#: `at fn (path:1:2)`, `at path:1:2`, vitest's ` ❯ fn path:1:2`, and the
#: `file:///` URLs node prints for ES modules.
_JS_FRAME = re.compile(
    r"(?:^|\s)(?:at|❯|>)\s+(?:(?P<fn>[\w$.<>\[\]/-]+)\s+)?\(?"
    r"(?P<path>(?:file:///)?(?:[A-Za-z]:[\\/]|/|\.{0,2}[\\/])?[^\s()'\":]+?\.[cm]?[jt]sx?)"
    r":(?P<line>\d+)(?::\d+)?\)?", re.M)
#: node:test's TAP `location:` / `stack:` lines name the file the same way.
_JS_TAP_LOC = re.compile(r"^\s*(?:location|stack):\s*'?(?P<path>[^']+?):(?P<line>\d+):\d+'?\s*$", re.M)
#: A frame inside a TAP `stack: |-` block, which has no `at ` in front of it:
#:     TestContext.<anonymous> (file:///C:/x/test/math.test.js:6:10)
#: Without this, node:test's only frame is the `test(...)` declaration line
#: rather than the line that actually threw.
_JS_BARE_FRAME = re.compile(r"^\s+(?P<fn>[\w$.<>\[\]-]+)\s*\((?P<path>(?:file:///|[A-Za-z]:[\\/])"
                            r"[^)\s]+?):(?P<line>\d+):\d+\)\s*$", re.M)

_VITEST_FAIL = re.compile(r"^\s*(?:FAIL|×|✕|❯)\s+(?P<file>\S+?\.[cm]?[jt]sx?)\s*>\s*(?P<name>.+?)\s*$", re.M)
#: A whole FILE that failed before any test in it ran (an import that would not
#: resolve, a syntax error): vitest prints `FAIL  path [ path ]`. Without this
#: the run failed and named nothing, and "unlocated" is a much worse answer
#: than "this file does not even load".
_VITEST_SUITE_FAIL = re.compile(r"^\s*FAIL\s+(?P<file>\S+?\.[cm]?[jt]sx?)\s*\[", re.M)
_JEST_FILE = re.compile(r"^\s*(?:FAIL|●\s*Console)?\s*FAIL\s+(?P<file>\S+\.[cm]?[jt]sx?)\s*$", re.M)
_JEST_CASE = re.compile(r"^\s*●\s+(?P<name>(?!Console\b)(?!Test suite failed)[^\n]+?)\s*$", re.M)
_MOCHA_CASE = re.compile(r"^\s*\d+\)\s*(?P<head>.+?)\s*$\n(?P<rest>(?:^\s{5,}.+$\n?)+)", re.M)
_TAP_NOT_OK = re.compile(r"^\s*not ok \d+ - (?P<name>.+?)\s*$", re.M)

#: Errors a JavaScript runner prints for a module it cannot load. The captured
#: specifier decides whether this is a broken relative path in HIS code (a
#: bounded repair) or a package that was never installed (an environment).
JS_MISSING_MODULE = re.compile(
    r"(?:Cannot find module|Cannot find package|Failed to resolve import|Cannot resolve|"
    r"ERR_MODULE_NOT_FOUND[^'\"]*|Could not resolve)\s*[:\s]*['\"]([^'\"]+)['\"]")


def _clean_path(raw: str) -> str:
    text = str(raw or "").strip()
    if text.startswith("file:///"):
        text = text[len("file:///"):]
        if not re.match(r"^[A-Za-z]:", text):
            text = "/" + text
    # node:test prints its TAP `location:` as YAML, where a Windows path's
    # backslashes arrive DOUBLED. Left alone, every node:test failure names a
    # file that does not exist.
    text = text.replace("\\\\", "\\")
    return text.replace("%20", " ")


def _uniq(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        if row not in out:
            out.append(row)
    return out


def python_frames(output: str) -> list[dict]:
    return _uniq([{"path": raw, "line": int(line), "function": fn}
                  for raw, line, fn in _PY_FRAME.findall(output or "")])


def js_frames(output: str) -> list[dict]:
    rows: list[dict] = []
    for m in _JS_FRAME.finditer(output or ""):
        rows.append({"path": _clean_path(m.group("path")), "line": int(m.group("line")),
                     "function": (m.group("fn") or "<anonymous>")[:80]})
    for m in _JS_BARE_FRAME.finditer(output or ""):
        rows.append({"path": _clean_path(m.group("path")), "line": int(m.group("line")),
                     "function": m.group("fn")[:80]})
    for m in _JS_TAP_LOC.finditer(output or ""):
        rows.append({"path": _clean_path(m.group("path")), "line": int(m.group("line")),
                     "function": "<anonymous>"})
    return _uniq(rows)


def python_failures(output: str) -> list[str]:
    found: list[str] = []
    for _kind, name, where in _PY_UNITTEST_FAIL.findall(output or ""):
        test_id = where if where.endswith("." + name) else f"{where}.{name}"
        if test_id not in found:
            found.append(test_id)
    for test_id in _PY_PYTEST_FAIL.findall(output or ""):
        if "::" in test_id and test_id not in found:
            found.append(test_id)
    return found


def _js_id(file: str, name: str) -> str:
    return f"{_clean_path(file).replace(chr(92), '/').removeprefix('./')}::{' '.join(str(name).split())[:200]}"


def _files_in_frames(output: str) -> list[str]:
    seen: list[str] = []
    for row in js_frames(output):
        path = row["path"].replace("\\", "/")
        if re.search(r"(?:\.|/|^)(?:test|spec)s?\.[cm]?[jt]sx?$|\.(?:test|spec)\.[cm]?[jt]sx?$"
                     r"|(?:^|/)(?:__tests__|tests?)/", path, re.I) and path not in seen:
            seen.append(path)
    return seen


def vitest_failures(output: str) -> list[str]:
    found: list[str] = []
    for m in _VITEST_FAIL.finditer(output or ""):
        ident = _js_id(m.group("file"), m.group("name").replace(" > ", " ").strip())
        if ident not in found:
            found.append(ident)
    for m in _VITEST_SUITE_FAIL.finditer(output or ""):
        path = _clean_path(m.group("file")).replace("\\", "/").removeprefix("./")
        if not any(f.startswith(path + "::") for f in found) and path not in found:
            found.append(path)                 # the whole file: no test in it ran
    return found


def jest_failures(output: str) -> list[str]:
    text = output or ""
    files = [_clean_path(m.group("file")) for m in _JEST_FILE.finditer(text)]
    names = [m.group("name").replace("›", " ").replace(" > ", " ") for m in _JEST_CASE.finditer(text)]
    if not names:
        return []
    file = files[0] if files else (_files_in_frames(text) or [""])[0]
    found: list[str] = []
    for name in names:
        ident = _js_id(file, name)
        if file and ident not in found:
            found.append(ident)
    return found


def mocha_failures(output: str) -> list[str]:
    text = output or ""
    file = (_files_in_frames(text) or [""])[0]
    found: list[str] = []
    for m in _MOCHA_CASE.finditer(text):
        title = " ".join((m.group("head") + " " + m.group("rest").split(":\n")[0]).split())
        title = re.sub(r"^\d+\)\s*", "", title).strip().rstrip(":")
        ident = _js_id(file, title)
        if file and ident not in found:
            found.append(ident)
    return found


def node_test_failures(output: str) -> list[str]:
    text = output or ""
    file = (_files_in_frames(text) or [""])[0]
    found: list[str] = []
    for m in _TAP_NOT_OK.finditer(text):
        name = m.group("name").strip()
        if name.lower().startswith(("/", "file:")) or name.endswith(JS_SUFFIXES):
            continue                       # the per-FILE summary line, not a test
        ident = _js_id(file, name)
        if file and ident not in found:
            found.append(ident)
    return found


#: HOW MANY TESTS ACTUALLY RAN. Measured on vitest 2.1.9: `-t 'a name that
#: matches nothing'` prints "Tests 3 skipped (3)" and exits ZERO. A runner that
#: reports success for running no tests turns the loop's "the failing test
#: passes now" into a lie, so every named-test run is checked against this.
#: None means the runner did not say, and nothing is inferred from silence.
_RAN_COUNTS: dict[str, re.Pattern] = {
    "vitest": re.compile(r"^\s*Tests\s+(?P<body>.+)$", re.M),
    "jest": re.compile(r"^\s*Tests:\s+(?P<body>.+)$", re.M),
    "mocha": re.compile(r"^\s*(?P<body>\d+ (?:passing|failing|pending).*)$", re.M),
    "node-test": re.compile(r"^#\s*(?:pass|fail)\s+\d+\s*$", re.M),
    "pytest": re.compile(r"^(?P<body>.*\b\d+ (?:passed|failed|error).*)$", re.M),
    "unittest": re.compile(r"^Ran (?P<n>\d+) tests?\b", re.M),
}
#: Words a runner counts by. Only the first group RAN; `skipped`, `todo` and
#: `pending` are counted so that "3 skipped" reads as ZERO ran rather than as
#: "the runner did not say".
_COUNT_PIECE = re.compile(r"(\d+)\s+(passed|failed|passing|failing|errors?|"
                          r"skipped|todo|pending|cancelled)\b", re.I)
_RAN_WORDS = {"passed", "failed", "passing", "failing", "error", "errors"}


def tests_ran(output: str, *, detection: dict | None = None) -> int | None:
    """How many tests the runner says it ran (skips do not count), or None."""
    runner = str((detection or {}).get("runner") or "unittest")
    pattern = _RAN_COUNTS.get(runner)
    text = output or ""
    if pattern is None:
        return None
    if runner == "unittest":
        m = pattern.search(text)
        return int(m.group("n")) if m else None
    if runner == "node-test":
        total = 0
        seen = False
        for line in re.findall(r"^#\s*(pass|fail)\s+(\d+)\s*$", text, re.M):
            seen = True
            total += int(line[1])
        return total if seen else None
    found = pattern.findall(text)
    if not found:
        return None
    # mocha prints one line per outcome ("1 passing", "1 failing"); the others
    # print one summary line, and a re-run appends a newer one.
    bodies = found if runner == "mocha" else found[-1:]
    pieces = [p for body in bodies
              for p in _COUNT_PIECE.findall(body if isinstance(body, str) else body[0])]
    if not pieces:
        return None
    return sum(int(n) for n, word in pieces if word.casefold() in _RAN_WORDS)


#: Lines a runner prints that say nothing about WHY a test failed. Measured on
#: his laptop (CLAUDE.md, "the local rung has to FIT"): a bounded repair draft
#: on qwen3:8b takes 200-300 s and LOCAL_MAX_TIMEOUT_S is 300, so the size of
#: the failure text is the difference between a repair and a packet. vitest
#: prints every failure TWICE (once inline, once in a "Failed Tests" block),
#: quotes the source with a line-number gutter, and wraps it all in box-drawing
#: rules; none of that is evidence a model does not already have in `files`.
_NOISE = re.compile(
    r"^\s*(?:RUN\s+v[\d.]|DEV\s+v[\d.]|Test Files\s|Tests\s+\d|Start at\s|Duration\s"
    r"|Snapshots\s|Coverage|Time:\s|Ran all test suites|Test Suites:\s"
    r"|[-=_─-╿⎯]{3,}|#\s*(?:subtest|pass|fail|cancelled|skipped|todo|duration_ms)"
    r"|\d+\s+(?:passing|failing|pending)\b|ok \d+ -|\.{3}$|---$)", re.I)
#: A quoted source line with a gutter: "     12|     expect(x).toBe(1);"
_GUTTER = re.compile(r"^\s*>?\s*\d+\s*[|│]")


def compact_failure(output: str, *, detection: dict | None = None, limit: int = 900) -> str:
    """The part of a run that says what failed, with the runner's furniture
    taken out. Same job as before for Python; the JavaScript runners are
    simply much noisier."""
    keep: list[str] = []
    for line in str(output or "").splitlines():
        text = line.rstrip()
        if not text.strip():
            continue
        if set(text.strip()) <= set("^~-=_ "):
            continue
        if text.startswith(("Ran ", "FAILED (")):
            continue
        if _NOISE.match(text) or _GUTTER.match(text):
            continue
        if text not in keep:                      # vitest says every failure twice
            keep.append(text)
    return "\n".join(keep)[-limit:]


def split_js_id(test_id: str) -> tuple[str, str]:
    """`path::full name` -> (path, name). A bare path is the WHOLE file, which
    is what a suite that failed before any test ran amounts to."""
    value = str(test_id or "")
    if "::" in value:
        path, name = value.split("::", 1)
        return path, name
    if value.lower().endswith(JS_SUFFIXES):
        return value, ""
    return "", value


#: JavaScript's regex metacharacters, and only those. Python's `re.escape`
#: also escapes a SPACE (for re.VERBOSE), and `\ ` is a syntax error in a
#: unicode-mode JavaScript RegExp - so escaping too much is its own way of
#: matching no test and calling it passed.
_JS_META = re.compile(r"([.*+?^${}()|\[\]\\/])")


def _pattern(name: str) -> str:
    """A runner's `-t` / `--grep` argument is a REGEX. His test titles contain
    parentheses and dots often enough that an unescaped one silently matches
    nothing, and "the test passes now" would be a lie."""
    return _JS_META.sub(r"\\\1", str(name))


# ---- the toolchains, as data -----------------------------------------------------------

def _py_suite(where: Path, _d: dict) -> list[str]:
    if uses_pytest(where):
        return [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    start = "tests" if (where / "tests").is_dir() else "."
    return [sys.executable, "-m", "unittest", "discover", "-s", start, "-t", "."]


def _py_some(where: Path, _d: dict, tests: list[str]) -> list[str]:
    if uses_pytest(where):
        return [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests]
    return [sys.executable, "-m", "unittest", *tests]


def _node_runner_argv(where: Path, detection: dict, extra: list[str]) -> list[str]:
    runner = detection.get("runner") or ""
    node = _tool("node")
    if not node:
        raise RunnerRefused("this machine has no node on PATH")
    if runner == "node-test":
        return [node, "--test", "--test-reporter=tap", *extra]
    package = NODE_RUNNERS[runner]["package"]
    entry = node_bin(where, package)
    if entry is None:
        raise RunnerRefused(f"{package} is not installed in this worktree's node_modules")
    return [node, str(entry), *NODE_RUNNERS[runner]["suite_args"], *extra]


def _node_suite(where: Path, detection: dict) -> list[str]:
    return _node_runner_argv(where, detection, [])


def _node_some(where: Path, detection: dict, tests: list[str]) -> list[str]:
    runner = detection.get("runner") or ""
    files, names = [], []
    for test_id in tests:
        path, name = split_js_id(test_id)
        if path and path not in files:
            files.append(path)
        if name:
            names.append(name)
    extra: list[str] = []
    if runner == "node-test":
        extra = list(files)
        if len(names) == 1:
            extra += ["--test-name-pattern", _pattern(names[0])]
        return _node_runner_argv(where, detection, extra)
    spec = NODE_RUNNERS[runner]
    extra = list(spec["file_args"](files)) if files else []
    if len(names) == 1:
        extra += [spec["name_flag"], _pattern(names[0])]
    return _node_runner_argv(where, detection, extra)


#: One row per JavaScript test runner. `package` is what must be in
#: node_modules, `signs` are the words in package.json or a CI command that
#: name it, `read` turns its output into test ids.
NODE_RUNNERS: dict[str, dict[str, Any]] = {
    "vitest": {"package": "vitest", "signs": (re.compile(r"\bvitest\b"),),
               "suite_args": ["run", "--reporter=verbose"],
               "file_args": lambda files: list(files), "name_flag": "-t",
               "read": vitest_failures},
    "jest": {"package": "jest", "signs": (re.compile(r"\bjest\b"),),
             "suite_args": ["--ci"],
             "file_args": lambda files: ["--runTestsByPath", *files], "name_flag": "-t",
             "read": jest_failures},
    "mocha": {"package": "mocha", "signs": (re.compile(r"\bmocha\b"),),
              "suite_args": ["--reporter", "spec"],
              "file_args": lambda files: list(files), "name_flag": "--grep",
              "read": mocha_failures},
    "node-test": {"package": "", "signs": (re.compile(r"node\s+--test\b"), re.compile(r"\bnode:test\b")),
                  "suite_args": [], "file_args": lambda files: list(files),
                  "name_flag": "--test-name-pattern", "read": node_test_failures},
}

#: One row per toolchain. Adding a language is one entry here (plus a
#: lockfile row below if it installs anything).
TOOLCHAINS: dict[str, dict[str, Any]] = {
    PYTHON: {"suite": _py_suite, "some": _py_some, "frames": python_frames,
             "read": lambda output, detection: python_failures(output)},
    NODE: {"suite": _node_suite, "some": _node_some, "frames": js_frames,
           "read": lambda output, detection: (NODE_RUNNERS.get(detection.get("runner") or "", {})
                                              .get("read") or (lambda _o: []))(output)},
}

#: lockfile -> how that package manager installs EXACTLY what the lockfile says.
#: `--ignore-scripts` everywhere: a `postinstall` is arbitrary code from the
#: internet, and nothing in a bounded repair needs one to run.
PACKAGE_MANAGERS: tuple[dict[str, Any], ...] = (
    {"name": "npm", "lockfile": "package-lock.json", "tool": "npm",
     "args": ["ci", "--no-audit", "--no-fund", "--ignore-scripts", "--prefer-offline"]},
    {"name": "npm", "lockfile": "npm-shrinkwrap.json", "tool": "npm",
     "args": ["ci", "--no-audit", "--no-fund", "--ignore-scripts", "--prefer-offline"]},
    {"name": "pnpm", "lockfile": "pnpm-lock.yaml", "tool": "pnpm",
     "args": ["install", "--frozen-lockfile", "--ignore-scripts", "--prefer-offline"]},
    {"name": "yarn", "lockfile": "yarn.lock", "tool": "yarn",
     "args": ["install", "--frozen-lockfile", "--ignore-scripts"]},
)


# ---- detection ---------------------------------------------------------------------------

def uses_pytest(where: Path) -> bool:
    where = Path(where)
    if (where / "pytest.ini").is_file() or (where / "conftest.py").is_file():
        return True
    for name in ("pyproject.toml", "setup.cfg", "tox.ini"):
        f = where / name
        try:
            if f.is_file():
                text = f.read_text(encoding="utf-8", errors="replace")
                if "[tool.pytest" in text or "[pytest]" in text:
                    return True
        except OSError:
            continue
    return False


def python_tests_present(where: Path) -> bool:
    where = Path(where)
    if (where / "conftest.py").is_file() or uses_pytest(where):
        return True
    for base in (where / "tests", where / "test", where):
        if base.is_dir() and any(base.glob("test_*.py")):
            return True
    return (where / "tests").is_dir() and any((where / "tests").rglob("test_*.py"))


def _python_evidence(where: Path) -> list[str]:
    found: list[str] = []
    for name in ("pyproject.toml", "setup.py", "setup.cfg", "tox.ini", "pytest.ini", "conftest.py",
                 "requirements.txt"):
        if (where / name).is_file():
            found.append(name)
    tests = where / "tests"
    if tests.is_dir() and any(tests.rglob("test_*.py")):
        found.append("tests/test_*.py")
    if not found and any(where.glob("*.py")):
        found.append("*.py")
    return found


def _node_evidence(where: Path) -> list[str]:
    found = []
    if (where / "package.json").is_file():
        found.append("package.json")
    for row in PACKAGE_MANAGERS:
        if (where / row["lockfile"]).is_file():
            found.append(row["lockfile"])
    return found


def package_manager(where: Path) -> dict | None:
    for row in PACKAGE_MANAGERS:
        if (Path(where) / row["lockfile"]).is_file():
            return row
    return None


def _node_runner(where: Path, manifest: dict, ci_commands: tuple[str, ...]) -> tuple[str, str]:
    """(runner, why). The project's own words decide: its test script first,
    then what its CI actually runs, then what it depends on."""
    scripts = manifest.get("scripts") if isinstance(manifest.get("scripts"), dict) else {}
    script = " ".join(str(v) for k, v in (scripts or {}).items()
                      if isinstance(k, str) and re.search(r"^(?:test|check)", k, re.I))
    deps = {}
    for key in ("devDependencies", "dependencies", "peerDependencies"):
        value = manifest.get(key)
        if isinstance(value, dict):
            deps.update({str(k): str(v) for k, v in value.items()})
    for source, text in (("its test script", script),
                         ("its CI command", " ".join(ci_commands)),
                         ("its dependencies", " ".join(deps))):
        for name, spec in NODE_RUNNERS.items():
            if any(sign.search(text or "") for sign in spec["signs"]):
                return name, f"{source} names {name}"
    for name in ("vitest", "jest", "mocha"):
        if (Path(where) / "node_modules" / name).is_dir():
            return name, f"{name} is installed in node_modules"
    if test_files(where):
        return "node-test", "it has test files and no runner dependency, so node's own test runner"
    return "", "package.json names no test runner she knows how to run"


_TEST_FILE = re.compile(r"\.(?:test|spec)\.[cm]?[jt]sx?$", re.I)


def test_files(where: str | Path, *, limit: int = 60) -> list[str]:
    """The project's own JavaScript test files, cheaply: never inside
    node_modules, never a build output, never deeper than it needs to be."""
    where = Path(where)
    skip = {"node_modules", ".git", "dist", "build", "coverage", ".next", "out", "vendor", ".venv"}
    found: list[str] = []
    for root, dirs, files in os.walk(where):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
        for name in files:
            if _TEST_FILE.search(name) or (Path(root).name in ("__tests__", "test", "tests")
                                           and name.lower().endswith(JS_SUFFIXES)):
                rel = (Path(root) / name).relative_to(where).as_posix()
                found.append(rel)
                if len(found) >= limit:
                    return found
    return found


#: What says "a project starts here".
MANIFEST_NAMES = ("package.json", "pyproject.toml", "setup.py", "setup.cfg", "Cargo.toml", "go.mod")


def find_project_root(where: str | Path, *, max_depth: int = 2) -> tuple[str, str]:
    """Where the project ACTUALLY starts, relative to `where`, and why.

    A charter names a folder, and the folder is not always the project: Barkly's
    charter path is `barkly`, and its package.json is at `barkly/app`. Asking
    the named folder what it is got "nothing names a toolchain" for a project
    with 50 test files sitting one directory down.

    Conservative: only descends when the named folder has NO manifest of its
    own, and only when EXACTLY ONE manifest is found within `max_depth`. Two
    of them is a monorepo, and which package a failure belongs to is not a
    guess this makes."""
    where = Path(where)
    if any((where / name).is_file() for name in MANIFEST_NAMES):
        return "", ""
    found: list[str] = []
    for depth in range(1, max_depth + 1):
        for name in MANIFEST_NAMES:
            for path in where.glob("/".join(["*"] * depth) + "/" + name):
                rel = path.parent.relative_to(where).as_posix()
                if not is_vendor_path(rel + "/") and rel not in found:
                    found.append(rel)
        if found:
            break
    if len(found) == 1:
        return found[0], f"the project starts at {found[0]}, not at the folder it was named by"
    if len(found) > 1:
        return "", (f"this folder holds {len(found)} packages ({', '.join(sorted(found)[:4])}); "
                    "which one a failure belongs to is not a guess she makes")
    return "", ""


def detect(where: str | Path, *, ci_commands: tuple[str, ...] | list[str] = ()) -> dict:
    """What this project IS, from its own files.

    Python wins a tie: it is what the tier already ran, and nothing about that
    behaviour changes here. A repository with BOTH is recorded as both, so a
    packet can say which half she looked at."""
    where = Path(where)
    ci = tuple(str(c) for c in ci_commands or ())
    python = _python_evidence(where)
    node = _node_evidence(where)
    manifest = _read_json(where / "package.json")
    runner, why = ("", "")
    if node:
        runner, why = _node_runner(where, manifest, ci)
    row: dict[str, Any] = {"toolchain": "", "runner": "", "evidence": [], "why": "",
                           "also": [], "package_manager": "", "lockfile": "",
                           "test_script": str((manifest.get("scripts") or {}).get("test") or "")[:300]
                           if isinstance(manifest.get("scripts"), dict) else ""}
    # A TIE goes to whichever half actually has TESTS, because the tier's whole
    # currency is "the project's own tests proved it". Python wins when both do,
    # which keeps every Python project exactly as it was.
    node_wins = bool(node and runner and not python_tests_present(where))
    if python and not node_wins:
        row.update(toolchain=PYTHON, runner="pytest" if uses_pytest(where) else "unittest",
                   evidence=python, why="its own files are Python (" + ", ".join(python[:3]) + ")")
        if node:
            row["also"] = [NODE]
    elif node and runner:
        pm = package_manager(where)
        row.update(toolchain=NODE, runner=runner, evidence=node, why=why,
                   package_manager=(pm or {}).get("name", ""), lockfile=(pm or {}).get("lockfile", ""),
                   also=[PYTHON] if python else [])
    elif node:
        row.update(toolchain=NODE, runner="", evidence=node, why=why,
                   package_manager=(package_manager(where) or {}).get("name", ""),
                   lockfile=(package_manager(where) or {}).get("lockfile", ""))
    else:
        # Unchanged fallback: unittest discovery, exactly as before.
        row.update(toolchain=PYTHON, runner="unittest", evidence=[],
                   why="nothing names a toolchain; unittest discovery, as before")
    return row


def can_run(detection: dict) -> tuple[bool, str]:
    """Whether the tier can actually prove a fix with this project's own tests."""
    if detection.get("toolchain") == NODE:
        if not detection.get("runner"):
            return False, detection.get("why") or "its package.json names no test runner she can run"
        if not node_available():
            return False, "this machine has no node on PATH, so its tests cannot be run here"
        if detection.get("runner") != "node-test" and not detection.get("lockfile"):
            return False, ("it has no committed lockfile, and she never installs dependencies that a "
                           "lockfile does not pin")
    return True, ""


# ---- test commands ------------------------------------------------------------------------

_SAFE_TEST_PATH = re.compile(r"[A-Za-z0-9_./:\[\]-]{1,300}")
_SAFE_TEST_NAME = re.compile(r"[^\x00-\x1f]{1,200}")


def check_test_id(test_id: str, toolchain: str) -> None:
    value = str(test_id or "")
    if toolchain == NODE:
        path, name = split_js_id(value)
        head = path or value
        if not _SAFE_TEST_PATH.fullmatch(head) or head.startswith("-") or ".." in head:
            raise RunnerRefused(f"unsafe test id {test_id!r}")
        if name and not _SAFE_TEST_NAME.fullmatch(name):
            raise RunnerRefused(f"unsafe test name in {test_id!r}")
        return
    if not _SAFE_TEST_PATH.fullmatch(value) or value.startswith("-"):
        raise RunnerRefused(f"unsafe test id {test_id!r}")


def test_command(where: str | Path, tests: list[str] | None = None, *, detection: dict | None = None) -> list[str]:
    """The argv that runs this project's whole suite, or exactly the tests named."""
    where = Path(where)
    detection = detection or detect(where)
    spec = TOOLCHAINS[detection.get("toolchain") or PYTHON]
    for t in tests or []:
        check_test_id(t, detection.get("toolchain") or PYTHON)
    if tests:
        return spec["some"](where, detection, list(tests))
    return spec["suite"](where, detection)


def relative_to(root: str | Path | None, path: str) -> str:
    """A repository-relative path. Jest, mocha and node:test name a test file
    by the absolute path it happens to sit at, and a throwaway worktree's
    location is noise in a record, a prompt and a packet."""
    text = _clean_path(path).replace("\\", "/")
    if root is None:
        return text
    try:
        base = Path(root).resolve()
        target = Path(text)
        rel = (target if target.is_absolute() else base / target).resolve().relative_to(base)
    except (ValueError, OSError):
        return text
    out = rel.as_posix()
    return out if out and not out.startswith("..") else text


def parse_failures(output: str, *, detection: dict | None = None,
                   root: str | Path | None = None) -> list[str]:
    """Every runner's output, read into the same list of test ids."""
    detection = detection or {"toolchain": PYTHON}
    spec = TOOLCHAINS.get(detection.get("toolchain") or PYTHON) or TOOLCHAINS[PYTHON]
    found = spec["read"](output or "", detection)
    if (detection.get("toolchain") or PYTHON) != NODE:
        return found
    out: list[str] = []
    for ident in found:
        path, name = split_js_id(ident)
        rel = relative_to(root, path) if path else ""
        value = f"{rel}::{name}" if (rel and name) else (rel or ident)
        if value not in out:
            out.append(value)
    return out


def parse_frames(output: str, *, detection: dict | None = None) -> list[dict]:
    """Stack frames, as {path, line, function}. The caller decides which of
    them land inside the repository."""
    detection = detection or {"toolchain": PYTHON}
    spec = TOOLCHAINS.get(detection.get("toolchain") or PYTHON) or TOOLCHAINS[PYTHON]
    rows = spec["frames"](output or "")
    if not rows and (detection.get("toolchain") or PYTHON) == PYTHON:
        return []
    return rows


# ---- imports, for evidence -----------------------------------------------------------------

_JS_IMPORT = re.compile(r"""(?:\bimport\b[^;\n]*?\bfrom\s*|\bimport\s*|\brequire\s*\(\s*|
                            \bexport\b[^;\n]*?\bfrom\s*|\bimport\s*\(\s*)['"]([^'"]+)['"]""", re.X)


def js_imports(where: Path, path: str) -> list[str]:
    """Repository files that `path` imports RELATIVELY. A bare specifier is a
    package, not a file of his, and is deliberately not followed."""
    where = Path(where)
    try:
        text = (where / path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    here = PurePosixPath(str(path).replace("\\", "/")).parent
    out: list[str] = []
    for spec in _JS_IMPORT.findall(text):
        if not str(spec).startswith("."):
            continue
        target = (here / spec).as_posix()
        target = PurePosixPath(os.path.normpath(target).replace("\\", "/")).as_posix()
        if target.startswith(".."):
            continue
        for candidate in [target, *[f"{target}{s}" for s in JS_SUFFIXES],
                          *[f"{target}/index{s}" for s in JS_SUFFIXES],
                          *[re.sub(r"\.js$", s, target) for s in (".ts", ".tsx", ".mts")]]:
            if (where / candidate).is_file() and candidate not in out and candidate != path:
                out.append(candidate)
                break
    return out


def imports_of(where: Path, path: str) -> list[str] | None:
    """Local imports of a file, or None when this module does not read that
    language (the caller keeps its own reader for Python)."""
    if str(path).lower().endswith(JS_SUFFIXES):
        return js_imports(where, path)
    return None


# ---- installing, inside the throwaway worktree only ------------------------------------------

def _dir_mb(path: Path, *, cap_mb: int) -> float:
    total = 0
    cap = cap_mb * 1024 * 1024
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
        if total > cap:
            break
    return round(total / (1024 * 1024), 1)


def install_plan(where: str | Path, detection: dict | None = None) -> dict:
    """What would be installed and why, or the refusal. Pure: reads files only."""
    where = Path(where)
    detection = detection or detect(where)
    if detection.get("toolchain") != NODE:
        return {"needed": False, "reason": "nothing to install: this is not a Node project"}
    if not (where / "package.json").is_file():
        return {"needed": False, "reason": "no package.json"}
    manifest = _read_json(where / "package.json")
    deps = {}
    for key in ("dependencies", "devDependencies"):
        value = manifest.get(key)
        if isinstance(value, dict):
            deps.update({str(k): str(v) for k, v in value.items()})
    if not deps:
        return {"needed": False, "reason": "package.json declares no dependencies"}
    if (where / "node_modules").is_dir() and any((where / "node_modules").iterdir()):
        return {"needed": False, "reason": "node_modules is already present in the worktree"}
    row = package_manager(where)
    if row is None:
        return {"needed": True, "refusal": (
            "no committed lockfile (package-lock.json, pnpm-lock.yaml or yarn.lock), so what she "
            "installed would not be what CI installs, and nothing she proved here would mean anything"),
            "declared": deps}
    tool = _tool(row["tool"])
    if not tool:
        return {"needed": True, "refusal": f"this machine has no {row['tool']} on PATH", "declared": deps}
    free_mb = round(shutil.disk_usage(str(where)).free / (1024 * 1024))
    if free_mb < INSTALL_MIN_FREE_MB:
        return {"needed": True, "refusal": f"only {free_mb} MB of disk is free; she will not install "
                                           f"under {INSTALL_MIN_FREE_MB} MB", "declared": deps}
    return {"needed": True, "manager": row["name"], "lockfile": row["lockfile"], "tool": tool,
            "command": [tool, *row["args"]], "declared": deps, "free_mb": free_mb,
            "scripts_ignored": True, "budget_s": INSTALL_TIMEOUT_S, "budget_mb": INSTALL_MAX_MB}


def install(where: str | Path, *, detection: dict | None = None, timeout_s: int = INSTALL_TIMEOUT_S,
            guard: Callable[[Path], Any] | None = None) -> dict:
    """Install the lockfile's dependencies IN THIS DIRECTORY, which the caller
    has already proved is a throwaway worktree.

    Never raises for a failure it can report: an install that refuses, fails or
    overruns comes back with `ok: False` and a sentence, so the caller makes an
    investigation packet that says so instead of guessing at a repair."""
    from aletheia import proc
    where = Path(where).resolve()
    plan = install_plan(where, detection)
    if not plan.get("needed") or plan.get("refusal"):
        return {**plan, "ok": not plan.get("refusal") and not plan.get("needed"), "ran": False,
                "reason": plan.get("refusal") or plan.get("reason") or ""}
    if guard is not None:
        # Only now, when something would actually be written: nothing is ever
        # installed into a checkout of his.
        try:
            guard(where)
        except Exception as exc:                                       # noqa: BLE001
            return {**plan, "ok": False, "ran": False,
                    "refusal": f"{type(exc).__name__}: {str(exc)[:200]}",
                    "reason": f"refused to install here: {str(exc)[:200]}"}
    started = time.monotonic()
    env = scrubbed_env({"npm_config_audit": "false", "npm_config_fund": "false",
                        "npm_config_ignore_scripts": "true", "ADBLOCK": "1",
                        "DISABLE_OPENCOLLECTIVE": "1"})
    try:
        done = proc.run_tree(plan["command"], timeout_s, cwd=str(where), env=env)
        output = (done.stdout or "") + (done.stderr or "")
        ok = done.returncode == 0
        why = "" if ok else f"{plan['manager']} exited {done.returncode}"
    except subprocess.TimeoutExpired:
        output, ok = "", False
        why = f"the install took longer than {timeout_s} seconds and was stopped"
    except OSError as exc:
        output, ok = "", False
        why = f"the install could not start ({type(exc).__name__}: {str(exc)[:120]})"
    seconds = round(time.monotonic() - started, 1)
    size_mb = _dir_mb(where / "node_modules", cap_mb=INSTALL_MAX_MB + 1) if (where / "node_modules").is_dir() else 0.0
    added = 0
    m = re.search(r"added (\d+) packages?", output or "")
    if m:
        added = int(m.group(1))
    if ok and size_mb > INSTALL_MAX_MB:
        ok = False
        why = f"node_modules is {size_mb} MB, over the {INSTALL_MAX_MB} MB budget for a local repair"
    return {**plan, "ok": ok, "ran": True, "seconds": seconds, "added": added, "size_mb": size_mb,
            "reason": why, "output_tail": (output or "")[-MAX_CHECK_OUTPUT:],
            "installed": sorted(plan.get("declared") or {})[:40]}


# ---- allowlisted read-only checks, for the packet ----------------------------------------------

#: Commands she may run to CAPTURE EVIDENCE for a packet. Claude's own critique
#: of the Barkly packet was that it named `npm audit` and carried none of its
#: output (the brief's rule 5). Each row is matched against the command a CI
#: workflow actually runs, and only the argv HERE is executed — never the
#: workflow's string.
CHECK_COMMANDS: tuple[dict[str, Any], ...] = (
    {"name": "npm audit", "tool": "npm", "args": ["audit", "--json"],
     "sign": re.compile(r"\bnpm\s+audit\b"), "reads_network": True},
    {"name": "npm ls", "tool": "npm", "args": ["ls", "--all", "--json"],
     "sign": re.compile(r"\bnpm\s+(?:ls|list)\b"), "reads_network": False},
    {"name": "npm outdated", "tool": "npm", "args": ["outdated", "--json"],
     "sign": re.compile(r"\bnpm\s+outdated\b"), "reads_network": True},
    {"name": "node --version", "tool": "node", "args": ["--version"],
     "sign": re.compile(r"\bnode\s+(?:-v|--version)\b"), "reads_network": False},
    {"name": "python --version", "tool": sys.executable, "args": ["--version"],
     "sign": re.compile(r"\bpython3?\s+(?:-V|--version)\b"), "reads_network": False},
    {"name": "pip check", "tool": sys.executable, "args": ["-m", "pip", "check"],
     "sign": re.compile(r"\bpip\s+check\b"), "reads_network": False},
)
#: package.json scripts she may run for evidence. A script whose NAME says it
#: only reads (lint, typecheck) is evidence; `npm run deploy` is not, whatever
#: a workflow file happens to say.
READ_ONLY_SCRIPTS = re.compile(r"^(?:lint|typecheck|type-check|types|tsc|check|format:check|"
                               r"lint:.*|test:types)$", re.I)
_NPM_RUN = re.compile(r"\bnpm\s+run\s+([A-Za-z0-9:_-]+)")


def checks_for(commands: list[str] | tuple[str, ...], *, where: str | Path | None = None) -> list[dict]:
    """Which allowlisted checks the failing CI commands justify running."""
    text = "\n".join(str(c) for c in commands or ())
    out: list[dict] = []
    for row in CHECK_COMMANDS:
        if row["sign"].search(text):
            tool = _tool(row["tool"]) if not os.path.isabs(row["tool"]) else row["tool"]
            if tool:
                out.append({"name": row["name"], "argv": [tool, *row["args"]],
                            "reads_network": row["reads_network"]})
    scripts: dict = {}
    if where is not None:
        scripts = (_read_json(Path(where) / "package.json").get("scripts") or {})
        scripts = scripts if isinstance(scripts, dict) else {}
    for name in dict.fromkeys(_NPM_RUN.findall(text)):
        if READ_ONLY_SCRIPTS.fullmatch(name) and name in scripts:
            tool = _tool("npm")
            if tool:
                out.append({"name": f"npm run {name}", "argv": [tool, "run", name], "reads_network": False})
    return out[:4]


def run_check(where: str | Path, check: dict, *, timeout_s: int = CHECK_TIMEOUT_S,
              env: dict | None = None) -> dict:
    """Run ONE allowlisted read-only check in the worktree and keep its output.

    Nothing here is built from repository text: `argv` came from
    `checks_for`, which only ever returns rows of `CHECK_COMMANDS` or an
    allowlisted script name that the project's own package.json declares."""
    from aletheia import proc
    where = Path(where)
    argv = list(check.get("argv") or [])
    if not argv:
        return {"command": check.get("name") or "", "ran": False, "said": "no command"}
    if not where.is_dir():
        return {"command": check.get("name") or "", "ran": False,
                "said": f"there is no checkout at {where.name} to run it in"}
    started = time.monotonic()
    # A check runs the project's own tooling; his tokens are not its business.
    run_env = dict(env) if env else scrubbed_env()
    run_env.update(CI="1", NO_COLOR="1", FORCE_COLOR="0")
    try:
        done = proc.run_tree(argv, timeout_s, cwd=str(where), env=run_env)
        output = (done.stdout or "") + (done.stderr or "")
        code = done.returncode
    except subprocess.TimeoutExpired:
        output, code = f"stopped after {timeout_s} seconds", -1
    except OSError as exc:
        output, code = f"could not run ({type(exc).__name__}: {str(exc)[:120]})", -1
    return {"command": check.get("name") or " ".join(Path(argv[0]).name for _ in [0]),
            "argv": " ".join([Path(argv[0]).name, *argv[1:]]), "exit_code": code, "ran": True,
            "reproduced": code != 0, "seconds": round(time.monotonic() - started, 1),
            "output": (output or "")[-MAX_CHECK_OUTPUT:],
            "said": ("it passed" if code == 0 else f"it exited {code}")}
