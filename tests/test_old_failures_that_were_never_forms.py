"""A page that was never a form is not a failure, written before that was true.

Until 2026-09-22 `stage` recorded a job-alert list or a page asking nothing
about him as FAILED. FAILED is not settled, so discovery kept offering those
pages back, and live 2026-10-07 51 of the funnel's 59 failures read "other".
"""
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from aletheia import apply_run, hunt_funnel, runtime

OLD = {
    "apply-a": "a talent-network / job-alert signup, not an application",
    "apply-b": ("nothing on this page asks for his name, email or phone, so it is not an "
                "application form - a bot check or a contact page looks like this"),
    "apply-c": ("there is no application form on this page to fill - the posting "
                "may have been taken down or the link was wrong"),
}


class OldNotAFormFailuresAreClosed(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = pathlib.Path(tmp.name)
        for p in (mock.patch.object(apply_run, "staged_dir", lambda: self.dir),
                  mock.patch("aletheia.apply_run.journal.append")):
            p.start()
            self.addCleanup(p.stop)

    def write(self, run_id, **record):
        record = {"id": run_id, "url": f"https://boards.example/{run_id}",
                  "staged_at": "2026-09-20T10:00:00Z", **record}
        (self.dir / f"{run_id}.json").write_text(json.dumps(record), encoding="utf-8")

    def test_the_old_sentences_close_as_not_a_form_on_their_own_day(self):
        for run_id, why in OLD.items():
            self.write(run_id, state="FAILED", failure=why)
        self.assertEqual(apply_run.settle_old_not_a_form(), 3)
        for run_id, why in OLD.items():
            record = apply_run.load_run(run_id)
            self.assertEqual(record["state"], apply_run.CLOSED)
            self.assertEqual(apply_run.closure_kind(record), apply_run.NOT_A_FORM)
            self.assertEqual(record["closed_because"], why)
            # Closed on the day it happened, not today: not a burst of closures.
            self.assertEqual(record["closed_at"], "2026-09-20T10:00:00Z")
        self.assertFalse(apply_run.all_runs("FAILED"))
        # Settled now: discovery leaves the pages out.
        urls, _ = apply_run.settled_index()
        self.assertIn("https://boards.example/apply-a", urls)

    def test_a_real_failure_and_a_pressed_one_are_left_alone(self):
        self.write("apply-x", state="FAILED", failure="TimeoutError: page took too long")
        self.write("apply-y", state="FAILED", failure=OLD["apply-b"], pressed_at="2026-09-20T10:01:00Z")
        self.assertEqual(apply_run.settle_old_not_a_form(), 0)
        self.assertEqual(apply_run.load_run("apply-x")["state"], "FAILED")
        self.assertEqual(apply_run.load_run("apply-y")["state"], "FAILED")

    def test_the_funnel_counts_them_as_closures_not_failures(self):
        for run_id, why in OLD.items():
            self.write(run_id, state="FAILED", failure=why)
        apply_run.settle_old_not_a_form()
        import datetime as dt
        out = hunt_funnel.counts(apply_run.all_runs(),
                                 now=dt.datetime(2026, 10, 7, 16, tzinfo=dt.timezone.utc))
        self.assertEqual(out["waiting"]["failed"], 0)
        self.assertEqual(sum(v for k, v in out["waiting"]["closed"].items() if k.startswith("not_a_form")), 3)

    def test_the_beat_settles_them_once(self):
        self.write("apply-a", state="FAILED", failure=OLD["apply-a"])
        with mock.patch.object(runtime, "_SETTLED_OLD", {"done": False}), \
                mock.patch("aletheia.browser_mission.leave_walls", return_value=[]), \
                mock.patch.object(apply_run, "settle_old_not_a_form",
                                  wraps=apply_run.settle_old_not_a_form) as settle:
            runtime.leave_walls()
            runtime.leave_walls()
        self.assertEqual(settle.call_count, 1)
        self.assertEqual(apply_run.load_run("apply-a")["state"], apply_run.CLOSED)


if __name__ == "__main__":
    unittest.main()
