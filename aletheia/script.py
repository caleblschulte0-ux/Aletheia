"""When there is no verb for it, she writes one — and runs it in a box.

The ceiling this breaks. Every other capability here is a NAMED verb, and
a fixed list of forty-five verbs is never "any request": the moment he
asks for something nobody anticipated — rename these 200 files by their
date, pull the totals out of this CSV, turn this folder of images into a
contact sheet — the planner has nothing to compile and says so. Adding a
verb per ask does not converge.

So: for a request with no verb, she writes a small Python program and
runs it. That is the same move that makes a coding assistant general, and
it is the most dangerous thing in this repository, so the confinement is
the actual design and the code generation is the easy part.

WHAT STOPS IT BEING A DISASTER, in the order it matters:

1. **A static check BEFORE anything runs.** The generated source is
   parsed and walked. Only an allowlisted set of imports survives; there
   is no socket, no urllib, no requests, no subprocess, no os.system, no
   ctypes, no importlib. `eval`, `exec`, `compile`, `__import__`,
   `globals`, and attribute access to dunders are refused outright. This
   is a whitelist, so a module nobody thought of is refused rather than
   permitted.

2. **No network is the point, not a side effect.** It is what makes
   "never spends money" hold for generated code: a program that cannot
   open a socket cannot reach a checkout page. The import check is how
   that is enforced, which is why it is a whitelist and why `subprocess`
   is refused — a shell would hand back everything the whitelist took.

3. **It runs somewhere else.** A separate process, with the workspace as
   its working directory, a wall-clock timeout, an output cap, and a
   fresh environment carrying none of his variables — no tokens, no
   keys, not even PATH beyond what the interpreter needs.

4. **He can read exactly what ran.** The source is saved next to its
   output before execution, journaled, and shown in the receipt. A
   generated program nobody can inspect afterwards is a black box, and a
   black box that touches his files is not something he should tolerate.

The static check is not a sandbox and this file does not pretend it is:
a determined adversary who could choose the source would eventually find
a way past a Python-level check. The reason it is nonetheless the right
control here is the threat model. The author is her own reasoner, the
realistic hazard is a poisoned web page steering it (research reads the
open internet), and an import whitelist plus no network stops that class
cold. What it does not stop is a genuinely hostile author — for which
the answer is the mission budget, the journal, and HALT.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from aletheia import journal, policy, proc, reasoner, stateio, workspace

ACTOR = "aletheia-script"

TIMEOUT_S = 120
MAX_SOURCE_CHARS = 20_000
MAX_OUTPUT_CHARS = 20_000
SCRIPTS_DIR = ".scripts"

# A WHITELIST: a module nobody thought of is refused, not permitted.
# Everything here is computation over data he already has. Nothing here
# opens a socket, starts a process, or loads native code.
ALLOWED_IMPORTS = frozenset({
    "json", "csv", "re", "math", "statistics", "random", "datetime", "time",
    "pathlib", "os.path", "collections", "itertools", "functools", "string",
    "textwrap", "difflib", "hashlib", "base64", "unicodedata", "html",
    "urllib.parse", "uuid", "decimal", "fractions", "zipfile", "tarfile",
    "shutil", "glob", "fnmatch", "tempfile", "io", "sys", "os", "typing",
    "dataclasses", "enum", "heapq", "bisect", "copy", "operator", "pprint",
    "sqlite3", "configparser", "xml.etree.ElementTree",
})

# Names that hand back everything the import whitelist took away.
FORBIDDEN_NAMES = frozenset({
    "eval", "exec", "compile", "__import__", "globals", "vars", "breakpoint",
    "memoryview",
})
# os and shutil are allowed for path work; these specific members are not.
FORBIDDEN_ATTRS = frozenset({
    "system", "popen", "spawn", "spawnl", "spawnv", "execv", "execve", "execl",
    "fork", "forkpty", "kill", "killpg", "putenv", "unsetenv",
})

# TAKING A FILE AWAY IS NOT THE SAME AS WRITING ONE. `os`, `shutil` and
# `pathlib` are allowed because a program that works with files needs
# them — and that quietly meant a generated program could `shutil.rmtree`
# his workspace with no approval, no version history and no receipt,
# while `file.author` next door keeps every version it replaces. "Delete
# every file in my workspace older than a month" is a plausible sentence
# and it routed straight here. So these need his yes, bound to the exact
# source, the same way every other irreversible thing does.
DESTRUCTIVE_ATTRS = frozenset({
    "remove", "unlink", "rmdir", "removedirs", "rmtree", "truncate",
    "rename", "renames", "replace", "move", "chmod", "chown",
})

SYSTEM = """You write one small, self-contained Python 3 program that carries
out the user's request, then stops.

