"""Fifty-second sandbox batch, 2026-10-05: the job hunt, asked about.

    > what jobs are you looking at           [5.5s] a model
    > why haven't you applied to anything    [16.5s] a model, which then guessed
    > skip jobs at amazon                    [4.6s] a plan, an approval

And two things the full suite found on a frozen copy: "how fresh is the
fleet reading" had two claimants, and a Core stopped with shutdown() alone
stayed in SERVERS, so "how long have you been up" answered from the test
process's own start.
"""
import unittest
from unittest import mock

from aletheia import apply_forever, campaign, core, current_state, quick, reasoner, standing, voice


class TheHuntByVoice(unittest.TestCase):
    def test_looking_at_and_a_company_to_skip(self):
        self.assertEqual(quick.match("what jobs are you looking at")[0], "hunting_for")
        self.assertEqual(quick.match("what are you going after")[0], "hunting_for")
        for said in ("skip jobs at amazon", "don't apply to anything at Amazon", "no amazon jobs", "avoid amazon"):
            d = voice.interpret(f"thea {said}")
            self.assertEqual(d["command"]["kind"], "preference_set", said)
            self.assertEqual(d["command"]["field"], "work_not_wanted", said)
            self.assertEqual(d["command"]["value"].casefold(), "amazon", said)
        self.assertEqual(voice.interpret("thea skip this song")["command"].get("kind"), "music")

    def test_why_nothing_was_sent_is_facts_from_the_stores(self):
        hunt = {"readable": True, "running": False,
                "today": {"discovered": 0, "qualified": 0, "attempted": 0, "ready": 0, "sent": 0, "blocked": 0, "replies": 0},
                "blockers": []}
        with mock.patch.object(current_state, "job_hunt", return_value=hunt), \
                mock.patch.object(apply_forever, "paused", return_value=None), \
                mock.patch.object(campaign, "read_resume", side_effect=FileNotFoundError("none")), \
                mock.patch.object(reasoner, "resting_until", return_value=None):
            said = quick.answer("why haven't you applied to anything")
        self.assertTrue(said.startswith("Nothing sent today. "), said)
        self.assertIn("I can't find a resume on this PC", said)
        self.assertIn("no batch is running", said)
        self.assertIn("nothing was found today", said)
        hunt["today"].update({"discovered": 4, "qualified": 2, "attempted": 2, "ready": 2})
        hunt["running"] = True
        with mock.patch.object(current_state, "job_hunt", return_value=hunt), \
                mock.patch.object(apply_forever, "paused", return_value={"reason": "you said stop"}), \
                mock.patch.object(campaign, "read_resume", return_value=("/r.docx", "text")), \
                mock.patch.object(reasoner, "resting_until", return_value=None), \
                mock.patch.object(standing, "jobs_status", return_value={"granted": False}):
            said = quick.answer("why haven't you applied to anything")
        self.assertIn("the job hunt is paused - you said stop", said)
        self.assertIn("2 applications are filled and waiting on your yes", said)
        self.assertIn("standing jobs on", said)
        hunt["today"]["sent"] = 3
        with mock.patch.object(current_state, "job_hunt", return_value=hunt):
            self.assertTrue(quick.answer("why haven't you applied to anything").startswith("I did - 3 applications sent today."))


class TwoThingsTheSuiteFound(unittest.TestCase):
    def test_one_claimant_per_fleet_question(self):
        self.assertEqual(quick.match("how fresh is the fleet reading")[0], "fleet_read_at")
        self.assertEqual(quick.match("how old is the pulse")[0], "pulse_age")

    def test_a_shut_down_core_is_not_a_running_one(self):
        import threading
        srv = core.OneCoreServer(("127.0.0.1", 0), core.Handler)
        worker = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        worker.start()
        try:
            core.SERVERS.append(srv)
            srv.shutdown()                      # the way most of the suite stops a Core
            worker.join(timeout=5)
            self.assertNotIn(srv, core.SERVERS)
        finally:
            srv.server_close()
            self.assertNotIn(srv, core.SERVERS)


if __name__ == "__main__":
    unittest.main()
