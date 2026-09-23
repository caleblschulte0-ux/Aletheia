"""His words, 2026-09-23: "the core's heartbeat is 19 minutes old... and then
that's all it tells you. There should be like a link afterwards to like
restart stuff... Everything should be one click."

So a sentence that names a problem carries what to do about it, and a
question a form asked carries the box that answers it."""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from aletheia import agenda, core, intercom, mission_control, needs_you, voice


class RestartHerCase(unittest.TestCase):
    def test_a_stale_heartbeat_carries_the_restart(self):
        now = dt.datetime(2026, 9, 23, 1, 0, tzinfo=dt.timezone.utc)
        head = mission_control.header({"state": "IDLE", "doing": ""}, now=now,
                                      core={"alive": True, "heartbeat_age_s": 19 * 60})
        self.assertIn("heartbeat", head["banner"])
        self.assertEqual(head["action"], {"label": "Restart her", "kind": "restart"})
        fine = mission_control.header({"state": "IDLE", "doing": ""}, now=now,
                                      core={"alive": True, "heartbeat_age_s": 30})
        self.assertEqual(fine["action"], {})

    def test_the_command_goes_through_the_code_update_door(self):
        calls = []
        with mock.patch.dict(core._RESTART_HOOK, {"fn": lambda changed: calls.append(changed)}), \
             mock.patch("threading.Timer") as timer:
            timer.return_value.start = lambda: timer.call_args[0][1]()
            self.assertTrue(core.request_restart("his tap"))
        self.assertEqual(len(calls), 1)
        self.assertIn("his tap", calls[0][0])

    def test_nothing_running_is_said_not_pretended(self):
        with mock.patch.dict(core._RESTART_HOOK, {"fn": None}):
            self.assertFalse(core.request_restart("a test"))
            with self.assertRaises(Exception) as caught:
                intercom.execute_command({"kind": "restart"}, {})
            self.assertIn("start her from the PC", str(caught.exception))

    def test_the_intercom_kind_restarts(self):
        with mock.patch("aletheia.core.request_restart", return_value=True) as ask:
            said = intercom.execute_command({"kind": "restart", "reason": "his tap"}, {})
        ask.assert_called_once_with("his tap")
        self.assertIn("back in about a minute", said)

    def test_no_model_and_no_agenda_may_say_it(self):
        self.assertIn("restart", intercom.PLANNER_FORBIDDEN)
        self.assertIn("restart", agenda.FORBIDDEN_KINDS)
        self.assertIn("restart", agenda.REFUSAL_REASON)

    def test_he_can_say_it(self):
        for said in ("thea restart yourself", "thea reboot yourself", "thea restart"):
            with self.subTest(said=said):
                self.assertEqual(voice.interpret(said)["command"]["kind"], "restart")
        for said in ("thea restart the music", "thea restart the job hunt"):
            with self.subTest(said=said):
                self.assertNotEqual((voice.interpret(said).get("command") or {}).get("kind"), "restart")


class AQuestionIsAnsweredOnItsRowCase(unittest.TestCase):
    def test_the_row_carries_the_question_verbatim(self):
        hunt = {"waiting_on_him": [{"id": "apply-3", "company": "Ramp", "job": "Account Manager",
                                    "questions": ["What is your percentage attainment to goal?"],
                                    "why": "only you know this", "at": "2026-09-23T00:00:00Z"}]}
        with mock.patch("aletheia.current_state.job_hunt", return_value=hunt):
            rows = needs_you._applications()
        self.assertEqual(rows[0]["kind"], "application")
        self.assertEqual(rows[0]["question"], "What is your percentage attainment to goal?")
        self.assertIn("Ramp asks", rows[0]["what"])
        # A decision row has no question; the field is still there, empty.
        self.assertEqual(needs_you._row(id="a", kind="approval", what="w", why="y",
                                        if_ignored="i")["question"], "")

    def test_the_page_answers_through_the_rooms_own_verb(self):
        from pathlib import Path
        js = (Path(__file__).resolve().parent.parent / "interface" / "thea-app.js").read_text(encoding="utf-8")
        self.assertIn('kind: "apply_answer"', js)
        self.assertIn("data-answer", js)
        self.assertIn('data-act', js)


