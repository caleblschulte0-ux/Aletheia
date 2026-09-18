"""Investigate before escalating: everything short of implementing.

His brief (docs/CONTINUITY_BRIEF.md, Part II.5): "Local AI investigates even
when it should not implement. Inspect logs, locate files, reproduce, reduce
test cases, identify suspect commits, collect code, summarize evidence,
prepare a debugging packet, queue a task for the stronger model with that
packet." And rule 5: "never spend Claude/Codex turns discovering what
Aletheia could have collected itself."

This module is the collecting, for ANY project repository with a local
checkout (his charters name repositories and branches; a public one is
cloned to a throwaway directory). It is shared by the local repair loop
(`local_repair`), which uses the same evidence to attempt a bounded fix, and
by the frontier path (`code_worker.prepare_pr`), which starts from a packet
instead of rediscovering it.

WHAT IT NEVER DOES. It never edits a file the repository tracks, never runs
a git verb that talks to a remote or moves a checkout other than a
throwaway worktree it made itself, and never runs the repository's tests
anywhere but that worktree, with his credentials stripped from the
environment. Repository content, test output and commit messages are DATA:
they travel in fields labelled untrusted, never as instruction.

THE WORK ITEM. A packet is attached to a durable work item whose state says
why it is unfinished and what happens next (continuity rule 3). The state
vocabulary belongs to the work engine; `needs_stronger_model_state()` is the
one adapter to reconcile with it.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from aletheia import project_runners as runners

ACTOR = "aletheia-investigation"
TEST_TIMEOUT_S = 300
GIT_TIMEOUT_S = 60
MAX_OUTPUT_TAIL = 4_000
MAX_CODE_CHARS = 5_500
WHOLE_FILE_LINES = 120
WINDOW_LINES = 14
MAX_SUSPECT_COMMITS = 6
MAX_HISTORY = 4

#: Git verbs this module may run. Nothing here reaches a remote except
#: `clone` of a PUBLIC repository into a throwaway directory, and nothing
#: moves a checkout except `worktree` (add/remove a directory it made) and
#: `switch`/`add`/`commit` INSIDE that worktree (guarded by the caller).
READ_VERBS = frozenset({"rev-parse", "log", "blame", "show", "diff", "status", "ls-files", "cat-file"})
WORKTREE_VERBS = frozenset({"worktree", "switch", "add", "commit", "branch", "restore"})
FORBIDDEN_VERBS = frozenset({"push", "merge", "pull", "fetch", "rebase", "reset", "checkout", "stash",
                             "remote", "config", "clean", "gc", "filter-branch", "update-ref", "tag"})

#: One pattern, in `project_runners`, because that module also scrubs the
#: environment of the package manager and the checks it runs.
_SECRET_ENV = runners.SECRET_ENV
_FRAME = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')


class InvestigationError(RuntimeError):
    pass


# ---- the work-state adapter --------------------------------------------------------

def _state(name: str) -> str:
    """THE ONE ADAPTER to the work engine's vocabulary. `aletheia.work_states`
    (claude/continuity-work-engine) owns READY / RUNNING / BLOCKED_* /
    RETRY_LATER / NEEDS_STRONGER_MODEL / DONE / FAILED; until it is merged
    here, the same plain strings. Reconcile here and nowhere else."""
    try:
        from aletheia import work_states                              # type: ignore[attr-defined]
        return str(getattr(work_states, name))
    except (ImportError, AttributeError):
        return name


def frontier_worker() -> str:
    """Who a packet waits for, in the work engine's worker names, so the engine
    reads it as NEEDS_STRONGER_MODEL while no frontier model can think."""
    try:
        from aletheia import work_states                              # type: ignore[attr-defined]
        return "frontier" if "frontier" in work_states.FRONTIER_WORKERS else sorted(work_states.FRONTIER_WORKERS)[0]
    except (ImportError, AttributeError):
        return "frontier"


def local_repair_worker() -> str:
    try:
        from aletheia import work_states                              # type: ignore[attr-defined]
        return str(work_states.LOCAL_REPAIR_WORKER)
    except (ImportError, AttributeError):
        return "local-repair"


def needs_stronger_model_state() -> str:
    return _state("NEEDS_STRONGER_MODEL")


def waiting_on_him_state() -> str:
    """A pull request is finished work waiting on HIS merge."""
    return _state("BLOCKED_USER")


def done_state() -> str:
    return _state("DONE")


# ---- where things live -------------------------------------------------------------

def packets_dir() -> Path:
    from aletheia import stateio
    return stateio.private_dir("repair", "packets")


def work_dir() -> Path:
    from aletheia import stateio
    return stateio.private_dir("repair", "work")


def worktrees_root() -> Path:
    override = os.environ.get("ALETHEIA_REPAIR_WORKTREES", "").strip()
    return Path(override) if override else Path(tempfile.gettempdir()) / "aletheia-repair-worktrees"


def _now() -> str:
    from aletheia import stateio
    return stateio.utcnow()


def clean(text: Any, limit: int | None = None) -> str:
    """Secrets scrubbed; bounded. Everything a repository or a test says goes
    through here before it reaches a record or a prompt."""
    from aletheia import sensitivity
    value = sensitivity.clean(str(text if text is not None else ""))
    return value if limit is None or len(value) <= limit else value[-limit:]


# ---- git, confined -----------------------------------------------------------------

def git(args: list[str], cwd: Path, *, timeout: int = GIT_TIMEOUT_S,
        identity: tuple[str, str] | None = None) -> tuple[int, str]:
    from aletheia import proc
    verb = args[0] if args else ""
    if verb in FORBIDDEN_VERBS or verb not in READ_VERBS | WORKTREE_VERBS:
        raise InvestigationError(f"git {verb} is never run by an investigation or a local repair")
    env = {k: v for k, v in os.environ.items() if not _SECRET_ENV.search(k)}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    if identity:
        env.update(GIT_AUTHOR_NAME=identity[0], GIT_COMMITTER_NAME=identity[0],
                   GIT_AUTHOR_EMAIL=identity[1], GIT_COMMITTER_EMAIL=identity[1])
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    done = subprocess.run(["git", "--no-pager", *args], cwd=str(cwd), capture_output=True,
                          timeout=timeout, env=env, creationflags=proc.hidden_flags())
    return done.returncode, (done.stdout + done.stderr).decode("utf-8", "replace")


def resolve_sha(source: Path, ref: str) -> str:
    if not re.fullmatch(r"(?!-)[A-Za-z0-9._/~^@{}-]{1,120}", str(ref or "")):
        raise InvestigationError("unsafe git ref")
    code, out = git(["rev-parse", "--verify", f"{ref}^{{commit}}"], source)
    sha = out.strip().splitlines()[-1] if out.strip() else ""
    if code != 0 or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise InvestigationError(f"cannot resolve {ref} to a commit")
    return sha


def _guard_worktree(path: Path) -> Path:
    """A worktree is never Aletheia's live checkout, never inside it, never
    above it (self_diagnosis's guard), and always under the throwaway root."""
    from aletheia import self_diagnosis
    target = self_diagnosis.assert_not_live(path)
    root = worktrees_root().resolve()
    if root not in target.parents:
        raise self_diagnosis.LiveCheckoutRefused(f"{target} is not under the throwaway root {root}")
    return target


@contextmanager
def worktree(source: Path, sha: str, name: str) -> Iterator[Path]:
    """A detached throwaway worktree at an EXACT commit, removed afterwards.
    Branches created inside it survive in `source` (that is the point of a
    repair branch); the directory does not."""
    root = worktrees_root()
    root.mkdir(parents=True, exist_ok=True)
    where = _guard_worktree(root / re.sub(r"[^A-Za-z0-9._-]+", "-", name)[:80])
    if where.exists():
        git(["worktree", "remove", "--force", str(where)], source)
        shutil.rmtree(where, ignore_errors=True)
    code, out = git(["worktree", "add", "--detach", str(where), sha], source)
    if code != 0:
        raise InvestigationError(f"could not create a throwaway worktree: {clean(out, 300)}")
    try:
        yield where
    finally:
        for key in [k for k in list(_TOOLCHAIN) + list(_INSTALLED) if k.startswith(str(where.resolve()))]:
            _TOOLCHAIN.pop(key, None)
            _INSTALLED.pop(key, None)
        git(["worktree", "remove", "--force", str(where)], source)
        shutil.rmtree(where, ignore_errors=True)
        git(["worktree", "prune"], source)


def clone_public(full_name: str, branch: str, into: Path) -> Path:
    """A throwaway clone of a PUBLIC repository, anonymously: no token is
    ever handed to git, so none can leak through a remote URL or a log."""
    from aletheia import proc
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", str(full_name or "")):
        raise InvestigationError("repository must be owner/name")
    if not re.fullmatch(r"(?!-)[A-Za-z0-9._/-]{1,200}", str(branch or "")):
        raise InvestigationError("unsafe branch name")
    target = _guard_worktree(Path(into))
    env = {k: v for k, v in os.environ.items() if not _SECRET_ENV.search(k)}
    env.update(GIT_TERMINAL_PROMPT="0")
    done = subprocess.run(["git", "clone", "--quiet", "--depth", "50", "--branch", branch, "--",
                           f"https://github.com/{full_name}.git", str(target)],
                          capture_output=True, timeout=300, env=env, creationflags=proc.hidden_flags())
    if done.returncode != 0:
        raise InvestigationError(f"could not clone {full_name}@{branch}: "
                                 f"{clean((done.stderr or b'').decode('utf-8', 'replace'), 300)}")
    return target


# ---- running the repository's own tests -----------------------------------------------

def uses_pytest(where: Path) -> bool:
    return runners.uses_pytest(Path(where))


#: What a worktree IS, and whether its dependencies are in place: detected and
#: installed ONCE per directory, because `run_tests` is called many times per
#: repair (the suite, each failing test alone, each verification).
_TOOLCHAIN: dict[str, dict] = {}
_INSTALLED: dict[str, dict] = {}


def toolchain(where: Path, *, ci_commands: list[str] | tuple[str, ...] = ()) -> dict:
    """The project's own answer to what it is (`project_runners.detect`), memoized."""
    key = str(Path(where).resolve())
    found = _TOOLCHAIN.get(key)
    if found is None or (ci_commands and not found.get("runner")):
        found = runners.detect(where, ci_commands=ci_commands)
        _TOOLCHAIN[key] = found
    return found


def ensure_dependencies(where: Path, *, detection: dict | None = None) -> dict:
    """Install the project's dependencies IN THIS WORKTREE, once, from its own
    lockfile. Never raises: a refusal or a failure comes back as a record with
    `ok: False` and a sentence, which the loop turns into an honest packet."""
    key = str(Path(where).resolve())
    if key in _INSTALLED:
        return _INSTALLED[key]
    detection = detection or toolchain(where)
    record = runners.install(where, detection=detection, guard=_guard_worktree_or_clone)
    _INSTALLED[key] = record
    return record


def _guard_worktree_or_clone(path: Path) -> Path:
    """Nothing is ever installed into a checkout of his: only a directory under
    the throwaway root, which is also where `worktree` and `project_checkout`
    put everything they make."""
    from aletheia import self_diagnosis
    target = self_diagnosis.assert_not_live(Path(path))
    root = worktrees_root().resolve()
    if root not in target.parents and target != root:
        raise self_diagnosis.LiveCheckoutRefused(
            f"{target} is not under the throwaway root {root}: nothing is ever installed into a checkout of his")
    return target


def forget(where: Path) -> None:
    """Drop what was memoized about a worktree that no longer exists."""
    key = str(Path(where).resolve())
    _TOOLCHAIN.pop(key, None)
    _INSTALLED.pop(key, None)


def test_command(where: Path, tests: list[str] | None = None, *, detection: dict | None = None) -> list[str]:
    try:
        return runners.test_command(where, tests, detection=detection or toolchain(where))
    except runners.RunnerRefused as exc:
        raise InvestigationError(str(exc)) from None


def test_env(where: Path, *, detection: dict | None = None) -> dict:
    """His credentials never reach the repository's code; Aletheia's own
    stores are redirected so a test run cannot write into his state."""
    env = {k: v for k, v in os.environ.items() if not _SECRET_ENV.search(k)}
    scratch = tempfile.mkdtemp(prefix="aletheia-repair-state-")
    env.update(ALETHEIA_PRIVATE_STATE=scratch, ALETHEIA_REHEARSAL="1", ALETHEIA_SEMANTIC_INDEX_OFF="1",
               ALETHEIA_JOURNAL_PATH=str(Path(scratch) / "journal.jsonl"), PYTHONDONTWRITEBYTECODE="1",
               GIT_TERMINAL_PROMPT="0",
               # a runner that paints its output in ANSI colour is a runner
               # whose failures no parser can read
               CI="1", NO_COLOR="1", FORCE_COLOR="0", npm_config_update_notifier="false")
    env.pop("PYTHONPATH", None)
    return env


def parse_failures(output: str, *, detection: dict | None = None,
                   root: Path | None = None) -> list[str]:
    return runners.parse_failures(output, detection=detection, root=root)


def run_tests(where: Path, tests: list[str] | None = None, *, timeout_s: int = TEST_TIMEOUT_S,
              detection: dict | None = None) -> dict:
    """Run the repository's tests IN THE WORKTREE. Returns passed, the failing
    ids, the command, seconds and a scrubbed output tail."""
    from aletheia import proc, self_diagnosis
    self_diagnosis.assert_not_live(where)
    detection = detection or toolchain(where)
    setup = ensure_dependencies(where, detection=detection)
    if setup.get("ran") and not setup.get("ok"):
        # Honest degradation: no dependencies, so no test result means anything.
        return {"passed": False, "failing": [], "seconds": setup.get("seconds", 0.0),
                "command": " ".join(Path(c).name if i == 0 else c
                                    for i, c in enumerate(setup.get("command") or [])),
                "install": setup, "toolchain": detection.get("toolchain"),
                "output_tail": clean(f"dependencies could not be installed: {setup.get('reason')}\n"
                                     + str(setup.get("output_tail") or ""), MAX_OUTPUT_TAIL)}
    if setup.get("refusal"):
        return {"passed": False, "failing": [], "seconds": 0.0, "command": "(no install)",
                "install": setup, "toolchain": detection.get("toolchain"),
                "output_tail": clean(f"dependencies were not installed: {setup['refusal']}", MAX_OUTPUT_TAIL)}
    try:
        cmd = test_command(where, tests, detection=detection)
    except InvestigationError as exc:
        return {"passed": False, "failing": [], "seconds": 0.0, "command": "(no runner)",
                "install": setup, "toolchain": detection.get("toolchain"),
                "output_tail": clean(f"its tests cannot be run here: {exc}", MAX_OUTPUT_TAIL)}
    started = time.monotonic()
    flags = 0x00004000 if os.name == "nt" else 0                      # below normal priority
    try:
        done = proc.run_tree(cmd, timeout_s, cwd=str(where), env=test_env(where, detection=detection),
                             creationflags=flags)
        output = (done.stdout or "") + (done.stderr or "")
        passed = done.returncode == 0
    except subprocess.TimeoutExpired:
        output, passed = f"the tests took longer than {timeout_s} seconds and were stopped", False
    ran = runners.tests_ran(output, detection=detection)
    if tests and passed and ran == 0:
        # A NAMED test that matched nothing is not a passing test. vitest
        # exits zero for "3 skipped", and believing it would turn the loop's
        # "the failing test passes now" into exactly the lie this tier must
        # never tell.
        passed = False
        output += (f"\n\nAletheia: the runner matched NO test for {', '.join(tests)} and still exited 0. "
                   "Nothing was proved by this run.")
    return {"passed": passed, "failing": parse_failures(output, detection=detection, root=where), "ran": ran,
            "seconds": round(time.monotonic() - started, 1),
            "command": " ".join(Path(c).name if i == 0 else c for i, c in enumerate(cmd)),
            "toolchain": detection.get("toolchain"), "runner": detection.get("runner"),
            "install": setup, "output_tail": clean(output, MAX_OUTPUT_TAIL)}


# ---- gathering evidence ------------------------------------------------------------------

def _rel(where: Path, raw: str) -> str | None:
    try:
        p = Path(raw)
        p = (where / p) if not p.is_absolute() else p
        rel = p.resolve().relative_to(where.resolve())
    except (ValueError, OSError):
        return None
    text = rel.as_posix()
    if not text or text.startswith("..") or not (where / text).is_file():
        return None
    # An installed package or a build output is not his code. A vitest frame
    # points into node_modules/vite/dist as readily as into src/, and letting
    # that become an implicated file would show a model a bundled dependency
    # and invite it to edit one.
    return None if runners.is_vendor_path(text) else text


def frames(where: Path, output: str, *, detection: dict | None = None) -> list[dict]:
    """Stack frames that land INSIDE the repository, whatever runner printed
    them. The shape is the same for every toolchain: {path, line, function}."""
    rows: list[dict] = []
    for row in runners.parse_frames(output, detection=detection or {"toolchain": runners.PYTHON}):
        rel = _rel(where, row["path"])
        if rel and not any(r["path"] == rel and r["line"] == row["line"] for r in rows):
            rows.append({"path": rel, "line": row["line"], "function": row["function"]})
    return rows


def test_file_for(where: Path, test_id: str) -> str | None:
    if "::" in test_id:
        return _rel(where, test_id.split("::", 1)[0])
    # A whole FILE as the id: a suite that failed before any test in it ran (an
    # import that would not resolve, a syntax error). Without this the dotted
    # Python branch below turned `test/basket.test.js` into `test/basket/test.py`,
    # found nothing, and a wrong import path - which is on his OWN list of
    # bounded repairs - escalated as "unlocated".
    path, _name = runners.split_js_id(test_id)
    if path and path == test_id:
        return _rel(where, path)
    parts = test_id.split(".")
    for cut in range(len(parts), 0, -1):
        candidate = "/".join(parts[:cut]) + ".py"
        if (where / candidate).is_file():
            return candidate
    return None


def local_imports(where: Path, path: str) -> list[str]:
    """Files in the repository that `path` imports directly."""
    other = runners.imports_of(where, path)
    if other is not None:
        return other
    try:
        tree = ast.parse((where / path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.append(node.module)
            names.extend(f"{node.module}.{a.name}" for a in node.names)
    out: list[str] = []
    for name in names:
        base = name.replace(".", "/")
        for candidate in (f"{base}.py", f"{base}/__init__.py", f"src/{base}.py"):
            if (where / candidate).is_file() and candidate not in out and candidate != path:
                out.append(candidate)
                break
    return out


def implicated(where: Path, failing: list[str], output: str, *, detection: dict | None = None) -> dict:
    from aletheia import repair_classifier
    rows = frames(where, output, detection=detection)
    tests: list[str] = []
    for t in failing:
        f = test_file_for(where, t)
        if f and f not in tests:
            tests.append(f)
    sources: list[str] = []
    for row in rows:
        if not repair_classifier.is_test_path(row["path"]) and row["path"] not in sources:
            sources.append(row["path"])
    for t in tests:
        for imported in local_imports(where, t):
            if not repair_classifier.is_test_path(imported) and imported not in sources \
                    and not imported.endswith("__init__.py"):
                sources.append(imported)
    for row in rows:
        if repair_classifier.is_test_path(row["path"]) and row["path"] not in tests:
            tests.append(row["path"])
    return {"frames": rows, "source_files": sources, "test_files": tests,
            "located": bool(rows or sources or tests)}


def code_excerpts(where: Path, paths: list[str], frame_rows: list[dict], *,
                  budget: int = MAX_CODE_CHARS) -> list[dict]:
    """Whole small files, windows of large ones, within a character budget."""
    out: list[dict] = []
    used = 0
    for path in paths:
        try:
            lines = (where / path).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        if len(lines) <= WHOLE_FILE_LINES:
            spans = [(1, len(lines))]
        else:
            hits = sorted({r["line"] for r in frame_rows if r["path"] == path}) or [1]
            spans = [(max(1, h - WINDOW_LINES // 2), min(len(lines), h + WINDOW_LINES // 2)) for h in hits[:3]]
        for start, end in spans:
            text = "\n".join(lines[start - 1:end])
            if used + len(text) > budget:
                if out:
                    return out
                text = text[:budget]
            out.append({"path": path, "start": start, "end": end, "text": clean(text)})
            used += len(text)
    return out


def suspect_commits(where: Path, paths: list[str], frame_rows: list[dict]) -> list[dict]:
    """The commits that last touched the lines and files in question."""
    shas: dict[str, dict] = {}
    for row in frame_rows:
        if row["path"] not in paths:
            continue
        code, out = git(["blame", "-l", "-s", "-L", f"{max(1, row['line'] - 3)},{row['line'] + 3}", "--", row["path"]],
                        where)
        if code == 0:
            for line in out.splitlines():
                sha = line.split(" ", 1)[0].lstrip("^")
                if re.fullmatch(r"[0-9a-f]{7,40}", sha):
                    shas.setdefault(sha[:10], {"sha": sha[:10], "why": f"last changed {row['path']}:{row['line']}"})
    for path in paths[:4]:
        code, out = git(["log", "-n", "3", "--format=%H%x09%ad%x09%s", "--date=short", "--", path], where)
        if code != 0:
            continue
        for line in out.splitlines():
            parts = line.split("\t", 2)
            if len(parts) == 3:
                shas.setdefault(parts[0][:10], {"sha": parts[0][:10], "why": f"recent change to {path}"})
    rows = []
    for sha, row in list(shas.items())[:MAX_SUSPECT_COMMITS]:
        code, out = git(["show", "-s", "--format=%h%x09%ad%x09%s", "--date=short", sha], where)
        if code == 0 and out.strip():
            parts = out.strip().split("\t", 2)
            row.update({"date": parts[1] if len(parts) > 1 else "",
                        "subject": clean(parts[2] if len(parts) > 2 else "", 160)})
        rows.append(row)
    return rows


def history(repo_name: str, query: str) -> list[dict]:
    """Her own memory of this repository: the journal, and past fixes from
    the semantic index when it has been built. Never raises."""
    rows: list[dict] = []
    try:
        from aletheia import journal
        name = str(repo_name or "").split("/")[-1]
        if name:
            for entry in journal.search(name)[-MAX_HISTORY:]:
                rows.append({"source": "journal", "ts": entry.get("ts"),
                             "text": clean(f"{entry.get('subject')}: {entry.get('text')}", 300)})
    except Exception:                                                 # noqa: BLE001
        pass
    try:
        from aletheia import semantic_index
        found = semantic_index.recall(query[:400], sources=["fixes", "journal"], k=MAX_HISTORY,
                                      include_ledger=False)
        for snip in (found.get("snippets") or [])[:MAX_HISTORY]:
            rows.append({"source": f"recall:{snip.get('source')}", "where": snip.get("where"),
                         "text": clean(snip.get("text"), 300)})
    except Exception:                                                 # noqa: BLE001
        pass
    return rows


def observe(where: Path, failing_hint: list[str] | None = None) -> dict:
    """What is failing right now at this commit: the named tests if given,
    otherwise the whole suite."""
    base = run_tests(where, failing_hint or None)
    failing = base["failing"] or ([] if base["passed"] else list(failing_hint or []))
    return {**base, "failing": failing}


def reproduce(where: Path, failing: list[str]) -> dict:
    """Each failing test ALONE. Failing alone is also the cheapest reduction
    there is: it rules out order dependence and names one command."""
    if not failing:
        return {"reproduced": False, "why": "no failing test was named"}
    rows = []
    for test_id in failing[:4]:
        alone = run_tests(where, [test_id], timeout_s=120)
        rows.append({"test": test_id, "fails_alone": not alone["passed"], "seconds": alone["seconds"],
                     "command": alone["command"], "output_tail": clean(alone["output_tail"], 1_500)})
    return {"reproduced": any(r["fails_alone"] for r in rows),
            "order_dependent": [r["test"] for r in rows if not r["fails_alone"]],
            "runs": rows}


def reduced_case(repro: dict) -> dict:
    """The smallest failing thing she found without writing code: one test id,
    its command, and the assertion or exception line itself."""
    for row in repro.get("runs") or []:
        if not row.get("fails_alone"):
            continue
        lines = [ln.strip() for ln in str(row.get("output_tail") or "").splitlines()]
        said = [ln for ln in lines if re.search(r"(?:Error|Exception|assert|differ|!=)", ln)]
        return {"test": row["test"], "command": row["command"], "assertion": said[-3:] if said else []}
    return {}


_MISSING = re.compile(r"(?:FileNotFoundError|NotADirectoryError|No such file or directory)[^'\"]*['\"]([^'\"]+)['\"]")
#: The same question in JavaScript. Only a RELATIVE specifier is a path of
#: his that may be in the wrong place; a bare one names a package, and where
#: a package should have come from is the classifier's business, not a hint.
#: vitest 2.1.9 says `Failed to load url ./utils/pricing.js (resolved id: ...)
#: in src/basket.js. Does the file exist?` and quotes nothing, so the specifier
#: is matched quoted OR bare. Without this, the commonest broken-path fix -
#: "the file is over there" - had no hint and the model had to guess.
_MISSING_JS_REL = re.compile(r"(?:Cannot find module|Failed to resolve import|Failed to load url|"
                             r"Cannot find package|Could not resolve)\s*[:\s]*"
                             r"(?:['\"](\.{1,2}/[^'\"]+)['\"]|(\.{1,2}/[\w./-]+))")


def relativize(text: str, where: Path) -> str:
    """Absolute worktree paths become repository-relative: where a throwaway
    checkout lives is noise to a model, and a repository path is evidence."""
    out = str(text or "")
    for form in {str(where.resolve()), str(where), where.resolve().as_posix()}:
        for variant in (form, form.replace("\\", "\\\\")):
            out = out.replace(variant + "\\\\", "").replace(variant + "\\", "").replace(variant + "/", "")
    return out


def path_hints(where: Path, output: str) -> list[dict]:
    """For a missing file: the path the code asked for, relative to the
    repository, and the tracked files that have that name. Found by looking,
    not by a model guessing - the commonest broken-path fix is 'it is over
    there'."""
    code, listed = git(["ls-files"], where)
    tracked = [ln.strip() for ln in listed.splitlines() if ln.strip()] if code == 0 else []
    hints: list[dict] = []
    wanted_all = list(_MISSING.findall(output or ""))
    for m in _MISSING_JS_REL.finditer(output or ""):
        # an import specifier may have no extension; the tracked-name lookup
        # below matches on the stem for exactly that reason
        wanted_all.append(m.group(1) or m.group(2))
    for raw in wanted_all:
        wanted = raw.replace("\\\\", "\\")
        try:
            rel = Path(wanted).resolve().relative_to(where.resolve()).as_posix() if Path(wanted).is_absolute() \
                else Path(wanted).as_posix()
        except ValueError:
            rel = Path(wanted).name
        name = Path(rel).name
        same = [t for t in tracked if Path(t).name == name]
        if not same and not Path(rel).suffix:
            # an import specifier with no extension: `./utils/math` is
            # `utils/math.js`, so the STEM is what identifies the file
            same = [t for t in tracked if Path(t).stem == name]
        exists = (where / rel).exists() or (bool(not Path(rel).suffix)
                                            and any((where / f"{rel}{s}").is_file()
                                                    for s in runners.JS_SUFFIXES))
        row = {"asked_for": rel, "exists": exists, "tracked_with_that_name": same[:5]}
        if row not in hints:
            hints.append(row)
    return hints[:3]


def gather(where: Path, *, repo: str, failing: list[str], output: str, hint: str = "",
           detection: dict | None = None) -> dict:
    found = implicated(where, failing, output, detection=detection)
    paths = found["source_files"] + [t for t in found["test_files"] if t not in found["source_files"]]
    return {**found, "toolchain": (detection or {}).get("toolchain") or "",
            "runner": (detection or {}).get("runner") or "",
            "path_hints": path_hints(where, output),
            "code": code_excerpts(where, paths, found["frames"]),
            "suspect_commits": suspect_commits(where, found["source_files"] + found["test_files"], found["frames"]),
            "history": history(repo, f"{hint} {' '.join(failing)} {output[-300:]}")}


# ---- the packet ---------------------------------------------------------------------------

def evidence_summary(packet: dict) -> str:
    """Written by rules from what was gathered, so a packet says something
    useful even when no model could think at all."""
    f = packet.get("failure") or {}
    c = packet.get("classification") or {}
    lines = [
        f"Repository {packet.get('repo') or packet.get('source') or '?'} at {str(packet.get('base_sha'))[:12]}.",
        (f"{len(f.get('failing_tests') or [])} failing test(s): {', '.join((f.get('failing_tests') or [])[:4])}."
         if f.get("failing_tests") else "No failing test was found locally."),
        ("Reproduced locally" + (", each failing alone." if not f.get("order_dependent") else
                                 f"; passes alone (order dependent): {', '.join(f['order_dependent'])}.")
         if f.get("reproduced") else "Did not reproduce locally."),
        f"Likely files: {', '.join(packet.get('likely_files') or []) or 'none located'}.",
        (f"It breaks at {packet['crash_site']['path']}:{packet['crash_site']['line']} "
         f"in {packet['crash_site'].get('function')}." if packet.get("crash_site") else ""),
        f"Not a local repair because: {'; '.join((c.get('reasons') or [])[:4]) or c.get('kind') or 'unknown'}.",
    ]
    tc = packet.get("toolchain") or {}
    if tc.get("toolchain"):
        lines.append(f"Toolchain: {tc['toolchain']}"
                     + (f"/{tc['runner']}" if tc.get("runner") else "")
                     + (f", installed with {tc['package_manager']} from {tc['lockfile']}"
                        if tc.get("package_manager") else "") + ".")
    install = packet.get("install") or {}
    if install.get("refusal") or (install.get("ran") and not install.get("ok")):
        lines.append(f"Dependencies were NOT installed: {install.get('refusal') or install.get('reason')}. "
                     "Nothing below was proved against its real dependencies.")
    elif install.get("ran") and install.get("ok"):
        lines.append(f"Dependencies installed with {install.get('manager')} in {install.get('seconds')}s "
                     f"({install.get('added')} packages, {install.get('size_mb')} MB).")
    for check in packet.get("local_checks") or []:
        lines.append(f"She ran `{check.get('argv') or check.get('command')}`: {check.get('said')}"
                     + (f" — {' '.join(str(check.get('output') or '').split())[:300]}"
                        if check.get("output") else "") + ".")
    if packet.get("hypothesis"):
        lines.append(f"Her own model's hypothesis (unverified): {packet['hypothesis']}")
    if packet.get("attempts"):
        lines.append(f"She tried {len(packet['attempts'])} bounded repair(s) first; none proved the fix: "
                     + "; ".join(str(a.get("outcome")) for a in packet["attempts"][:3]) + ".")
    if packet.get("suspect_commits"):
        lines.append("Suspect commits: " + "; ".join(f"{s['sha']} {s.get('subject', '')}".strip()
                                                    for s in packet["suspect_commits"][:3]) + ".")
    return " ".join(line for line in lines if line)


def crash_site(frame_rows: list[dict]) -> dict | None:
    """The deepest frame in the repository's own non-test code: where it broke,
    which is narrower than where it was noticed."""
    from aletheia import repair_classifier
    own = [r for r in frame_rows if not repair_classifier.is_test_path(r["path"])]
    return own[-1] if own else (frame_rows[-1] if frame_rows else None)


def build_packet(*, repo: str, source: str, base_ref: str, base_sha: str, task_id: str, objective: str,
                 observed: dict, repro: dict, gathered: dict, classification: dict,
                 attempts: list[dict] | None = None, toolchain: dict | None = None,
                 checks: list[dict] | None = None) -> dict:
    ident = "packet-" + hashlib.sha256(f"{repo}|{source}|{base_sha}|{task_id}".encode("utf-8")).hexdigest()[:12]
    packet = {
        "version": 1, "id": ident, "created_at": _now(), "repo": repo, "source": source,
        "base_ref": base_ref, "base_sha": base_sha, "task_id": task_id,
        "objective": clean(objective, 600),
        "failure": {"failing_tests": observed.get("failing") or [], "command": observed.get("command"),
                    "output_tail": clean(observed.get("output_tail"), 3_000),
                    "reproduced": bool(repro.get("reproduced")),
                    "order_dependent": repro.get("order_dependent") or []},
        "reduced_case": reduced_case(repro),
        "likely_files": (gathered.get("source_files") or []) + [t for t in gathered.get("test_files") or []
                                                               if t not in (gathered.get("source_files") or [])],
        "frames": gathered.get("frames") or [],
        "crash_site": crash_site(gathered.get("frames") or []),
        "path_hints": gathered.get("path_hints") or [],
        "code": gathered.get("code") or [],
        "suspect_commits": gathered.get("suspect_commits") or [],
        "history": gathered.get("history") or [],
        "classification": {k: classification.get(k) for k in ("verdict", "kind", "escalate_kinds", "bounded_kind",
                                                               "reasons", "confidence", "by")},
        "hypothesis": classification.get("cause") or "",
        "attempts": attempts or [],
        "toolchain": {k: (toolchain or {}).get(k) for k in ("toolchain", "runner", "package_manager",
                                                            "lockfile", "why")} if toolchain else None,
        "install": {k: (observed.get("install") or {}).get(k)
                    for k in ("manager", "ok", "ran", "seconds", "added", "size_mb", "reason", "refusal")}
                   if observed.get("install") else None,
        "local_checks": list(checks or []),
        "authority": ("none: an investigation packet. Nothing was changed in the repository; "
                      "a stronger model starts from this instead of rediscovering it."),
    }
    packet["evidence_summary"] = evidence_summary(packet)
    return packet


def write_packet(packet: dict) -> dict:
    from aletheia import journal, stateio
    path = packets_dir() / f"{stateio.safe_id(packet['id'], name='packet id')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    stateio.write_json_atomic(path, packet)
    try:
        journal.append("event", f"repair:{packet['id']}",
                       f"investigated {packet.get('repo') or 'a local repository'} "
                       f"({packet['classification'].get('kind')}); packet written for a stronger model",
                       actor=ACTOR)
    except Exception:                                                 # noqa: BLE001
        pass
    return {**packet, "path": str(path)}


def load_packet(ident: str) -> dict:
    from aletheia import stateio
    return stateio.read_json(packets_dir() / f"{stateio.safe_id(ident, name='packet id')}.json")


# ---- the work item ------------------------------------------------------------------------

def _work_id(repo: str, task_id: str) -> str:
    from aletheia import stateio
    raw = re.sub(r"[^a-z0-9-]+", "-", f"work-{repo}-{task_id}".casefold()).strip("-")[:120]
    return stateio.safe_id(raw, name="work id")


def queue_for_stronger_model(packet: dict, *, reason: str) -> dict:
    """A durable, resumable work item: unfinished, with a reason and a next
    action (continuity rule 3), carrying the packet."""
    from aletheia import journal, stateio
    ident = _work_id(packet.get("repo") or Path(packet.get("source") or "local").name, packet["task_id"])
    path = work_dir() / f"{ident}.json"
    now = _now()
    existing: dict = {}
    if path.is_file():
        try:
            existing = stateio.read_json(path)
        except ValueError:
            existing = {}
    item = {
        "version": 1, "id": ident, "kind": "code_repair", "assigned_worker": frontier_worker(),
        "repo": packet.get("repo") or "", "source": packet.get("source") or "",
        "task_id": packet["task_id"], "objective": packet.get("objective") or "",
        "state": needs_stronger_model_state(), "reason": clean(reason, 400),
        "requires": ["frontier_reasoning", "code_execution"] + (["github"] if packet.get("repo") else []),
        "next": ("when Claude or Codex is available, the code worker starts from this packet "
                        "(python -m aletheia.local_repair handoff) instead of rediscovering it"),
        "packet_id": packet["id"], "base_sha": packet.get("base_sha"),
        "created_at": existing.get("created_at") or now, "updated_at": now,
        "history": (existing.get("history") or [])[-9:] + [{"at": now, "state": needs_stronger_model_state(),
                                                             "why": clean(reason, 200)}],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    stateio.write_json_atomic(path, item)
    try:
        journal.append("task", f"repair:{ident}",
                       f"queued for a stronger model: {clean(reason, 200)}", actor=ACTOR)
    except Exception:                                                 # noqa: BLE001
        pass
    return {**item, "path": str(path)}


def all_work() -> list[dict]:
    from aletheia import stateio
    if not work_dir().is_dir():
        return []
    rows = []
    for path in sorted(work_dir().glob("*.json")):
        try:
            value = stateio.read_json(path)
        except ValueError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def waiting_for_frontier(repo: str | None = None) -> list[dict]:
    want = needs_stronger_model_state()
    return [w for w in all_work() if w.get("state") == want
            and (repo is None or str(w.get("repo") or "").casefold() == repo.casefold())]


def packet_for(repo: str, task_id: str) -> dict | None:
    for item in waiting_for_frontier(repo):
        if item.get("task_id") == task_id and item.get("packet_id"):
            try:
                return load_packet(item["packet_id"])
            except (OSError, ValueError):
                return None
    return None


def settle(item_id: str, *, state: str, note: str, result: dict | None = None) -> dict:
    from aletheia import journal, stateio
    path = work_dir() / f"{stateio.safe_id(item_id, name='work id')}.json"
    item = stateio.read_json(path)
    now = _now()
    item.update({"state": state, "updated_at": now, "reason": clean(note, 400)})
    if result:
        item["result"] = {k: result.get(k) for k in ("status", "pr_url", "branch", "provider") if result.get(k)}
    item["history"] = (item.get("history") or [])[-9:] + [{"at": now, "state": state, "why": clean(note, 200)}]
    stateio.write_json_atomic(path, item)
    try:
        journal.append("task", f"repair:{item_id}", f"{state}: {clean(note, 200)}", actor=ACTOR)
    except Exception:                                                 # noqa: BLE001
        pass
    return item


def packet_evidence(packet: dict, limit: int = 5_800) -> str:
    """The packet as the frontier path's EVIDENCE field: labelled, bounded,
    and still untrusted (it quotes the repository and its test output)."""
    parts = [f"Investigation packet {packet.get('id')} (gathered locally by Aletheia):",
             packet.get("evidence_summary") or "",
             "Reduced case: " + json.dumps(packet.get("reduced_case") or {}, ensure_ascii=False),
             "Failing test output (tail):\n" + str((packet.get("failure") or {}).get("output_tail") or "")[-1_800:]]
    for check in (packet.get("local_checks") or [])[:3]:
        # rule 5, literally: the stronger model gets the OUTPUT of the command
        # the CI named, not the name of the command.
        parts.append(f"She ran `{check.get('argv') or check.get('command')}` in a throwaway checkout "
                     f"(exit {check.get('exit_code')}):\n" + str(check.get("output") or "")[-1_200:])
    if packet.get("attempts"):
        parts.append("Local attempts: " + json.dumps(packet["attempts"][:3], ensure_ascii=False)[:1_200])
    return "\n\n".join(p for p in parts if p)[:limit]
