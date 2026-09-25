"""His interview hours are his to say (2026-09-24).

"Set my interview window to 2 to 4" went to nobody at the bottom rung and
had no verb at all. It is a kind now: his own sentence sets it, a planner
and a mission may never (a guess here books interviews at the wrong
time), and "what's my interview window" reads it back.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from aletheia import agenda, intercom, interviews, journal, voice


class TheSentence(unittest.TestCase):
    def test_bare_hours_read_as_interview_hours(self):
        self.assertEqual(voice._interview_hours("2", "4"), ("14:00", "16:00"))
        self.assertEqual(voice._interview_hours("9", "11"), ("09:00", "11:00"))
        self.assertEqual(voice._interview_hours("1", "2:30"), ("13:00", "14:30"))
        self.assertEqual(voice._interview_hours("10am", "noon"), ("10:00", "12:00"))
        self.assertIsNone(voice._interview_hours("4", "2"), "the end must follow the start")

    def test_his_phrasings_set_it_and_the_zone_travels(self):
        self.assertEqual(voice.interpret("thea set my interview window to 2 to 4")["command"],
                         {"kind": "interview_window_set", "start": "14:00", "end": "16:00"})
        self.assertEqual(voice.interpret("thea I can do interviews from 9 to 11 eastern")["command"],
                         {"kind": "interview_window_set", "start": "09:00", "end": "11:00", "timezone": "America/New_York"})
        self.assertEqual(voice.interpret("thea what's my interview window")["command"], {"kind": "interview_status"})


class OnlyHisWordReachesIt(unittest.TestCase):
    def test_forbidden_to_planners_and_missions(self):
        self.assertIn("interview_window_set", intercom.PLANNER_FORBIDDEN)
        self.assertIn("interview_window_set", agenda.FORBIDDEN_KINDS)
        self.assertEqual(intercom.tier("interview_window_set"), intercom.TIER_ROUTINE)
        self.assertEqual(intercom.tier("interview_status"), intercom.TIER_READ)


class TheStoreMoves(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": tmp.name})
        env.start(); self.addCleanup(env.stop)
        p = mock.patch.object(journal, "append")
        p.start(); self.addCleanup(p.stop)

    def test_set_then_read(self):
        said = intercom.execute_command({"kind": "interview_window_set", "start": "14:00", "end": "16:00"}, {}, quote="t")
        self.assertTrue(said.startswith("Interviews go 2 PM to 4 PM Central on weekdays now"), said)
        self.assertEqual(interviews.status()["window"]["start"], "14:00")
        self.assertIn("2 PM to 4 PM Central", intercom.execute_command({"kind": "interview_status"}, {}, quote="t"))
        with self.assertRaises(intercom.act.Refused):
            intercom.execute_command({"kind": "interview_window_set", "start": "16:00", "end": "14:00"}, {}, quote="t")


if __name__ == "__main__":
    unittest.main()
