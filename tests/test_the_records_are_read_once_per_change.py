"""The application records are read once per change, not once per request.

Measured on his PC 2026-09-24: a thousand application files, read in full
by every /api/status, /api/mission and /api/needs - 2.4 s, 3.7 s and 3.4 s
a request - and the page said "Reconnecting…" over a Core that was fine.
The cache is honest in both directions: her own write in this process
forgets it at once, and another process's write is seen within two
seconds, because the fingerprint is the file count and the newest mtime.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import apply_run, stateio


class ReadOncePerChange(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(self.d)})
        env.start(); self.addCleanup(env.stop)
        apply_run._RUNS_CACHE.update({"key": None, "rows": [], "checked": 0.0})
        self.addCleanup(lambda: apply_run._RUNS_CACHE.update({"key": None, "rows": [], "checked": 0.0}))

    def _drop(self, run_id: str, state: str = "AWAITING_YOU") -> None:
        d = apply_run.staged_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{run_id}.json").write_text(json.dumps({"id": run_id, "state": state}), encoding="utf-8")

    def test_the_second_read_within_two_seconds_opens_no_file(self):
        self._drop("apply-1")
        self.assertEqual([r["id"] for r in apply_run.all_runs()], ["apply-1"])
        with mock.patch.object(stateio, "read_json", side_effect=AssertionError("must not read")):
            self.assertEqual([r["id"] for r in apply_run.all_runs()], ["apply-1"])
            self.assertEqual(apply_run.all_runs("SUBMITTED"), [])

    def test_her_own_write_is_seen_at_once(self):
        self._drop("apply-1")
        apply_run.all_runs()
        apply_run._write_record("apply-2", {"id": "apply-2", "state": "SUBMITTED"})
        self.assertEqual(sorted(r["id"] for r in apply_run.all_runs()), ["apply-1", "apply-2"])

    def test_another_processes_write_is_seen_once_the_trust_window_passes(self):
        self._drop("apply-1")
        apply_run.all_runs()
        self._drop("apply-3")
        apply_run._RUNS_CACHE["checked"] -= 10.0          # the two seconds have passed
        self.assertEqual(sorted(r["id"] for r in apply_run.all_runs()), ["apply-1", "apply-3"])

    def test_a_caller_editing_a_row_does_not_edit_the_cache(self):
        self._drop("apply-1")
        apply_run.all_runs()[0]["state"] = "EDITED"
        self.assertEqual(apply_run.all_runs()[0]["state"], "AWAITING_YOU")


if __name__ == "__main__":
    unittest.main()
