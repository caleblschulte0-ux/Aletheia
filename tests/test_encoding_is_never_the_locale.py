"""Text written with no encoding is written in the machine's dialect.

`Path.write_text(s)` with no `encoding=` uses the LOCALE default. On the
operator's Windows PC that is cp1252; in CI it is UTF-8. So a test that
writes an em-dash produces different BYTES on the two machines, and
`workspace.read` — strict on purpose, because a document she cannot
decode is a document she must not guess at — refuses the Windows ones.

This is not hypothetical and it is not new. `docs/ROADMAP.md` records it
under 2026-09-04: "Its ten Windows test failures were a test writing a
resume without an encoding; the product's strict UTF-8 read was right."
It was diagnosed correctly, and then the write was never fixed — so the
same ten errors were still there on 2026-09-07, and the full suite could
not be used as a pre-push gate on the machine it is meant to gate.

The check is deliberately narrow. Most of the ~118 encoding-less
`write_text` calls in this repo write plain ASCII, where the locale makes
no difference and an `encoding=` argument would be noise. Only a write
whose content is VISIBLY non-ASCII at the call site is a real difference
in bytes between two machines, and only those are failed here.
"""
from __future__ import annotations

import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _module_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level NAME = "..." assignments, so `write_text(RESUME)` can
    be resolved to the text it actually writes."""
    out: dict[str, str] = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value.value
    return out


def _written_text(call: ast.Call, constants: dict[str, str]) -> str | None:
    """The text this `write_text(...)` writes, when it is knowable here."""
    if not call.args:
        return None
    arg = call.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if isinstance(arg, ast.Name):
        return constants.get(arg.id)
    if isinstance(arg, ast.JoinedStr):        # an f-string's literal parts
        return "".join(part.value for part in arg.values
                       if isinstance(part, ast.Constant)
                       and isinstance(part.value, str))
    return None


def locale_dependent_writes(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    constants = _module_constants(tree)
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "write_text"
                and not any(kw.arg == "encoding" for kw in node.keywords)):
            continue
        text = _written_text(node, constants)
        if text and any(ord(ch) > 127 for ch in text):
            odd = "".join(sorted({ch for ch in text if ord(ch) > 127}))
            found.append(f"{path.name}:{node.lineno} writes {odd!r} "
                         "with no encoding=")
    return found


class NonAsciiIsNeverWrittenInTheLocaleCase(unittest.TestCase):

    def test_no_test_or_module_writes_non_ascii_without_an_encoding(self):
        offenders: list[str] = []
        for folder in ("tests", "aletheia"):
            for path in sorted((ROOT / folder).glob("*.py")):
                offenders.extend(locale_dependent_writes(path))
        self.assertEqual(offenders, [],
                         "these write different bytes on Windows than in CI")

    def test_the_check_can_actually_fail(self):
        """The exact shape of the bug: an em-dash, no encoding."""
        source = ('RESUME = "EXPERIENCE — built a pipeline."\n'
                  'p.write_text(RESUME)\n')
        tree = ast.parse(source)
        call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
        self.assertEqual(_written_text(call, _module_constants(tree)),
                         "EXPERIENCE — built a pipeline.")

    def test_plain_ascii_is_left_alone(self):
        """Most encoding-less writes are ASCII, where the locale cannot
        matter. Failing those would be noise nobody would keep."""
        tree = ast.parse('p.write_text("hello")\n')
        call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
        text = _written_text(call, {})
        self.assertEqual(text, "hello")
        self.assertFalse(any(ord(c) > 127 for c in text))



class NoStraySourceControlCharactersCase(unittest.TestCase):
    """A control character in source is invisible and can be load-bearing.

    2026-09-07: a patch meant to write the regex escape for a word
    boundary wrote a literal BACKSPACE (0x08) into `recollection.py`
    instead, because this environment eats backslashes on the way to the
    shell. `_PAST` then ended in a real backspace, so the pattern matched
    nothing, so `for_question` returned {} for every question about her
    past — silently, with no error anywhere, and looking completely
    normal in an editor. Only the compiled pattern's repr gave it away.

    Tab, newline, carriage return and form feed are ordinary. Everything
    else below 0x20 is somebody's escape that did not survive the trip.
    """

    ALLOWED = frozenset({chr(9), chr(10), chr(13), chr(12)})

    def test_no_source_file_carries_a_control_character(self):
        offenders = []
        for folder in ("aletheia", "tests"):
            for path in sorted((ROOT / folder).glob("*.py")):
                for number, line in enumerate(
                        path.read_text(encoding="utf-8").splitlines(), 1):
                    bad = sorted({ch for ch in line
                                  if ord(ch) < 32 and ch not in self.ALLOWED})
                    if bad:
                        offenders.append(
                            path.name + ":" + str(number) + " contains "
                            + ", ".join("0x%02x" % ord(c) for c in bad))
        self.assertEqual(offenders, [], "control character in source")

    def test_the_check_can_actually_fail(self):
        """The exact shape of the bug: a word-boundary escape that arrived
        as a backspace."""
        mangled = 'r"(yesterday|last week)' + chr(8) + '"'
        bad = [ch for ch in mangled
               if ord(ch) < 32 and ch not in self.ALLOWED]
        self.assertEqual(bad, [chr(8)])

    def test_ordinary_source_is_not_flagged(self):
        fine = 'pattern = re.compile(r"' + chr(92) + 'b(yes|no)")'
        self.assertEqual([ch for ch in fine
                          if ord(ch) < 32 and ch not in self.ALLOWED], [])


if __name__ == "__main__":
    unittest.main()
