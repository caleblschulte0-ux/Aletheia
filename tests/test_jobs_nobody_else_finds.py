"""Employers she remembers, sites she crawls herself, openings ranked by value.

His words, 2026-09-15: *"find unusually good opportunities wherever employers
publish them, including small companies."* The model case is his ECG job - a
small South Dakota employer paying well, found on its own site, on no board.

Nothing here reaches the network: every fetch, feed, search and sleep is a
stub, and every store is a temporary file.
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (apply_run, campaign, career_sites, employers, job_discovery, job_value,
                      jobs, journal, profile, web_search_jobs as wsj)

NOW = dt.datetime(2026, 9, 15, 15, 0, tzinfo=dt.timezone.utc)
KNOWN = {"state": "SD", "country": "United States", "willing_to_relocate": "Yes",
         "current_title": "Business Development Associate", "years_experience": "2",
         "desired_pay": "$100,000 minimum for a nationwide or remote role; $95,000 minimum "
                        "for a role based in Sioux Falls, South Dakota.",
         "work_wanted": "business development, partnerships, account management, operations",
         "work_not_wanted": "cold calling, and jobs built around chasing quotas"}


class Isolated(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for target, name, value in (
                (employers, "path", lambda: self.root / "employers.json"),
                (job_discovery, "summary_path", lambda: self.root / "discovery.json"),
                (wsj, "_state_path", lambda: self.root / "web_search.json"),
                (wsj, "_cache_path", lambda: self.root / "web_search_cache.json"),
                (jobs, "_learned_path", lambda: self.root / "learned.json"),
                (journal, "JOURNAL_PATH", self.root / "j.jsonl"),
                (profile, "path", lambda: self.root / "answers.json")):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        career_sites._last_hit.clear()


# ---- the employer store ------------------------------------------------------------

class EmployersAreRemembered(Isolated):
    def test_an_upsert_is_idempotent_and_widens(self):
        a = employers.upsert(name="Acme Corp", url="https://www.acme.com/careers", source="a crawl")
        b = employers.upsert(name="Acme Corporation, Inc.", career_url="https://acme.com/jobs",
                             location="Sioux Falls, SD", jobs_seen=4)
        self.assertEqual(len(employers.all_rows()), 1)
        self.assertEqual(a["domains"], ["acme.com"])
        self.assertIn("https://acme.com/jobs", b["career_urls"])
        self.assertEqual(b["locations"], ["Sioux Falls, SD"])
        self.assertEqual(b["jobs_seen"], 4)
        self.assertEqual(b["first_seen"], a["first_seen"])

    def test_an_ats_host_is_never_the_employers_domain(self):
        row = employers.upsert(name="Gong", url="https://boards.greenhouse.io/gongio/jobs/4627272006")
        self.assertEqual(row["domains"], [])
        self.assertEqual((row["ats"], row["token"]), ("greenhouse", "gongio"))
        again = employers.upsert(name="Gong Inc", ats="greenhouse", token="gongio")
        self.assertEqual(len(employers.all_rows()), 1)
        self.assertEqual(again["name"], "Gong")

    def test_a_workday_tenant_is_an_ats_with_no_domain(self):
        row = employers.upsert(name="Equity LifeStyle",
                               career_url="https://equitylifestyleproperties.wd5.myworkdayjobs.com/ELS")
        self.assertEqual(row["domains"], [])
        self.assertEqual(row["ats"], "workday")

    def test_what_do_you_know_about_x(self):
        employers.upsert(name="Expansion Capital Group", url="https://expansioncapital.com",
                         location="Sioux Falls, SD", jobs_seen=3)
        self.assertEqual(employers.about("expansion capital")["name"], "Expansion Capital Group")
        self.assertEqual(employers.about("https://www.expansioncapital.com/x")["name"],
                         "Expansion Capital Group")
        self.assertIsNone(employers.about("Nobody Ever"))
        said = employers.describe(employers.about("Expansion Capital Group"))
        self.assertIn("expansioncapital.com", said)
        self.assertIn("never crawled", said)

    def test_every_source_a_search_meets_is_remembered(self):
        found = [
            {"title": "Account Manager", "company": "Stripe", "provider": "greenhouse", "board": "stripe",
             "posting_url": "https://stripe.com/jobs/search?gh_jid=1", "location": "Remote"},
            {"title": "Ops Analyst", "company": "Bechtel", "provider": "company site",
             "posting_url": "https://jobs.bechtel.com/us/en/job/298819", "location": "Reston, VA",
             "found_by": "company site"},
            {"title": "Ops Analyst", "company": "Bechtel", "provider": "company site",
             "posting_url": "https://jobs.bechtel.com/us/en/job/298820", "location": "Reston, VA"},
            {"title": "x", "company": "", "provider": "", "posting_url": ""},
        ]
        self.assertEqual(employers.remember_jobs(found, now="2026-09-15T00:00:00Z"), 2)
        stripe = employers.about("Stripe")
        self.assertEqual((stripe["ats"], stripe["token"]), ("greenhouse", "stripe"))
        self.assertIn("stripe.com", stripe["domains"])
        self.assertIn("jobs.bechtel.com", employers.about("Bechtel")["domains"])

    def test_her_other_stores_seed_it(self):
        sent = {"https://boards.greenhouse.io/embed/job_app?for=carta&token=1":
                {"company": "Carta", "job_title": "Account Manager — Carta", "id": "apply-1"}}
        with mock.patch.object(jobs, "boards", return_value=[
                {"provider": "lever", "token": "acme", "company": "Acme", "learned": True}]), \
             mock.patch.object(apply_run, "already_sent", return_value=sent), \
             mock.patch.object(apply_run, "all_runs", return_value=[
                 {"company": "Bechtel", "posting": "https://jobs.bechtel.com/us/en/job/1", "url": "u"}]):
            employers.seed_from_records()
        names = {r["name"] for r in employers.all_rows()}
        self.assertEqual(names, {"Acme", "Carta", "Bechtel"})

    def test_stale_and_new_today(self):
        employers.upsert(name="Old", url="https://old.com", crawled=True, now="2026-09-13T00:00:00Z")
        employers.upsert(name="Fresh", url="https://fresh.com", crawled=True, now="2026-09-15T10:00:00Z")
        employers.upsert(name="Never", url="https://never.com", now="2026-09-15T10:00:00Z")
        employers.upsert(name="Nameless board", ats="lever", token="x", now="2026-09-15T10:00:00Z")
        self.assertEqual({r["name"] for r in employers.stale(now=NOW)}, {"Old", "Never"})
        self.assertEqual({r["name"] for r in employers.new_since("2026-09-15")},
                         {"Fresh", "Never", "Nameless board"})


# ---- the crawl ------------------------------------------------------------------------

HOME = """<html><a href="/about">About</a><a href="/careers">Careers</a>
<a href="https://www.linkedin.com/company/acme">LinkedIn</a></html>"""
POSTING = {"@context": "https://schema.org", "@type": "JobPosting",
           "title": "Business Development Associate",
           "hiringOrganization": {"@type": "Organization", "name": "Acme Manufacturing"},
           "jobLocation": {"@type": "Place", "address": {"addressLocality": "Sioux Falls",
                                                         "addressRegion": "SD", "addressCountry": "US"}},
           "employmentType": "FULL_TIME", "datePosted": "2026-09-12", "validThrough": "2026-10-30",
           "baseSalary": {"@type": "MonetaryAmount", "currency": "USD",
                          "value": {"@type": "QuantitativeValue", "minValue": 95000,
                                    "maxValue": 120000, "unitText": "YEAR"}},
           "description": "<p>Grow partner accounts across the upper Midwest.</p>",
           "url": "https://acme.com/careers/business-development-associate"}
CAREERS = f"""<html><script type="application/ld+json">{json.dumps(POSTING)}</script>
<a href="/careers/operations-coordinator">Operations Coordinator</a>
<a href="/careers">View all jobs</a>
<a href="https://boards.greenhouse.io/acmemfg">Our Greenhouse board</a>
<a href="https://acme.wd5.myworkdayjobs.com/External">Legacy portal</a>
<a href="/blog/why-we-hire">Why we hire</a>
</html>"""
SITEMAP = """<?xml version="1.0"?><urlset><url><loc>https://acme.com/</loc></url>
<url><loc>https://acme.com/careers/warehouse-lead</loc></url></urlset>"""


