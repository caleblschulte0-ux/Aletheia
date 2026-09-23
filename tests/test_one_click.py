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


if __name__ == "__main__":
    unittest.main()
