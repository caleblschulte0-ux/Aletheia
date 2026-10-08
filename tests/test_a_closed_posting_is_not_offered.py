"""A posting the board no longer lists is not offered to the batch.

Live 2026-10-08, 15 of three days' closures were postings already gone, 9 on
Ashby, whose closed postings still answer 200 with an empty shell. Each one
was found by a search that remembered it and cost a slot and a browser.
"""
import unittest
from unittest import mock

from aletheia import jobs


def job(provider, board, jid, found_by="web search"):
    return {"provider": provider, "board": board, "id": jid, "found_by": found_by,
            "apply_url": f"https://{provider}.example/{board}/{jid}"}


class AClosedPostingIsNotOffered(unittest.TestCase):
    def test_a_job_its_board_no_longer_lists_is_left_out(self):
        kept, gone = jobs.drop_unlisted(
            [job("ashby", "Acme", "OPEN-1"), job("ashby", "acme", "closed-2")],
            listed={("ashby", "acme"): {"open-1", "other"}})
        self.assertEqual([j["id"] for j in kept], ["OPEN-1"])
        self.assertEqual(gone, 1)

    def test_a_board_not_read_yet_is_read_once(self):
        asked = []

        def lister(provider, token):
            asked.append((provider, token))
            return [{"id": "1"}]

        kept, gone = jobs.drop_unlisted(
            [job("lever", "beta", "1"), job("lever", "beta", "2")], lister=lister)
        self.assertEqual(asked, [("lever", "beta")])
        self.assertEqual([j["id"] for j in kept], ["1"])
        self.assertEqual(gone, 1)

    def test_it_fails_open(self):
        def broken(provider, token):
            raise OSError("no network")

        found = [job("greenhouse", "gamma", "9"), job("ashby", "empty", "3"),
                 job("workable", "delta", "ABCDEFGH"), job("company site", "x.com", "u")]
        kept, gone = jobs.drop_unlisted(found, listed={("ashby", "empty"): set()}, lister=broken)
        self.assertEqual(kept, found)
        self.assertEqual(gone, 0)

    def test_search_many_leaves_a_closed_search_result_out(self):
        rows = [{"title": "Account Executive", "company": "Acme", "location": "Remote",
                 "provider": "ashby", "board": "acme", "id": "open-1",
                 "apply_url": "https://jobs.ashbyhq.com/acme/open-1/application"}]

        def fetcher():
            return rows, [], 1

        web = [{**job("ashby", "acme", "closed-2", "ai web search"), "title": "Account Executive",
                "company": "Acme", "location": "Remote", "score": 1},
               {**job("ashby", "acme", "open-1", "ai web search"), "title": "Account Executive",
                "company": "Acme", "location": "Remote", "score": 1,
                "apply_url": "https://jobs.ashbyhq.com/acme/open-1/application"}]
        with mock.patch.object(jobs, "_gather", lambda f: (list(rows), [], 1)):
            out = jobs.search_many(["account executive"], limit=10, fetcher=fetcher, discover=True,
                                   http=lambda q: {"links": []}, companies=lambda *a, **k: [],
                                   websearch=lambda *a, **k: web, employers=lambda *a, **k: [])
        self.assertNotIn("closed-2", [m["id"] for m in out["matches"]])
        self.assertEqual(out["unlisted"], 1)


if __name__ == "__main__":
    unittest.main()
