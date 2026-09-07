"""Closing her, the way you close a window.

There was no way to do it. The Core and the supervisor each stop cleanly
on Ctrl+C and journal it — and both run as hidden scheduled tasks, where
nobody can press Ctrl+C. So the only available stop was terminating the
task: no clean exit, no journal line, mid-action if she was mid-action,
and the five-minute watchdog reopened her anyway.

The operator: *"i just need her to close like i close a window not kill
her."*

A closed window stays closed. That is the whole difference between this
and a kill.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import closed, journal, supervisor


class ClosedCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(root)})
        env.start(); self.addCleanup(env.stop)
        patch = mock.patch.object(journal, "JOURNAL_PATH", root / "j.jsonl")
        patch.start(); self.addCleanup(patch.stop)


class ItIsAWindowButtonNotAKill(ClosedCase):
    def test_she_starts_open(self):
        self.assertFalse(closed.is_closed())

    def test_closing_her_says_so_and_says_why(self):
        closed.close("going away for the weekend")
        self.assertTrue(closed.is_closed())
        self.assertEqual(closed.why(), "going away for the weekend")

    def test_opening_her_again_undoes_it(self):
        closed.close()
        self.assertTrue(closed.open_again())
        self.assertFalse(closed.is_closed())

    def test_opening_one_that_was_never_closed_is_not_an_error(self):
        self.assertFalse(closed.open_again())

    def test_it_is_journaled_both_ways(self):
        closed.close("testing")
        closed.open_again()
        texts = [e["text"] for e in journal.entries()]
        self.assertIn("closed by operator — testing", texts)
        self.assertIn("reopened by operator", texts)

    def test_an_unreadable_marker_is_NOT_closed(self):
        """This is checked in a loop and at every start. Failing to
        'closed' would strand her shut with no obvious reason."""
        with mock.patch.object(closed, "marker", side_effect=OSError("gone")):
            self.assertFalse(closed.is_closed())

    def test_it_is_PRIVATE_state(self):
        """Closing her is a thing he did on this machine at this moment.
        It is not a fact about the fleet, it does not belong in a public
        repository, and it must not sync over and close a machine he
        never touched."""
        closed.close()
        # It resolves under whatever ALETHEIA_PRIVATE_STATE points at,
        # which is the gitignored private root in real life.
        from aletheia import stateio
        self.assertTrue(str(closed.marker()).startswith(str(stateio.private_root())))
        import subprocess
        ignored = subprocess.run(["git", "check-ignore", "state/private"],
                                 capture_output=True)
        self.assertEqual(ignored.returncode, 0, "state/private must be gitignored")

    def test_it_is_not_the_kill_switch_and_does_not_pretend_to_be(self):
        """HALT is the safety gate — she keeps running and refuses to act.
        This is the window button. Confusing them would be bad in both
        directions."""
        from aletheia import policy
        closed.close()
        self.assertIsNone(policy.halted())


class AClosedWindowSTAYS_CLOSED(ClosedCase):
    """The watchdog trigger fires every five minutes whatever else is
    true. Without this, "close her" would mean "she is gone for up to
    five minutes", which is not what closing something means."""

    def test_the_supervisor_does_not_open_her(self):
        closed.close("not now")
        launched = []
        with mock.patch.object(supervisor, "core_alive", return_value=False):
            code = supervisor.run_forever(launch=lambda: launched.append(1) or 0,
                                  max_runs=3)
        self.assertEqual(code, 0)
        self.assertEqual(launched, [], "the watchdog started her anyway")

    def test_and_it_says_why_rather_than_exiting_silently(self):
        closed.close()
        with mock.patch.object(supervisor, "core_alive", return_value=False):
            supervisor.run_forever(launch=lambda: 0, max_runs=1)
        self.assertIn("closed — not starting",
                      [e["text"] for e in journal.entries()])

    def test_opening_her_lets_the_watchdog_work_again(self):
        closed.close()
        closed.open_again()
        launched = []
        with mock.patch.object(supervisor, "core_alive", return_value=False):
            supervisor.run_forever(launch=lambda: launched.append(1) or 0, max_runs=1)
        self.assertEqual(launched, [1])

    def test_closing_her_MID_RUN_is_an_answer_not_a_crash(self):
        """She exits; the supervisor must read that as 'he closed me',
        not as a Core that fell over and needs relaunching."""
        launched = []

        def launch():
            launched.append(1)
            closed.close("while running")
            return 0
        with mock.patch.object(supervisor, "core_alive", return_value=False):
            code = supervisor.run_forever(launch=launch, max_runs=5)
        self.assertEqual(code, 0)
        self.assertEqual(launched, [1], "it relaunched a window he closed")
        self.assertIn("closed by operator",
                      [e["text"] for e in journal.entries()])


class TheCoreWatchesForIt(unittest.TestCase):
    def test_it_shuts_the_server_down_rather_than_being_terminated(self):
        from aletheia import core
        source = Path(core.__file__).read_text(encoding="utf-8")
        self.assertIn("closed.is_closed()", source)
        self.assertIn("server.shutdown", source)

    def test_and_reports_the_clean_exit_the_supervisor_reads(self):
        from aletheia import core
        source = Path(core.__file__).read_text(encoding="utf-8")
        tail = source[source.index("server.serve_forever()"):]
        self.assertIn('journal.append("event", "core", "closed")', tail)


if __name__ == "__main__":
    unittest.main()
