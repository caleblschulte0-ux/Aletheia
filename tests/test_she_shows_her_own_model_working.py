"""He can SEE her own model working, and what it is doing, while it grinds.

His words, 2026-09-21: the local model will never be off, only slow, and
he needs "a better way for me to see it's working and what it's doing ...
mainly when it's just the local model up so I can make sure it's working
since it is a lot slower." So every local call leaves a mark while it runs
and a line when it ends; "what are you doing", the Right now panel, the
ask box and the room all read them. Held here with no Ollama anywhere.
"""
import datetime as dt
import os
import tempfile
import unittest
from unittest import mock

from aletheia import current_state, local_model_pool, mission_control, model_pool_config, speech


class BusyAndRecentCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": self.tmp.name})
        env.start(); self.addCleanup(env.stop)
        model_pool_config.save_settings(enabled=True)
        current_state.forget_cache()

    def _run(self, infer):
        with mock.patch.object(local_model_pool, "room_for_role", return_value={"fits": True}), \
             mock.patch("aletheia.local_brain.infer_json", side_effect=infer), \
             mock.patch("aletheia.training_data.record_turn", return_value="turn"):
            return local_model_pool.run_json("system", "add a task to call the plumber", role="fast")

    def test_the_mark_is_there_while_it_runs_and_gone_after(self):
        seen = {}
        def infer(system, text, *, context, config, should_yield=None):
            seen["busy"] = local_model_pool.busy()
            return {"ok": True}
        self.assertIsNone(local_model_pool.busy())
        self._run(infer)
        self.assertEqual(seen["busy"]["what"], "add a task to call the plumber")
        self.assertEqual(seen["busy"]["role"], "fast")
        self.assertIn("elapsed_s", seen["busy"])
        self.assertIsNone(local_model_pool.busy())

    def test_the_mark_is_cleared_even_when_the_model_fails(self):
        def infer(*a, **k):
            raise local_model_pool.local_brain.LocalBrainUnavailable("timed out")
        with self.assertRaises(local_model_pool.LocalPoolUnavailable):
            self._run(infer)
        self.assertIsNone(local_model_pool.busy())
        recent = local_model_pool.recent()
        self.assertEqual(recent["today"], 1)
        self.assertEqual(recent["today_ok"], 0)
        self.assertFalse(recent["last_ok"])

    def test_a_stale_mark_from_a_crash_reads_as_nothing(self):
        local_model_pool._mark_busy("fast", "m", "x", "attended")
        from aletheia import stateio
        old = stateio.read_json(local_model_pool._busy_path())
        old["started_at"] = "2020-01-01T00:00:00Z"
        stateio.write_json_atomic(local_model_pool._busy_path(), old)
        self.assertIsNone(local_model_pool.busy())

    def test_recent_counts_answers_and_the_typical_time(self):
        for s in (40, 90, 60):
            local_model_pool._remember_run("fast", s * 1000, True, "x")
        local_model_pool._remember_run("fast", 5000, False, "y")
        recent = local_model_pool.recent()
        self.assertEqual(recent["today"], 4)
        self.assertEqual(recent["today_ok"], 3)
        self.assertEqual(recent["typical_s"], 60.0)
        self.assertEqual(recent["last_s"], 5.0)

    def test_the_room_and_the_ask_box_hear_that_it_is_her_own_model(self):
        local_model_pool._remember_run("fast", 70000, True, "x")
        lines = []
        def infer(*a, **k):
            return {"ok": True}
        with mock.patch("aletheia.followups.report", side_effect=lambda line: lines.append(line) or True):
            self._run(infer)
        self.assertEqual(lines, ["Thinking with my own model, which is slower, usually about a minute."])

    def test_background_work_says_nothing_to_the_room(self):
        lines = []
        def infer(*a, **k):
            return {"ok": True}
        with mock.patch.object(local_model_pool, "room_for_role", return_value={"fits": True}), \
             mock.patch("aletheia.local_brain.infer_json", side_effect=infer), \
             mock.patch("aletheia.training_data.record_turn", return_value="turn"), \
             mock.patch("aletheia.followups.report", side_effect=lambda line: lines.append(line) or True):
            local_model_pool.run_json("system", "draft it", role="fast",
                                      attention=local_model_pool.BACKGROUND)
        self.assertEqual(lines, [])


class WhatAreYouDoingCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": self.tmp.name})
        env.start(); self.addCleanup(env.stop)
        current_state.forget_cache()
        self.addCleanup(current_state.forget_cache)

    def test_agent_says_thinking_with_her_own_model_and_how_long(self):
        local_model_pool._remember_run("fast", 60000, True, "x")
        local_model_pool._mark_busy("fast", "m", "add a task to call the plumber", "attended")
        with mock.patch("aletheia.policy.halted", return_value=None), \
             mock.patch("aletheia.closed.is_closed", return_value=False):
            block = current_state.agent(hunt={"readable": True, "thinking": current_state.thinking()},
                                        browsing={"active": False}, sessions={})
        self.assertEqual(block["state"], "THINKING")
        self.assertIn("thinking with my own model about “add a task to call the plumber”", block["step"])
        self.assertIn("so far", block["step"])
        self.assertIn("usually about a minute", block["step"])
        said = current_state.agent_words(block)
        self.assertTrue(said.startswith("I'm thinking about thinking with my own model") or
                        said.startswith("I'm thinking about"), said)

    def test_brains_words_in_each_state(self):
        base = {"claude": {"resting_until": None}, "codex": {"resting_until": None},
                "local": {"allowed": True, "why": "ok", "busy": None,
                          "recent": {"typical_s": 55.0, "today_ok": 3}}}
        said = current_state.brains_words(base)
        self.assertEqual(said, "Thinking with the big models; my own model is ready as backup, "
                               "usually about a minute an answer. 3 answers from it today.")
        out = dict(base, claude={"resting_until": "2026-09-21T16:40:00Z"},
                   codex={"resting_until": "2026-09-21T16:40:00Z", "why": "out"})
        out["local"] = dict(base["local"], busy={"what": "add a task", "elapsed_s": 48})
        said = current_state.brains_words(out)
        self.assertIn("so I'm thinking with my own model: slower, usually about a minute an answer.", said)
        self.assertIn("Working on “add a task” now, 48 seconds in.", said)
        off = dict(out); off["local"] = {"allowed": False, "why": "my own model is not running",
                                          "busy": None, "recent": {}}
        said = current_state.brains_words(off)
        self.assertIn("my own model is not running; I start it myself", said)
        self.assertIn("Nobody can think", said)
        for brand in ("Claude", "ChatGPT", "qwen", "ollama"):
            self.assertNotIn(brand, said)

    def test_the_header_carries_it_to_the_page(self):
        now = dt.datetime(2026, 9, 21, 15, 0, tzinfo=dt.timezone.utc)
        h = mission_control.header({"state": "IDLE"}, now=now, core={"heartbeat_age_s": 5, "alive": True},
                                   brains="Thinking with the big models; my own model is ready as backup.")
        self.assertEqual(h["brains"], "Thinking with the big models; my own model is ready as backup.")
        self.assertIn("brains", current_state.sections(fresh=True))


class AboutSecondsCase(unittest.TestCase):
    def test_it_says_it_the_way_a_person_does(self):
        for s, said in ((5, "under 10 seconds"), (30, "about 30 seconds"), (48, "about 50 seconds"),
                        (70, "about a minute"), (95, "about a minute and a half"),
                        (150, "about 2 and a half minutes"), (200, "about 3 minutes"),
                        (600, "about 10 minutes"), (0, ""), (None, "")):
            self.assertEqual(speech.about_seconds(s), said, s)


if __name__ == "__main__":
    unittest.main()
