"""`CLOSE_POLL_S` was used and never defined, and closing her did nothing.

`core.watch_for_close` — the thread that notices "close her" and shuts the
server down — ended its loop on `time.sleep(CLOSE_POLL_S)`. The name did
not exist anywhere in the package, so the thread died with NameError on
its first pass. In a daemon thread, under `pythonw`, where a traceback
goes nowhere.

Everything around it worked: the marker was written, the supervisor
honoured it, the watchdog refused to start her. Only the Core that was
ALREADY RUNNING never noticed — which is the one case that matters. The
operator: "i did both them and its still talking in the back."

A unit test cannot catch this, because the broken line only runs on a real
machine with a real Core up. A NAME CHECK can, and it costs milliseconds.
"""
import builtins
import symtable
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "aletheia"
BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__",
                                 "__package__", "__spec__", "__loader__",
                                 "__builtins__", "__debug__", "__path__"}


def _undefined(path: Path) -> list[str]:
    """Names read in this module that nothing in it ever binds."""
    source = path.read_text(encoding="utf-8")
    table = symtable.symtable(source, str(path), "exec")
    module_level = set(table.get_identifiers())

    found: list[str] = []

    def walk(scope):
        for symbol in scope.get_symbols():
            name = symbol.get_name()
            if not symbol.is_referenced() or symbol.is_parameter():
                continue
            if symbol.is_assigned() or symbol.is_imported():
                continue
            # A name resolved from an enclosing function is fine; only a
            # GLOBAL read can be a name that does not exist.
            if not symbol.is_global():
                continue
            if name in module_level or name in BUILTINS:
                continue
            found.append(f"{path.name}:{scope.get_name()}: {name}")
        for child in scope.get_children():
            walk(child)

    walk(table)
    return found


class EveryNameExists(unittest.TestCase):
    def test_nothing_in_the_package_reads_a_name_that_is_never_defined(self):
        problems = []
        for path in sorted(PACKAGE.rglob("*.py")):
            problems += _undefined(path)
        self.assertEqual(problems, [], "used and never defined: " + "; ".join(problems))

    def test_the_check_really_catches_one(self):
        # A check that cannot fail is not a check. This is the exact shape
        # of the bug: a constant used inside a function, defined nowhere.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "broken.py"
            broken.write_text("import time\n\n\ndef go():\n    time.sleep(NOPE_S)\n",
                              encoding="utf-8")
            self.assertTrue(any("NOPE_S" in row for row in _undefined(broken)))

    def test_the_constant_that_started_this_is_there(self):
        from aletheia import core
        self.assertIsInstance(core.CLOSE_POLL_S, (int, float))
        self.assertGreater(core.CLOSE_POLL_S, 0)
        # A closed window closes now, not eventually.
        self.assertLessEqual(core.CLOSE_POLL_S, 5.0)


class ClosingHerReallyStopsHer(unittest.TestCase):
    """The watcher is a real function now, so this can be tested at all.

    It was a closure inside `main()`, which is why the one line that
    mattered was never executed by anything but his machine.
    """

    def setUp(self):
        import threading
        from aletheia import core
        self.core = core
        self.restarting = threading.Event()

        class FakeServer:
            def __init__(self):
                self.stopped = threading.Event()

            def shutdown(self):
                self.stopped.set()

        self.server = FakeServer()

    def test_it_shuts_the_server_down_when_she_is_closed(self):
        from unittest import mock
        from aletheia import closed, journal
        with mock.patch.object(closed, "is_closed", return_value=True), \
             mock.patch.object(journal, "append"):
            self.assertTrue(self.core.watch_for_close(
                self.server, self.restarting, poll_s=0.001, limit=3))
        self.assertTrue(self.server.stopped.wait(1.0))

    def test_it_leaves_her_alone_while_she_is_open(self):
        from unittest import mock
        from aletheia import closed
        with mock.patch.object(closed, "is_closed", return_value=False):
            self.assertFalse(self.core.watch_for_close(
                self.server, self.restarting, poll_s=0.001, limit=3))
        self.assertFalse(self.server.stopped.is_set())

    def test_a_restart_ends_the_watch_without_closing_anything(self):
        from unittest import mock
        from aletheia import closed
        self.restarting.set()
        with mock.patch.object(closed, "is_closed", return_value=True):
            self.assertFalse(self.core.watch_for_close(
                self.server, self.restarting, poll_s=0.001, limit=3))
        self.assertFalse(self.server.stopped.is_set())

    def test_main_really_starts_it(self):
        import inspect
        source = inspect.getsource(self.core)
        self.assertIn("target=watch_for_close", source)


if __name__ == "__main__":
    unittest.main()
