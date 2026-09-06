"""`--sandbox` has to mean it, and it has been wrong three times.

`python -m aletheia.talk --sandbox` promises an audit leaves no trace.
Private state moves with ALETHEIA_PRIVATE_STATE; a dozen other stores are
anchored at the REPOSITORY and do not move on their own.

    v1 redirected private state only, and left three build tasks and a
      journal line in the repo on its first run.
    v2 added tasks and plans, and still missed `policy.HALT_PATH` — so
      saying "halt" to a sandbox HALTED THE REAL ALETHEIA and left her
      halted, answering every later question with "only a resume command
      executes". A kill switch is the one thing a test must never reach.

Both were found by using it, not by reading it, which is why this file
exists: the list is now held against the modules, so the next store
anchored at REPO_ROOT fails the suite rather than the operator's machine.
"""
import ast
import importlib
import re
import tempfile
import unittest
from pathlib import Path

from aletheia import talk

AXIOM = Path(__file__).resolve().parent.parent / "aletheia"


def repo_anchored() -> set[tuple[str, str]]:
    """Every module-level NAME = REPO_ROOT / ... under aletheia/."""
    found = set()
    for path in sorted(AXIOM.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            source = ast.unparse(node.value)
            if re.match(r"^REPO_ROOT\b", source):
                found.add((f"aletheia.{path.stem}", target.id))
    return found


class EveryRepoStoreIsAccountedForCase(unittest.TestCase):
    def test_nothing_anchored_at_the_repo_is_unclassified(self):
        """Redirected, or explicitly read-only. There is no third option —
        an unclassified store is one an audit writes to his real repo."""
        classified = {(m, a) for m, a, _rel in talk.SANDBOX_STORES}
        classified |= talk.SANDBOX_READ_ONLY
        self.assertEqual(repo_anchored() - classified, set())

    def test_the_scan_actually_finds_things(self):
        """A regex that stopped matching would make the check vacuous."""
        self.assertGreater(len(repo_anchored()), 10)

    def test_the_kill_switch_is_redirected(self):
        """Named on its own because this is the one that bit."""
        self.assertIn(("aletheia.policy", "HALT_PATH"),
                      {(m, a) for m, a, _rel in talk.SANDBOX_STORES})

    def test_every_listed_store_really_exists_on_its_module(self):
        for module_name, attribute, _relative in talk.SANDBOX_STORES:
            with self.subTest(store=f"{module_name}.{attribute}"):
                module = importlib.import_module(module_name)
                self.assertTrue(hasattr(module, attribute))


class RedirectingReallyMovesThemCase(unittest.TestCase):
    def setUp(self):
        # Restore EVERY store afterwards, not just the one under test. A
        # file about not leaking stores is a poor place to leak one for
        # the rest of the suite.
        self.before = {}
        for module_name, attribute, _relative in talk.SANDBOX_STORES:
            module = importlib.import_module(module_name)
            self.before[(module_name, attribute)] = getattr(module, attribute)
        self.addCleanup(self.restore)
        self.room = Path(tempfile.mkdtemp())

    def restore(self):
        for (module_name, attribute), value in self.before.items():
            setattr(importlib.import_module(module_name), attribute, value)

    def test_each_store_ends_up_inside_the_room(self):
        talk._redirect_repo_stores(self.room)
        for module_name, attribute, _relative in talk.SANDBOX_STORES:
            module = importlib.import_module(module_name)
            moved = Path(getattr(module, attribute))
            with self.subTest(store=f"{module_name}.{attribute}"):
                self.assertTrue(str(moved).startswith(str(self.room)), moved)

    def test_redirecting_is_reversible(self):
        """Nothing may be left pointing elsewhere for the rest of the run."""
        from aletheia import policy
        before = policy.HALT_PATH
        talk._redirect_repo_stores(self.room)
        self.assertNotEqual(policy.HALT_PATH, before)
        self.restore()
        self.assertEqual(policy.HALT_PATH, before)


if __name__ == "__main__":
    unittest.main()
