"""Guards on the test suite itself.

A defect in a test file can hide every other test. On 2026-08-27 a review
found `RuntimeAdvisorCase` with a helper named `run`, which replaced
`unittest.TestCase.run(result)` — so `unittest discover` died on a
TypeError and the WHOLE suite stopped, not just that file. It looked like
a passing branch because the crash scrolled past above the summary.

Two sessions made that same mistake on the same day, which is the
argument for asserting it rather than remembering it.
"""
import importlib
import pkgutil
import unittest
from pathlib import Path

import tests as tests_package

# `tests` is a namespace package (no __init__.py), so __file__ is None and
# __path__ is the only reliable way to its directory.
TESTS_DIR = Path(list(tests_package.__path__)[0])
REPO_ROOT = TESTS_DIR.parent

# Names unittest owns on TestCase. Rebinding one of these silently changes
# how tests are collected, run, or reported.
RESERVED = {
    "run", "debug", "subTest", "skipTest", "countTestCases", "defaultTestResult",
    "shortDescription", "id", "addCleanup", "doCleanups", "addTypeEqualityFunc",
}


def _test_modules():
    for info in pkgutil.iter_modules([str(TESTS_DIR)]):
        if info.name.startswith("test_"):
            yield importlib.import_module(f"tests.{info.name}")


class SuiteHealthCase(unittest.TestCase):
    def test_no_test_case_shadows_a_unittest_method(self):
        offences = []
        for module in _test_modules():
            for name, obj in vars(module).items():
                if not (isinstance(obj, type) and issubclass(obj, unittest.TestCase)):
                    continue
                for reserved in RESERVED & set(vars(obj)):
                    offences.append(f"{module.__name__}.{name}.{reserved}")
        self.assertEqual(
            offences, [],
            "these helpers replace a unittest.TestCase method and can take the "
            "whole suite down: " + ", ".join(offences))

    def test_every_test_module_imports(self):
        # A module that raises on import is a file whose tests never run and
        # whose absence nobody notices.
        for module in _test_modules():
            self.assertTrue(module.__name__)

    def test_source_files_end_with_a_newline(self):
        # Two files arrived without one on 2026-08-27; it makes every later
        # diff noisier than the change it carries.
        offences = []
        for path in sorted(list((REPO_ROOT / "aletheia").glob("*.py"))
                           + list(TESTS_DIR.glob("*.py"))):
            data = path.read_bytes()
            if data and not data.endswith(b"\n"):
                offences.append(path.name)
        self.assertEqual(offences, [], f"missing trailing newline: {offences}")


if __name__ == "__main__":
    unittest.main()
