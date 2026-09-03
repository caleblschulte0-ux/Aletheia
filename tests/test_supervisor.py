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
        # off Windows: install must refuse and say what it would do.
        # (Mocked, not environment-sniffed: on the operator's real PC this
        # test used to pass only because unelevated schtasks was denied —
        # and actually re-registered the task once install worked.)
        with mock.patch.object(supervisor.os, "name", "posix"):
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


class WindowlessInterpreterCase(unittest.TestCase):
    """The at-logon task must name THIS interpreter, never PATH's."""

    def test_prefers_the_sibling_of_the_running_interpreter(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "python.exe"
            exe.write_text("")
            pyw = Path(tmp) / "pythonw.exe"
            pyw.write_text("")
            with mock.patch.object(supervisor.sys, "executable", str(exe)):
                self.assertEqual(supervisor.windowless_interpreter(), str(pyw))

    def test_falls_back_to_the_running_interpreter_when_no_pythonw(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "python.exe"
            exe.write_text("")
            with mock.patch.object(supervisor.sys, "executable", str(exe)):
                self.assertEqual(supervisor.windowless_interpreter(), str(exe))

    def test_never_takes_a_pythonw_from_PATH(self):
        # the 2026-08-26 trap: an old 3.9 pythonw ahead on PATH got
        # registered, and pythonw has no console to show the refusal
        with tempfile.TemporaryDirectory() as tmp:
            here, stale = Path(tmp) / "here", Path(tmp) / "stale"
            here.mkdir(); stale.mkdir()
            (here / "python.exe").write_text("")
            (here / "pythonw.exe").write_text("")
            (stale / "pythonw.exe").write_text("")
            with mock.patch.object(supervisor.sys, "executable",
                                   str(here / "python.exe")):
                with mock.patch.dict("os.environ", {"PATH": str(stale)}):
                    chosen = supervisor.windowless_interpreter()
            self.assertEqual(chosen, str(here / "pythonw.exe"))
            self.assertNotIn("stale", chosen)


class JournalRoutingCase(unittest.TestCase):
    def test_the_pc_writer_is_private_and_entries_still_merge(self):
        """Since 2026-09-03 the PC writer lives in PRIVATE state (the repo is
        public and it holds what she did on his behalf), while a read of the
        in-repo journal still returns one merged stream."""
        import os
        import tempfile
        from aletheia import journal as j
        with tempfile.TemporaryDirectory() as tmp:
            repo_journal = Path(tmp) / "state" / "journal"
            private = Path(tmp) / "private"
            with mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(private)}),                     mock.patch.object(j, "REPO_JOURNAL_DIR", repo_journal),                     mock.patch.object(j, "JOURNAL_PATH", repo_journal / "journal.jsonl"):
                j.append("note", "cloud", "from the cloud writer")
                pc = j.use_pc_journal()
                self.assertEqual(pc.name, "journal-pc.jsonl")
                self.assertTrue(str(pc).startswith(str(private)),
                                f"the PC journal must be private, got {pc}")
                with mock.patch.object(j, "JOURNAL_PATH", pc):
                    j.append("note", "pc", "from the pc writer")
                # a reader at the in-repo location sees BOTH writers
                with mock.patch.object(j, "JOURNAL_PATH", repo_journal / "journal.jsonl"):
                    texts = {e["text"] for e in j.entries()}
            self.assertEqual(texts, {"from the cloud writer", "from the pc writer"})
