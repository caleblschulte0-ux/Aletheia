"""Three days of stale code hid behind "Everything's running" (2026-09-21).

`running.version` knew the checkout was 85 commits behind; nothing above
it ever asked, so the page and "what are you doing" both said all was
well while every merge of the week sat unpulled. And two Cores were
answering on one port, each on whichever code it had started with.
"""
from __future__ import annotations

import datetime as dt
import threading
import unittest
from unittest import mock

from aletheia import running

T0 = dt.datetime(2026, 9, 18, 21, 0, tzinfo=dt.timezone.utc)


def state(**over):
    base = {
        "parts": [{"part": "supervisor", "what": "x", "up": True, "pids": [1]},
                  {"part": "core", "what": "y", "up": True, "pids": [2]},
                  {"part": "voice", "what": "z", "up": True, "pids": [3]}],
        "tasks": {}, "closed": False, "closed_reason": "", "listening": True,
        "halted": False, "halt_reason": "", "heartbeat_age_s": 4.0,
    }
    base.update(over)
    return base


class TheUpdateSheCouldNotTakeCase(unittest.TestCase):
    def setUp(self):
        running._BEHIND_SEEN = None

    def tearDown(self):
        running._BEHIND_SEEN = None

    def behind(self, n, commit="45d4634e"):
        return {"commit": commit, "behind_count": n,
                "behind": f"{n} commits behind origin/live"}

    def test_a_merge_that_just_landed_is_not_stuck(self):
        # The next beat pulls it. Crying wolf here would teach him to
        # ignore the line that matters.
        self.assertIsNone(running.update_stuck(now=T0, info=self.behind(3)))
        later = T0 + dt.timedelta(minutes=5)
        self.assertIsNone(running.update_stuck(now=later, info=self.behind(3)))

    def test_behind_for_half_an_hour_on_the_same_commit_is_stuck(self):
        running.update_stuck(now=T0, info=self.behind(85))
        later = T0 + dt.timedelta(seconds=running.UPDATE_STUCK_AFTER_S + 1)
        stuck = running.update_stuck(now=later, info=self.behind(85))
        self.assertIsNotNone(stuck)
        self.assertEqual(stuck["waiting"], 85)
        self.assertEqual(stuck["since"], T0.isoformat())
        self.assertGreater(stuck["for_s"], running.UPDATE_STUCK_AFTER_S)

    def test_it_is_measured_from_when_she_saw_it_not_from_the_commits(self):
        # A branch merged today carries last week's commits. The clock
        # starts when THIS process first saw the checkout behind.
        running.update_stuck(now=T0, info=self.behind(40))
        moved = T0 + dt.timedelta(minutes=2)
        # she pulled some of it and is on a new commit: the clock restarts
        self.assertIsNone(running.update_stuck(now=moved, info=self.behind(2, "b2b2b2b2")))
        late = moved + dt.timedelta(minutes=29)
        self.assertIsNone(running.update_stuck(now=late, info=self.behind(2, "b2b2b2b2")))

    def test_catching_up_clears_it(self):
        running.update_stuck(now=T0, info=self.behind(85))
        later = T0 + dt.timedelta(hours=3)
        self.assertIsNotNone(running.update_stuck(now=later, info=self.behind(85)))
        self.assertIsNone(running.update_stuck(now=later, info={"commit": "a", "behind_count": 0}))
        self.assertIsNone(running._BEHIND_SEEN)

    def test_the_sync_loops_own_reason_travels_when_it_is_known(self):
        core = mock.Mock()
        core.SYNC_STATUS = {"pull": {"ok": False, "detail": "uncommitted changes the Core does not own: x"}}
        running.update_stuck(now=T0, info=self.behind(85))
        later = T0 + dt.timedelta(hours=3)
        with mock.patch.dict("sys.modules", {"aletheia.core": core}):
            stuck = running.update_stuck(now=later, info=self.behind(85))
        self.assertIn("does not own", stuck["because"])

    def test_a_version_that_cannot_be_read_is_not_an_alarm(self):
        with mock.patch.object(running, "version", side_effect=RuntimeError("no git")):
            self.assertIsNone(running.update_stuck(now=T0))