def site(robots: str = "", pages: dict | None = None):
    """A fetch stub for acme.com: (status, final url, body), and the log of what was asked."""
    pages = {"https://acme.com/": HOME, "https://acme.com/careers": CAREERS,
             "https://acme.com/sitemap.xml": SITEMAP, **(pages or {})}
    asked = []

    def fetch(url):
        asked.append(url)
        if url.endswith("/robots.txt"):
            return (200, url, robots) if robots else (404, url, "")
        body = pages.get(url)
        return (200, url, body) if body is not None else (404, url, "")
    fetch.asked = asked
    return fetch


class TheCrawlIsShallowAndPolite(Isolated):
    def crawl(self, **kw):
        return career_sites.crawl("acme.com", fetch=site(**kw), sleeper=lambda s: None)

    def test_it_finds_where_the_employer_posts_jobs(self):
        out = self.crawl()
        self.assertIn("https://acme.com/careers", out["career_urls"])
        self.assertEqual(out["postings"][0]["title"], "Business Development Associate")
        self.assertEqual(out["postings"][0]["salary"], [95000.0, 120000.0])
        self.assertEqual(out["postings"][0]["location"], "Sioux Falls, SD, US")
        self.assertEqual(out["postings"][0]["posted"], "2026-09-12")
        self.assertIn("Grow partner accounts", out["postings"][0]["description"])
        self.assertIn({"provider": "greenhouse", "token": "acmemfg",
                       "url": "https://boards.greenhouse.io/acmemfg", "job": False}, out["ats"])
        self.assertEqual(out["account_systems"], ["https://acme.wd5.myworkdayjobs.com/External"])
        titles = {j["title"] for j in out["job_links"]}
        self.assertIn("Operations Coordinator", titles)
        self.assertNotIn("View all jobs", titles)
        self.assertNotIn("Why we hire", titles)
        self.assertEqual(out["stopped"], "")

    def test_robots_is_read_first_and_obeyed(self):
        fetch = site(robots="User-agent: *\nDisallow: /careers\n")
        out = career_sites.crawl("acme.com", fetch=fetch, sleeper=lambda s: None)
        self.assertTrue(fetch.asked[0].endswith("/robots.txt"))
        self.assertNotIn("https://acme.com/careers", fetch.asked)
        self.assertIn("https://acme.com/careers", out["robots_blocked"])
        self.assertEqual(out["postings"], [])

    def test_a_named_agent_rule_counts_and_an_allow_wins_over_a_shorter_disallow(self):
        rules = career_sites.robots_rules("User-agent: aletheia\nDisallow: /\nAllow: /careers\n")
        self.assertFalse(career_sites.allowed("https://acme.com/about", rules))
        self.assertTrue(career_sites.allowed("https://acme.com/careers/x", rules))

    def test_the_page_cap_holds(self):
        many = {f"https://acme.com/{p.strip('/')}": "<html>nothing</html>" for p in career_sites.LIKELY_PATHS}
        fetch = site(pages=many)
        out = career_sites.crawl("acme.com", fetch=fetch, sleeper=lambda s: None)
        self.assertLessEqual(out["pages_read"], career_sites.MAX_PAGES)
        self.assertLessEqual(len([u for u in fetch.asked if not u.endswith("robots.txt")]),
                             career_sites.MAX_PAGES)

    def test_a_bot_check_stops_the_crawl_and_says_so(self):
        out = self.crawl(pages={"https://acme.com/": "<html><title>Just a moment...</title></html>"})
        self.assertEqual(out["stopped"], "the site puts a bot check in front of its pages")
        self.assertEqual(out["pages_read"], 1)

    def test_an_aggregator_is_never_crawled(self):
        fetch = site()
        out = career_sites.crawl("https://www.indeed.com/cmp/acme", fetch=fetch, sleeper=lambda s: None)
        self.assertEqual(fetch.asked, [])
        self.assertIn("aggregator", out["stopped"])

    def test_one_host_is_not_hit_twice_inside_the_gap(self):
        clock = iter([0.0, 0.0, 0.2, 0.2 + career_sites.MIN_GAP_S])
        slept = []
        career_sites._wait_turn("acme.com", sleeper=slept.append, clock=lambda: next(clock))
        career_sites._wait_turn("acme.com", sleeper=slept.append, clock=lambda: next(clock))
        self.assertEqual(len(slept), 1)
        self.assertAlmostEqual(slept[0], career_sites.MIN_GAP_S - 0.2, places=3)


