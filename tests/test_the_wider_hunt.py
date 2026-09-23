"""His words, 2026-09-23: "it sounds like it's not looking on the widespread
deep corners of the internet that I want if it keeps getting cycled back to
these couple companies." Measured: 373 employers remembered, 228 with no
board and no domain, the same 152 boards read every five minutes in the same
order. A name is a handful of candidate boards; one system searches across
every employer on it; and a different employer leads each batch."""
import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import board_probe, job_discovery, jobs, stateio

NOW = dt.datetime(2026, 9, 23, 13, 0, tzinfo=dt.timezone.utc)


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": self.tmp.name})
        env.start(); self.addCleanup(env.stop)


class ANameIsAHandfulOfBoards(unittest.TestCase):
    def test_the_slugs_per_system(self):
        s = board_probe.slugs("Open Range Interactive, Inc.")
        self.assertEqual(s["greenhouse"], ["openrangeinteractive", "open-range-interactive"])
        self.assertEqual(s["smartrecruiters"][0], "OpenRangeInteractive")
        self.assertEqual(board_probe.slugs("Adyen")["lever"], ["adyen"])
        self.assertEqual(board_probe.slugs(""), {})
        rows = board_probe.candidates("Adyen")
        self.assertTrue(all(c["provider"] in jobs.PROVIDERS for c in rows))
        self.assertIn({"provider": "ashby", "board": "adyen", "company": "Adyen", "found_by": "name probe"}, rows)

    def test_the_published_name_must_be_the_employers(self):
        self.assertTrue(board_probe.same_employer("Adyen N.V.", "Adyen"))
        self.assertTrue(board_probe.same_employer("Notion Labs", "Notion"))
        self.assertTrue(board_probe.same_employer("Advantage Solutions", "Advantage Solutions Inc"))
        self.assertFalse(board_probe.same_employer("Achieve Together", "Achieve"), "one word inside another name")
        self.assertFalse(board_probe.same_employer("Acme Labs", "Beta Labs"), "'Labs' is nobody's name")
        self.assertFalse(board_probe.same_employer("", "Adyen"))


class TheProbeLearnsOnlyLiveBoardsOfTheRightEmployer(Isolated):
    ROWS = [{"name": "Adyen", "ats": "", "token": "", "domains": []},
            {"name": "Achieve", "ats": "", "token": "", "domains": []},
            {"name": "Notion", "ats": "greenhouse", "token": "notion", "domains": ["notion.so"]}]

    def fetcher(self, board):
        # Adyen answers on SmartRecruiters under its own name; "achieve" on
        # Lever is somebody else's board; "achieve" on Recruitee is a trial
        # subdomain with a sample offer (live: "allstate" was); the rest empty.
        if board["provider"] == "smartrecruiters" and board["token"] == "Adyen":
            return [{"title": "Account Manager", "company": "Adyen", "apply_url": "https://x/1", "id": "1"}]
        if board["provider"] == "lever" and board["token"] == "achieve":
            return [{"title": "Nurse", "company": "Achieve Together", "apply_url": "https://x/2", "id": "2"}]
        if board["provider"] == "recruitee" and board["token"] == "achieve":
            return [{"title": "Senior Marketer (Sample)", "company": "Achieve", "apply_url": "https://x/3", "id": "3"}]
        return []

    def test_a_name_becomes_a_board_and_a_collision_does_not(self):
        report = board_probe.probe(fetcher=self.fetcher, now=NOW, rows=self.ROWS, limit=6)
        self.assertEqual(report["tried"], ["Adyen", "Achieve"], "the employer with a board is not probed")
        learned = {(r["provider"], r["token"]): r for r in jobs._learned_boards()}
        self.assertIn(("smartrecruiters", "Adyen"), learned)
        self.assertEqual(learned[("smartrecruiters", "Adyen")]["from"], "name probe")
        self.assertNotIn(("lever", "achieve"), learned, "Achieve Together is not Achieve")
        self.assertNotIn(("recruitee", "achieve"), learned, "a sample offer is not an opening")
        self.assertEqual([f["company"] for f in report["found"]], ["Adyen"])
        self.assertEqual(board_probe.real_openings([{"title": "Demo Job"}, {"title": "Account Manager"}]),
                         [{"title": "Account Manager"}])

    def test_an_employer_is_probed_once_a_month(self):
        board_probe.probe(fetcher=self.fetcher, now=NOW, rows=self.ROWS, limit=6)
        again = board_probe.probe(fetcher=self.fetcher, now=NOW + dt.timedelta(days=1), rows=self.ROWS, limit=6)
        self.assertEqual(again["tried"], [])
        later = board_probe.probe(fetcher=self.fetcher, now=NOW + dt.timedelta(days=31), rows=self.ROWS, limit=6)
        self.assertEqual(later["tried"], ["Achieve"], "Adyen's board is known now; Achieve is due again")

    def test_it_is_bounded_and_never_raises(self):
        many = [{"name": f"Company {i}", "ats": "", "token": ""} for i in range(50)]
        report = board_probe.probe(fetcher=lambda b: [], now=NOW, rows=many, limit=6)
        self.assertEqual(len(report["tried"]), 6)

        def broken(board):
            raise RuntimeError("boom")
        self.assertEqual(board_probe.probe(fetcher=broken, now=NOW, rows=self.ROWS)["found"], [])


