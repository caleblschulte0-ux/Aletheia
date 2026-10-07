"""A search's window holds openings she has not met yet.

Live 2026-10-07 one batch was handed 90 openings: 36 were jobs already
applied for or waiting, 43 were jobs judged not realistic before, and one
was new enough to stage. The search cut its window first and the batch
threw the settled ones away after, so the fresh ones below the cut were
never offered at all.
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import apply_run, campaign, jobs

NOW = dt.datetime(2026, 10, 7, 16, 0, tzinfo=dt.timezone.utc)


def job(n, company="Acme"):
    return {"title": f"Operations Analyst {n}", "company": company,
            "apply_url": f"https://boards.example/acme/{n}", "location": "Remote"}


class TheSearchLeavesSettledJobsOut(unittest.TestCase):
    def search(self, everything, *, limit, skip):
        fetcher = lambda: (everything, [], 1)   # noqa: E731
        with mock.patch.object(jobs, "_gather", side_effect=lambda f: fetcher()):
            return jobs.search_many(["operations analyst"], limit=limit, fetcher=object(),
                                    skip=skip)

    def test_settled_jobs_do_not_take_the_window(self):
        everything = [job(n, company=f"Co{n}") for n in range(6)]
        settled = {everything[0]["apply_url"], everything[1]["apply_url"]}
        found = self.search(everything, limit=3, skip=lambda j: j["apply_url"] in settled)
        urls = [j["apply_url"] for j in found["matches"]]
        self.assertEqual(len(urls), 3)
        self.assertFalse(settled & set(urls))

    def test_one_role_posted_in_many_cities_takes_one_slot(self):
        """Live 2026-10-07: 50 of 180 slots went on copies of a role the
        batch then threw away as the same job."""
        copies = [{"title": "Operations Analyst", "company": "Acme",
                   "apply_url": f"https://boards.example/acme/{city}", "location": city}
                  for city in ("Austin", "Denver", "Boston", "Remote")]
        others = [job(n, company=f"Co{n}") for n in range(4)]
        found = self.search(copies + others, limit=4, skip=None)
        titles = [(j["company"], j["title"]) for j in found["matches"]]
        self.assertEqual(len(titles), 4)
        self.assertEqual(titles.count(("Acme", "Operations Analyst")), 1)

    def test_a_skip_that_breaks_leaves_everything_in(self):
        everything = [job(n, company=f"Co{n}") for n in range(3)]
        found = self.search(everything, limit=3, skip=lambda j: 1 / 0)
        self.assertEqual(len(found["matches"]), 3)


class _Stores(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        root = Path(self.dir.name)
        for target, value in ((campaign, {"PASSED_PATH": root / "passed.json",
                                          "UNREACHABLE_PATH": root / "unreachable.json"}),):
            for name, path in value.items():
                patcher = mock.patch.object(target, name, path)
                patcher.start()
                self.addCleanup(patcher.stop)

    def runs(self, rows):
        patcher = mock.patch.object(apply_run, "all_runs",
                                    side_effect=lambda state=None: [r for r in rows
                                                                    if state is None or r["state"] == state])
        patcher.start()
        self.addCleanup(patcher.stop)


class WhatCountsAsSettled(_Stores):
    def test_sent_waiting_and_closed_are_settled_and_failed_is_not(self):
        self.runs([
            {"state": "SUBMITTED", "url": "u-sent", "company": "A", "job_title": "Analyst"},
            {"state": "NEEDS_YOU", "url": "u-wait", "company": "B", "job_title": "Coordinator"},
            {"state": "CLOSED", "closed_kind": "gone", "url": "u-gone", "company": "C", "job_title": "X"},
            {"state": "FAILED", "url": "u-failed", "company": "D", "job_title": "Specialist"},
        ])
        skip = campaign.settled_already(now=NOW)
        self.assertTrue(skip({"apply_url": "u-sent"}))
        self.assertTrue(skip({"apply_url": "elsewhere", "company": "A", "title": "Analyst"}))
        self.assertTrue(skip({"apply_url": "u-wait"}))
        self.assertTrue(skip({"apply_url": "u-gone"}))
        self.assertFalse(skip({"apply_url": "elsewhere", "company": "C", "title": "X"}),
                         "a posting that was gone says nothing about another link")
        self.assertFalse(skip({"apply_url": "u-failed", "company": "D", "title": "Specialist"}))
        self.assertFalse(skip({"apply_url": "u-new", "company": "E", "title": "Analyst"}))

    def test_an_unfit_closure_from_before_his_preferences_is_judged_again(self):
        self.runs([{"state": "CLOSED", "closed_kind": "unfit", "closed_at": "2026-09-01T00:00:00Z",
                    "url": "u-old", "company": "A", "job_title": "Analyst"},
                   {"state": "CLOSED", "closed_kind": "unfit", "closed_at": "2026-10-01T00:00:00Z",
                    "url": "u-new", "company": "B", "job_title": "Analyst"}])
        skip = campaign.settled_already(since="2026-09-15T00:00:00Z", now=NOW)
        self.assertFalse(skip({"apply_url": "u-old"}))
        self.assertTrue(skip({"apply_url": "u-new"}))
        self.assertTrue(skip({"apply_url": "x", "company": "B", "title": "Analyst"}))

    def test_a_job_a_batch_passed_over_is_left_out_until_he_changes_his_mind(self):
        self.runs([])
        campaign.remember_passed([{"url": "u-passed", "why": "wants 8 years"}], now=NOW)
        self.assertTrue(campaign.settled_already(since="2026-09-01T00:00:00Z", now=NOW)(
            {"apply_url": "u-passed"}))
        self.assertFalse(campaign.settled_already(since="2026-10-08T00:00:00Z", now=NOW)(
            {"apply_url": "u-passed"}))

    def test_a_passed_over_memory_forgets_after_a_month(self):
        self.runs([])
        campaign.remember_passed([{"url": "u-old"}], now=NOW - dt.timedelta(days=40))
        campaign.remember_passed([{"url": "u-new"}], now=NOW)
        self.assertEqual(set(campaign._passed_read()), {"u-new"})

    def test_a_memory_that_cannot_be_written_never_stops_a_batch(self):
        blocked = Path(self.dir.name) / "a-file"
        blocked.write_text("x", encoding="utf-8")
        with mock.patch.object(campaign, "PASSED_PATH", blocked / "passed.json"):
            campaign.remember_passed([{"url": "u"}])


if __name__ == "__main__":
    unittest.main()


class WorkHeWillNotDoIsLeftOutByItsTitle(_Stores):
    """Live 2026-10-07: a batch spent 39 of its 90 openings on jobs titled
    sales, and every one was turned away after the cut by the same rule."""

    def skip_with(self, not_wanted):
        self.runs([])
        with mock.patch.object(campaign.profile, "known", return_value={"work_not_wanted": not_wanted}):
            return campaign.settled_already(now=NOW)

    def test_a_sales_title_is_left_out_when_he_said_no_sales(self):
        skip = self.skip_with("definitely don't wanna do sales, no cold calling")
        self.assertTrue(skip({"apply_url": "u1", "company": "A", "title": "Account Executive"}))
        self.assertTrue(skip({"apply_url": "u2", "company": "A", "title": "Inbound SDR"}))
        self.assertFalse(skip({"apply_url": "u3", "company": "A", "title": "Sales Operations Analyst"}),
                         "the work behind a sales team is not selling")
        self.assertFalse(skip({"apply_url": "u4", "company": "A", "title": "Project Coordinator"}))

    def test_his_own_words_decide_it(self):
        skip = self.skip_with("")
        self.assertFalse(skip({"apply_url": "u1", "company": "A", "title": "Account Executive"}))


class ASystemThatNeverLetsHerIn(_Stores):
    """Live 2026-10-07: 24 SmartRecruiters forms in a month closed as asking
    nothing about him - a bot wall - and no confirmation from that system had
    ever reached his inbox. Each one was a batch slot spent on a page load."""

    WALL = ("nothing on this page asks for his name, email or phone, so it is not an "
            "application form - a bot check or a contact page looks like this")

    def walled(self, n, host="jobs.smartrecruiters.com", days_ago=2):
        at = (NOW - dt.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return [{"id": f"w{host}{i}", "state": "CLOSED", "url": f"https://{host}/oneclick-ui/x/{i}",
                 "closed_kind": apply_run.NOT_A_FORM, "closed_because": self.WALL, "closed_at": at}
                for i in range(n)]

    def test_a_walled_system_is_left_out_before_the_cut(self):
        self.runs(self.walled(campaign.WALLED_AFTER))
        skip = campaign.settled_already(now=NOW)
        self.assertTrue(skip({"apply_url": "https://jobs.smartrecruiters.com/oneclick-ui/y/9",
                              "title": "Operations Analyst", "company": "Acme"}))
        self.assertFalse(skip({"apply_url": "https://boards.greenhouse.io/embed/job_app?for=a&token=1",
                               "title": "Operations Analyst", "company": "Acme"}))

    def test_one_that_ever_let_one_through_is_not_walled(self):
        rows = self.walled(campaign.WALLED_AFTER + 3) + [
            {"id": "s", "state": "SUBMITTED", "url": "https://jobs.smartrecruiters.com/oneclick-ui/z/1"}]
        self.assertEqual(campaign.walled_systems(rows, now=NOW), {})

    def test_too_few_or_too_old_is_not_a_wall(self):
        self.assertEqual(campaign.walled_systems(self.walled(campaign.WALLED_AFTER - 1), now=NOW), {})
        old = self.walled(campaign.WALLED_AFTER, days_ago=campaign.WALLED_DAYS + 1)
        self.assertEqual(campaign.walled_systems(old, now=NOW), {})

    def test_a_system_now_sent_to_the_browser_is_a_different_attempt(self):
        rows = self.walled(campaign.WALLED_AFTER + 3, host="acme.bamboohr.com")
        self.assertEqual(campaign.walled_systems(rows, now=NOW), {})
        self.assertEqual(campaign.walled_systems(self.walled(campaign.WALLED_AFTER), now=NOW),
                         {"smartrecruiters": campaign.WALLED_AFTER})