class TheLadder(Isolated):
    def test_feed_then_json_ld_then_ats_page_then_links(self):
        feed_rows = [{"title": "Account Manager", "company": "Acme", "location": "Remote",
                      "posting_url": "https://boards.greenhouse.io/acmemfg/jobs/1",
                      "apply_url": "https://boards.greenhouse.io/embed/job_app?for=acmemfg&token=1",
                      "provider": "greenhouse", "board": "acmemfg", "id": "1"}]
        feeds = []

        def feed(board):
            feeds.append(board["token"])
            return feed_rows
        report: dict = {}
        out = career_sites.openings({"name": "Acme", "domains": ["acme.com"], "ats": "greenhouse",
                                     "token": "acmemfg"},
                                    fetch=site(), sleeper=lambda s: None, feed=feed, report=report)
        rungs = {j["extracted_by"] for j in out}
        self.assertEqual(rungs, {"ats feed", "jobposting json-ld", "careers page link"})
        self.assertEqual(feeds, ["acmemfg"], "the board she already knows is read once")
        ld = next(j for j in out if j["extracted_by"] == "jobposting json-ld")
        self.assertEqual(ld["salary"], [95000.0, 120000.0])
        self.assertEqual(ld["provider"], "company site")
        self.assertFalse(ld["direct"])
        self.assertEqual(ld["found_on"], career_sites.FOUND_ON)
        link = next(j for j in out if j["extracted_by"] == "careers page link")
        self.assertTrue(link["unverified"])
        self.assertTrue(all(j["found_by"] == "employer crawl" for j in out))

    def test_a_board_met_on_the_site_is_read_now(self):
        feeds = []
        out = career_sites.openings({"name": "Acme", "domains": ["acme.com"]},
                                    fetch=site(), sleeper=lambda s: None,
                                    feed=lambda b: feeds.append(b["token"]) or [])
        self.assertEqual(feeds, ["acmemfg"])
        self.assertTrue(any(j["extracted_by"] == "jobposting json-ld" for j in out))

    def test_crawl_employers_remembers_what_it_learned_and_skips_the_fresh(self):
        employers.upsert(name="Acme", url="https://acme.com", now="2026-09-13T00:00:00Z")
        employers.upsert(name="Fresh", url="https://fresh.com", crawled=True, now="2026-09-15T10:00:00Z")
        learned = []
        with mock.patch.object(jobs, "learn_boards", side_effect=lambda rows, source: learned.extend(rows)):
            report: dict = {}
            out = career_sites.crawl_employers(fetch=site(), sleeper=lambda s: None, feed=lambda b: [],
                                               now=NOW, report=report)
        self.assertEqual([r["name"] for r in report["crawled"]], ["Acme"])
        acme = employers.about("Acme")
        self.assertEqual(acme["last_crawled"], "2026-09-15T15:00:00Z")
        self.assertEqual(acme["jobs_seen"], len(out))
        self.assertEqual((acme["ats"], acme["token"]), ("greenhouse", "acmemfg"))
        self.assertIn("https://acme.com/careers", acme["career_urls"])
        self.assertEqual(learned, [{"provider": "greenhouse", "board": "acmemfg", "company": "Acme"}])
        self.assertEqual(employers.stale(now=NOW), [], "crawled today, so not due again")


