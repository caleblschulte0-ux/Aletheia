"""An update must hand back what it was given, and say so when it did not.

The Windows bring-up updates the checkout in place, with his private state
inside it, and nothing checked afterwards that the state was still there.
`continuity.snapshot` before, `continuity.verify` after - and the bring-up
fails, in English, before it says "Core: UP" over an empty memory.
"""
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from aletheia import continuity, model_pool_config


class ContinuityCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "private"
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(self.root)})
        env.start(); self.addCleanup(env.stop)
        for name, files in (("profile", 2), ("jobs", 5), ("conversation", 1)):
            (self.root / name).mkdir(parents=True)
            for i in range(files):
                (self.root / name / f"{i}.json").write_text("{}", encoding="utf-8")

    def test_a_snapshot_counts_every_store_it_finds(self):
        snap = continuity.snapshot()
        self.assertTrue(snap["private_root_exists"])
        self.assertEqual({k: v["files"] for k, v in snap["stores"].items()},
                         {"profile": 2, "jobs": 5, "conversation": 1})
        self.assertEqual(snap["private_files"], 8)
        self.assertEqual(snap["stores"]["profile"]["said"], "your profile")

    def test_an_update_that_kept_everything_passes(self):
        before = continuity.snapshot()
        (self.root / "jobs" / "new.json").write_text("{}", encoding="utf-8")
        self.assertEqual(continuity.verify(before), [])

    def test_a_store_that_shrank_is_named_out_loud(self):
        before = continuity.snapshot()
        for p in (self.root / "jobs").iterdir():
            p.unlink()
        lost = continuity.verify(before)
        self.assertEqual(len(lost), 1)
        self.assertIn("job hunt records", lost[0])
        self.assertIn("5 files before", lost[0])

    def test_a_vanished_private_root_is_the_first_and_only_finding(self):
        before = continuity.snapshot()
        import shutil
        shutil.rmtree(self.root)
        lost = continuity.verify(before)
        self.assertEqual(len(lost), 1)
        self.assertIn("is gone", lost[0])

    def test_local_ai_turned_off_by_the_update_is_a_loss(self):
        model_pool_config.save_settings(enabled=True)
        before = continuity.snapshot()
        self.assertTrue(before["local_ai_enabled"])
        model_pool_config.save_settings(enabled=False)
        lost = continuity.verify(before)
        self.assertTrue(any("local AI" in line for line in lost), lost)

    def test_local_ai_that_was_off_stays_a_non_finding(self):
        before = continuity.snapshot()
        self.assertFalse(before["local_ai_enabled"])
        self.assertEqual(continuity.verify(before), [])

    def test_a_different_python_is_said(self):
        before = dict(continuity.snapshot(), python="C:/old/python.exe")
        lost = continuity.verify(before)
        self.assertTrue(any("different Python" in line for line in lost), lost)

    def test_the_command_line_round_trips_and_fails_closed(self):
        path = Path(self.tmp.name) / "before.json"
        with redirect_stdout(StringIO()):
            self.assertEqual(continuity.main(["snapshot", str(path)]), 0)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["private_files"], 8)
        with redirect_stdout(StringIO()):
            self.assertEqual(continuity.main(["verify", str(path)]), 0)
        for p in (self.root / "profile").iterdir():
            p.unlink()
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(continuity.main(["verify", str(path)]), 2)
        self.assertIn("LOST", out.getvalue())
        self.assertIn("your profile", out.getvalue())
        with redirect_stdout(StringIO()):
            self.assertEqual(continuity.main(["verify", str(path) + ".missing"]), 2)


if __name__ == "__main__":
    unittest.main()
