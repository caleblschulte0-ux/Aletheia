"""Not only the boards she knows: employers' own careers sites too.

His words, 2026-09-13: *"make sure that we are not just looking on these job
sites but also company websites and make sure it continue to fix and handle
edge cases."*

Measured the same afternoon, before this was written: DuckDuckGo answered
every job query from his PC with an HTTP 202 challenge and Bing's RSS answered
"Customer Success Manager careers" with dictionary pages, so the batch at
17:05Z found "0 more by web search" and she only ever reached the same sixty
Greenhouse and Lever boards. The Muse's free developer API names, on each
posting's page, the employer's own job page - jobs.bechtel.com, a Workday
tenant, boards.greenhouse.io/spacex - and that is where these leads go.

Nothing here reaches the network: every fetch is a stub.
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import campaign, company_sites, jobs, journal

NOW = dt.datetime(2026, 9, 13, 18, 0, tzinfo=dt.timezone.utc)


def muse_page(*links: str) -> str:
    """A listing page the way The Muse ships it: its own links, assets, and the employer's."""
    return ("<html><a href='https://www.themuse.com/advice'>Advice</a>"
            "<img src='https://cdn.themuse.com/logo.png'>"
            "<a href='https://www.linkedin.com/company/the-daily-muse'>LinkedIn</a>"
            + "".join(f"<script>window.__job={{\"u\":\"{link}\"}}</script>" for link in links)
            + "</html>")


class TheEmployersOwnPageIsFound(unittest.TestCase):
    def link(self, *links):
        return company_sites.employer_link(muse_page(*links), lead_host="www.themuse.com")

    def test_a_public_form_she_already_fills_wins(self):
        self.assertEqual(
            self.link("https://jobs.bechtel.com/us/en/job/298819",
                      "https://boards.greenhouse.io/spacex/jobs/8733461002?gh_jid=8733461002"),
            "https://boards.greenhouse.io/spacex/jobs/8733461002?gh_jid=8733461002")

    def test_the_employers_own_careers_site_is_found(self):
        self.assertEqual(self.link("https://jobs.bechtel.com/us/en/job/298819"),
                         "https://jobs.bechtel.com/us/en/job/298819")

    def test_a_workday_posting_is_found_and_needs_an_account(self):
        url = "https://equitylifestyleproperties.wd5.myworkdayjobs.com/ELS/job/Front-Desk-Clerk_R253761"
        self.assertEqual(self.link(url), url)
        self.assertTrue(company_sites.needs_account(url))
        self.assertFalse(company_sites.needs_account("https://jobs.bechtel.com/us/en/job/1"))

    def test_the_listing_site_its_assets_and_aggregators_never_count(self):
        self.assertEqual(self.link("https://www.indeed.com/viewjob?jk=abc",
                                   "https://www.linkedin.com/jobs/view/123"), "")
        self.assertEqual(company_sites.employer_link(muse_page(), lead_host="www.themuse.com"), "")

    def test_aggregators_are_recognised_by_host(self):
        for url in ("https://www.indeed.com/viewjob?jk=1", "https://www.linkedin.com/jobs/view/1",
                    "https://www.ziprecruiter.com/c/x", "https://www.glassdoor.com/job-listing/x"):
            self.assertTrue(company_sites.is_aggregator(url), url)
        self.assertFalse(company_sites.is_aggregator("https://jobs.uber.com/en/jobs/1/"))


class ATakenDownPostingCostsNoBrowser(unittest.TestCase):
    def check(self, status=200, body=""):
        return company_sites.still_open("https://jobs.acme.com/1",
                                        fetch=lambda url: (status, url, body), now=NOW)

    def test_gone_pages_are_closed(self):
        self.assertFalse(self.check(404)[0])
        self.assertFalse(self.check(410)[0])

    def test_the_employer_saying_so_closes_it(self):
        self.assertFalse(self.check(body="<p>This position has been filled.</p>")[0])
        self.assertFalse(self.check(body="<p>We are no longer accepting applications.</p>")[0])

    def test_a_closing_date_that_has_passed_closes_it(self):
        posting = {"@context": "https://schema.org", "@type": "JobPosting", "title": "Analyst",
                   "validThrough": "2026-09-01T00:00:00Z"}
        body = f"<script type='application/ld+json'>{json.dumps(posting)}</script>"
        self.assertFalse(self.check(body=body)[0])
        posting["validThrough"] = "2026-10-01T00:00:00Z"
        body = f"<script type='application/ld+json'>{json.dumps(posting)}</script>"
        self.assertTrue(self.check(body=body)[0])

    def test_a_posting_outside_the_us_is_closed(self):
        posting = {"@type": "JobPosting", "jobLocation": {"@type": "Place", "address": {
            "@type": "PostalAddress", "addressCountry": "Germany"}}}
        body = f"<script type='application/ld+json'>{json.dumps({'@graph': [posting]})}</script>"
        self.assertFalse(self.check(body=body)[0])

    def test_a_bot_check_in_front_of_the_jobs_is_skipped_not_fought(self):
        """Live: jobs.uber.com answered even a real browser with Cloudflare."""
        closed, why = self.check(403, "<html><head><title>Just a moment...</title></head></html>")
        self.assertFalse(closed)
        self.assertIn("bot check", why)
        self.assertFalse(self.check(403, "")[0])

    def test_a_javascript_shell_or_an_unreadable_page_stays_open(self):
        self.assertTrue(self.check(body="<div id='root'></div><script src='app.js'></script>")[0])

        def broken(url):
            raise OSError("reset")
        self.assertTrue(company_sites.still_open("https://jobs.acme.com/1", fetch=broken, now=NOW)[0])


