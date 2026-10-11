"""Windows refuses to replace a file another thread is reading (CI on Windows, 2026-10-11:
one of eight concurrent conversation turns lost). The write tries again instead of losing it."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import stateio


class ARefusedReplaceIsTriedAgain(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "x.json"

    def test_a_replace_refused_twice_still_writes(self):
        real, calls = os.replace, []

        def refuse_twice(src, dst):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError(13, "in use")
            return real(src, dst)
        with mock.patch.object(stateio.os, "replace", refuse_twice), mock.patch.object(stateio.time, "sleep"):
            stateio.write_json_atomic(self.path, {"a": 1})
        self.assertEqual(stateio.read_json(self.path), {"a": 1})
        self.assertEqual(len(calls), 3)
        self.assertEqual([p.name for p in Path(self.dir.name).iterdir()], ["x.json"], "no temp file left")

    def test_a_replace_that_never_succeeds_still_raises(self):
        with mock.patch.object(stateio.os, "replace", side_effect=PermissionError(13, "in use")), \
                mock.patch.object(stateio.time, "sleep"):
            with self.assertRaises(PermissionError):
                stateio.write_json_atomic(self.path, {"a": 1})
        self.assertEqual(list(Path(self.dir.name).iterdir()), [], "no temp file left")

    def test_any_other_error_is_not_retried(self):
        with mock.patch.object(stateio.os, "replace", side_effect=FileNotFoundError(2, "gone")) as rep:
            with self.assertRaises(FileNotFoundError):
                stateio.write_json_atomic(self.path, {"a": 1})
        self.assertEqual(rep.call_count, 1)


if __name__ == "__main__":
    unittest.main()
