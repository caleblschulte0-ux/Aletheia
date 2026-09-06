"""A kind in the grammar with no branch behind it is a verb that
validates, plans, gets approved — and then does nothing, at the last
possible moment.

`KIND_ARGS` is the vocabulary: it gates what may be relayed, what the
planner is allowed to compile, and what the Core will accept. Nothing
checked that `execute_command` could actually carry any of it out.

Found while adding `tasks` and `task_done`: the media block ended in a
bare `else` that ran `media.convert`, so ANY future `media_*` kind would
have silently transcoded and reported success.
"""
import ast
import re
import unittest
from pathlib import Path

from aletheia import intercom

SOURCE = Path(intercom.__file__).read_text(encoding="utf-8")


def branched_kinds() -> set[str]:
    """Every kind `execute_command` explicitly compares against."""
    found = set(re.findall(r'kind == "([a-z_]+)"', SOURCE))
    for group in re.findall(r'kind in \(([^)]*)\)', SOURCE):
        found |= {k.strip().strip('"\'') for k in group.split(",") if k.strip()}
    for group in re.findall(r'kind in \{([^}]*)\}', SOURCE):
        found |= {k.strip().strip('"\'') for k in group.split(",") if k.strip()}
    return found


class EveryVerbCanBeCarriedOutCase(unittest.TestCase):
    def test_every_kind_in_the_grammar_has_a_branch(self):
        missing = sorted(set(intercom.KIND_ARGS) - branched_kinds())
        self.assertEqual(missing, [],
                         "these kinds validate and plan but nothing executes them")

    def test_no_branch_names_a_kind_that_is_not_in_the_grammar(self):
        """The other direction: dead code that can never be reached, or a
        kind somebody removed from the grammar and left handled."""
        grammar = set(intercom.KIND_ARGS)
        # Words that appear in a `kind ==` comparison for reasons other
        # than dispatch (a guard, a re-check), each deliberate.
        allowed = {"resume", "approve"}
        stray = sorted(branched_kinds() - grammar - allowed)
        self.assertEqual(stray, [])

    def test_the_scan_finds_a_realistic_number(self):
        """A regex that stopped matching would make both checks vacuous."""
        self.assertGreater(len(branched_kinds()), 50)
        self.assertGreater(len(intercom.KIND_ARGS), 50)

    def test_the_media_block_no_longer_ends_in_a_catch_all(self):
        """It ran `media.convert` for anything unrecognised, and reported
        success. A kind nobody wrote a branch for must fail loudly."""
        self.assertIn('raise ValueError(f"no handler for media kind', SOURCE)


class TheGrammarIsWellFormedCase(unittest.TestCase):
    def test_no_kind_is_declared_twice(self):
        """A duplicate key in a dict literal is silent: Python keeps the
        last one, and the first set of required arguments simply stops
        applying."""
        tree = ast.parse(SOURCE)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            names = [k.value for k in node.keys
                     if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            duplicated = {n for n in names if names.count(n) > 1}
            self.assertEqual(duplicated, set(),
                             f"duplicate keys near line {node.lineno}")

    def test_required_and_optional_arguments_never_overlap(self):
        for kind, (required, optional) in intercom.KIND_ARGS.items():
            with self.subTest(kind=kind):
                self.assertEqual(required & optional, set(), kind)

    def test_every_read_only_kind_is_a_real_kind(self):
        self.assertEqual(intercom.READ_ONLY_KINDS - set(intercom.KIND_ARGS), set())

    def test_every_routine_kind_is_a_real_kind(self):
        self.assertEqual(intercom.ROUTINE_KINDS - set(intercom.KIND_ARGS), set())

    def test_every_local_kind_is_a_real_kind(self):
        self.assertEqual(intercom.LOCAL_KINDS - set(intercom.KIND_ARGS), set())

    def test_a_kind_is_not_both_read_only_and_routine(self):
        """The tier is its most demanding claim; being in both makes
        `tier()` depend on the order the checks happen to be written in."""
        self.assertEqual(intercom.READ_ONLY_KINDS & intercom.ROUTINE_KINDS, set())


if __name__ == "__main__":
    unittest.main()