# ---- discovering employers ----------------------------------------------------------------

class EmployersAreDiscovered(Isolated):
    def test_the_queries_are_diverse_and_near_him(self):
        places = job_discovery.places_for(KNOWN)
        self.assertEqual(places[0], "South Dakota")
        queries = job_discovery.plan_employer_queries(
            ["Business Development Associate"], places,
            fields=job_discovery.fields_for(["Business Development Associate"], KNOWN), count=6)
        texts = [q["query"] for q in queries]
        self.assertEqual(len(set(texts)), 6)
        self.assertTrue(any("South Dakota" in t for t in texts))
        self.assertTrue(any("now hiring" in t for t in texts))
        self.assertTrue(any("site:*.com/careers" in t for t in texts))
        self.assertTrue(any("partnerships" in t for t in texts), "his fields, not only his titles")

    def answer(self, *rows):
        return json.dumps({"employers": list(rows)}), "stub"

    def test_a_search_names_employers_within_the_days_budget_and_the_cache(self):
        calls = []

        def searcher(system, prompt):
            calls.append(json.loads(prompt))
            self.assertIn("EMPLOYERS", system)
            return self.answer({"name": "Acme Manufacturing", "website": "https://acme.com",
                                "careers_url": "https://acme.com/careers", "location": "Sioux Falls, SD",
                                "why": "regional manufacturer with a partnerships team"},
                               {"name": "", "website": "not a url"})
        report: dict = {}
        found = job_discovery.find_employers(["Business Development Associate"], ["South Dakota"],
                                             searcher=searcher, report=report, now=NOW)
        self.assertEqual([f["name"] for f in found], ["Acme Manufacturing"])
        self.assertEqual(report["searches"], 1)
        self.assertEqual(calls[0]["place"], "South Dakota")
        again = job_discovery.find_employers(["Business Development Associate"], ["South Dakota"],
                                             searcher=searcher, report={}, now=NOW)
        self.assertEqual(len(calls), 2, "the cursor moved, so the second batch asks differently")
        state = json.loads((self.root / "web_search.json").read_text())
        self.assertEqual(state["searches_today"], 2)
        self.assertEqual(state["employer_cursor"], 2)
        with mock.patch.object(wsj, "MAX_SEARCHES_PER_DAY", 2):
            spent: dict = {}
            job_discovery.find_employers(["Business Development Associate"], ["South Dakota"],
                                         searcher=searcher, report=spent, now=NOW)
        self.assertEqual(len(calls), 2)
        self.assertIn("spent", spent["stopped"])

    def test_discovery_remembers_the_search_and_the_muse(self):
        leads = [{"title": "Ops Coordinator", "company": "Sanford Health", "locations": ["Sioux Falls, SD"],
                  "lead": "https://www.themuse.com/jobs/sanford/1"}]
        report: dict = {}
        new = job_discovery.discover_employers(
            ["Operations Coordinator"], known=KNOWN, now=NOW, report=report,
            searcher=lambda s, p: self.answer({"name": "Acme Manufacturing", "website": "https://acme.com",
                                               "careers_url": "", "location": "Sioux Falls, SD", "why": "x"}),
            leads=lambda roles, **kw: leads)
        self.assertEqual({r["name"] for r in new}, {"Acme Manufacturing", "Sanford Health"})
        self.assertEqual(employers.about("Sanford Health")["source"], "a listing on The Muse")
        self.assertEqual(employers.about("acme.com")["notes"], "x")
        again = job_discovery.discover_employers(
            ["Operations Coordinator"], known=KNOWN, now=NOW, report={},
            searcher=lambda s, p: self.answer(), leads=lambda roles, **kw: leads)
        self.assertEqual(again, [], "met before is not new")

    def test_employer_openings_is_the_whole_chain_with_no_network(self):
        report: dict = {}
        out = job_discovery.employer_openings(
            ["Business Development Associate", "Operations Coordinator"], limit=10,
            country="United States", known=KNOWN, now=NOW, report=report,
            searcher=lambda s, p: self.answer({"name": "Acme Manufacturing", "website": "https://acme.com",
                                               "careers_url": "", "location": "Sioux Falls, SD", "why": "x"}),
            leads=lambda roles, **kw: [], fetch=site(), feed=lambda b: [], sleeper=lambda s: None)
        titles = [j["title"] for j in out]
        self.assertIn("Business Development Associate", titles)
        self.assertIn("Operations Coordinator", titles)
        self.assertTrue(all(j["score"] > 0 for j in out))
        self.assertEqual(report["crawled"][0]["name"], "Acme Manufacturing")
        today = job_discovery.today(NOW)
        self.assertEqual(today["employers_new"], ["Acme Manufacturing"])
        self.assertGreaterEqual(today["discovered"], 2)


