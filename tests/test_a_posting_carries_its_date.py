"""Recency scored nothing until 2026-10-07: no board reader carried a date,
so a posting from last year ranked with one from this morning."""

import datetime as dt
import unittest
from unittest import mock

from aletheia import job_value, jobs


class APostingCarriesItsDate(unittest.TestCase):
    def test_greenhouse_says_when_it_went_up(self):
        data = {"jobs": [{"id": 1, "title": "Customer Success Manager",
                          "company_name": "Gong.io", "absolute_url": "https://x/1",
                          "first_published": "2026-10-05T09:00:00-04:00",
                          "updated_at": "2026-10-06T13:12:14-04:00"}]}
        with mock.patch.object(jobs, "_fetch", return_value=data):
            job = jobs._greenhouse({"token": "gongio", "company": "Gong"})[0]
        self.assertTrue(job["posted"].startswith("2026-10-05T09:00"))

    def test_lever_writes_milliseconds(self):
        data = [{"id": "a", "text": "Account Manager", "hostedUrl": "https://x/a",
                 "createdAt": 1790350084485}]
        with mock.patch.object(jobs, "_fetch", return_value=data):
            job = jobs._lever({"token": "aledade"})[0]
        self.assertTrue(job["posted"].startswith("2026-09-25"))

    def test_ashby_says_published(self):
        data = {"jobs": [{"id": "z", "title": "Operations Associate",
                          "publishedAt": "2026-08-24T14:44:49.699+00:00"}]}
        with mock.patch.object(jobs, "_fetch", return_value=data):
            job = jobs._ashby({"token": "notion"})[0]
        self.assertTrue(job["posted"].startswith("2026-08-24"))

    def test_lever_says_what_it_pays(self):
        data = [{"id": "a", "text": "Account Manager", "hostedUrl": "https://x/a",
                 "salaryRange": {"min": 95000, "max": 100000, "currency": "USD",
                                 "interval": "per-year-salary"}},
                {"id": "b", "text": "Account Manager", "hostedUrl": "https://x/b",
                 "salaryRange": {"min": 50000, "max": 60000, "currency": "EUR",
                                 "interval": "per-year-salary"}}]
        with mock.patch.object(jobs, "_fetch", return_value=data):
            paid, euros = jobs._lever({"token": "aledade"})
        self.assertEqual(job_value.annual_pay(paid), (95000.0, 100000.0))
        self.assertNotIn("salary", euros)

    def test_hourly_pay_is_a_year_of_hours(self):
        pay = jobs._lever_pay({"min": 20, "max": 25, "currency": "USD",
                               "interval": "per-hour-wage"})
        self.assertEqual(job_value.annual_pay(pay), (41600.0, 52000.0))

    def test_the_listing_text_ranks_every_opening_on_its_pay(self):
        data = {"jobs": [{"id": "z", "title": "Business Development Representative",
                          "descriptionPlain": "The base salary range is $100,000 - $115,000 per year."}]}
        with mock.patch.object(jobs, "_fetch", return_value=data):
            job = jobs._ashby({"token": "notion"})[0]
        self.assertEqual(job_value.annual_pay(job, job["description"]), (100000.0, 115000.0))

    def test_lever_lists_and_extra_text_travel_too(self):
        data = [{"id": "a", "text": "Account Manager", "hostedUrl": "https://x/a",
                 "descriptionPlain": "About the role.",
                 "lists": [{"text": "Requirements", "content": "<li>2+ years in B2B</li>"}],
                 "additionalPlain": "Pay: $70,000 - $80,000"}]
        with mock.patch.object(jobs, "_fetch", return_value=data):
            job = jobs._lever({"token": "x"})[0]
        for words in ("About the role.", "Requirements", "2+ years in B2B", "$70,000"):
            self.assertIn(words, job["description"])
        self.assertNotIn("<li>", job["description"])

    def test_greenhouse_text_comes_with_the_listing(self):
        data = {"jobs": [{"id": 1, "title": "Account Manager", "absolute_url": "https://x/1",
                          "content": "&lt;p&gt;The annual OTE is $160,000 - $210,000 USD.&lt;/p&gt;"}]}
        asked = []
        def fetch(url):
            asked.append(url)
            return data
        with mock.patch.object(jobs, "_fetch", side_effect=fetch):
            job = jobs._greenhouse({"token": "gongio"})[0]
        self.assertTrue(asked[0].endswith("?content=true"))
        self.assertEqual(job["description"], "The annual OTE is $160,000 - $210,000 USD.")

    def test_a_board_too_big_for_its_text_is_read_without_it(self):
        plain = {"jobs": [{"id": 1, "title": "Account Manager", "absolute_url": "https://x/1"}]}
        def fetch(url):
            if "content=true" in url:
                raise TimeoutError("too big")
            return plain
        with mock.patch.object(jobs, "_fetch", side_effect=fetch):
            job = jobs._greenhouse({"token": "big"})[0]
        self.assertEqual(job["title"], "Account Manager")
        self.assertNotIn("description", job)

    def test_a_gone_board_is_still_gone(self):
        with mock.patch.object(jobs, "_fetch", side_effect=jobs.BoardGone("404")):
            with self.assertRaises(jobs.BoardGone):
                jobs._greenhouse({"token": "gone"})

    def test_greenhouse_pay_beside_the_text_is_read(self):
        page = {"content": "&lt;p&gt;Join us.&lt;/p&gt;",
                "pay_input_ranges": [{"min_cents": 7000000, "max_cents": 9000000,
                                      "currency_type": "USD", "title": "US"},
                                     {"min_cents": 5000000, "max_cents": 6000000,
                                      "currency_type": "EUR"}]}
        asked = []
        def fetch(url):
            asked.append(url)
            return page
        text = jobs.posting_text({"url": "https://boards.greenhouse.io/embed/job_app?for=gongio&token=123"},
                                 fetch=fetch)
        self.assertIn("pay_transparency=true", asked[0])
        self.assertIn("Join us.", text)
        self.assertEqual(job_value.annual_pay({}, text), (70000.0, 90000.0))

    def test_no_pay_fields_adds_nothing(self):
        self.assertEqual(jobs._greenhouse_pay([]), "")
        self.assertEqual(jobs._greenhouse_pay(None), "")
        self.assertEqual(jobs._greenhouse_pay([{"min_cents": "x"}]), "")

    def test_a_listing_with_no_text_carries_none(self):
        with mock.patch.object(jobs, "_fetch", return_value={"jobs": [{"id": "z", "title": "Ops"}]}):
            self.assertNotIn("description", jobs._ashby({"token": "n"})[0])

    def test_no_date_or_a_bad_one_is_no_date(self):
        for value in (None, "", "soon", 0):
            self.assertEqual(jobs._when(value), "")

    def test_the_date_reaches_the_ranking(self):
        now = dt.datetime(2026, 10, 7, tzinfo=dt.timezone.utc)
        fresh = jobs._when((now - dt.timedelta(days=2)).timestamp() * 1000)
        self.assertEqual(job_value._days_old(fresh, now), 2)


if __name__ == "__main__":
    unittest.main()
