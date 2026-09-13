"""Being third in a list is not a reason to be invisible.

`discover_openings` searched `job-boards.greenhouse.io`, then
`boards.greenhouse.io`, then `jobs.lever.co`, sharing ONE result list with
an early return at `limit`. The two Greenhouse hosts filled the quota, so
Lever was usually never searched at all — which is why, asked why she only
applies on Greenhouse, the answer was partly "because the code never looks
anywhere else".

This is the same starvation the comment one level up already describes,
where thirty-six configured boards crowded out the web search entirely and
"every slot went to Stripe and Databricks". The fix there was to always run
the search; the fix here is to give every site its own bucket and
interleave them.
"""
from __future__ import annotations

import collections
import unittest

from aletheia import jobs


def _links(site, prefix, n):
    if "lever" in site:
        return [{"href": f"https://jobs.lever.co/{prefix}{i}/"
                         f"00000000-0000-4000-8000-{i:012d}",
                 "text": f"Sales Rep at {prefix}{i}"} for i in range(n)]
    host = "job-boards" if "job-boards" in site else "boards"
    return [{"href": f"https://{host}.greenhouse.io/{prefix}{i}/jobs/{1000 + i}",
             "text": f"Job Application for Sales Rep at {prefix}{i}"}
            for i in range(n)]


def searcher(counts):
    """A stub search: how many results each board host returns."""
    calls = []

    def http(query):
        for site, n in counts.items():
            if site in query:
                calls.append(site)
                return {"links": _links(site, site.split(".")[0], n)}
        return {"links": []}
    http.calls = calls
    return http


ALL_RICH = {s: 20 for s in jobs.SEARCH_SITES}


class EverySiteIsSearched(unittest.TestCase):
    def test_lever_is_searched_even_when_greenhouse_is_full(self):
        """The bug: two Greenhouse hosts returning plenty meant the Lever
        search never ran."""
        http = searcher(ALL_RICH)
        jobs.discover_openings(["Sales Rep"], limit=9, http=http)
        self.assertIn("jobs.lever.co", http.calls)

    def test_results_come_from_more_than_one_provider(self):
        out = jobs.discover_openings(["Sales Rep"], limit=9,
                                     http=searcher(ALL_RICH))
        providers = collections.Counter(j["provider"] for j in out)
        self.assertEqual(len(out), 9)
        self.assertIn("lever", providers)
        self.assertIn("greenhouse", providers)

    def test_no_single_host_takes_every_slot(self):
        out = jobs.discover_openings(["Sales Rep"], limit=9,
                                     http=searcher(ALL_RICH))
        by_host = collections.Counter(j["board"][:4] for j in out)
        self.assertLess(max(by_host.values()), len(out),
                        "one host took every slot — that is the starvation")


class ItStillFillsUp(unittest.TestCase):
    """Fairness must not cost him openings. A site with nothing to give
    should not reserve slots that another site could have filled."""

    def test_an_empty_lever_does_not_shrink_the_results(self):
        counts = dict(ALL_RICH, **{"jobs.lever.co": 0})
        out = jobs.discover_openings(["Sales Rep"], limit=9,
                                     http=searcher(counts))
        self.assertEqual(len(out), 9)

    def test_one_site_alone_can_fill_the_limit(self):
        counts = {s: 0 for s in jobs.SEARCH_SITES}
        counts["job-boards.greenhouse.io"] = 30
        out = jobs.discover_openings(["Sales Rep"], limit=9,
                                     http=searcher(counts))
        self.assertEqual(len(out), 9)

    def test_the_limit_is_never_exceeded(self):
        for limit in (1, 2, 5, 9, 25):
            with self.subTest(limit=limit):
                out = jobs.discover_openings(["Sales Rep"], limit=limit,
                                             http=searcher(ALL_RICH))
                self.assertLessEqual(len(out), limit)

    def test_nothing_anywhere_is_an_empty_list(self):
        counts = {s: 0 for s in jobs.SEARCH_SITES}
        self.assertEqual(
            jobs.discover_openings(["Sales Rep"], limit=9, http=searcher(counts)),
            [])

    def test_no_duplicates_across_sites(self):
        out = jobs.discover_openings(["Sales Rep"], limit=20,
                                     http=searcher(ALL_RICH))
        urls = [j["apply_url"] for j in out]
        self.assertEqual(len(urls), len(set(urls)))