HARD RULES:
- Standard library only, and only these modules: {allowed}
- NO network of any kind. No sockets, no urllib.request, no http, no requests.
- NO subprocess, os.system, ctypes, importlib, eval, exec or compile.
- Work relative to the CURRENT DIRECTORY, which is the user's workspace.
  Never use an absolute path and never walk above it.
- Read what you need; write only what the request asks for.
- PRINT what you did — counts, filenames, totals. The printed output is the
  entire receipt the user will see, so a silent program is a failed one.
- If the request cannot be done under these rules, print one line beginning
  "CANNOT: " explaining exactly what is missing, and write nothing."""

# The first live run (2026-09-02) failed before a line of code ran: the
# brief ended "Return ONLY the program" and the caller appended "Return
# JSON", and the model did the sensible thing — returned the program, in
# a fence — which the JSON-only subscription seam refused. One brief, one
# answer shape, and a text fallback that accepts the program as a program.
SYSTEM_JSON_TAIL = ('\n\nReturn ONLY a JSON object of the form '
                    '{"program": "<the complete Python source>"} — no markdown '
                    'fence, no commentary outside the JSON.')
SYSTEM_TEXT_TAIL = "\n\nReturn ONLY the program. No markdown fence, no commentary."


class ScriptError(RuntimeError):
    pass


class ScriptRefused(PermissionError):
    """The generated program wanted something a generated program may not have."""


def _module_allowed(name: str) -> bool:
    """`os.path` permits `os.path`; `os` permits `os`. A dotted module is
    allowed only if it or its root is named, never by prefix accident."""
    if name in ALLOWED_IMPORTS:
        return True
    root = name.split(".")[0]
    return root in ALLOWED_IMPORTS and f"{root}." not in name


def destructive_calls(source: str) -> list[str]:
    """Every call in the program that takes a file away or moves it.

    A list, not a refusal: a program that deletes is not forbidden, it is
    a thing he has to say yes to. Named so the approval can quote them.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        name = (target.attr if isinstance(target, ast.Attribute)
                else getattr(target, "id", ""))
        if name in DESTRUCTIVE_ATTRS and name not in found:
            found.append(name)
    return sorted(found)


def check(source: str) -> None:
    """Refuse a program before it runs. Raises with the exact reason."""
    if not source.strip():
        raise ScriptRefused("the generated program was empty")
    if len(source) > MAX_SOURCE_CHARS:
        raise ScriptRefused(f"the program is over {MAX_SOURCE_CHARS:,} characters")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ScriptRefused(f"the program does not parse: {exc}") from None

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _module_allowed(alias.name):
                    raise ScriptRefused(
                        f"`import {alias.name}` is not allowed. Generated code "
                        "runs without a network and without starting processes; "
                        "that is what keeps it unable to spend money or reach out.")
        elif isinstance(node, ast.ImportFrom):
            # `from . import x` has no module; a relative import cannot resolve
            # to anything in a one-file program anyway.
            if node.level or node.module is None:
                raise ScriptRefused("relative imports are not allowed")
            if not _module_allowed(node.module):
                raise ScriptRefused(
                    f"`from {node.module} import ...` is not allowed")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            raise ScriptRefused(
                f"`{node.id}` is not allowed — it would undo the import check")
        elif isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_ATTRS:
                raise ScriptRefused(
                    f"`.{node.attr}(...)` starts or signals a process, which "
                    "generated code may not do")
            if node.attr.startswith("__") and node.attr.endswith("__"):
                raise ScriptRefused(
                    f"`.{node.attr}` reaches into the interpreter's internals, "
                    "which is how an import check gets walked around")


