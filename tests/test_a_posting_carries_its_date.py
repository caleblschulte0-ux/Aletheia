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

    def test_no_date_or_a_bad_one_is_no_date(self):
        for value in (None, "", "soon", 0):
            self.assertEqual(jobs._when(value), "")

    def test_the_date_reaches_the_ranking(self):
        now = dt.datetime(2026, 10, 7, tzinfo=dt.timezone.utc)
        fresh = jobs._when((now - dt.timedelta(days=2)).timestamp() * 1000)
        self.assertEqual(job_value._days_old(fresh, now), 2)


if __name__ == "__main__":
    unittest.main()