class TheFourthSourceSharesTheSlot(Isolated):
    def search(self, crawled, *, limit=9, companies=3, anywhere=3, rows=12):
        board_rows = [{"title": "Account Manager", "company": f"Board{i}", "location": "",
                       "apply_url": f"https://board/{i}"} for i in range(rows)]
        own = [{"title": "Account Manager", "company": f"Own{i}", "location": "",
                "apply_url": f"https://own/{i}", "found_by": "company site"} for i in range(companies)]
        ai = [{"title": "Account Manager", "company": f"Web{i}", "location": "",
               "apply_url": f"https://web/{i}", "found_by": "ai web search"} for i in range(anywhere)]
        with mock.patch.object(jobs, "boards", return_value=[{"provider": "greenhouse", "token": "t"}]):
            return jobs.search_many(["Account Manager"], fetcher=lambda b: board_rows, limit=limit,
                                    discover=True, http=lambda q: {"links": []},
                                    companies=lambda roles, **kw: own,
                                    websearch=lambda roles, **kw: ai,
                                    employers=lambda roles, **kw: crawled)

    @staticmethod
    def crawled(n, title="Account Manager"):
        return [{"title": title, "company": f"Crawl{i}", "location": "Sioux Falls, SD",
                 "apply_url": f"https://crawl/{i}", "posting_url": f"https://crawl{i}.com/jobs/{i}",
                 "provider": "company site", "found_by": "employer crawl"} for i in range(n)]

    def test_her_own_crawl_gets_a_turn_and_the_boards_keep_two_in_three(self):
        out = self.search(self.crawled(3), limit=12)
        kinds = [j.get("found_by") or "board" for j in out["matches"]]
        self.assertEqual(kinds.count("board"), 8)
        self.assertIn("employer crawl", kinds)
        self.assertIn("company site", kinds)
        self.assertIn("ai web search", kinds)
        self.assertEqual(out["employer_sites"], kinds.count("employer crawl"))

    def test_a_flood_from_the_crawl_does_not_starve_the_others(self):
        out = self.search(self.crawled(40), limit=30)
        kinds = [j.get("found_by") or "board" for j in out["matches"]]
        self.assertEqual(kinds.count("board"), 12)
        self.assertGreaterEqual(kinds.count("company site"), 3)
        self.assertGreaterEqual(kinds.count("ai web search"), 3)

    def test_a_crawl_row_that_does_not_fit_his_roles_is_not_offered(self):
        out = self.search(self.crawled(2, title="Forklift Operator"), limit=12)
        self.assertEqual(out["employer_sites"], 0)

    def test_every_employer_met_is_remembered(self):
        self.search(self.crawled(2), limit=12)
        self.assertIsNotNone(employers.about("Crawl0"))
        self.assertIsNotNone(employers.about("Own0"))
        self.assertIsNotNone(employers.about("Board0"))

    def test_a_test_search_never_crawls_for_real(self):
        with mock.patch.object(jobs, "_employer_openings", side_effect=AssertionError("network")), \
             mock.patch.object(jobs, "boards", return_value=[{"provider": "greenhouse", "token": "t"}]):
            jobs.search_many(["Account Manager"], limit=5, discover=True, fetcher=lambda b: [],
                             http=lambda q: {"links": []}, companies=lambda roles, **kw: [],
                             websearch=lambda roles, **kw: [])


