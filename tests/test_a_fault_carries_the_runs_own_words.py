"""A red workflow's fault carries what the run itself said.

"Daily failed 11 hours ago" was the whole fault on his page (2026-09-24)
while the run had annotated itself: "partial day (4 uploaded) - run is
RED for repair visibility, but a held/quarantined video is the gate
working, not an error". The pulse reads a failed run's first warning or
error annotation - two extra reads, only on a failure, never a reason the
pulse fails - and the fault sentence says it.
"""
from __future__ import annotations

import unittest

from aletheia import faults, pulse


class _Client(pulse.GitHubSource):
    def __init__(self, answers: dict, *, boom: set[str] = frozenset()):
        self.owner = "o"
        self.answers = answers
        self.boom = set(boom)
        self.calls: list[str] = []

    def _get(self, path: str):
        self.calls.append(path)
        for key, value in self.answers.items():
            if key in path:
                if key in self.boom:
                    raise OSError("api down")
                return value
        raise AssertionError(f"unexpected read {path}")


RUN = {"workflow_runs": [{"id": 77, "status": "completed", "conclusion": "failure",
                          "updated_at": "2026-09-24T19:50:00Z", "html_url": "https://example.invalid/77"}]}
JOBS = {"jobs": [{"id": 900, "conclusion": "failure"}]}
NOTES = [{"annotation_level": "warning", "message": "Process completed with exit code 1."},
         {"annotation_level": "warning",
          "message": "partial day (4 uploaded) — run is RED for repair visibility, but a held/quarantined video is the gate working, not an error"}]


class TheRunsOwnWordsReachTheRow(unittest.TestCase):
    def test_a_failed_run_carries_its_first_real_annotation(self):
        client = _Client({"/runs?per_page=1": RUN, "/runs/77/jobs": JOBS, "/check-runs/900/annotations": NOTES})
        row = client.workflow_run("Shorts-pipeline", "daily.yml")
        self.assertEqual(row["conclusion"], "failure")
        self.assertTrue(row["said"].startswith("partial day (4 uploaded)"), row["said"])
        self.assertNotIn("Process completed", row["said"], "the generic line is not the run's words")

    def test_a_green_run_makes_no_extra_reads(self):
        green = {"workflow_runs": [{**RUN["workflow_runs"][0], "conclusion": "success"}]}
        client = _Client({"/runs?per_page=1": green})
        row = client.workflow_run("Shorts-pipeline", "daily.yml")
        self.assertNotIn("said", row)
        self.assertEqual(len(client.calls), 1)

    def test_a_second_read_that_fails_costs_the_words_not_the_pulse(self):
        client = _Client({"/runs?per_page=1": RUN, "/runs/77/jobs": JOBS}, boom={"/runs/77/jobs"})
        row = client.workflow_run("Shorts-pipeline", "daily.yml")
        self.assertEqual(row["conclusion"], "failure")
        self.assertNotIn("said", row)


class TheFaultSaysThem(unittest.TestCase):
    def test_the_sentence_carries_the_words_after_the_verdict(self):
        alert = {"repo": "shorts_pipeline", "failing": ["daily.yml"]}
        repo = {"workflows": {"daily.yml": {"conclusion": "failure", "updated_at": "2026-09-24T19:50:00Z",
                                            "said": "partial day (4 uploaded) — run is RED for repair visibility."}}}
        import datetime as dt
        said = faults.said(alert, repo, now=dt.datetime(2026, 9, 24, 21, 50, tzinfo=dt.timezone.utc))
        self.assertTrue(said.startswith("Daily failed 2 hours ago - partial day (4 uploaded)"), said)

    def test_without_the_words_the_sentence_is_as_it_was(self):
        alert = {"repo": "shorts_pipeline", "failing": ["daily.yml"]}
        repo = {"workflows": {"daily.yml": {"conclusion": "failure", "updated_at": "2026-09-24T19:50:00Z"}}}
        import datetime as dt
        said = faults.said(alert, repo, now=dt.datetime(2026, 9, 24, 21, 50, tzinfo=dt.timezone.utc))
        self.assertEqual(said, "Daily failed 2 hours ago.")


if __name__ == "__main__":
    unittest.main()