class HisKindOfWorkPicksTheCategories(unittest.TestCase):
    def test_categories_come_from_his_roles_and_his_words(self):
        got = company_sites.categories_for(
            ["Partnership Manager", "Business Operations Analyst", "Account Coordinator"],
            "customer success, operations")
        self.assertIn("Business Operations", got)
        self.assertIn("Account Management", got)
        self.assertLessEqual(len(got), company_sites.MAX_CATEGORIES)

    def test_filler_words_choose_nothing(self):
        self.assertEqual(company_sites.categories_for(["the and of"], ""), [])


def muse_api(rows_per_page=3, pages=None):
    """A stub of The Muse API that records what was asked."""
    asked = []

    def fetch_json(url):
        asked.append(url)
        page = int(url.split("page=")[1].split("&")[0])
        if pages is not None and page >= pages:
            return {"results": []}
        return {"results": [{"name": f"Partnership Manager {page}-{i}",
                             "company": {"name": f"Co{page}{i}"},
                             "locations": [{"name": "Austin, TX"}],
                             "refs": {"landing_page": f"https://www.themuse.com/jobs/co/{page}-{i}-{hash(url) % 997}"}}
                            for i in range(rows_per_page)]}
    fetch_json.asked = asked
    return fetch_json


class EachBatchReadsFurtherIn(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cursor = Path(tmp.name) / "pages.json"

    def pages_asked(self, api):
        return sorted({int(u.split("page=")[1].split("&")[0]) for u in api.asked})

    def test_the_next_batch_starts_where_the_last_stopped(self):
        first = muse_api()
        company_sites.muse_leads(["Partnership Manager"], fetch_json=first, cursor_path=self.cursor)
        second = muse_api()
        company_sites.muse_leads(["Partnership Manager"], fetch_json=second, cursor_path=self.cursor)
        self.assertEqual(self.pages_asked(first), list(range(company_sites.PAGES_PER_CATEGORY)))
        self.assertTrue(set(self.pages_asked(second)).isdisjoint(self.pages_asked(first)))

    def test_the_end_of_a_category_starts_it_over(self):
        api = muse_api(pages=2)
        company_sites.muse_leads(["Partnership Manager"], fetch_json=api, cursor_path=self.cursor)
        self.assertEqual(set(json.loads(self.cursor.read_text()).values()), {0})

    def test_an_early_career_asks_only_for_entry_and_mid_levels(self):
        api = muse_api()
        company_sites.muse_leads(["Partnership Manager"], fetch_json=api, cursor_path=self.cursor,
                                 early=True)
        self.assertTrue(all("Senior+Level" not in u for u in api.asked))


class LeadsBecomeOpenings(unittest.TestCase):
    LEADS = [
        {"title": "Partnership Manager", "company": "Acme", "locations": ["Austin, TX"],
         "lead": "https://www.themuse.com/jobs/acme/1"},
        {"title": "Partnership Manager", "company": "Beta", "locations": ["Remote"],
         "lead": "https://www.themuse.com/jobs/beta/2"},
        {"title": "Partnership Manager", "company": "Gamma", "locations": ["Chicago, IL"],
         "lead": "https://www.themuse.com/jobs/gamma/3"},
        {"title": "Partnership Manager", "company": "Delta", "locations": ["Berlin, Germany"],
         "lead": "https://www.themuse.com/jobs/delta/4"},
        {"title": "Senior Partnership Manager", "company": "Eps", "locations": ["Denver, CO"],
         "lead": "https://www.themuse.com/jobs/eps/5"},
        {"title": "Registered Nurse", "company": "Zeta", "locations": ["Omaha, NE"],
         "lead": "https://www.themuse.com/jobs/zeta/6"},
        {"title": "Partnership Manager", "company": "Eta", "locations": ["Boston, MA"],
         "lead": "https://www.themuse.com/jobs/eta/7"},
    ]
    PAGES = {
        "https://www.themuse.com/jobs/acme/1": muse_page("https://job-boards.greenhouse.io/acme/jobs/4001"),
        "https://www.themuse.com/jobs/beta/2": muse_page("https://careers.beta.com/jobs/77"),
        "https://www.themuse.com/jobs/gamma/3": muse_page("https://gamma.wd1.myworkdayjobs.com/External/job/PM_R1"),
        "https://www.themuse.com/jobs/delta/4": muse_page("https://careers.delta.de/jobs/1"),
        "https://www.themuse.com/jobs/eps/5": muse_page("https://careers.eps.com/jobs/5"),
        "https://www.themuse.com/jobs/zeta/6": muse_page("https://careers.zeta.com/jobs/6"),
        "https://www.themuse.com/jobs/eta/7": muse_page("https://careers.eta.com/jobs/7"),
        "https://careers.beta.com/jobs/77": "<h1>Partnership Manager</h1><a>Apply now</a>",
        "https://careers.eta.com/jobs/7": "<p>This job is no longer available.</p>",
    }

    def fetch(self, url):
        self.fetched.append(url)
        return (200, url, self.PAGES.get(url, "")) if url in self.PAGES else (404, url, "")

    def openings(self, **kw):
        self.fetched = []
        return company_sites.openings(["Partnership Manager"], limit=10, country="United States",
                                      exclude=jobs.SENIOR_TITLE_WORDS, fetch=self.fetch,
                                      leads=lambda *a, **k: self.LEADS, **kw)

    def test_each_lead_lands_where_its_employer_takes_applications(self):
        by_company = {job["company"]: job for job in self.openings()}
        self.assertEqual(set(by_company), {"Acme", "Beta", "Gamma"})
        acme, beta, gamma = by_company["Acme"], by_company["Beta"], by_company["Gamma"]
        self.assertTrue(acme["direct"])
        self.assertIn("boards.greenhouse.io/embed/job_app?for=acme&token=4001", acme["apply_url"])
        self.assertEqual((beta["direct"], beta["needs_account"], beta["apply_url"]),
                         (False, False, "https://careers.beta.com/jobs/77"))
        self.assertTrue(gamma["needs_account"])
        for job in by_company.values():
            self.assertEqual(job["found_by"], "company site")
            self.assertEqual(job["found_on"], "the company's own careers page")

    def test_the_boards_rules_hold_here_too(self):
        companies = {job["company"] for job in self.openings()}
        self.assertNotIn("Delta", companies)      # outside the US
        self.assertNotIn("Eps", companies)        # Senior, for someone early
        self.assertNotIn("Zeta", companies)       # not his role
        self.assertNotIn("Eta", companies)        # the employer took it down

    def test_a_lead_that_does_not_match_is_never_even_opened(self):
        self.openings()
        self.assertNotIn("https://www.themuse.com/jobs/zeta/6", self.fetched)
        self.assertNotIn("https://www.themuse.com/jobs/delta/4", self.fetched)

    def test_every_lead_read_and_dropped_says_why(self):
        skipped = []
        company_sites.openings(["Partnership Manager"], limit=10, country="United States",
                               exclude=jobs.SENIOR_TITLE_WORDS, fetch=self.fetch,
                               leads=lambda *a, **k: self.LEADS, skipped=skipped)
        self.assertIn("Eta", {row["company"] for row in skipped})
        self.assertTrue(all(row["why"] for row in skipped))

    def test_a_source_that_fails_costs_only_itself(self):
        def boom(*a, **k):
            raise RuntimeError("the API is down")
        self.assertEqual(company_sites.openings(["Partnership Manager"], leads=boom), [])


class APayPerClickHopIsFollowedToWhereItLands(unittest.TestCase):
    """Live 2026-09-13: dsp.prng.co led to chevronstations.com's posting;
    click.appcast.io bounced back to The Muse's own search page."""

    def fetch(self, url):
        landing = {
            "https://dsp.prng.co/abc": "https://www.chevronstations.com/job/-/-/35016/961?p_sid=abc",
            "https://click.appcast.io/t/xyz": "https://www.themuse.com/search/",
            "https://click.appcast.io/t/agg": "https://www.indeed.com/viewjob?jk=1",
        }
        return 200, landing.get(url, url), "<h1>Customer Service Representative</h1>"

    def test_a_hop_that_lands_on_the_employer_is_kept(self):
        page = muse_page("https://dsp.prng.co/abc")
        self.assertEqual(
            company_sites.follow_hops(page, lead_host="www.themuse.com", fetch=self.fetch),
            "https://www.chevronstations.com/job/-/-/35016/961?p_sid=abc")

    def test_a_hop_back_to_the_listing_site_or_an_aggregator_is_dropped(self):
        for hop in ("https://click.appcast.io/t/xyz", "https://click.appcast.io/t/agg"):
            self.assertEqual(company_sites.follow_hops(muse_page(hop), lead_host="www.themuse.com",
                                                       fetch=self.fetch), "", hop)


class TheBoardsAreNotStarved(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for target, name, value in ((journal, "JOURNAL_PATH", Path(tmp.name) / "j.jsonl"),
                                    (jobs, "_learned_path", lambda: Path(tmp.name) / "l.json")):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def search(self, companies, http=None, rows=12):
        board_rows = [{"title": "Partnership Manager", "company": f"Board{i}", "location": "",
                       "apply_url": f"https://board/{i}"} for i in range(rows)]
        own = [{"title": "Partnership Manager", "company": f"Own{i}", "location": "",
                "apply_url": f"https://own/{i}", "found_by": "company site", "direct": False}
               for i in range(companies)]
        with mock.patch.object(jobs, "boards", return_value=[{"provider": "greenhouse", "token": "t"}]):
            return jobs.search_many(["Partnership Manager"], fetcher=lambda b: board_rows, limit=9,
                                    discover=True, http=http or (lambda q: {"links": []}),
                                    companies=lambda roles, **kw: own)

    def test_employer_sites_take_the_third_slot_and_the_boards_keep_two(self):
        out = self.search(companies=6)
        kinds = [("own" if j.get("found_by") == "company site" else "board") for j in out["matches"]]
        self.assertEqual(kinds[:3], ["board", "board", "own"])
        self.assertEqual(kinds.count("board"), 6)
        self.assertEqual(out["company_sites"], 3)

    def test_with_the_web_finding_things_too_they_take_turns(self):
        web = {"links": [{"href": f"https://boards.greenhouse.io/web{i}/jobs/{900 + i}",
                          "text": "Partnership Manager"} for i in range(6)]}
        out = self.search(companies=6, http=lambda q: web)
        third = [j.get("found_by") for j in out["matches"][2::3]]
        self.assertIn("web search", third)
        self.assertIn("company site", third)

    def test_a_test_search_never_reaches_the_real_company_finder(self):
        with mock.patch.object(jobs, "_company_openings", side_effect=AssertionError("network")), \
             mock.patch.object(jobs, "boards", return_value=[{"provider": "greenhouse", "token": "t"}]):
            jobs.search_many(["Partnership Manager"], limit=5, discover=True,
                             fetcher=lambda b: [], http=lambda q: {"links": []})


class TheCampaignWalksAnEmployersSite(unittest.TestCase):
    def test_an_embedded_form_is_tried_before_any_link(self):
        pages = {
            "https://careers.acme.com/jobs/1": ([], [
                {"href": "https://careers.acme.com/apply-info", "text": "Apply"},
                {"href": "https://boards.greenhouse.io/embed/job_app?for=acme&token=1",
                 "text": "apply (form embedded on this page)", "embedded": True}]),
            "https://boards.greenhouse.io/embed/job_app?for=acme&token=1": (FORM, []),
        }
        opened = []

        def opener(url):
            opened.append(url)
            return pages.get(url, ([], []))
        url, fields = campaign._application_url("https://careers.acme.com/jobs/1", opener=opener)
        self.assertEqual(url, "https://boards.greenhouse.io/embed/job_app?for=acme&token=1")
        self.assertNotIn("https://careers.acme.com/apply-info", opened)

    def test_apply_by_email_and_apply_on_an_aggregator_are_not_followed(self):
        opened = []

        def opener(url):
            opened.append(url)
            if url == "https://careers.acme.com/jobs/2":
                return [], [{"href": "mailto:jobs@acme.com", "text": "Apply by email"},
                            {"href": "https://www.indeed.com/viewjob?jk=1", "text": "Apply now"}]
            return FORM, []
        self.assertEqual(campaign._application_url("https://careers.acme.com/jobs/2", opener=opener),
                         ("", []))
        self.assertEqual(opened, ["https://careers.acme.com/jobs/2"])

    def test_an_account_wall_is_not_a_ready_application(self):
        said = campaign.spoken({"ready": [], "blocked": [], "failed": [],
                                "needs_account": [{"url": "x"}, {"url": "y"}]})
        self.assertIn("2 on employer sites that want an account", said)
        self.assertNotIn("filled in and waiting", said)


FORM = [{"type": "text", "label": "First name", "name": "first_name"},
        {"type": "email", "label": "Email", "name": "email"},
        {"type": "file", "label": "Resume", "name": "resume"},
        {"type": "text", "label": "Phone", "name": "phone"}]


if __name__ == "__main__":
    unittest.main()