# ---- value ------------------------------------------------------------------------------

def page(**kw):
    base = {"url": "https://boards.greenhouse.io/embed/job_app?for=acme&token=1",
            "posting": "https://acme.com/jobs/1", "title": "Business Development Associate — Acme",
            "company": "Acme", "provider": "greenhouse", "direct": True, "score": 1.0}
    base.update(kw)
    return base


class OpeningsAreScoredForValue(Isolated):
    def value(self, **kw):
        return job_value.score(page(**kw), known=KNOWN, early=True, employer=kw.pop("employer", None),
                               risky=set(), now=NOW)

    def test_the_index_is_coarse_and_says_where(self):
        self.assertEqual(job_value.col_index("Sioux Falls, SD"), (93, "SD"))
        self.assertEqual(job_value.col_index("San Francisco, CA")[0], 180)
        self.assertEqual(job_value.col_index("Remote"), (100, ""))
        self.assertEqual(job_value.col_index("Madison, Wisconsin"), (97, "Wisconsin"))

    def test_his_floor_depends_on_where(self):
        self.assertEqual(job_value.pay_floor(KNOWN, "Sioux Falls, SD"), 95000)
        self.assertEqual(job_value.pay_floor(KNOWN, "Remote"), 100000)
        self.assertEqual(job_value.pay_floor({}, "Remote"), 0)

    def test_pay_is_read_from_the_record_or_the_posting(self):
        self.assertEqual(job_value.annual_pay({"salary": [45, 55], "salary_unit": "HOUR"}), (93600, 114400))
        self.assertEqual(job_value.annual_pay({}, "The range is $106,802.50 &mdash; $161,550 USD."),
                         (106802.5, 161550))
        self.assertIsNone(job_value.annual_pay({}, "competitive pay"))

    def test_below_the_floor_ranks_under_above_it(self):
        low = self.value(location="Remote", salary=[60000, 80000])
        high = self.value(location="Remote", salary=[105000, 130000])
        self.assertLess(low["value"], high["value"])
        self.assertTrue(any("below your" in r for r in low["why_not"]))
        self.assertTrue(any("above your floor" in r for r in high["why_she_liked_it"]))

    def test_the_ecg_shape_is_an_outlier_that_ranks_up(self):
        small = {"name": "Acme Manufacturing", "jobs_seen": 6, "high_value": False}
        said = self.value(location="Sioux Falls, SD", salary=[110000, 130000], provider="company site",
                          direct=False, employer=small)
        self.assertEqual(said["queue"], "outlier")
        self.assertTrue(any("unusually good pay" in r for r in said["why_she_liked_it"]))
        self.assertTrue(any("small employer" in r for r in said["why_she_liked_it"]))
        plain = self.value(location="Remote", salary=[105000, 130000])
        self.assertEqual(plain["queue"], "best-fit")
        self.assertGreater(said["value"], plain["value"])

    def test_geography_and_ease_count(self):
        abroad = self.value(location="Dublin, Ireland", salary=[110000, 130000])
        self.assertLess(abroad["value"], 0)
        wall = self.value(location="Remote", needs_account=True, provider="account site", direct=False)
        form = self.value(location="Remote")
        self.assertLess(wall["value"], form["value"])
        self.assertIn("wants an account first", " ".join(wall["why_not"]))
        senior = self.value(title="Senior Director, Business Development — Acme", location="Remote")
        self.assertLess(senior["value"], form["value"])

    def test_the_rules_he_cannot_be_talked_out_of_still_hold(self):
        spanish = self.value(title="Business Development Associate - Spanish Speaking — Acme",
                             location="Remote", salary=[110000, 130000])
        self.assertEqual(spanish["queue"], "")
        self.assertIn("speaks Spanish", " ".join(spanish["why_not"]))
        dup = job_value.score(page(location="Remote"), known=KNOWN, early=True, taken=True, risky=set(), now=NOW)
        self.assertLess(dup["value"], 0)
        scam = job_value.score(page(location="Remote", salary=[600000, 900000]), known=KNOWN, early=True,
                               text="Send a wire transfer for your training fee.", risky=set(), now=NOW)
        self.assertLess(scam["value"], 0)
        self.assertTrue(any("scam" in r for r in scam["why_not"]))
        nowhere = self.value(location="Remote", posting="", url="https://www.indeed.com/viewjob?jk=1")
        self.assertIn("no employer address", " ".join(nowhere["why_not"]))

    def test_rank_writes_the_reasons_and_orders_by_value(self):
        pages = [page(url="a", location="Dublin, Ireland"),
                 page(url="b", location="Sioux Falls, SD", salary=[110000, 130000]),
                 page(url="c", location="Remote")]
        read = []
        ranked = job_value.rank(pages, known=KNOWN, describe=lambda p: read.append(p["url"]) or "", risky=set())
        self.assertEqual([p["url"] for p in ranked], ["b", "c", "a"])
        self.assertTrue(all(isinstance(p["why_she_liked_it"], list) for p in ranked))
        self.assertEqual(read, ["b", "c", "a"], "the posting text is read for the top ones")
        why = job_value.why(ranked[0])
        self.assertTrue(why.startswith("I liked it because"))
        self.assertNotIn("_", why)

    def test_between_equals_the_order_given_holds(self):
        pages = [page(url=f"u{i}", location="Remote") for i in range(5)]
        ranked = job_value.rank(pages, known=KNOWN, risky=set())
        self.assertEqual([p["url"] for p in ranked], ["u0", "u1", "u2", "u3", "u4"])