class BehindIsMeasuredAgainstHerOwnBranchCase(unittest.TestCase):
    """An even checkout on `live` read as "1 commit behind origin/main" the
    moment CI put a state commit on main, and the health line told him she
    had not managed to update for an hour (2026-09-22)."""

    def version_with(self, answers):
        import subprocess as sp
        calls = []

        def fake_run(args, **kw):
            calls.append(args[1:])
            key = " ".join(args[1:])
            out = next((v for k, v in answers.items() if key.startswith(k)), "")
            return mock.Mock(returncode=0 if out or "verify" not in key else 1, stdout=out)
        with mock.patch.object(running.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(running, "running_old_code", return_value=("", "", False)), \
             mock.patch.object(running, "_VERSION_CACHE", None), \
             mock.patch.object(running, "_git_signature", return_value=("fresh",)):
            return running.version(), calls

    def test_even_with_her_own_remote_is_not_behind_main(self):
        info, calls = self.version_with({
            "log -1": "abc1234\nHEAD -> live, origin/live\nsubject\n",
            "rev-parse --abbrev-ref HEAD": "live",
            "rev-parse --verify origin/live": "deadbeef",
            "rev-list --count HEAD..origin/live": "0",
            "rev-list --count HEAD..origin/main": "1",
        })
        self.assertEqual(info["behind_count"], 0)
        self.assertEqual(info["behind"], "")
        self.assertNotIn(["rev-list", "--count", "HEAD..origin/main"], calls)

    def test_a_branch_with_no_remote_is_measured_against_main(self):
        info, _calls = self.version_with({
            "log -1": "abc1234\nHEAD -> scratch\nsubject\n",
            "rev-parse --abbrev-ref HEAD": "scratch",
            "rev-list --count HEAD..origin/main": "3",
        })
        self.assertEqual(info["behind_count"], 3)
        self.assertIn("origin/main", info["behind"])


class TheHeadlineSaysItCase(unittest.TestCase):
    STUCK = {"since": T0.isoformat(), "for_s": 3 * 86400, "waiting": 85,
             "because": "uncommitted changes the Core does not own: Aletheia-new/"}

    def test_it_is_not_all_well(self):
        self.assertFalse(running.all_well(state(update_stuck=self.STUCK)))
        self.assertTrue(running.all_well(state(update_stuck=None)))

    def test_it_says_how_long_and_how_much_and_nothing_a_developer_would(self):
        said = running.headline(state(update_stuck=self.STUCK))
        self.assertIn("3 days", said)
        self.assertIn("85 newer changes", said)
        self.assertNotEqual(said, "Everything's running.")
        for word in ("origin", "rebase", "autostash", "commit", "Aletheia-new", "45d4634e"):
            self.assertNotIn(word, said)

    def test_it_does_not_tell_him_to_restart_her(self):
        # A restart picks up nothing while the pull itself is refused;
        # the old-code line's advice would be wrong advice here.
        said = running.headline(state(update_stuck=self.STUCK, running_old_code=True))
        self.assertNotIn("Restart me", said)

    def test_one_change_is_singular(self):
        said = running.headline(state(update_stuck={**self.STUCK, "waiting": 1}))
        self.assertIn("1 newer change waiting", said)

    def test_how_long_reads_like_a_person_said_it(self):
        self.assertEqual(running.for_words(20 * 60), "20 minutes")
        self.assertEqual(running.for_words(70 * 60), "about an hour")
        self.assertEqual(running.for_words(5 * 3600), "5 hours")
        self.assertEqual(running.for_words(3 * 86400), "3 days")
        for seconds in (61, 3599, 7200, 100000, 250000):
            self.assertNotRegex(running.for_words(seconds), r"\d\.\d")


class OnePortOneCoreCase(unittest.TestCase):
    """Two Cores answered on 8777 on 2026-09-21, one on Thursday's code."""

    def test_a_second_core_cannot_bind_the_same_port(self):
        from aletheia import core
        first = core.make_server(port=0)
        try:
            port = first.server_address[1]
            with self.assertRaises(OSError):
                core.make_server(port=port)
        finally:
            first.server_close()

    def test_a_second_core_yields_when_the_first_answers(self):
        from aletheia import core, journal
        first = core.make_server(port=0)
        try:
            port = first.server_address[1]
            with mock.patch.object(core, "another_core_answering", return_value=True), \
                 mock.patch.object(journal, "append") as noted:
                self.assertIsNone(core.bind_or_yield(port=port))
            self.assertEqual(noted.call_args.args[0], "event")
            self.assertIn("already answering", noted.call_args.args[2])
        finally:
            first.server_close()

    def test_a_held_port_whose_holder_is_slow_is_still_a_reason_to_step_aside(self):
        # Live 2026-09-21: the real Core answered in 2.5 s under memory load;
        # a 2 s probe called that "not a Core", the bind error was re-raised,
        # and the watchdog's supervisor crash-looped to a false alarm.
        from aletheia import core, journal
        first = core.make_server(port=0)
        try:
            port = first.server_address[1]
            with mock.patch.object(core, "another_core_answering", return_value=False), \
                 mock.patch.object(journal, "append") as noted:
                self.assertIsNone(core.bind_or_yield(port=port))
            self.assertEqual(noted.call_args.args[0], "alert")
            self.assertIn("did not answer", noted.call_args.args[2])
        finally:
            first.server_close()

    def test_a_bind_error_that_is_not_a_held_port_is_still_raised(self):
        from aletheia import core
        with mock.patch.object(core, "make_server", side_effect=OSError(13, "permission denied")):
            with self.assertRaises(OSError):
                core.bind_or_yield(port=1)

    def test_the_probe_is_patient_and_the_supervisor_uses_the_same_one(self):
        from aletheia import core, supervisor
        self.assertGreaterEqual(core.ALIVE_PROBE_S, 5.0)
        with mock.patch.object(core, "another_core_answering", return_value=True) as probe:
            self.assertTrue(supervisor.core_alive(8777))
        self.assertTrue(probe.called)

    def test_the_first_core_really_answers_the_probe(self):
        from aletheia import core
        server = core.make_server(port=0)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            self.assertTrue(core.another_core_answering(port))
        finally:
            server.shutdown()
            server.server_close()
        self.assertFalse(core.another_core_answering(port))


if __name__ == "__main__":
    unittest.main()
