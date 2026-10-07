"""A site that refused her twice today refuses the third; leave it alone.

Live 2026-09-23/24 the general browser was refused by salesforce's
Workday five times, henryschein's three and autodesk's twice in one night
- a fresh posting every time, the same site, the same answer every hour.
"Never the same job twice" held, and nothing remembered the SITE.
"""
from __future__ import annotations

import datetime as dt
import unittest

from aletheia import apply_run


def _ago(minutes: float) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


RUNS = [
    {"id": "a", "state": "REJECTED", "url": "https://salesforce.wd12.myworkdayjobs.com/x/job/1", "rejected_at": _ago(30)},
    {"id": "b", "state": "REJECTED", "url": "https://salesforce.wd12.myworkdayjobs.com/x/job/2", "staged_at": _ago(90)},
    {"id": "c", "state": "REJECTED", "url": "https://autodesk.wd1.myworkdayjobs.com/y/job/3", "rejected_at": _ago(40)},
    {"id": "d", "state": "REJECTED", "url": "https://www.henryschein.wd1.myworkdayjobs.com/z/job/4",
     "rejected_at": _ago(60 * 30)},                               # yesterday: forgotten
    {"id": "e", "state": "SUBMITTED", "url": "https://salesforce.wd12.myworkdayjobs.com/x/job/5", "submitted_at": _ago(5)},
]


class ASiteThatRefusedTwiceTodayIsLeftAlone(unittest.TestCase):
    def test_refusals_are_counted_per_site_within_the_day(self):
        self.assertEqual(apply_run.host_refusals(runs=RUNS),
                         {"salesforce.wd12.myworkdayjobs.com": 2, "autodesk.wd1.myworkdayjobs.com": 1})

    def test_two_refusals_leave_the_site_alone_one_does_not(self):
        refusals = apply_run.host_refusals(runs=RUNS)
        why = apply_run.refusing_host("https://salesforce.wd12.myworkdayjobs.com/x/job/9", refusals=refusals)
        self.assertIn("salesforce.wd12.myworkdayjobs.com", why)
        self.assertIn(" 2 of her applications", why)
        self.assertIn("until tomorrow", why)
        self.assertEqual(apply_run.refusing_host("https://autodesk.wd1.myworkdayjobs.com/y/job/9", refusals=refusals), "")
        self.assertEqual(apply_run.refusing_host("https://henryschein.wd1.myworkdayjobs.com/z/job/9", refusals=refusals), "")
        self.assertEqual(apply_run.refusing_host("https://jobs.ashbyhq.com/acme/1", refusals=refusals), "")

    def test_nothing_refused_means_nothing_left_alone(self):
        self.assertEqual(apply_run.host_refusals(runs=[]), {})
        self.assertEqual(apply_run.refusing_host("https://jobs.ashbyhq.com/acme/1", refusals={}), "")
        self.assertEqual(apply_run.refusing_host("", refusals={"x": 9}), "")


class ASiteSheGaveUpOnTwiceTodayIsLeftAlone(unittest.TestCase):
    """Live 2026-10-07: 71 closures were the general browser finding no way
    forward, 14 going in circles, 13 a human check - each a batch's minutes
    spent on a site that had stopped her on another posting that day."""

    def left(self, url, because, minutes=30, kind="left"):
        return {"id": url, "state": "CLOSED", "url": url, "closed_kind": kind,
                "closed_because": because, "closed_at": _ago(minutes)}

    def test_a_wall_of_the_sites_counts_toward_leaving_it_alone(self):
        runs = [self.left("https://acme.wd1.myworkdayjobs.com/a/job/1",
                          "nothing more she could do here: no way forward on the page"),
                self.left("https://acme.wd1.myworkdayjobs.com/a/job/2",
                          "a human check on a job application, which is not yours to do")]
        refusals = apply_run.host_refusals(runs=runs)
        self.assertEqual(refusals, {"acme.wd1.myworkdayjobs.com": 2})
        self.assertTrue(apply_run.refusing_host("https://acme.wd1.myworkdayjobs.com/a/job/3",
                                                refusals=refusals))

    def test_a_wall_about_one_job_never_counts_against_the_site(self):
        runs = [self.left("https://acme.example/jobs/1", "nothing more she could do here: you said no"),
                self.left("https://acme.example/jobs/2", "nothing more she could do here: the posting closed"),
                self.left("https://acme.example/jobs/3",
                          "waited two days for questions only you can answer and you did not come"),
                self.left("https://acme.example/jobs/4", "no way forward on the page", kind="gone"),
                self.left("https://acme.example/jobs/5", "no way forward on the page", minutes=60 * 30)]
        self.assertEqual(apply_run.host_refusals(runs=runs), {})

    def test_an_applicant_tracking_system_is_never_left_alone_for_one_employer(self):
        runs = [self.left(f"https://jobs.ashbyhq.com/acme/{n}", "no way forward on the page") for n in (1, 2, 3)]
        self.assertEqual(apply_run.host_refusals(runs=runs), {})


if __name__ == "__main__":
    unittest.main()