class TheCampaignTriesOpeningsInValueOrder(Isolated):
    def setUp(self):
        super().setUp()
        for target, name, value in ((campaign, "LOCK_PATH", self.root / "running.json"),
                                    (campaign, "RUN_DIR", self.root)):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        profile.save({k: {"value": v, "at": "2026-09-01T00:00:00Z"} for k, v in KNOWN.items()})

    def test_the_best_value_is_tried_first_and_the_reason_is_kept(self):
        openings = [
            {"title": "Business Development Associate", "company": "Far Away", "location": "Dublin, Ireland",
             "apply_url": "https://far/1", "posting_url": "https://faraway.com/jobs/1", "score": 1.0},
            {"title": "Business Development Associate", "company": "Acme Manufacturing",
             "location": "Sioux Falls, SD", "apply_url": "https://acme/1",
             "posting_url": "https://acme.com/careers/1", "provider": "company site", "direct": False,
             "salary": [110000, 130000], "score": 1.0},
            {"title": "Business Development Associate", "company": "Big Co", "location": "Remote",
             "apply_url": "https://big/1", "posting_url": "https://big.com/jobs/1", "score": 1.0},
        ]
        tried, kept = [], []

        def stager(url, resume="", note="", extra=None, found_on=""):
            tried.append(url)
            return {"id": url, "url": url, "state": "AWAITING_YOU", "questions": []}
        with mock.patch.object(campaign, "read_resume", return_value=("resume.pdf", "resume text")), \
             mock.patch.object(campaign, "_application_url", side_effect=lambda url, opener=None: (url, [])), \
             mock.patch.object(apply_run, "all_runs", return_value=[]), \
             mock.patch.object(apply_run, "remember",
                               side_effect=lambda rid, **f: kept.append((rid, f)) or {"id": rid, "state": "AWAITING_YOU", **f}):
            out = campaign.run("Business Development Associate", count=3, json_think=False,
                               searcher=lambda roles, **kw: {"matches": openings, "searched": 1},
                               stager=stager, draft_essays_too=False, fit_think=False)
        self.assertEqual(tried[:2], ["https://acme/1", "https://big/1"])
        first = next(f for rid, f in kept if rid == "https://acme/1")
        self.assertEqual(first["queue"], "outlier")
        self.assertTrue(any("unusually good pay" in r for r in first["why_she_liked_it"]))
        summary = job_discovery.today()
        self.assertEqual(summary["outliers"][0]["company"], "Acme Manufacturing")
        self.assertIn("unusually good", job_discovery.spoken(summary))


class TheDayIsSummarised(Isolated):
    def test_counts_add_up_and_names_are_kept_once(self):
        job_discovery.record(discovered=200, employers_new=["Acme", "Beta"], now=NOW)
        job_discovery.record(discovered=112, qualified=9, employers_new=["Acme"],
                             outliers=[{"company": "Acme", "title": "BD Associate", "why": "pay"},
                                       {"company": "Acme", "title": "BD Associate", "why": "again"}], now=NOW)
        today = job_discovery.today(NOW)
        self.assertEqual((today["discovered"], today["qualified"]), (312, 9))
        self.assertEqual(today["employers_new"], ["Acme", "Beta"])
        self.assertEqual(len(today["outliers"]), 1)
        said = job_discovery.spoken(today)
        self.assertIn("312 openings", said)
        self.assertIn("BD Associate at Acme", said)
        self.assertIn("2 employers I had never seen", said)
        self.assertEqual(job_discovery.spoken(None), "I have not gone looking for jobs yet today.")
        self.assertIsNone(job_discovery.today(NOW + dt.timedelta(days=1)))


if __name__ == "__main__":
    unittest.main()