class ADifferentEmployerLeadsEachBatch(Isolated):
    def test_the_cursor_rotates_and_survives(self):
        queues = [["a"], ["b"], ["c"]]
        self.assertEqual(jobs._rotated(queues), [["a"], ["b"], ["c"]])
        self.assertEqual(jobs._rotated(queues), [["b"], ["c"], ["a"]])
        self.assertEqual(jobs._rotated(queues), [["c"], ["a"], ["b"]])
        self.assertEqual(json.loads(jobs._rotation_path().read_text())["cursor"], 3)
        self.assertEqual(jobs._rotated([["only"]]), [["only"]])

    def test_a_test_search_with_its_own_fetcher_is_not_rotated(self):
        rows = [{"title": "Account Manager", "company": c, "location": "Remote", "apply_url": f"https://x/{c}",
                 "posting_url": f"https://x/{c}", "provider": "greenhouse", "board": c, "id": c}
                for c in ("alpha", "beta", "gamma")]
        first = [j["company"] for j in jobs.search_many(["Account Manager"], fetcher=lambda b: rows, limit=3)["matches"]]
        second = [j["company"] for j in jobs.search_many(["Account Manager"], fetcher=lambda b: rows, limit=3)["matches"]]
        self.assertEqual(first, second)


class TheDiscoveryPassCarriesTheProbe(Isolated):
    def test_the_prober_runs_on_the_pass(self):
        report: dict = {}
        job_discovery.employer_openings(
            ["Account Manager"], limit=10, known={"city": "Sioux Falls", "state": "SD"}, now=NOW, report=report,
            searcher=lambda s, p: [], leads=lambda roles, **kw: [], fetch=lambda url: None,
            feed=lambda b: [], sleeper=lambda s: None, http=lambda q: {"links": []},
            prober=lambda **kw: {"tried": ["Adyen"], "found": []})
        self.assertEqual(report["probed"]["tried"], ["Adyen"])

    def test_a_pass_with_its_own_site_never_probes_the_network(self):
        with mock.patch.object(board_probe, "probe", side_effect=AssertionError("network")):
            report: dict = {}
            job_discovery.employer_openings(
                ["Account Manager"], limit=10, known={}, now=NOW, report=report,
                searcher=lambda s, p: [], leads=lambda roles, **kw: [], fetch=lambda url: None,
                feed=lambda b: [], sleeper=lambda s: None, http=lambda q: {"links": []})
        self.assertEqual(report["probed"], {})


class TheCapsGrew(unittest.TestCase):
    def test_the_numbers(self):
        from aletheia import career_sites, company_sites
        self.assertGreaterEqual(career_sites.MAX_EMPLOYERS_PER_BATCH, 12)
        self.assertGreaterEqual(company_sites.MAX_LEADS_READ, 100)
        self.assertGreaterEqual(job_discovery.MAX_HTTP_SEARCHES_PER_BATCH, 4)
        self.assertGreaterEqual(jobs.MAX_RESULTS, 90)


if __name__ == "__main__":
    unittest.main()
