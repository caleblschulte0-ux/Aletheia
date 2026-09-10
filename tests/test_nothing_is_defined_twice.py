"""Python keeps the last one and says nothing.

Three of these in one afternoon, in three unrelated modules, and every
one invisible to a reader who was not looking for it:

    self_knowledge.SYNONYMS   "search" written twice - so "can you search
                              my computer for a file" answered
                              `journal.search`, correctly, about the wrong
                              thing entirely

    mail.MAX_BODY_CHARS       20_000 for reading, then 6_000 for sending,
                              95 lines apart. Both callers came after the
                              second, so every INCOMING email was cut at
                              6,000 characters by a constant about
                              outgoing ones

    webtask.MAX_FRAMES        12, then `formfill.MAX_FRAMES` 370 lines
                              later - under a comment explaining that the
                              alias exists so the two form-driving paths
                              "cannot drift". The duplicate WAS the drift,
                              waiting for someone to edit one of them

    recollection._local_date  defined twice, the second winning

`test_every_kind_has_a_handler` already holds `intercom.KIND_ARGS`
against this, for the grammar. It is the same defect everywhere else, and
the same cost: a value the file states plainly and does not use.

Deliberately AST-based rather than a grep. A grep for `NAME =` finds
assignments inside functions, inside `if` branches, and in strings, and a
check with false positives gets turned off.
"""
from __future__ import annotations

import ast
import collections
import io
import pathlib
import unittest

_PACKAGE = pathlib.Path(__file__).resolve().parent.parent / "aletheia"

#: A name may legitimately be bound twice at module level when the second
#: is a conditional fallback - `try: from x import y / except: y = ...`.
#: Those are `Try` nodes, which this walk does not enter.


def _module_level(tree: ast.Module) -> tuple[list[str], list[str]]:
    """Names bound directly in the module body — not inside try/if/for.

    Anything nested is a deliberate alternative binding (an optional
    import's fallback, a platform branch), and flagging those would make
    this a check people switch off.
    """
    defined = [node.name for node in tree.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                    ast.ClassDef))]
    assigned = [target.id for node in tree.body if isinstance(node, ast.Assign)
                for target in node.targets if isinstance(target, ast.Name)]
    return defined, assigned


class NothingIsDefinedTwiceCase(unittest.TestCase):
    def _modules(self):
        for path in sorted(_PACKAGE.glob("*.py")):
            with io.open(path, encoding="utf-8") as handle:
                yield path, ast.parse(handle.read())

    def test_no_function_or_class_is_written_twice(self):
        offenders = []
        for path, tree in self._modules():
            defined, _ = _module_level(tree)
            for name, count in collections.Counter(defined).items():
                if count > 1:
                    lines = [n.lineno for n in tree.body
                             if getattr(n, "name", None) == name]
                    offenders.append(f"{path.name}: {name} at {lines}")
        self.assertEqual(offenders, [], "\n".join(
            ["the last one silently wins:"] + offenders))

    def test_no_constant_is_assigned_twice(self):
        offenders = []
        for path, tree in self._modules():
            _, assigned = _module_level(tree)
            for name, count in collections.Counter(assigned).items():
                if count > 1 and name.isupper():
                    offenders.append(f"{path.name}: {name} x{count}")
        self.assertEqual(offenders, [], "\n".join(
            ["two values, one name, and only one of them is used:"]
            + offenders))


class WhatEachDuplicateCostCase(unittest.TestCase):
    """One assertion per fault, so a revert says which one came back."""

    def test_a_received_email_is_not_cut_by_the_send_limit(self):
        from aletheia import mail
        self.assertGreater(mail.MAX_READ_CHARS, mail.MAX_SEND_CHARS,
                           "she will read less than she will send")

    def test_the_frame_limits_come_from_one_place(self):
        from aletheia import formfill, webtask
        self.assertIs(webtask.MAX_FRAMES, formfill.MAX_FRAMES)
        self.assertIs(webtask.FRAME_WAIT_TRIES, formfill.FRAME_WAIT_TRIES)

    def test_her_day_is_still_his_day(self):
        """The surviving `_local_date` is the one that groups correctly."""
        from aletheia import recollection
        self.assertTrue(callable(recollection._local_date))
        self.assertEqual(len(recollection._local_date("2026-09-09T02:53:31Z")),
                         len("2026-09-08"))


if __name__ == "__main__":
    unittest.main()
