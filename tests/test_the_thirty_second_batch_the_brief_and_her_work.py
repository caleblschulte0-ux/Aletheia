"""Thirty-second sandbox batch, 2026-10-05: the brief, her work, her workers.

    > read me the morning brief / what's in today's brief   [3.7s] [4.1s] models,
                                                            for the answer "give
                                                            me the brief" gives in 0.0s
    > stop working                     the planner: "Pause all my background work"
    > what agents are running          [6.0s] "I can't see a live list"
    > how long have you been working   [5.0s] a model
    > what did you look up today       [8.0s] a model
    > summarize my day                 "Nothing of mine is running ... something
                                       went wrong" - said by the Core itself
"""
import datetime as dt
import sys
import types
import unittest
from unittest import mock

from aletheia import quick, voice


class TheBriefAndTheWorkers(unittest.TestCase):
    def test_the_phrasings_reach_the_kinds(self):
        for said in ("read me the morning brief", "what's in today's brief", "today's brief"):
            self.assertEqual(voice.interpret(said)["command"], {"kind": "brief"}, said)
        for said in ("what agents are running", "any workers running"):
            self.assertEqual(voice.interpret(said)["command"], {"kind": "agents"}, said)

    def test_stop_working_asks_for_the_one_word(self):
        out = voice.interpret("stop working")
        self.assertIsNone(out["command"])
        self.assertIn("'halt'", out["say"])
        self.assertIn("'stop applying'", out["say"])


class HerOwnWork(unittest.TestCase):
    def test_the_work_session_or_none(self):
        with mock.patch("aletheia.work_session.status", return_value={"active": True, "actions_left": 7, "expires": "2030-01-01T10:00:00+00:00"}):
            said = quick.answer("how long have you been working")
        self.assertTrue(said.startswith("I'm in a work session with 7 actions left, until "), said)
        with mock.patch("aletheia.work_session.status", return_value={"active": False}), \
             mock.patch("aletheia.quick._uptime", return_value="Up 2 hours, since today at 7 pm."):
            self.assertEqual(quick.answer("are you in a work session"), "I'm not in a work session. Up 2 hours, since today at 7 pm.")

    def test_what_she_looked_up_is_the_journal(self):
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        rows = [{"ts": now, "kind": "event", "subject": "research", "text": "http search gave no usable results for 'capital of peru'; trying the driven engines"},
                {"ts": now, "kind": "action", "subject": "browser:read", "text": "read https://example.com/x — Example Domain"}]
        with mock.patch("aletheia.recollection._read_journal", return_value=(rows, True)):
            self.assertEqual(quick.answer("what did you look up today"), "Today I searched for capital of peru and read Example Domain.")
        with mock.patch("aletheia.recollection._read_journal", return_value=([], True)):
            self.assertEqual(quick.answer("did you look anything up today"), "Nothing looked up today.")

    def test_the_core_answering_is_running(self):
        fake = types.SimpleNamespace(SERVERS=[object()], PROCESS_STARTED_AT=0)
        with mock.patch("aletheia.running.headline", return_value="Nothing of mine is running, and you haven't closed me — so something went wrong."), \
             mock.patch("aletheia.running.snapshot", return_value={}), \
             mock.patch.dict(sys.modules, {"aletheia.core": fake}):
            self.assertEqual(quick._running(), "The Core is running - I'm it.")


if __name__ == "__main__":
    unittest.main()
