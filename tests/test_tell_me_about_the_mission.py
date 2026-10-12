"""Talked to her, 2026-10-12: with the mission running, "tell me about the move plan" looked for a
note about it, and "what's the move plan", "how's the reboot", "what are you working on for the
move" and "why is the move plan stuck" all went to a model. The mission answers them."""

from tests import test_his_mission_rehearsed as rehearsed


class TellMeAboutTheMission(rehearsed.HisMissionRunsWithoutHim):

    def setUp(self):
        super().setUp()
        rehearsed.pg.add_words(self.pid, "also start planning a move somewhere warm", via="operator-voice",
                               now=rehearsed.NOW)

    def test_asking_about_the_mission_is_its_status(self):
        from aletheia import voice
        for asked in ("tell me about the move plan", "what's the move plan", "what is project reboot",
                      "how's the reboot", "what are you working on for the move"):
            self.assertEqual(voice._interpret(asked)["command"], {"kind": "missions", "which": self.pid}, asked)

    def test_asking_what_is_stuck_is_its_waits(self):
        from aletheia import voice
        for asked in ("is anything stuck on the move plan", "why is the move plan stuck"):
            self.assertEqual(voice._interpret(asked)["command"],
                             {"kind": "missions", "about": "waiting", "which": self.pid}, asked)

    def test_other_subjects_are_left_alone(self):
        from aletheia import voice
        self.assertEqual(voice._interpret("tell me about dana")["command"]["kind"], "recall")
        for asked in ("how's the trader", "what's the plan", "what's the weather"):
            self.assertNotEqual(((voice._interpret(asked) or {}).get("command") or {}).get("kind"), "missions", asked)