def _clean(text: str) -> str:
    """Strip a markdown fence if the model added one anyway."""
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        value = "\n".join(lines)
    return value.strip()


def _program_from_text(raw: str) -> str:
    """A text answer is the program itself, or the JSON object wrapping it."""
    try:
        value = reasoner._first_json_object(raw)
        if isinstance(value, dict) and isinstance(value.get("program"), str):
            return _clean(value["program"])
    except ValueError:
        pass
    return _clean(raw)


def write_program(request: str, *, think=None) -> str:
    custom = think is not None
    think = think or reasoner.subscription_json
    listing = ", ".join(sorted(ALLOWED_IMPORTS))

    def validator(value: dict) -> dict:
        if not isinstance(value, dict) or "program" not in value:
            raise ValueError("expected {\"program\": \"...\"}")
        program = value.get("program")
        if not isinstance(program, str) or not program.strip():
            raise ValueError("program must be a non-empty string")
        return {"program": _clean(program)}

    files = [row["path"] for row in workspace.listing()][:60]
    brief = SYSTEM.format(allowed=listing)
    try:
        result = think(
            brief + SYSTEM_JSON_TAIL, request,
            context={"request": request, "files_in_workspace": files},
            model=reasoner.PLAN_MODEL, validator=validator)
        return result["program"]
    except (reasoner.ReasonerUnavailable, ValueError) as exc:
        if custom:
            raise
        # The subscription seam insists on JSON. A model asked for a program
        # will sometimes hand back the program itself; that is not a failure
        # of the program. Ask once more, as text, under the same rules — the
        # static check afterwards is identical either way.
        journal.append("event", "script:write",
                       f"JSON answer unusable ({type(exc).__name__}); asking for "
                       "the program as text", actor=ACTOR)
        prompt = request
        if files:
            prompt += "\n\nFiles already in the workspace: " + ", ".join(files)
        raw = reasoner.infer_text(brief + SYSTEM_TEXT_TAIL, prompt,
                                  model=reasoner.PLAN_MODEL)
        program = _program_from_text(raw)
        if not program.strip():
            raise ScriptError("the model returned no program") from None
        return program


def _environment() -> dict:
    """A fresh environment carrying none of his variables — no tokens, no
    keys. Only what an interpreter needs to start."""
    keep = {}
    for name in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT", "COMSPEC"):
        if name in os.environ:
            keep[name] = os.environ[name]
    keep["PATH"] = os.path.dirname(sys.executable)
    keep["PYTHONIOENCODING"] = "utf-8"
    keep["PYTHONDONTWRITEBYTECODE"] = "1"
    return keep


# HOW MUCH SHE WILL COPY BEFORE LETTING A PROGRAM LOOSE. `file.author`
# keeps every version it replaces; a generated program writing directly
# bypasses that entirely, and I gated DELETING without doing anything
# about overwriting — a program that rewrites his notes with garbage is
# not obviously better than one that deletes them. So: copy first, within
# a bound, and when the bound is exceeded SAY SO rather than implying an
# undo that does not exist.
MAX_BACKUP_FILES = 400
MAX_BACKUP_BYTES = 4 * 1024 * 1024      # per file
BACKUPS = ".before-scripts"


def _manifest(base: Path) -> dict:
    """What is in the workspace right now, so a run can say what it did."""
    out = {}
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        parts = path.relative_to(base).parts
        if parts and parts[0] in (workspace.VERSIONS, BACKUPS, SCRIPTS_DIR):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        out[str(path.relative_to(base))] = (stat.st_size, int(stat.st_mtime_ns))
    return out


