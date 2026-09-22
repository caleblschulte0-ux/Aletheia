""""Stop applying for now" - the switch that did not exist.

With every frontier off (2026-09-22) the sentence went to the planner and
waited two minutes on her own model, because the job hunt had a start and
a keep-going and no stop. Not the kill switch: everything else of hers
keeps going, a batch already running finishes, and "start applying" lifts
it. And a follow-up word with nothing before it answers at once.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from aletheia import apply_forever, intercom, tools, voice


class TheSentenceIsHisSwitchCase(unittest.TestCase):
    def test_his_ways_of_saying_stop(self):
        for sentence, reason in (("thea stop applying for now", "for now"),
                                 ("Thea, pause the job hunt", ""),
                                 ("thea hold off on applications until tomorrow", "until tomorrow"),
                                 ("thea no more applications for today", "for today"),
                                 ("thea take a break from the job hunt", "")):
            with self.subTest(sentence=sentence):
                out = voice.interpret(sentence)
                self.assertEqual(out["command"]["kind"], "apply_pause", sentence)
                self.assertEqual(out["command"].get("reason", ""), reason)

    def test_stop_everything_is_still_the_kill_switch(self):
        self.assertEqual(voice.interpret("thea stop everything")["command"]["kind"], "halt")

    def test_the_planner_may_never_say_it(self):
        self.assertIn("apply_pause", intercom.PLANNER_FORBIDDEN)
        self.assertIn("apply_pause", tools.SWITCH_KINDS)


class TheLoopHonoursItCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": self.tmp.name})
        env.start(); self.addCleanup(env.stop)
        self.addCleanup(self.tmp.cleanup)
        journal = mock.patch("aletheia.journal.append")
        journal.start(); self.addCleanup(journal.stop)

    def test_paused_starts_no_batch_and_keeps_its_beat(self):
        started = []
        apply_forever.pause("for now", via="test")
        self.assertEqual(apply_forever.paused()["reason"], "for now")
        with mock.patch.object(apply_forever.campaign, "running", return_value=None):
            out = apply_forever.once(starter=lambda **kw: started.append(1) or {"started": True})
        self.assertFalse(out["started"])
        self.assertEqual(out["paused"], "for now")
        self.assertEqual(started, [])

    def test_start_applying_lifts_it(self):
        apply_forever.pause("for now", via="test")
        self.assertTrue(apply_forever.resume_hunt(via="test"))
        self.assertIsNone(apply_forever.paused())
        self.assertFalse(apply_forever.resume_hunt(via="test"))

    def test_the_intercom_sets_it_and_the_campaign_lifts_it(self):
        with mock.patch("aletheia.campaign.running", return_value={"pid": 7}):
            said = intercom.execute_command({"kind": "apply_pause", "reason": "for today"}, {"repos": {}},
                                            quote="stop applying for today")
        self.assertIn("no more applications", said)
        self.assertIn("finishes first", said)
        self.assertEqual(apply_forever.paused()["reason"], "for today")
        with mock.patch("aletheia.campaign.start", return_value={"started": True, "pid": 9}), \
             mock.patch("aletheia.campaign.started_words", return_value="Started."), \
             mock.patch.object(intercom, "rehearsing", return_value=False):
            said = intercom.execute_command({"kind": "apply_campaign"}, {"repos": {}}, quote="start applying")
        self.assertTrue(said.startswith("Back on it."))
        self.assertIsNone(apply_forever.paused())

    def test_the_status_line_says_it_is_paused(self):
        from aletheia import quick
        apply_forever.pause("", via="test")
        with mock.patch("aletheia.current_state.job_hunt_words", return_value="No applications today."):
            said = quick.answer("how is the job hunt going")
        self.assertIn("paused since you said stop", said)


class AFollowUpWithNothingBeforeItCase(unittest.TestCase):
    def test_the_other_one_with_an_empty_thread_answers_at_once(self):
        with mock.patch("aletheia.converse.recent", return_value=[]):
            out = voice.interpret("thea the other one")
        self.assertIsNone(out["command"])
        self.assertIn("Nothing came before this", out["say"])

    def test_with_a_thread_it_still_goes_on_to_be_understood(self):
        with mock.patch("aletheia.converse.recent", return_value=[{"he_asked": "add a task", "she_said": "ok"}]):
            out = voice.interpret("thea the other one")
        self.assertNotIn("Nothing came before this", str(out.get("say") or ""))


if __name__ == "__main__":
    unittest.main()