class WhenTheEnginesRefuse(unittest.TestCase):
    def test_a_refusal_keeps_what_earlier_sites_found(self):
        """A 202 challenge from one engine used to return immediately and
        throw away the whole run. Whatever was already found is his."""
        def http(query):
            if "job-boards.greenhouse.io" in query:
                return {"links": _links("job-boards.greenhouse.io", "acme", 5)}
            return {"links": [], "error": "202 challenge"}
        out = jobs.discover_openings(["Sales Rep"], limit=9, http=http)
        self.assertEqual(len(out), 5)

    def test_a_search_that_raises_does_not_lose_the_other_sites(self):
        def http(query):
            if "jobs.lever.co" in query:
                raise RuntimeError("network")
            return {"links": _links("boards.greenhouse.io", "beta", 4)}
        out = jobs.discover_openings(["Sales Rep"], limit=9, http=http)
        self.assertTrue(out)
        self.assertTrue(all(j["provider"] == "greenhouse" for j in out))



class AddingASystemIsARow(unittest.TestCase):
    """Greenhouse and Lever were two hardcoded regexes and two hardcoded
    URL shapes, so a third system meant editing the search list, the
    matcher and the converter in three places. That is how "she only
    applies on Greenhouse" happens."""

    def test_the_search_sites_are_derived_from_the_table(self):
        """Two lists to keep in step is one list to forget."""
        self.assertEqual(set(jobs.SEARCH_SITES), {a.site for a in jobs.ATS})

    def test_she_can_reach_more_than_greenhouse_and_lever(self):
        providers = {a.provider for a in jobs.ATS}
        self.assertGreaterEqual(len(providers), 5)
        self.assertIn("greenhouse", providers)
        self.assertIn("lever", providers)

    def test_a_job_url_on_each_system_is_recognised(self):
        cases = {
            "https://job-boards.greenhouse.io/acme/jobs/4001": "greenhouse",
            "https://boards.greenhouse.io/acme/jobs/4002": "greenhouse",
            "https://jobs.lever.co/acme/00000000-0000-4000-8000-000000000001": "lever",
            "https://jobs.ashbyhq.com/acme/00000000-0000-4000-8000-000000000002": "ashby",
            "https://apply.workable.com/acme/j/ABCD1234/": "workable",
            "https://jobs.smartrecruiters.com/Acme/744000012345": "smartrecruiters",
            "https://acme.recruitee.com/o/sales-rep": "recruitee",
        }
        for url, provider in cases.items():
            with self.subTest(url=url):
                found = jobs.job_from_url(url)
                self.assertIsNotNone(found, url)
                self.assertEqual(found[0].provider, provider)

    def test_a_page_that_is_not_a_job_is_not_one(self):
        for url in ("https://example.com/careers/123",
                    "https://jobs.lever.co/acme",
                    "https://www.linkedin.com/jobs/view/123456",
                    ""):
            with self.subTest(url=url):
                self.assertIsNone(jobs.job_from_url(url))

    def test_every_system_builds_an_apply_url_for_its_own_job(self):
        """A row whose apply shape is wrong sends her to a page that is not
        an application, and the failure looks like a broken form."""
        for ats in jobs.ATS:
            with self.subTest(provider=ats.provider):
                url = ats.apply("acme", "12345678-0000-4000-8000-000000000001")
                self.assertTrue(url.startswith("https://"), url)
                self.assertIn("acme", url)

    def test_a_new_system_widens_the_sweep_without_other_edits(self):
        """The point of the table: one row, and discovery finds it."""
        found = jobs.discover_openings(
            ["Sales Rep"], limit=6,
            http=lambda q: {"links": [{
                "href": "https://jobs.ashbyhq.com/acme/"
                        "00000000-0000-4000-8000-000000000002",
                "text": "Sales Rep at Acme"}]} if "ashbyhq" in q else {"links": []})
        self.assertTrue(any(j["provider"] == "ashby" for j in found))

if __name__ == "__main__":
    unittest.main()
