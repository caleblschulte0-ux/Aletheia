"""Casting the net where the jobs actually are.

His words, 2026-09-13: *"there are companies all over the country that
only have [jobs] on their website. Like, I've never heard of that I
probably would like to work at."*

Three things were wrong, and this file holds all three:

  * the web search carried NO geography — `site:greenhouse.io "Account
    Executive"` and whatever the engine ranked, which is San Francisco;
  * a web-found job's location was an empty string that `_in_country`
    reads as "not ruled out" and everything downstream reads as "fine";
  * a company with no applicant-tracking system was invisible, and those
    are most companies.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import careers, jobs


# ---------------------------------------------------------------- geography

class WhereToLook(unittest.TestCase):
    def test_his_town_and_state_come_from_his_profile(self):
        """Never a list in code: the place he lives is a fact about him."""
        self.assertEqual(
            jobs.places_to_search({"home_city": "Hartford", "state": "South Dakota"}),
            ["Hartford, South Dakota", "South Dakota", "remote"])

    def test_remote_is_always_there_and_always_last(self):
        """Last so it fills what is left rather than crowding out the
        places he could drive to."""
        for known in ({"home_city": "Hartford", "state": "South Dakota"},
                      {"state": "Iowa"}, {}):
            with self.subTest(known=known):
                places = jobs.places_to_search(known)
                self.assertEqual(places[-1], "remote")
                self.assertEqual(places.count("remote"), 1)

    def test_knowing_nothing_is_remote_not_a_guess(self):
        """A profile with no home town must not invent one."""
        self.assertEqual(jobs.places_to_search({}), ["remote"])

    def test_the_sweep_is_bounded(self):
        """Each place is another search, and the engines answer the later
        ones with a challenge page."""
        known = {"home_city": "Hartford", "state": "South Dakota",
                 "also_search": ["Sioux Falls", "Minneapolis", "Omaha", "Denver"]}
        self.assertLessEqual(len(jobs.places_to_search(known)),
                             jobs.MAX_PLACES_PER_SWEEP)

    def test_an_explicit_where_beats_the_profile(self):
        self.assertEqual(
            jobs.places_to_search(jobs._where_from_profile("Denver, CO")),
            ["Denver, CO", "remote"])


class ThePlaceGoesInTheQuery(unittest.TestCase):
    """A filter cannot recover a local job the engine never returned."""

    def _asked(self, where):
        asked = []

        def http(query):
            asked.append(query)
            return {"links": []}
        jobs.discover_openings(["Account Executive"], where=where, limit=5, http=http)
        return asked

    def test_the_place_is_in_every_query(self):
        asked = self._asked("South Dakota")
        self.assertTrue(asked)
        for query in asked:
            self.assertIn('"South Dakota"', query)

    def test_no_place_asked_means_no_place_in_the_query(self):
        for query in self._asked(""):
            self.assertNotIn('""', query)

    def test_the_role_survives_the_place(self):
        for query in self._asked("Iowa"):
            self.assertIn('"Account Executive"', query)


class AnUnknownLocationSaysSo(unittest.TestCase):
    """The bug: a web-found job got `location: ""`, `_in_country` reads an
    empty location as "not ruled out", and everything downstream read it
    as a job he could take. She did not know where a single one was."""

    def _one(self, where="South Dakota"):
        def http(query):
            return {"links": [{
                "href": "https://job-boards.greenhouse.io/acme/jobs/4001",
                "text": "Job Application for Account Executive at Acme"}]}
        return jobs.discover_openings(["Account Executive"], where=where,
                                      limit=1, http=http)[0]

    def test_a_web_found_job_admits_its_location_is_unknown(self):
        job = self._one()
        self.assertFalse(job["location_known"])

    def test_it_records_which_place_surfaced_it(self):
        """Evidence, not a claim: the engine was ASKED about South Dakota."""
        self.assertEqual(self._one("South Dakota")["found_for_place"],
                         "South Dakota")

    def test_an_empty_location_is_still_not_ruled_out(self):
        """Deliberate, and unchanged: dropping a job because we do not know
        where it is would throw away most of what the search finds."""
        self.assertTrue(jobs._in_country("", "United States"))

    def test_a_board_job_still_carries_its_real_location(self):
        """The configured boards get a real location from the provider's
        API. Only the SEARCH half is blind, and it must not infect this."""
        self.assertFalse(jobs._in_country("Dublin, Ireland", "United States"))
        self.assertTrue(jobs._in_country("Sioux Falls, SD", "United States"))


# ------------------------------------------------------- company own site

def page(text="", links=(), url="https://acme.com/careers"):
    return {"url": url, "title": "Careers", "text": text,
            "links": [{"text": t, "href": h} for t, h in links]}


class ACareersPageIsNotAnyPageSayingCareers(unittest.TestCase):
    def test_a_page_that_lists_jobs_is_one(self):
        for text in ("Open Positions", "Current Openings", "View all jobs",
                     "We're hiring", "Join our team", "Now hiring"):
            with self.subTest(text=text):
                self.assertTrue(careers.looks_like_careers(text))

    def test_a_page_about_working_somewhere_is_not(self):
        for text in ("Our culture is what sets us apart",
                     "Read about life at Acme",
                     "Acme was founded in 1974"):
            with self.subTest(text=text):
                self.assertFalse(careers.looks_like_careers(text))

    def test_nothing_open_is_an_answer_not_a_failure(self):
        """A company with nothing open today is worth asking again next
        month. A broken parser is not, and the two must not look alike."""
        out = careers.openings_on("https://acme.com/careers", reader=lambda u:
                                  page("No current openings. Check back soon."))
        self.assertEqual(out["state"], careers.NOTHING_OPEN)
        self.assertEqual(out["openings"], [])

    def test_a_page_that_is_not_careers_says_that_instead(self):
        out = careers.openings_on("https://acme.com/about", reader=lambda u:
                                  page("Acme was founded in 1974."))
        self.assertEqual(out["state"], careers.NOT_A_CAREERS_PAGE)

    def test_an_unreadable_page_is_not_an_empty_one(self):
        def boom(url):
            raise RuntimeError("connection reset")
        out = careers.openings_on("https://acme.com/careers", reader=boom)
        self.assertEqual(out["state"], careers.UNREADABLE)
        self.assertIn("careers page", out["why"])


class ReadingTheOpenings(unittest.TestCase):
    LINKS = (
        ("Sales Representative - Apply", "https://acme.com/careers/sales-rep"),
        ("Warehouse Associate position", "/careers/warehouse"),
        ("Account Executive", "https://job-boards.greenhouse.io/acme/jobs/4001"),
        ("Email us your resume", "mailto:jobs@acme.com"),
        ("Privacy policy", "https://acme.com/privacy"),
        ("Employee handbook", "https://acme.com/handbook.pdf"),
        ("Follow us", "https://www.linkedin.com/company/acme"),
    )

    def _read(self):
        return careers.openings_on(
            "https://acme.com/careers",
            reader=lambda u: page("Open Positions", self.LINKS))

    def test_real_postings_are_found(self):
        urls = {j["url"] for j in self._read()["openings"]}
        self.assertIn("https://acme.com/careers/sales-rep", urls)
        self.assertIn("https://acme.com/careers/warehouse", urls)

    def test_a_relative_link_becomes_a_real_address(self):
        """A posting she cannot open is a posting she did not find."""
        urls = [j["url"] for j in self._read()["openings"]]
        self.assertTrue(all(u.startswith(("http", "mailto:")) for u in urls), urls)

    def test_an_ats_link_is_handed_back_to_jobs(self):
        """Most mid-size companies link out to Greenhouse. jobs.job_from_url
        already knows those shapes and stays the one implementation."""
        found = next(j for j in self._read()["openings"]
                     if "greenhouse" in j["url"])
        self.assertEqual(found["kind"], careers.ATS)

    def test_send_us_your_resume_is_recorded_as_an_email(self):
        """Half the 'apply' links on the internet are a mailto. What it IS
        gets recorded, so the caller does not discover it three steps on."""
        found = next(j for j in self._read()["openings"]
                     if j["url"].startswith("mailto:"))
        self.assertEqual(found["kind"], careers.MAILTO)

    def test_furniture_is_left_out(self):
        urls = " ".join(j["url"] for j in self._read()["openings"])
        for junk in ("privacy", "handbook.pdf", "linkedin.com"):
            self.assertNotIn(junk, urls)

    def test_every_opening_says_where_it_came_from(self):
        for job in self._read()["openings"]:
            self.assertEqual(job["found_by"], "careers page")
            self.assertTrue(job["careers_page"])


class FindingTheCareersPage(unittest.TestCase):
    def test_an_aggregator_is_not_the_company(self):
        """Indeed's page ABOUT Acme is not Acme's careers page."""
        asked = []

        def http(q):
            return {"links": [
                {"href": "https://www.indeed.com/cmp/Acme/jobs"},
                {"href": "https://acme.com/careers"}]}

        def reader(url):
            asked.append(url)
            return page("Open Positions",
                        (("Sales Rep - Apply", "/careers/sales"),))
        out = careers.find_careers_page("Acme", http=http, reader=reader)
        self.assertEqual(out["state"], "ok")
        self.assertNotIn("https://www.indeed.com/cmp/Acme/jobs", asked)

    def test_the_common_paths_are_tried_when_search_finds_nothing(self):
        tried = []

        def reader(url):
            tried.append(url)
            if url.rstrip("/").endswith("/careers"):
                return page("Open Positions", (("Apply here", "/jobs/1"),))
            raise RuntimeError("404")
        out = careers.find_careers_page(
            "Acme", http=lambda q: {"links": []}, reader=reader, site="acme.com")
        self.assertEqual(out["state"], "ok")
        self.assertTrue(any(u.endswith("/careers") for u in tried))

    def test_a_company_with_no_findable_page_says_so(self):
        out = careers.find_careers_page(
            "Nowhere Inc", http=lambda q: {"links": []},
            reader=lambda u: page("nothing here"))
        self.assertEqual(out["state"], careers.NOT_A_CAREERS_PAGE)
        self.assertIn("Nowhere Inc", out["why"])

    def test_a_company_needs_a_name(self):
        with self.assertRaises(ValueError):
            careers.find_careers_page("")

    def test_it_reads_and_never_presses_anything(self):
        """Applying is formfill's and apply_run's job, under an approval.
        This module finds the door."""
        import ast
        with open("aletheia/careers.py", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                base = getattr(node.func.value, "id", "")
                if base == "browse" and node.func.attr != "read_page":
                    self.fail(f"careers calls browse.{node.func.attr}")
                if node.func.attr in ("interact", "click", "fill", "press", "submit"):
                    self.fail(f"careers calls {base}.{node.func.attr}")


if __name__ == "__main__":
    unittest.main()


class TheCampaignAsksTheCompaniesThemselves(unittest.TestCase):
    """Built and wired, not built and left sitting. The careers sweep runs
    when the boards and the web search came up short of the target."""

    def test_it_turns_careers_rows_into_the_same_shape_jobs_returns(self):
        """So the campaign does not learn a second vocabulary."""
        rows = [{"title": "Sales Rep", "url": "https://acme.com/careers/sales",
                 "kind": careers.PAGE, "careers_page": "https://acme.com/careers"}]
        job = careers.as_openings(rows, company="Acme")[0]
        for key in ("title", "company", "location", "posting_url", "apply_url",
                    "provider", "board", "id"):
            self.assertIn(key, job)
        self.assertEqual(job["company"], "Acme")
        self.assertFalse(job["location_known"])

    def test_a_posting_page_is_its_own_apply_url(self):
        rows = [{"title": "Sales Rep", "url": "https://acme.com/careers/sales",
                 "kind": careers.PAGE}]
        job = careers.as_openings(rows)[0]
        self.assertEqual(job["apply_url"], "https://acme.com/careers/sales")
        self.assertEqual(job["provider"], "careers-page")

    def test_an_ats_link_is_converted_by_jobs_not_reimplemented(self):
        rows = [{"title": "AE", "kind": careers.ATS,
                 "url": "https://job-boards.greenhouse.io/acme/jobs/4001"}]
        job = careers.as_openings(rows)[0]
        self.assertEqual(job["provider"], "greenhouse")
        self.assertIn("job_app", job["apply_url"])

    def test_a_mailto_is_dropped_rather_than_faked(self):
        """Applying by email is a capability that does not exist yet. A row
        that cannot be applied to must not reach the stager as if it could."""
        rows = [{"title": "Email us", "url": "mailto:jobs@acme.com",
                 "kind": careers.MAILTO}]
        self.assertEqual(careers.as_openings(rows), [])

    def test_the_sweep_is_bounded(self):
        """A board is one API call for all its jobs; a careers page is a
        page read per company. Unbounded, this is his whole evening."""
        from aletheia import campaign
        read = []

        def reader(url):
            read.append(url)
            return page("Open Positions", (("Apply", "/jobs/1"),))
        hits = {"matches": [{"company": f"Company {i}"} for i in range(50)]}
        campaign._careers_page_openings(
            hits, ["Sales Rep"], want=999,
            reader=reader, http=lambda q: {"links": [{"href": "https://x.com/careers"}]})
        self.assertLessEqual(len(read), campaign.CAREERS_PAGES_PER_RUN * 2)

    def test_it_asks_about_employers_already_in_hand(self):
        """Inventing company names to look up would be a guess, and a guess
        costs a page read and returns somebody else's business."""
        from aletheia import campaign
        asked = []

        def http(query):
            asked.append(query)
            return {"links": []}
        campaign._careers_page_openings(
            {"matches": [{"company": "Raven Industries"}]}, ["Sales Rep"],
            want=3, http=http, reader=lambda u: page("nothing"))
        self.assertTrue(any("Raven Industries" in q for q in asked))

    def test_nothing_in_hand_asks_nobody(self):
        from aletheia import campaign
        def explode(*a, **k):
            raise AssertionError("must not search with no employer in hand")
        self.assertEqual(
            campaign._careers_page_openings({"matches": []}, ["x"], want=3,
                                            http=explode, reader=explode), [])

    def test_a_company_whose_site_fails_does_not_stop_the_sweep(self):
        from aletheia import campaign
        def http(q):
            if "Bad" in q:
                raise RuntimeError("network")
            return {"links": [{"href": "https://good.com/careers"}]}
        out = campaign._careers_page_openings(
            {"matches": [{"company": "Bad Co"}, {"company": "Good Co"}]},
            ["Sales Rep"], want=3, http=http,
            reader=lambda u: page("Open Positions", (("Apply now", "/jobs/1"),)))
        self.assertTrue(out)
