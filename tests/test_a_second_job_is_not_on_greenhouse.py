"""The local employer is not on Greenhouse, and that is where he lives.

His words, 2026-09-25, wanting a SECOND job in Sioux Falls - a bar, a gym, a
tanning salon, and "I don't give a shit" which one: *"I didn't make a whole
fucking bot to, that can apply for jobs to, for it to tell me it can't apply
to fucking jobs."*

He was right. The six systems she could LIST are what tech and corporate
employers run. The YMCA down the road from him runs BambooHR, which publishes
exactly the same shape - `/careers/list` is public JSON, `/careers/<id>` is
the posting, and the application form is on that page. Measured live the day
this was written against the Sioux Falls YMCA: five openings, four of them
part-time, one of them in Hartford, which is his town.

The network is stubbed here; the endpoint itself was proved with a real
request first.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import jobs

LIST = {"result": [
    {"id": 73, "jobOpeningName": "YMCA Gym Supervisor",
     "employmentStatusLabel": "Part-Time", "departmentLabel": "Sports",
     "location": {"city": "Sioux Falls", "state": "South Dakota"}},
    {"id": 70, "jobOpeningName": "Site Lead", "employmentStatusLabel": "Part-Time",
     "departmentLabel": "Child Care",
     "location": {"city": "Hartford", "state": "South Dakota"}},
    {"id": 0, "jobOpeningName": "no id, dropped", "location": {}},
]}


class TheLocalBoardIsSearchable(unittest.TestCase):
    MISSING = object()

    def rows(self, payload=MISSING):
        # A sentinel, not `payload or LIST`: {} and None are exactly the
        # payloads this is here to test, and `or` swallowed both.
        sent = LIST if payload is self.MISSING else payload
        with mock.patch.object(jobs, "_fetch", return_value=sent) as got:
            out = jobs.PROVIDERS["bamboohr"]({"token": "siouxfallsymca",
                                              "company": "Sioux Falls YMCA"})
        self.url = got.call_args[0][0]
        return out

    def test_it_reads_the_public_list_and_keeps_the_part_time_label(self):
        rows = self.rows()
        self.assertEqual(self.url, "https://siouxfallsymca.bamboohr.com/careers/list")
        self.assertEqual(len(rows), 2, "a row with no id is dropped, not guessed at")
        gym = rows[0]
        self.assertEqual(gym["title"], "YMCA Gym Supervisor")
        self.assertEqual(gym["location"], "Sioux Falls, South Dakota")
        # The thing that makes it a SECOND job is on the row.
        self.assertEqual(gym["employment_type"], "Part-Time")
        self.assertEqual(gym["provider"], "bamboohr")
        self.assertEqual(gym["posting_url"],
                         "https://siouxfallsymca.bamboohr.com/careers/73")
        # BambooHR keeps the form on the posting, so there is no other address.
        self.assertEqual(gym["apply_url"], gym["posting_url"])

    def test_his_own_town_comes_through(self):
        self.assertEqual(self.rows()[1]["location"], "Hartford, South Dakota")

    def test_a_list_rather_than_an_envelope_still_reads(self):
        self.assertEqual(len(self.rows(LIST["result"])), 2)

    def test_junk_is_survived_rather_than_raised(self):
        for payload in (None, {}, {"result": None}, {"result": ["", 3]}):
            with self.subTest(payload=payload):
                self.assertEqual(self.rows(payload), [])


class ALinkToOneIsRecognised(unittest.TestCase):
    """Searching is half of it: a bamboohr link handed to her by a search
    result or a careers page has to be known for what it is."""

    def test_the_url_names_its_board_and_its_job(self):
        found = jobs._BAMBOOHR_JOB.search(
            "https://siouxfallsymca.bamboohr.com/careers/73")
        self.assertTrue(found)
        self.assertEqual(found.group(1), "siouxfallsymca")
        self.assertEqual(found.group(2), "73")

    def test_it_is_in_the_ats_table_and_every_ats_is_searchable(self):
        self.assertIn("bamboohr", {a.provider for a in jobs.ATS})
        self.assertLessEqual({a.provider for a in jobs.ATS}, set(jobs.PROVIDERS))

    def test_a_token_may_never_carry_a_host(self):
        ok = jobs._TOKEN_OK["bamboohr"]
        self.assertTrue(ok.fullmatch("siouxfallsymca"))
        for bad in ("evil.com", "a/b", "a_b", "../x"):
            with self.subTest(bad=bad):
                self.assertFalse(ok.fullmatch(bad))


class ItIsInTheRegistry(unittest.TestCase):
    def test_the_board_is_configured_so_she_searches_it_by_default(self):
        import json
        from aletheia.fleet import REPO_ROOT
        boards = json.loads((REPO_ROOT / "config" / "job_boards.json")
                            .read_text(encoding="utf-8"))["boards"]
        bamboo = [b for b in boards if b.get("provider") == "bamboohr"]
        self.assertTrue(bamboo, "a provider nothing is configured for is not wired")
        for b in bamboo:
            self.assertIn(b["provider"], jobs.PROVIDERS)


if __name__ == "__main__":
    unittest.main()
