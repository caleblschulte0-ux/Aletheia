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
        self.assertIn("salesforce.wd12.myworkdayjobs.com refused 2", why)
        self.assertIn("until tomorrow", why)
        self.assertEqual(apply_run.refusing_host("https://autodesk.wd1.myworkdayjobs.com/y/job/9", refusals=refusals), "")
        self.assertEqual(apply_run.refusing_host("https://henryschein.wd1.myworkdayjobs.com/z/job/9", refusals=refusals), "")
        self.assertEqual(apply_run.refusing_host("https://jobs.ashbyhq.com/acme/1", refusals=refusals), "")

    def test_nothing_refused_means_nothing_left_alone(self):
        self.assertEqual(apply_run.host_refusals(runs=[]), {})
        self.assertEqual(apply_run.refusing_host("https://jobs.ashbyhq.com/acme/1", refusals={}), "")
        self.assertEqual(apply_run.refusing_host("", refusals={"x": 9}), "")


if __name__ == "__main__":
    unittest.main()
