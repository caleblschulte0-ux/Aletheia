"""SpaceX, 2026-09-23: "you have exceeded our limit of 10 job applications
during a 30-day period". One employer gets a few of her best, not all of them."""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import apply_run

NOW = dt.datetime(2026, 10, 7, 12, tzinfo=dt.timezone.utc)


def ago(days):
    return (NOW - dt.timedelta(days=days)).isoformat()


class OneEmployerIsNotASpray(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        self.runs = d / "applications"
        self.sent = d / "applications-sent" / "already-sent.json"
        self.runs.mkdir()
        self.sent.parent.mkdir()
        for target, attr, value in (
                (apply_run, "staged_dir", lambda: self.runs),
                (apply_run, "sent_path", lambda: self.sent)):
            patch = mock.patch.object(target, attr, value)
            patch.start()
            self.addCleanup(patch.stop)
        apply_run._RUNS_CACHE["key"] = None
        self.addCleanup(lambda: apply_run._RUNS_CACHE.update(key=None))

    def record(self, rid, company, state, at, url=None):
        (self.runs / f"{rid}.json").write_text(json.dumps(
            {"id": rid, "company": company, "job_title": rid, "state": state,
             "staged_at": at, "url": url or f"https://jobs.example/{rid}"}))
        apply_run._RUNS_CACHE["key"] = None

    def test_three_this_month_leaves_the_employer_alone(self):
        self.sent.write_text(json.dumps({
            "https://jobs.example/a": {"company": "SpaceX", "at": ago(3), "job_title": "a"},
            "https://jobs.example/b": {"company": "spacex ", "at": ago(10), "job_title": "b"}}))
        self.record("c", "SpaceX", "AWAITING_YOU", ago(1))
        self.assertEqual(apply_run.employer_load("SpaceX", now=NOW), 3)
        why = apply_run.employer_full("SpaceX", now=NOW)
        self.assertIn("3 applications to SpaceX", why)

    def test_two_still_leaves_room_for_a_third(self):
        self.record("a", "Datadog", "SUBMITTED", ago(2))
        self.record("b", "Datadog", "AWAITING_YOU", ago(1))
        self.assertEqual(apply_run.employer_full("Datadog", now=NOW), "")

    def test_old_closed_and_failed_ones_do_not_count(self):
        self.sent.write_text(json.dumps({
            "https://jobs.example/old": {"company": "Okta", "at": ago(45)}}))
        self.record("x", "Okta", apply_run.CLOSED, ago(1))
        self.record("y", "Okta", "FAILED", ago(1))
        self.record("z", "Okta", "SUBMITTED", ago(2))
        self.assertEqual(apply_run.employer_load("Okta", now=NOW), 1)

    def test_one_application_said_twice_counts_once(self):
        url = "https://jobs.example/same"
        self.sent.write_text(json.dumps({url: {"company": "Affirm", "at": ago(2)}}))
        self.record("s", "Affirm", "SUBMITTED", ago(2), url=url)
        self.assertEqual(apply_run.employer_load("Affirm", now=NOW), 1)

    def test_no_name_is_no_limit(self):
        self.record("n", "", "SUBMITTED", ago(1))
        self.assertEqual(apply_run.employer_full("", now=NOW), "")


if __name__ == "__main__":
    unittest.main()