def _back_up(base: Path, stamp: str) -> tuple[str, str]:
    """Copy the workspace aside. Returns (where, why-not)."""
    folder = base / BACKUPS / stamp
    kept = 0
    for name in _manifest(base):
        source = base / name
        try:
            if source.stat().st_size > MAX_BACKUP_BYTES:
                return "", f"{name} is larger than {MAX_BACKUP_BYTES // 1024}KB"
            if kept >= MAX_BACKUP_FILES:
                return "", f"there are more than {MAX_BACKUP_FILES} files here"
            target = folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            kept += 1
        except OSError as exc:
            return "", f"{name} could not be copied ({exc.__class__.__name__})"
    return (str(folder.relative_to(base)) if kept else ""), ""


def _changes(before: dict, after: dict) -> dict:
    return {
        "created": sorted(set(after) - set(before)),
        "changed": sorted(n for n in set(after) & set(before)
                          if after[n] != before[n]),
        "removed": sorted(set(before) - set(after)),
    }


def source_digest(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def approval_for(source: str) -> str:
    """The `requested_action` an approval for THIS program must carry."""
    return f"script.destructive:{source_digest(source)}"


def execute(source: str, *, label: str = "task",
            approval_id: str | None = None) -> dict:
    """Run a checked program in the workspace, and capture everything.

    A program that DELETES needs his yes first, bound to the exact source
    — change one line after he says yes and the hash no longer matches.
    """
    check(source)
    policy.ensure_not_halted()
    takes_away = destructive_calls(source)
    if takes_away:
        if not approval_id:
            raise ScriptRefused(
                "this program removes or moves files ("
                + ", ".join(takes_away)
                + ") — that needs your yes, and nothing has been run")
        ok, why = policy.usable(approval_id)
        if not ok:
            raise ScriptRefused(f"{why} — nothing was run")
        approval = policy.load(approval_id)
        if approval.get("requested_action") != approval_for(source):
            raise ScriptRefused(
                f"approval {approval_id} was given for a different program — "
                "nothing was run")
    base = workspace.root()
    folder = base / SCRIPTS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    stamp = stateio.utcnow().replace(":", "").replace("-", "")
    saved = folder / f"{stateio.safe_id(label, name='label')}-{stamp}.py"
    # Saved BEFORE it runs: a generated program nobody can read afterwards
    # is a black box, and this one touches his files.
    saved.write_text(source, encoding="utf-8")
    before = _manifest(base)
    kept_at, no_backup = _back_up(base, stamp)
    journal.append("action", "script:run",
                   f"running generated program {saved.name} ({len(source):,} chars)",
                   actor=ACTOR)
    try:
        completed = proc.run(
            [sys.executable, "-I", "-S", str(saved)],
            cwd=str(base), env=_environment(), capture_output=True,
            text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise ScriptError(
            f"the program ran past {TIMEOUT_S}s and was stopped — it is "
            "probably looping") from None
    out = (completed.stdout or "")[:MAX_OUTPUT_CHARS]
    err = (completed.stderr or "")[-2_000:]
    if completed.returncode != 0:
        journal.append("alert", "script:run",
                       f"{saved.name} exited {completed.returncode}", actor=ACTOR)
        raise ScriptError(f"the program failed: {err.strip()[:600]}")
    if out.strip().startswith("CANNOT:"):
        raise ScriptError(out.strip()[:600])
    journal.append("action", "script:run",
                   f"{saved.name} finished — {len(out):,} chars of output",
                   actor=ACTOR)
    # WHAT IT ACTUALLY DID TO HIS FILES. The receipt used to be the
    # program's own stdout, which is whatever the program felt like
    # saying about itself.
    changes = _changes(before, _manifest(base))
    return {"program": str(saved.relative_to(base)), "output": out,
            "stderr": err.strip(), "chars": len(out), **changes,
            "backup": kept_at, "no_backup_because": no_backup}


def run(request: str, *, think=None, label: str = "task",
        approval_id: str | None = None) -> dict:
    """Write a program for the request, check it, run it, report it.

    If the program it wrote takes files away, it is SAVED and he is asked
    — with the program itself readable and the exact calls named — rather
    than run and reported afterwards.
    """
    request = str(request or "").strip()
    if not request:
        raise ValueError("a request is required")
    policy.ensure_not_halted()
    try:
        source = write_program(request, think=think)
    except ScriptRefused:
        # The box said no. That is a thing he asked for and did not get.
        try:
            from aletheia import demand
            demand.record_attempt("task.script", request, "REFUSED",
                                  source="script")
        except Exception:
            pass
        raise
    takes_away = destructive_calls(source)
    if takes_away and not approval_id:
        held = propose(source, request=request, label=label)
        return {"state": "AWAITING_YOU", "request": request, **held}
    result = execute(source, label=label, approval_id=approval_id)
    result["request"] = request
    result["state"] = "DONE"
    return result


def propose(source: str, *, request: str, label: str = "task") -> dict:
    """Save the program, show it to him, and ask — running nothing."""
    base = workspace.root()
    folder = base / SCRIPTS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    stamp = stateio.utcnow().replace(":", "").replace("-", "")
    saved = folder / f"{stateio.safe_id(label, name='label')}-{stamp}.py"
    saved.write_text(source, encoding="utf-8")
    takes_away = destructive_calls(source)
    approval_id = f"script-{source_digest(source)[:12]}"
    policy.request(
        approval_id, approval_for(source),
        reason=(f"{request[:120]} — a program that calls "
                + ", ".join(takes_away)
                + f". Read it first: {saved.relative_to(base)}"),
        consequence=("It removes or moves files in your workspace. There is "
                     "no undo and no version kept."),
        reversible=False, capability="task.script")
    journal.append("action", "script:propose",
                   f"{saved.name} removes files ({', '.join(takes_away)}) — "
                   "waiting on him", actor=ACTOR)
    return {"approval": approval_id, "program": str(saved.relative_to(base)),
            "destructive": takes_away, "source": source,
            "say": ("That needs a program that deletes things ("
                    + ", ".join(takes_away)
                    + "). I have written it and run nothing — read "
                    + str(saved.relative_to(base)) + " and confirm it.")}


def confirmed(approval_id: str, *, label: str = "task") -> dict:
    """Run the program he approved, once, from the source he approved."""
    ok, why = policy.usable(approval_id)
    if not ok:
        raise ScriptRefused(f"{why} — nothing was run")
    approval = policy.load(approval_id)
    base = workspace.root()
    wanted = str(approval.get("requested_action") or "")
    for path in sorted((base / SCRIPTS_DIR).glob("*.py"), reverse=True):
        source = path.read_text(encoding="utf-8")
        if approval_for(source) == wanted:
            out = execute(source, label=label, approval_id=approval_id)
            out["state"] = "DONE"
            return out
    raise ScriptRefused(
        f"the program {approval_id} was given for is no longer on disk")


def spoken(result: dict) -> str:
    """What it said, and what it DID.

    The receipt used to be the program's own stdout, which is whatever
    the program felt like saying about itself. What his files did is
    observed, not reported.
    """
    if result.get("state") == "AWAITING_YOU":
        return str(result.get("say", "It needs your yes."))
    out = (result.get("output") or "").strip()
    said = (" ".join([line for line in out.splitlines() if line.strip()][:3])[:400]
            if out else "It ran and printed nothing")
    touched = []
    for verb in ("created", "changed", "removed"):
        names = result.get(verb) or []
        if names:
            touched.append(f"{verb} " + ", ".join(names[:4])
                           + (f" and {len(names) - 4} more" if len(names) > 4 else ""))
    if not touched:
        return said + " — it changed no files."
    tail = "; ".join(touched)
    if result.get("backup"):
        tail += f". The originals are in {result['backup']} if that was wrong"
    elif result.get("no_backup_because"):
        # NEVER imply an undo that does not exist.
        tail += (f". I could not keep copies first ({result['no_backup_because']}),"
                 " so this one cannot be undone")
    return f"{said} — {tail}."


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Do something there is no verb for: she writes a small "
                    "program and runs it in the workspace.")
    ap.add_argument("request")
    ap.add_argument("--show", action="store_true", help="print the program too")
    args = ap.parse_args(argv)
    try:
        result = run(args.request)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if args.show:
        print((workspace.root() / result["program"]).read_text(encoding="utf-8"))
        print("---")
    print(result["output"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
