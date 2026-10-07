"""The funnel says what each batch did with the openings it was handed.

Live 2026-10-07: 13 found for the day where mid-September days said forty
and more, and nothing said whether the boards ran dry, the fit judge
turned them away, the angle called them weak shots, or the per-employer
limit held them. Counts only: the file is public.
"""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import hunt_funnel

NOW = dt.datetime(2026, 10, 7, 15, 0, tzinfo=dt.timezone.utc)


def result(**parts):
    base = {k: [] for k in ("ready", "blocked", "failed", "needs_account",
                            "passed_over", "duplicates", "later")}
    base.update(parts)
    return base


class WhatBatchesDid(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "tallies.json"

    def test_a_batch_is_kept_as_counts_and_never_its_names(self):
        hunt_funnel.note_batch(result(
            ready=[{"url": "https://acme.example/1", "company": "Acme"}],
            passed_over=[{"url": "u2", "title": "AE - Acme", "why": "wants 5 years"},
                         {"url": "u3", "title": "AM - Acme", "why": "a weak shot: no pair"}],
            duplicates=[{"url": "u4", "title": "x", "why": "the same job is already applied for or waiting"},
                        {"url": "u5", "title": "y", "why": "Acme has had 3 applications this month"}],
            later=[{"url": "u6"}]), offered=20, now=NOW, path=self.path)
        rows = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 1)
        self.assertNotIn("acme", json.dumps(rows).casefold())
        tally = rows[0]
        self.assertEqual(tally["offered"], 20)
        self.assertEqual(tally["ready"], 1)
        self.assertEqual(tally["not_realistic"], 1)
        self.assertEqual(tally["weak_shot"], 1)
        self.assertEqual(tally["duplicate"], 1)
        self.assertEqual(tally["employer_full"], 1)
        self.assertEqual(tally["unjudged"], 1)

    def test_a_job_passed_over_is_counted_by_the_rule_that_did_it(self):
        hunt_funnel.note_batch(result(passed_over=[
            {"url": "u1", "why": "it asks for 7+ years of experience"},
            {"url": "u2", "why": "it is a sales job, and he does not want sales"},
            {"url": "u3", "why": "Acme wants a CPA and his resume shows none"},
            {"url": "u4", "why": "not realistic: it requires a CDL license"},
            {"url": "u5", "why": "closed as not realistic"},
            {"url": "u6", "why": "a weak shot: no pair"}]), now=NOW, path=self.path)
        tally = json.loads(self.path.read_text(encoding="utf-8"))[0]
        self.assertEqual(tally["not_realistic"], 5)
        self.assertEqual(tally["weak_shot"], 1)
        self.assertEqual({k: v for k, v in tally.items() if k.startswith("unfit_")},
                         {"unfit_years": 1, "unfit_sales": 1, "unfit_model": 1,
                          "unfit_license": 1, "unfit_closed_before": 1})
        self.assertNotIn("acme", json.dumps(tally).casefold())

    def test_batches_sum_by_his_local_day_and_a_month_is_kept(self):
        old = NOW - dt.timedelta(days=40)
        hunt_funnel.note_batch(result(ready=[{}]), offered=5, now=old, path=self.path)
        hunt_funnel.note_batch(result(ready=[{}, {}]), offered=9, now=NOW, path=self.path)
        hunt_funnel.note_batch(result(failed=[{}]), offered=4, now=NOW, path=self.path)
        rows = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 2, "a batch older than the window is dropped on write")
        days = hunt_funnel.batches(rows, now=NOW)
        today = days["2026-10-07"]
        self.assertEqual(today["runs"], 2)
        self.assertEqual(today["offered"], 13)
        self.assertEqual(today["ready"], 2)
        self.assertEqual(today["unreachable"], 1)

    def test_a_tally_that_cannot_be_written_never_stops_the_hunt(self):
        blocked = Path(self.dir.name) / "a-file"
        blocked.write_text("x", encoding="utf-8")
        hunt_funnel.note_batch(result(), path=blocked / "tallies.json")

    def test_the_published_funnel_carries_the_batches(self):
        hunt_funnel.note_batch(result(ready=[{}]), offered=3, now=NOW, path=self.path)
        out = Path(self.dir.name) / "funnel.json"
        with mock.patch.object(hunt_funnel, "TALLIES_PATH", self.path), \
                mock.patch.object(hunt_funnel, "_LAST", {"at": -1e12}), \
                mock.patch("aletheia.apply_run.all_runs", return_value=[]):
            hunt_funnel.publish(now=NOW, path=out)
        published = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(published["batches"]["2026-10-07"]["offered"], 3)


if __name__ == "__main__":
    unittest.main()


class HowLongABatchTook(unittest.TestCase):
    """One batch that found one is either a sparse board or a batch that ran
    all afternoon; the minutes tell them apart."""

    def test_minutes_are_kept_and_summed_by_day(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "tallies.json"
            hunt_funnel.note_batch(result(ready=[{}]), offered=90, minutes=95.4, now=NOW, path=path)
            hunt_funnel.note_batch(result(), offered=10, minutes=12.2, now=NOW, path=path)
            rows = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual([r["minutes"] for r in rows], [95, 12])
            self.assertEqual(hunt_funnel.batches(rows, now=NOW)["2026-10-07"]["minutes"], 107)
