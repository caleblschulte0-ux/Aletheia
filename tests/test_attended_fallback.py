"""He should not have to switch ChatGPT on. He should have to be there.

His ruling, 2026-09-08: *"I shouldn't have to turn on ChatGPT or
Claude... if they can't solve the problem it should route to our Claude
headless, and if it can't hit that, then ChatGPT via our subscription,
not API."*

The ladder was already automatic. What blocked its second rung was a
lease asking the wrong question - *is this PROCESS allowed to drive his
personal ChatGPT* - answered "no" by every always-on process, including
`core` and `voice_room`, which are also where he talks to her. So a
protection written against background loops was refusing his own
questions.

The question that matters is whether HE IS WAITING. Everything below is
about that line, and the tests that matter most are the negative ones: a
scheduled tick at four in the morning must still not reach his account.
"""
from __future__ import annotations

import threading
import unittest
from unittest import mock

from aletheia import browser_reasoner, core


class TheAttendedMarkCase(unittest.TestCase):
    def test_nothing_is_attended_by_default(self):
        self.assertFalse(browser_reasoner.attended())

    def test_it_lasts_exactly_as_long_as_the_request(self):
        with browser_reasoner.attending():
            self.assertTrue(browser_reasoner.attended())
        self.assertFalse(browser_reasoner.attended())

    def test_it_survives_an_exception(self):
        with self.assertRaises(RuntimeError):
            with browser_reasoner.attending():
                raise RuntimeError("the request failed")
        self.assertFalse(browser_reasoner.attended())

    def test_nesting_does_not_end_it_early(self):
        with browser_reasoner.attending():
            with browser_reasoner.attending():
                pass
            self.assertTrue(browser_reasoner.attended(),
                            "an inner block ended the outer one")

    def test_a_background_thread_does_not_inherit_it(self):
        """The grain the whole design rests on.

        A thread started while he waits is not itself something he is
        waiting on, and work the Core picks up on a later tick never had
        the mark at all.
        """
        seen = {}
        with browser_reasoner.attending():
            worker = threading.Thread(
                target=lambda: seen.update(inside=browser_reasoner.attended()))
            worker.start()
            worker.join()
        self.assertFalse(seen["inside"])


class TheLadderOpensForHimCase(unittest.TestCase):
    def setUp(self):
        # No env lease and no standing grant: the marker must be the only
        # thing doing the work in these tests.
        p = mock.patch.dict("os.environ", {browser_reasoner.ALLOW_ENV: ""})
        p.start(); self.addCleanup(p.stop)
        p = mock.patch("aletheia.second_opinion.granted", return_value=False)
        p.start(); self.addCleanup(p.stop)

    def test_an_unattended_process_still_may_not_use_his_account(self):
        """The reason the lease exists, kept intact."""
        self.assertFalse(browser_reasoner.operator_lease_enabled())

    def test_a_request_he_is_waiting_on_may(self):
        with browser_reasoner.attending():
            self.assertTrue(browser_reasoner.operator_lease_enabled())

    def test_a_standing_grant_still_works_on_its_own(self):
        with mock.patch("aletheia.second_opinion.granted", return_value=True):
            self.assertTrue(browser_reasoner.operator_lease_enabled())

    def test_the_environment_lease_still_works_on_its_own(self):
        with mock.patch.dict("os.environ", {browser_reasoner.ALLOW_ENV: "1"}):
            self.assertTrue(browser_reasoner.operator_lease_enabled())


class OnlyHisRequestsAreMarkedCase(unittest.TestCase):
    def test_the_core_command_door_marks_the_request(self):
        seen = {}

        def spy(payload, fleet):
            seen["attended"] = browser_reasoner.attended()
            return {"outcome": "done", "detail": "ok"}

        with mock.patch.object(core, "_run_command", spy):
            core.run_command({"kind": "brief"}, {})
        self.assertTrue(seen["attended"])

    def test_the_mark_is_cleared_when_the_request_is_served(self):
        with mock.patch.object(core, "_run_command",
                               return_value={"outcome": "done", "detail": "x"}):
            core.run_command({"kind": "brief"}, {})
        self.assertFalse(browser_reasoner.attended())

    def test_a_failed_request_does_not_leave_the_door_open(self):
        with mock.patch.object(core, "_run_command",
                               side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                core.run_command({"kind": "brief"}, {})
        self.assertFalse(browser_reasoner.attended())

    def test_the_background_paths_do_not_go_through_this_door(self):
        """An agenda or a beat must never be able to pick up the mark.

        They call `intercom.execute_command` directly; `run_command` is
        reached only from /api/command, /api/ask and /api/voice. If that
        stops being true, this fallback silently widens to unattended
        work, so the boundary is asserted rather than remembered.
        """
        import ast
        import pathlib

        root = pathlib.Path(core.__file__).parent
        offenders = []
        for path in sorted(root.glob("*.py")):
            if path.name == "core.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Attribute)
                        and node.attr == "run_command"):
                    offenders.append(path.name)
                elif (isinstance(node, ast.Name) and node.id == "run_command"):
                    offenders.append(path.name)
        self.assertEqual(sorted(set(offenders)), [],
                         "run_command is the attended door; these modules "
                         "reach it from outside the HTTP request path")


if __name__ == "__main__":
    unittest.main()
