"""Every time he had to do something a normal person should not is counted.

The seamless brief, 2026-09-21: "Friction ledger: every time Caleb had to
do something a normal person shouldn't, record it, and treat it as a
defect." A ledger with a writer and no reader would make her deny it
exists, so both readers are held here too.
"""
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from aletheia import friction, quick


class FrictionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": self.tmp.name})
        env.start(); self.addCleanup(env.stop)

    def test_a_row_is_written_in_his_words_and_ranked(self):
        self.assertIsNotNone(friction.record("question", "which sister?", asked="text my sister"))
        self.assertIsNotNone(friction.record("question", "what 'keep going' meant", asked="keep going"))
        self.assertIsNotNone(friction.record("restart", "he started her from the task"))
        rows = friction.ranked()
        self.assertEqual([(r["kind"], r["times"]) for r in rows], [("question", 2), ("restart", 1)])
        self.assertEqual(rows[0]["examples"][-1], "what 'keep going' meant")

    def test_an_unknown_kind_or_empty_row_is_refused_not_written(self):
        self.assertIsNone(friction.record("mystery", "x"))
        self.assertIsNone(friction.record("question", "   "))
        self.assertFalse(friction.path().exists())

    def test_it_is_private_state_never_the_repo(self):
        from aletheia.fleet import REPO_ROOT
        friction.record("sysadmin", "ran the bring-up")
        self.assertTrue(str(friction.path()).startswith(self.tmp.name))
        self.assertFalse(str(friction.path()).startswith(str(REPO_ROOT)))

    def test_spoken_says_nothing_recorded_as_that(self):
        said = friction.spoken()
        self.assertIn("Nothing I recorded", said)

    def test_spoken_counts_and_names_the_latest(self):
        friction.record("question", "which monitor did you mean")
        friction.record("question", "what 'keep going' meant")
        friction.record("sysadmin", "bring-up failed: git fetch failed")
        said = friction.spoken()
        self.assertTrue(said.startswith("3 times in 30 days"), said)
        self.assertIn("I asked you something 2 times", said)
        self.assertIn("keep going", said)
        self.assertIn("fix something yourself", said)

    def test_the_spoken_reader_is_in_the_fast_lane(self):
        friction.record("restart", "he started her from the task")
        for sentence in ("what have I had to do myself", "what have you been asking me",
                         "how often have I had to babysit you", "what's been annoying"):
            with self.subTest(sentence=sentence):
                said = quick.answer(sentence)
                self.assertIsNotNone(said, sentence)
                self.assertIn("start me", said)

    def test_the_command_line_records_and_lists(self):
        with redirect_stdout(StringIO()):
            self.assertEqual(friction.main(["record", "sysadmin", "bring-up failed: no git",
                                            "--source", "bring-up"]), 0)
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(friction.main([]), 0)
        self.assertIn("sysadmin", out.getvalue())
        self.assertIn("no git", out.getvalue())

    def test_an_old_row_is_history_not_friction(self):
        friction.record("repeat", "said it twice")
        rows = friction._load()
        rows[0]["at"] = "2020-01-01T00:00:00Z"
        friction.path().write_text(__import__("json").dumps(rows[0]) + "\n", encoding="utf-8")
        self.assertEqual(friction.ranked(), [])


class TheWritersAreReal(unittest.TestCase):
    """Rule zero: a store nothing writes to is theatre."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": self.tmp.name})
        env.start(); self.addCleanup(env.stop)

    def test_keep_going_with_no_context_is_a_question_counted(self):
        from aletheia import voice
        with mock.patch.object(voice, "_job_hunt_is_the_context", return_value=False):
            out = voice._interpret("keep going")
        self.assertIsNone(out["command"])
        self.assertEqual([r["kind"] for r in friction.ranked()], ["question"])
        self.assertEqual(friction.recent()[0]["asked"], "keep going")

    def test_a_lost_store_at_the_bring_up_is_counted(self):
        from aletheia import continuity
        before = {"private_root": self.tmp.name, "private_root_exists": True,
                  "stores": {"profile": {"said": "your profile", "files": 4}},
                  "local_ai_enabled": False, "python": None}
        snap = Path(self.tmp.name) / "before.json"
        snap.write_text(__import__("json").dumps(before), encoding="utf-8")
        with redirect_stdout(StringIO()):
            self.assertEqual(continuity.main(["verify", str(snap)]), 2)
        self.assertEqual([r["kind"] for r in friction.ranked()], ["lost"])
        self.assertIn("your profile", friction.recent()[0]["what"])

    def test_a_local_ai_that_did_not_answer_is_counted(self):
        from aletheia import local_ai, local_model_pool
        with mock.patch.object(local_model_pool, "smoke",
                               side_effect=local_model_pool.LocalPoolUnavailable("missing")), \
             redirect_stdout(StringIO()):
            self.assertEqual(local_ai.main(["activate"]), 1)
        self.assertEqual([r["kind"] for r in friction.ranked()], ["sysadmin"])

    def test_the_bring_up_records_its_own_failure(self):
        from aletheia.fleet import REPO_ROOT
        script = (REPO_ROOT / "scripts" / "bringup_windows.ps1").read_text(encoding="utf-8")
        catch = script[script.index("$failure = $_"):]
        self.assertIn("aletheia.friction record sysadmin", catch)
        self.assertLess(catch.index("aletheia.friction record"), catch.index("Restore-AletheiaCore"))

    def test_a_clarifying_question_from_the_planner_is_counted(self):
        from aletheia import brain, intents, journal, policy
        root = Path(self.tmp.name)
        with mock.patch.object(policy, "APPROVALS_DIR", root / "approvals"), \
             mock.patch.object(journal, "JOURNAL_PATH", root / "journal.jsonl"), \
             mock.patch.object(policy, "halted", return_value=None):
            provider = brain.Provider("stub", lambda text, ctx: {
                "intent": "clarify", "summary": "Which sister - Ana or Mia?", "steps": []})
            record = intents.propose("text my sister that I'm late", quote="", fleet={"repos": {}},
                                     provider=provider, registry={"capabilities": []})
        self.assertEqual(record.get("intent"), "clarify")
        rows = friction.recent()
        self.assertEqual(rows[0]["kind"], "question")
        self.assertEqual(rows[0]["what"], "Which sister - Ana or Mia?")
        self.assertEqual(rows[0]["asked"], "text my sister that I'm late")


if __name__ == "__main__":
    unittest.main()
