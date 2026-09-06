"""Nothing she says may contain "(s)".

Every one of these reaches a room through the voice door:

    "Assets 0.00, liabilities 0.00, net 0.00 across 0 account(s)."
    "I can't do room.scene yet; filed 1 build task(s)."
    "Done — 3 step(s)."
    "no matches across 36 board(s)."

A parenthesised plural is a thing only a form has ever said. `speech.
count_phrase` exists for it, and the reason this is a test rather than
four edits is that the fifth one will be written next month.
"""
import ast
import unittest
from pathlib import Path

AXIOM = Path(__file__).resolve().parent.parent / "aletheia"

# The modules whose output reaches HIM — a spoken reply, a receipt read
# back, or a journal line `recollection` says out loud. Deliberately a
# list rather than "all of aletheia/": argparse help, CLI tables and
# developer logs are read on a screen, where "3 file(s)" is ordinary, and
# sweeping those in would be churn with no listener.
#
# If a module starts producing sentences for the room, add it here.
SPOKEN_MODULES = (
    "intercom", "voice", "speech", "recollection", "presence", "announce",
    "pursue", "work_direct", "campaign", "formfill", "apply_run",
    "scheduling", "policy", "jobs", "hass", "research", "applications",
    "webtask", "converse",
    # `planner` journals what a plan did, and `recollection` reads that
    # line back out loud — "executed 1/1 step(s) of ..." was one of them.
    "planner", "intercom",
)

# Files whose PROSE quotes the defect on purpose — the docstrings above
# and the comments explaining why a fix exists. Comments are not AST
# strings, so only these docstrings need naming.
QUOTING_THE_BUG = {"talk.py", "intents.py", "quick.py"}


def spoken_literals(path: Path):
    """Every string literal in a file that is not a docstring."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings):
            yield node.lineno, node.value


class NoParenthesisedPluralsCase(unittest.TestCase):
    def test_nothing_she_says_carries_a_parenthesised_plural(self):
        offenders = []
        for name in SPOKEN_MODULES:
            path = AXIOM / f"{name}.py"
            if path.name in QUOTING_THE_BUG:
                continue
            for line, text in spoken_literals(path):
                # "http(s) URL" is a real parenthetical, not a plural.
                if "(s)" in text and "http(s)" not in text:
                    offenders.append(f"{path.name}:{line}: {text.strip()[:70]}")
        self.assertEqual(offenders, [], "use speech.count_phrase")

    def test_every_named_module_exists(self):
        """A typo here would silently stop checking a whole surface."""
        for name in SPOKEN_MODULES:
            with self.subTest(module=name):
                self.assertTrue((AXIOM / f"{name}.py").is_file(), name)

    def test_the_scan_would_notice(self):
        """A walker that stopped finding literals would make this vacuous."""
        found = list(spoken_literals(AXIOM / "intercom.py"))
        self.assertGreater(len(found), 100)

    def test_count_phrase_is_what_they_should_use(self):
        from aletheia import speech
        self.assertEqual(speech.count_phrase(1, "account"), "1 account")
        self.assertEqual(speech.count_phrase(0, "account"), "0 accounts")
        self.assertEqual(speech.count_phrase(3, "match", "matches"), "3 matches")


if __name__ == "__main__":
    unittest.main()
