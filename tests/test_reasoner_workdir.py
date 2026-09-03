"""The CLI's working directory never costs the caller its answer.

2026-09-02, on the operator's PC: fifteen of sixteen planner calls returned
a correct plan and then crashed in TemporaryDirectory cleanup with
PermissionError — Windows still held the (empty) directory for a moment
after the CLI exited. These tests hold the repair: discard with bounded
retries, never raise, sweep what an earlier call had to leave behind.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from aletheia import reasoner


class DiscardCase(unittest.TestCase):
    def test_a_free_directory_is_removed_first_try(self):
        path = tempfile.mkdtemp(prefix=reasoner.WORKDIR_PREFIX)
        with mock.patch.object(reasoner.time, "sleep") as sleep:
            self.assertTrue(reasoner._discard_workdir(path))
        self.assertFalse(os.path.exists(path))
        sleep.assert_not_called()

    def test_a_held_directory_is_retried_a_bounded_number_of_times_and_never_raises(self):
        path = tempfile.mkdtemp(prefix=reasoner.WORKDIR_PREFIX)
        self.addCleanup(lambda: os.path.isdir(path) and os.rmdir(path))
        # rmtree that cannot remove it — what Windows does while a child
        # of the CLI still has the directory as its working directory.
        with mock.patch.object(reasoner.shutil, "rmtree") as rmtree, \
                mock.patch.object(reasoner.time, "sleep") as sleep:
            self.assertFalse(reasoner._discard_workdir(path))
        self.assertEqual(rmtree.call_count, reasoner.DISCARD_TRIES)
        self.assertEqual(sleep.call_count, reasoner.DISCARD_TRIES)
        # every call swallows its own errors: a raise here is the bug
        for call in rmtree.call_args_list:
            self.assertTrue(call.kwargs.get("ignore_errors"))
        self.assertTrue(os.path.isdir(path))

    def test_a_directory_released_mid_retry_counts_as_removed(self):
        path = tempfile.mkdtemp(prefix=reasoner.WORKDIR_PREFIX)
        real = reasoner.shutil.rmtree
        calls = []

        def held_then_free(p, ignore_errors=False):
            calls.append(p)
            if len(calls) >= 3:
                real(p, ignore_errors=ignore_errors)

        with mock.patch.object(reasoner.shutil, "rmtree", side_effect=held_then_free), \
                mock.patch.object(reasoner.time, "sleep"):
            self.assertTrue(reasoner._discard_workdir(path))
        self.assertEqual(len(calls), 3)
        self.assertFalse(os.path.exists(path))


class SweepCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.patch = mock.patch.object(reasoner.tempfile, "gettempdir",
                                       return_value=self.root.name)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def make(self, name: str, age_s: float) -> str:
        path = os.path.join(self.root.name, name)
        os.mkdir(path)
        stamp = time.time() - age_s
        os.utime(path, (stamp, stamp))
        return path

    def test_only_stale_brain_directories_are_swept(self):
        stale = self.make(reasoner.WORKDIR_PREFIX + "old", reasoner.WORKDIR_STALE_S + 5)
        fresh = self.make(reasoner.WORKDIR_PREFIX + "new", 1)
        other = self.make("somebody-elses-old", reasoner.WORKDIR_STALE_S + 5)
        with open(os.path.join(self.root.name, reasoner.WORKDIR_PREFIX + "file"), "w") as fh:
            fh.write("not a directory")
        self.assertEqual(reasoner._sweep_stale_workdirs(), 1)
        self.assertFalse(os.path.exists(stale))
        self.assertTrue(os.path.isdir(fresh))
        self.assertTrue(os.path.isdir(other))

    def test_a_new_workdir_sweeps_first(self):
        stale = self.make(reasoner.WORKDIR_PREFIX + "old", reasoner.WORKDIR_STALE_S + 5)
        with mock.patch.object(reasoner.tempfile, "mkdtemp",
                               return_value="made") as mk:
            self.assertEqual(reasoner._workdir(), "made")
        mk.assert_called_once_with(prefix=reasoner.WORKDIR_PREFIX)
        self.assertFalse(os.path.exists(stale))

    def test_an_unreadable_temp_root_sweeps_nothing_and_does_not_raise(self):
        with mock.patch.object(reasoner.os, "listdir", side_effect=OSError("denied")):
            self.assertEqual(reasoner._sweep_stale_workdirs(), 0)


class RunKeepsTheAnswerCase(unittest.TestCase):
    """The defect itself: the model answered, cleanup failed, the caller
    got a traceback. Now the caller gets the answer."""

    def test_a_held_workdir_does_not_lose_the_result(self):
        made = []
        real_mkdtemp = tempfile.mkdtemp

        def mkdtemp(prefix):
            path = real_mkdtemp(prefix=prefix)
            made.append(path)
            return path

        completed = subprocess.CompletedProcess([], 0, '{"result": "{\\"ok\\": 1}"}', "")
        with mock.patch.object(reasoner, "cli_path", return_value="claude.exe"), \
                mock.patch.object(reasoner.subprocess, "run", return_value=completed), \
                mock.patch.object(reasoner.tempfile, "mkdtemp", side_effect=mkdtemp), \
                mock.patch.object(reasoner.shutil, "rmtree"), \
                mock.patch.object(reasoner.time, "sleep"):
            text = reasoner._run_cli("sys", "user", "haiku")
        self.assertEqual(text, '{"ok": 1}')
        self.assertEqual(len(made), 1)
        self.assertTrue(os.path.isdir(made[0]))   # held: left for the sweep
        os.rmdir(made[0])

    def test_the_workdir_is_discarded_after_a_failure_too(self):
        made = []
        real_mkdtemp = tempfile.mkdtemp

        def mkdtemp(prefix):
            path = real_mkdtemp(prefix=prefix)
            made.append(path)
            return path

        with mock.patch.object(reasoner, "cli_path", return_value="claude.exe"), \
                mock.patch.object(reasoner.subprocess, "run",
                                  side_effect=subprocess.TimeoutExpired("claude", 1)), \
                mock.patch.object(reasoner.tempfile, "mkdtemp", side_effect=mkdtemp):
            with self.assertRaises(reasoner.ReasonerUnavailable):
                reasoner._run_cli("sys", "user", "haiku", timeout_s=1)
        self.assertEqual(len(made), 1)
        self.assertFalse(os.path.exists(made[0]))


if __name__ == "__main__":
    unittest.main()