class TheHealthLineCarriesItsClickCase(unittest.TestCase):
    """Six of `running.headline`'s sentences named an action and none carried
    one - and the line hid the banner's Restart button while it did."""
    def _state(self, **over):
        base = {"parts": [{"part": "supervisor", "up": True}, {"part": "core", "up": True},
                          {"part": "voice", "up": False}],
                "closed": False, "halted": False, "listening": False,
                "running_old_code": False, "update_stuck": None, "tasks": {}}
        base.update(over)
        return base

    def test_each_sentence_that_asks_carries_its_command(self):
        from aletheia import running
        with mock.patch("aletheia.running._by_design", side_effect=lambda st, p: p["part"] == "voice"):
            self.assertEqual(running.action(self._state(closed=True))["kind"], "open")
            self.assertEqual(running.action(self._state(halted=True))["kind"], "resume")
            self.assertEqual(running.action(self._state(running_old_code=True))["kind"], "restart")
            self.assertEqual(running.action(self._state())["kind"], "mic_on")
            self.assertEqual(running.action(self._state(listening=True)), {})
            # A stuck update is the one a restart would not fix: its button tries the pull now.
            self.assertEqual(running.action(self._state(update_stuck={"for_s": 4000, "waiting": 3}))["kind"], "update_now")
        nothing_up = [{"part": p["part"], "up": False} for p in self._state()["parts"]]
        for state in (self._state(closed=True, parts=nothing_up), self._state(halted=True), self._state()):
            with self.subTest(state=state):
                said = running.headline(state).lower()
                word = {"open": "open", "resume": "resume", "mic_on": "microphone"}[running.action(state)["kind"]]
                self.assertIn(word, said)

    def test_the_health_route_carries_it(self):
        from aletheia import core
        import json, threading, urllib.request
        srv = core.make_server(port=0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            got = json.load(urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/api/health", timeout=20))
        finally:
            srv.shutdown()
        self.assertIn("action", got)
        self.assertIsInstance(got["action"], dict)


class ANoticeCarriesItsClickCase(unittest.TestCase):
    def test_a_notice_may_carry_one_validated_command(self):
        from aletheia import notifications
        made = notifications.publish("Overdue: call the plumber", "was due Tue 09:00",
                                     action={"label": "Done", "kind": "task_done",
                                             "args": {"which": "call the plumber"}},
                                     dedupe_key="test-one-click-notice")
        self.assertEqual(made["action"], {"label": "Done", "kind": "task_done", "args": {"which": "call the plumber"}})
        with self.assertRaises(ValueError):
            notifications.action_shape({"label": "x", "kind": "not_a_kind", "args": {}})
        with self.assertRaises(ValueError):
            notifications.action_shape({"label": "x", "kind": "halt", "args": {}})

    def test_the_overdue_task_and_the_part_time_job_carry_theirs(self):
        from aletheia import runtime
        record = {"id": "apply-5", "state": "AWAITING_YOU", "approval": "apply-5-submit",
                  "job_title": "Ops (part-time)", "company": "Acme", "url": "https://x/5", "employment": "part-time"}
        with mock.patch("aletheia.apply_run.all_runs", return_value=[record]),              mock.patch("aletheia.policy.load", return_value={"state": "PENDING"}),              mock.patch("aletheia.apply_run.waits_for_his_ok", return_value="part-time"),              mock.patch("aletheia.notifications.publish") as publish:
            runtime.send_approved_applications()
        action = publish.call_args[1]["action"]
        self.assertEqual(action["kind"], "approve")
        self.assertEqual(action["args"], {"id": "apply-5-submit"})


class AMissionCardCarriesItsClickCase(unittest.TestCase):
    def test_a_proposed_plan_offers_yes_and_his_step_offers_done(self):
        from aletheia import mission_control
        now = dt.datetime(2026, 9, 23, 1, 0, tzinfo=dt.timezone.utc)
        proposed = {"slug": "barkly", "title": "Barkly", "goal": "g", "state": "proposed",
                    "steps": [{"n": 1, "text": "do x", "owner": "caleb", "state": "todo"}]}
        cards = mission_control.generic_missions(mission_record=None, plans=[proposed], tasks=[], now=now)
        card = next(c for c in cards if c["id"] == "plan:barkly")
        self.assertEqual(card["action"]["kind"], "plan_set")
        self.assertEqual(card["action"]["args"]["state"], "open")
        opened = dict(proposed, state="open")
        cards = mission_control.generic_missions(mission_record=None, plans=[opened], tasks=[], now=now)
        card = next(c for c in cards if c["id"] == "plan:barkly")
        if card["status"] == "NEEDS YOU":
            self.assertEqual(card["action"], {"label": "I did it", "kind": "plan_step",
                                              "args": {"slug": "barkly", "n": 1, "state": "done"}})

    def test_a_signal_banner_carries_its_action_into_the_header(self):
        from aletheia import mission_control
        now = dt.datetime(2026, 9, 23, 1, 0, tzinfo=dt.timezone.utc)
        head = mission_control.header({"state": "IDLE", "doing": ""}, now=now,
                                      core={"alive": True, "heartbeat_age_s": 10},
                                      signals=[{"what": "apply loop", "ok": False,
                                                "banner": "The job hunt looks stopped: x.",
                                                "action": {"label": "Start it again", "kind": "apply_campaign", "args": {}}}])
        self.assertEqual(head["banner"], "The job hunt looks stopped: x.")
        self.assertEqual(head["action"]["kind"], "apply_campaign")


if __name__ == "__main__":
    unittest.main()
