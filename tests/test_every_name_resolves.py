"""A name that does not exist is a crash waiting for the right branch.

2026-09-07. `core.watch_for_close` slept on `CLOSE_POLL_S`, which was
never defined anywhere. The thread raised NameError on its first pass and
died, so "close her" — shipped two days earlier, with tests — did nothing
at runtime until the process restarted. Every test passed: they covered
`closed.close()` and `closed.is_closed()`, and nothing ever ran the
Core's own watcher.

The whole class of bug is invisible to a test suite, because the line
only runs on a branch the suite never takes. It is visible to the parser
for free.

**Why this is deliberately permissive.** Bindings are collected from the
WHOLE module rather than per scope, so a name assigned in any function
counts as defined everywhere in that file. That is far weaker than real
scope analysis and it is the right trade here: it cannot cry wolf about a
name that genuinely exists somewhere, so nobody will ever be tempted to
add a suppression comment, and it still catches the thing that actually
went wrong — a name that exists NOWHERE. It is not a substitute for
pyflakes; it is the part of pyflakes that would have caught this, with
nothing to install.
"""
from __future__ import annotations

import ast
import builtins
import pathlib
import unittest

PACKAGE = pathlib.Path(__file__).resolve().parent.parent / "aletheia"

# Module-level dunders the interpreter provides. They are not in
# `builtins`, so without this the check would report `__file__` as
# undefined in any module that reads it.
MODULE_DUNDERS = frozenset({
    "__file__", "__name__", "__doc__", "__package__", "__spec__",
    "__loader__", "__builtins__", "__debug__", "__path__", "__all__",
    "__class__",
})


def _bound_names(tree: ast.AST) -> set[str]:
    """Every name this module binds, however it binds it."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            found.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.add(node.name)
        elif isinstance(node, ast.arg):
            found.add(node.arg)
        elif isinstance(node, ast.alias):
            # `import a.b` binds "a"; `import a.b as c` binds "c".
            found.add((node.asname or node.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            found.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            found.update(node.names)
        elif isinstance(node, ast.MatchAs) and node.name:
            found.add(node.name)
        elif isinstance(node, ast.MatchStar) and node.name:
            found.add(node.name)
    return found


def _names_read(tree: ast.AST) -> set[str]:
    return {node.id for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}


def undefined_in(source: str, filename: str = "<test>") -> set[str]:
    tree = ast.parse(source, filename)
    known = _bound_names(tree) | set(dir(builtins)) | MODULE_DUNDERS
    return _names_read(tree) - known


class EveryNameResolvesCase(unittest.TestCase):

    def test_no_module_reads_a_name_that_exists_nowhere(self):
        missing: list[str] = []
        for path in sorted(PACKAGE.glob("*.py")):
            for name in sorted(undefined_in(path.read_text(encoding="utf-8"),
                                            str(path))):
                missing.append(f"{path.name}: {name}")
        self.assertEqual(missing, [], "names read but defined nowhere")

    def test_the_check_can_actually_fail(self):
        """A guard that cannot fail is decoration. This is the exact shape
        of the bug it was written for."""
        self.assertEqual(
            undefined_in("import time\n"
                         "def loop():\n"
                         "    time.sleep(CLOSE_POLL_S)\n"),
            {"CLOSE_POLL_S"})

    def test_a_name_bound_anywhere_in_the_file_is_accepted(self):
        """The permissiveness is the point — see the module docstring."""
        self.assertEqual(
            undefined_in("def setup():\n"
                         "    global later\n"
                         "    later = 1\n"
                         "def use():\n"
                         "    return later\n"),
            set())

    def test_module_dunders_are_not_reported(self):
        self.assertEqual(undefined_in("print(__file__, __name__)\n"), set())


if __name__ == "__main__":
    unittest.main()
