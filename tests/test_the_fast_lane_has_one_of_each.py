"""Every fast-lane answer has one name, one pattern list entry and one handler.

A second `"uptime"` pattern, or a second `"uptime":` key in ANSWERS, is
silent in Python: the dict keeps the last handler and the pattern list
matches whichever comes first. Adding an answer that already exists looks
like it worked while the old code still answers (2026-10-07, nearly).
"""
import ast
import collections
import unittest
from pathlib import Path

from aletheia import quick


class OneOfEach(unittest.TestCase):
    def test_no_pattern_name_twice(self):
        twice = [n for n, c in collections.Counter(n for n, _ in quick.PATTERNS).items() if c > 1]
        self.assertEqual(twice, [])

    def test_no_handler_key_twice(self):
        tree = ast.parse(Path(quick.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "ANSWERS" for t in node.targets):
                keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
                twice = [k for k, c in collections.Counter(keys).items() if c > 1]
                self.assertEqual(twice, [])
                return
        self.fail("ANSWERS not found")

    def test_every_pattern_has_a_handler(self):
        missing = [n for n, _ in quick.PATTERNS if n not in quick.ANSWERS]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
