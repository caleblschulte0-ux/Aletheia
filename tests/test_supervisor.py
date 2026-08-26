"""The supervisor's contract: immortal loop, honest exits, bounded backoff."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, supervisor
from aletheia.core import RESTART_EXIT_CODE


class SupervisorCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(journal, "JOURNAL_PATH",
                              Path(self.tmp.name) / "journal.jsonl")
        p.start(); self.addCleanup(p.stop)
        self.sleeps: list[float] = []

    def run_codes(self, codes, max_runs=None):
        it = iter(codes)
        return supervisor.run_forever(
            launch=lambda: next(it),
            sleep=self.sleeps.append,
            max_runs=max_runs if max_runs is not None else len(codes))

    def test_clean_exit_stops_the_loop(self):
        self.assertEqual(self.run_codes([0]), 0)
        self.assertEqual(self.sleeps, [])

    def test_restart_code_relaunches_immediately(self):
        # two self-updates then a clean stop: no backoff sleeps at all
        self.assertEqual(self.run_codes([RESTART_EXIT_CODE, RESTART_EXIT_CODE, 0]), 0)
        self.assertEqual(self.sleeps, [])

    def test_crash_backoff_doubles_and_caps(self):
        self.run_codes([1] * 8)
        self.assertEqual(self.sleeps, [2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0, 60.0])

    def test_self_update_resets_crash_backoff(self):
        self.run_codes([1, 1, RESTART_EXIT_CODE, 1])
        self.assertEqual(self.sleeps, [2.0, 4.0, 2.0])

    def test_ctrl_c_stops_cleanly(self):
        def boom():
            raise KeyboardInterrupt
        self.assertEqual(
            supervisor.run_forever(launch=boom, sleep=self.sleeps.append, max_runs=5), 0)

    def test_install_is_honest_off_windows(self):
        # container is linux: install must refuse and say what it would do
        code = supervisor.install()
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()


class OutageRegressionCase(SupervisorCase):
    """Guards from the 2026-08-26 outage: a dead Core with nothing to
    relaunch it, and a second supervisor fighting the first for the port."""

    def test_supervised_child_carries_the_marker(self):
        env = supervisor._child_env()
        self.assertEqual(env.get("ALETHEIA_SUPERVISED"), "1")

    def test_second_supervisor_yields_when_core_already_serving(self):
        with mock.patch.object(supervisor, "core_alive", return_value=True):
            code = supervisor.run_forever()  # no launch stub: real preflight path
        self.assertEqual(code, 0)

    def test_core_alive_false_when_nothing_listens(self):
        # port 1 is never an Aletheia Core
        self.assertFalse(supervisor.core_alive(port=1))
