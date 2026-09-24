"""A Core that dies leaves its last words where somebody can read them.

Live 2026-09-24 the journal said "Core died (exit 4294967295) after 85s —
relaunching in 2s" and nothing else, anywhere: the Core's stderr went to a
console nobody was looking at (under the hidden logon task, to nowhere), so
the one crash of the night could not be diagnosed after the fact. The
supervisor tails the Core's stderr now, the crash line carries the
exception, and the tail is written to private state.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import supervisor

CRASH = ("import sys\n"
         "sys.stderr.write('warming up\\n')\n"
         "sys.stderr.write('Traceback (most recent call last):\\n')\n"
         "sys.stderr.write('  File \"core.py\", line 9, in <module>\\n')\n"
         "sys.stderr.write('    boom()\\n')\n"
         "sys.stderr.write('ValueError: the beat could not read its own state\\n')\n"
         "sys.exit(3)\n")


class TheCoreDiesWithItsLastWordsOnRecord(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": self.tmp.name})
        env.start(); self.addCleanup(env.stop)
        supervisor._last_stderr["lines"] = []

    def test_the_exit_code_comes_back_and_the_tail_is_kept(self):
        with mock.patch.object(supervisor, "_child_env", lambda: dict(os.environ)):
            code = supervisor._launch_core([sys.executable, "-c", CRASH])
        self.assertEqual(code, 3)
        self.assertEqual(supervisor.last_crash_line(), "ValueError: the beat could not read its own state")

    def test_the_crash_sentence_says_why_and_where_the_tail_is(self):
        supervisor._last_stderr["lines"] = CRASH_LINES = [
            "warming up", "Traceback (most recent call last):",
            '  File "core.py", line 9, in <module>', "    boom()",
            "ValueError: the beat could not read its own state"]
        said = supervisor._crash_sentence(3, 85.0, 2.0)
        self.assertIn("Core died (exit 3) after 85s", said)
        self.assertIn("ValueError: the beat could not read its own state", said)
        self.assertIn(supervisor.CRASH_LOG_NAME, said)
        self.assertIn("relaunching in 2s", said)
        log = Path(self.tmp.name) / "logs" / supervisor.CRASH_LOG_NAME
        self.assertTrue(log.exists())
        self.assertIn("boom()", log.read_text(encoding="utf-8"))
        del CRASH_LINES

    def test_a_crash_with_nothing_on_stderr_still_says_it_died(self):
        said = supervisor._crash_sentence(1, 12.0, 4.0)
        self.assertEqual(said, "Core died (exit 1) after 12s — relaunching in 4s")
        self.assertFalse((Path(self.tmp.name) / "logs" / supervisor.CRASH_LOG_NAME).exists())

    def test_the_last_line_is_the_last_line_when_there_was_no_traceback(self):
        supervisor._last_stderr["lines"] = ["one", "", "two words  "]
        self.assertEqual(supervisor.last_crash_line(), "two words")


if __name__ == "__main__":
    unittest.main()
