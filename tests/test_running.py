"""One place that says what is on, and one switch for all of it.

The operator: *"i want it to be very clear if any part of aletheia is
running and i want to make it very easy to turn off and on."*

The half of this that is a real defect and not a display problem: until
2026-09-07 the `closed` marker was honoured by the Core and the
supervisor and by NOTHING ELSE. The room voice and the project loop run
as their own scheduled tasks, so "close her" stopped the Core, told the
watchdog to leave it stopped, and left a microphone listening in his
room. An off switch that reports success and leaves the part he can hear
still running is worse than no off switch, because he believes it.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import running


def state(**over):
    base = {
        "parts": [{"part": "supervisor", "what": "x", "up": True, "pids": [1]},
                  {"part": "core", "what": "y", "up": True, "pids": [2]},
                  {"part": "voice", "what": "z", "up": True, "pids": [3]}],
        "tasks": {}, "closed": False, "closed_reason": "",
        "halted": False, "halt_reason": "", "heartbeat_age_s": 4.0,
    }
    base.update(over)
    return base


def down(*parts):
    rows = state()["parts"]
    for row in rows:
        if row["part"] in parts:
            row["up"], row["pids"] = False, []
    return rows


class TheHeadlineSaysTheThingCase(unittest.TestCase):
    """He should not have to read a table to learn whether she is on."""

    def test_everything_up(self):
        self.assertEqual(running.headline(state()), "ON. Everything is running.")

    def test_closed_and_stopped_is_plainly_off(self):
        said = running.headline(state(closed=True, parts=down("supervisor", "core", "voice")))
        self.assertTrue(said.startswith("OFF"), said)

    def test_closed_while_parts_are_still_winding_down_says_so(self):
        """Closing is not instant — the Core finishes what it is holding.
        Reporting OFF while three processes are alive would be the same
        lie in the other direction."""
        said = running.headline(state(closed=True))
        self.assertIn("CLOSED", said)
        self.assertIn("still running", said)

    def test_nothing_running_but_not_closed_is_not_hidden(self):
        said = running.headline(state(parts=down("supervisor", "core", "voice")))
        self.assertIn("OFF", said)
        self.assertIn("not marked closed", said)

    def test_halted_is_not_reported_as_off(self):
        """HALT and closed are different things and always have been. A
        halted Aletheia is RUNNING and refusing to act; calling that "off"
        would send him looking for the wrong switch."""
        said = running.headline(state(halted=True))
        self.assertIn("HALTED", said)
        self.assertNotIn("OFF", said)

    def test_one_part_missing_is_not_reported_as_on(self):
        said = running.headline(state(parts=down("voice")))
        self.assertIn("PARTLY ON", said)
        self.assertIn("voice", said)


class TheDetailIsReadableCase(unittest.TestCase):

    def test_a_halted_render_names_the_switch_that_lifts_it(self):
        text = running.render(state(halted=True, halt_reason="he said stop"))
        self.assertIn("he said stop", text)
        self.assertIn("policy resume", text)
        self.assertIn("not the", text)      # ...the same as off

    def test_a_closed_render_names_the_switch_that_opens_her(self):
        text = running.render(state(closed=True, closed_reason="testing"))
        self.assertIn("testing", text)
        self.assertIn("running on", text)

    def test_task_states_come_back_as_words(self):
        """`schtasks.exe` reports the state in words, which is half the
        reason it is preferred: the cmdlet's JSON gives the ENUM NUMBER,
        and this read "AletheiaVoice 3"."""
        def fake(args, **kw):
            name = args[args.index("/TN") + 1]
            state = {"Aletheia": "Running"}.get(name, "Ready")
            return mock.Mock(returncode=0,
                             stdout='"\\%s","9/7/2026 9:50 AM","%s"\n'
                                    % (name, state))
        with mock.patch("subprocess.run", side_effect=fake):
            found = running.tasks()
        self.assertEqual(found["Aletheia"], "running")
        self.assertIn("ready", found["AletheiaVoice"])

    def test_it_says_what_each_part_costs(self):
        """The room voice holds the speech models in RAM and was sitting
        on nearly a gigabyte after three days. "What is running" should
        include what it costs to have running."""
        rows = [{"pid": 7, "command": "python -m aletheia.voice_room",
                 "mb": 1024}]
        with mock.patch.object(running, "_psutil_rows", return_value=rows):
            found = running.processes()
        self.assertEqual(found[0]["part"], "voice")
        self.assertEqual(found[0]["mb"], 1024)

    def test_a_process_that_is_not_hers_is_ignored(self):
        rows = [{"pid": 8, "command": "python -m pip install x", "mb": 12}]
        with mock.patch.object(running, "_psutil_rows", return_value=rows):
            self.assertEqual(running.processes(), [])

    def test_the_powershell_fallback_still_reads_sizes(self):
        """psutil is optional; a machine without it must degrade, not
        fail — so the slow path stays exercised."""
        payload = ('[{"ProcessId":7,"CommandLine":"python -m aletheia.core",'
                   '"WorkingSetSize":1073741824}]')
        with mock.patch.object(running, "_psutil_rows", return_value=None), \
             mock.patch.object(running, "_powershell", return_value=payload):
            self.assertEqual(running.processes()[0]["mb"], 1024)

    def test_a_process_with_no_size_is_not_a_crash(self):
        payload = ('[{"ProcessId":7,"CommandLine":"python -m aletheia.core",'
                   '"WorkingSetSize":null}]')
        with mock.patch.object(running, "_psutil_rows", return_value=None), \
             mock.patch.object(running, "_powershell", return_value=payload):
            self.assertEqual(running.processes()[0]["mb"], 0)

    def test_a_single_task_is_not_dropped_by_the_fallback(self):
        """PowerShell emits a bare object rather than a list of one."""
        with mock.patch("subprocess.run", side_effect=OSError("no schtasks")), \
             mock.patch.object(running, "_powershell",
                               return_value='{"TaskName":"Aletheia","State":4}'):
            self.assertEqual(running.tasks(), {"Aletheia": "running"})

    def test_a_task_that_is_not_registered_is_not_an_error(self):
        """schtasks exits non-zero for a name it does not know. That is an
        answer — "not registered" — not a failure."""
        with mock.patch("subprocess.run",
                        return_value=mock.Mock(returncode=1, stdout="")), \
             mock.patch.object(running, "_powershell", return_value=""):
            self.assertEqual(running.tasks(), {})


class ReadingIsFreeCase(unittest.TestCase):

    def test_status_writes_no_journal_line(self):
        """Asking whether she is on must not itself be an event."""
        with mock.patch.object(running, "_powershell", return_value=""), \
             mock.patch("aletheia.journal.append") as wrote:
            running.main(["status"])
        wrote.assert_not_called()

    def test_a_store_that_explodes_still_answers(self):
        """A status command that dies is a status command that lies about
        the thing it could not see."""
        with mock.patch.object(running, "_powershell", return_value=""), \
             mock.patch("aletheia.policy.halted", side_effect=OSError("gone")), \
             mock.patch("aletheia.closed.is_closed", side_effect=OSError("gone")):
            found = running.snapshot()
        self.assertFalse(found["halted"])
        self.assertFalse(found["closed"])

    def test_every_scan_failing_is_not_a_crash(self):
        """No psutil, no schtasks, no PowerShell. She should report that
        she can see nothing, not raise."""
        with mock.patch.object(running, "_psutil_rows", return_value=None), \
             mock.patch("subprocess.run", side_effect=OSError("no shell")):
            self.assertEqual(running.processes(), [])
            self.assertEqual(running.tasks(), {})

    def test_garbage_from_powershell_is_not_a_crash(self):
        with mock.patch.object(running, "_psutil_rows", return_value=None), \
             mock.patch("subprocess.run", side_effect=OSError("no schtasks")), \
             mock.patch.object(running, "_powershell", return_value="not json"):
            self.assertEqual(running.processes(), [])
            self.assertEqual(running.tasks(), {})

    def test_the_headline_does_not_pay_for_the_task_query(self):
        """The scheduled-task read is the slow half (0.6s against ~20ms)
        and `headline` never uses it, so the spoken answer must not wait
        for it. That is what `include_tasks` is for."""
        with mock.patch.object(running, "_psutil_rows", return_value=[]), \
             mock.patch.object(running, "tasks") as asked:
            running.snapshot(include_tasks=False)
        asked.assert_not_called()


class OffMeansEveryPartCase(unittest.TestCase):
    """The defect, not the display. Each of these was running through a
    "close" before 2026-09-07."""

    def test_the_room_refuses_to_listen_while_she_is_closed(self):
        from aletheia import voice_room
        with mock.patch("aletheia.closed.is_closed", return_value=True), \
             mock.patch.object(voice_room, "VoiceInstanceLock") as lock:
            code = voice_room.main([])
        self.assertEqual(code, 0)
        lock.assert_not_called()

    def test_the_room_checks_again_while_it_is_already_listening(self):
        """He closes her while she is listening. A microphone that stays
        on until the next reboot is not a closed window."""
        import inspect
        source = inspect.getsource(voice_room_module().microphone_recognizer)
        self.assertIn("closed.is_closed()", source)
        self.assertIn("CLOSED_POLL_S", source)

    def test_the_project_loop_does_not_run_while_she_is_closed(self):
        from aletheia import project_loop
        with mock.patch("aletheia.closed.is_closed", return_value=True), \
             mock.patch.object(project_loop, "cycle") as ran:
            code = project_loop.main(["once"])
        self.assertEqual(code, 0)
        ran.assert_not_called()

    def test_asking_its_status_still_works_while_closed(self):
        """Being closed is a thing he should be able to ask about."""
        from aletheia import project_loop
        with mock.patch("aletheia.closed.is_closed", return_value=True), \
             mock.patch.object(project_loop, "status", return_value={}) as asked:
            project_loop.main(["status"])
        asked.assert_called()


def voice_room_module():
    from aletheia import voice_room
    return voice_room


class TheSwitchIsOneVerbCase(unittest.TestCase):

    def test_off_closes_her(self):
        with mock.patch("aletheia.closed.close") as shut:
            running.main(["off", "--reason", "going out"])
        shut.assert_called_once_with("going out")

    def test_on_opens_her(self):
        with mock.patch("aletheia.closed.open_again", return_value=True) as opened:
            running.main(["on"])
        opened.assert_called_once()

    def test_it_does_not_invent_a_third_switch(self):
        """`closed` and HALT already exist and mean different things. This
        module routes to them; it must never grow its own marker."""
        import inspect
        source = inspect.getsource(running)
        self.assertNotIn("def close(", source)
        self.assertNotIn("def halt(", source)


class SayingItOutLoudCase(unittest.TestCase):
    """Voice could reach the KILL SWITCH and not the off switch, so "turn
    yourself off" went to the planner — which is forbidden from emitting
    a switch verb, leaving it to compile something else and report
    success. On this command that means he believes the microphone is
    off when it is not."""

    def reaches(self, said):
        from aletheia import voice
        return voice.interpret(said).get("command")

    def test_the_off_verbs_reach_the_switch(self):
        for said in ("Thea, turn yourself off", "Thea, close",
                     "Thea, close yourself", "Thea, go to sleep",
                     "Thea, turn off", "Thea, shut yourself down",
                     "Thea, go offline"):
            with self.subTest(said=said):
                self.assertEqual(self.reaches(said)["kind"], "close", said)

    def test_the_reason_carries_his_own_words(self):
        self.assertIn("turn yourself off",
                      self.reaches("Thea, turn yourself off")["reason"])

    def test_asking_what_is_running_reaches_the_status(self):
        for said in ("Thea, what is running", "Thea, what's running",
                     "Thea, is anything running", "Thea, are you all running"):
            with self.subTest(said=said):
                self.assertEqual(self.reaches(said)["kind"], "running", said)

    def test_ordinary_sentences_with_the_same_verbs_are_untouched(self):
        """The whole risk of this change. Each of these is a thing he
        actually says, and swallowing one would trade a missing switch
        for a silent one."""
        for said in ("Thea, turn off the kitchen lights",
                     "Thea, close the browser tab",
                     "Thea, open my resume",
                     "Thea, read my resume",
                     "Thea, stop the music",
                     "Thea, what is on my task list"):
            with self.subTest(said=said):
                self.assertEqual(self.reaches(said)["kind"], "intent", said)

    def test_the_planner_may_not_compile_a_switch(self):
        """Same rule as halt/resume, same reason: a compiler that turns
        English into command names can be led to one by a word that
        merely looks like it."""
        from aletheia import intercom
        for kind in ("close", "open", "halt", "resume"):
            self.assertIn(kind, intercom.PLANNER_FORBIDDEN)

    def test_asking_whether_she_is_on_stays_answerable_when_she_is_not(self):
        from aletheia import intercom
        self.assertIn("running", intercom.READ_ONLY_KINDS)



class SheIsRunningOldCodeCase(unittest.TestCase):
    """The defect this whole session began with: the Core had been up
    since 2026-09-04, the tree had moved ninety commits, "what time is
    it" took 26 SECONDS because the process predated the fast lane — and
    every part reported itself healthy, because every part WAS healthy.
    It was just old, and nothing anywhere said so."""

    def test_a_module_newer_than_her_start_is_old_code(self):
        with mock.patch("aletheia.liveness.last",
                        return_value={"started_at": "2026-09-07T10:00:00Z"}), \
             mock.patch("pathlib.Path.glob") as globbed:
            newer = mock.Mock()
            newer.stat.return_value = mock.Mock(
                st_mtime=__import__("datetime").datetime(
                    2026, 9, 7, 11, 0, tzinfo=__import__("datetime").timezone.utc
                ).timestamp())
            newer.name = "quick.py"
            globbed.return_value = [newer]
            started, newest, stale = running.running_old_code()
        self.assertTrue(stale)
        self.assertEqual(newest, "quick.py")

    def test_code_older_than_her_start_is_current(self):
        import datetime as dt
        with mock.patch("aletheia.liveness.last",
                        return_value={"started_at": "2026-09-07T12:00:00Z"}), \
             mock.patch("pathlib.Path.glob") as globbed:
            older = mock.Mock()
            older.stat.return_value = mock.Mock(
                st_mtime=dt.datetime(2026, 9, 7, 11, 0,
                                     tzinfo=dt.timezone.utc).timestamp())
            older.name = "quick.py"
            globbed.return_value = [older]
            _started, _newest, stale = running.running_old_code()
        self.assertFalse(stale)

    def test_no_start_stamp_is_not_a_guess(self):
        """Every heartbeat written before `started_at` existed. "I do not
        know" is the only honest answer, and it must not read as "current"
        — that is the reassuring lie this exists to prevent."""
        with mock.patch("aletheia.liveness.last", return_value={}):
            _started, _newest, stale = running.running_old_code()
        self.assertIsNone(stale)

    def test_the_headline_says_it_rather_than_saying_everything_is_fine(self):
        """"ON. Everything is running." is the exact sentence that hid
        this for three days."""
        said = running.headline(state(running_old_code=True))
        self.assertIn("OLDER CODE", said)
        self.assertNotIn("Everything is running", said)

    def test_a_healthy_current_core_still_reads_simply(self):
        said = running.headline(state(running_old_code=False))
        self.assertEqual(said, "ON. Everything is running.")

    def test_not_knowing_does_not_raise_the_alarm(self):
        """A warning that fires when she cannot tell would be noise, and
        noise is how a real warning gets ignored."""
        said = running.headline(state(running_old_code=None))
        self.assertEqual(said, "ON. Everything is running.")

    def test_the_words_name_the_file_and_the_fix(self):
        info = {"branch": "main", "commit": "abc1234", "subject": "a change",
                "newest_code": "quick.py", "running_old_code": True}
        said = running.version_words(info)
        self.assertIn("main", said)
        self.assertIn("abc1234", said)
        self.assertIn("quick.py", said)
        self.assertIn("restart", said.lower())

    def test_current_code_says_so_plainly(self):
        info = {"branch": "main", "commit": "abc1234", "subject": "a change",
                "newest_code": "quick.py", "running_old_code": False}
        self.assertIn("This is the code I am running",
                      running.version_words(info))

    def test_the_fast_lane_answers_which_code(self):
        from aletheia import quick
        with mock.patch.object(running, "version",
                               return_value={"branch": "main",
                                             "commit": "abc1234",
                                             "subject": "s",
                                             "running_old_code": False}):
            said = quick.answer("what version are you on")
        self.assertIn("abc1234", said)

    def test_being_behind_the_remote_is_said_out_loud(self):
        """THE staleness that actually bit him. A file changing on disk is
        caught by the supervisor, which relaunches within minutes. Nothing
        caught a CHECKOUT ninety commits behind the remote — no disk
        change, every part healthy, and a clock question taking 26
        seconds because the process predated the fast lane."""
        said = running.version_words(
            {"branch": "claude/catchup-audit-20260901", "commit": "31ac0e6",
             "subject": "an older change",
             "behind": "90 commits behind origin/main"})
        self.assertIn("90 commits behind", said)
        self.assertIn("not the newest code", said)

    def test_a_current_checkout_says_nothing_about_being_behind(self):
        said = running.version_words(
            {"branch": "main", "commit": "abc1234", "subject": "s",
             "behind": "", "running_old_code": False})
        self.assertNotIn("behind", said)

    def test_the_count_never_touches_the_network(self):
        """A status read that fetches would be slow, would fail offline,
        and would be a write to the repository from a question."""
        import inspect
        source = inspect.getsource(running.version)
        self.assertNotIn('"fetch"', source)
        self.assertIn("rev-list", source)

    def test_it_is_measured_against_CODE_not_against_commits(self):
        """A commit that touches only docs or tests changes nothing she
        runs. Crying "restart me" for one would teach him to ignore the
        line, which costs more than the warning is worth."""
        import inspect
        source = inspect.getsource(running.running_old_code)
        self.assertIn('"aletheia"', source)
        self.assertIn("*.py", source)



if __name__ == "__main__":
    unittest.main()
