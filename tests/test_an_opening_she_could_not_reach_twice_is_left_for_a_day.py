"""An opening she could not reach a form on twice today is left until tomorrow.

Live 2026-09-24 the campaign's own log: Aptiv's J000698866 timed out on
the same select box on every pass, every twelve minutes, all night, and
"12 could not be reached" was mostly the same dozen pages - each one a
page load and a twenty-second timeout before the next real opening.
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import campaign

URL = "https://www.aptiv.com/en/jobs/search/open-positions/J000698866?source=Muse"


def _ago(hours: float) -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)


class AnOpeningSheCouldNotReachTwiceIsLeftForADay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(campaign, "UNREACHABLE_PATH", Path(self.tmp.name) / "unreachable.json")
        p.start(); self.addCleanup(p.stop)

    def test_once_is_tried_again_twice_is_left(self):
        campaign.remember_unreachable([{"url": URL, "why": "TimeoutError: Page.select_option"}])
        self.assertEqual(campaign.unreachable_today(URL), "")
        campaign.remember_unreachable([{"url": URL, "why": "TimeoutError: Page.select_option"}])
        why = campaign.unreachable_today(URL)
        self.assertIn("twice today", why)
        self.assertIn("until tomorrow", why)
        self.assertEqual(campaign.unreachable_today("https://jobs.example.com/other"), "")

    def test_yesterdays_failures_are_forgotten(self):
        campaign.remember_unreachable([{"url": URL, "why": "x"}], now=_ago(30))
        campaign.remember_unreachable([{"url": URL, "why": "x"}], now=_ago(29))
        self.assertEqual(campaign.unreachable_today(URL), "", "a day-old failure is not today's")
        # and the store does not grow without bound: a write prunes the old
        campaign.remember_unreachable([{"url": "https://jobs.example.com/new", "why": "y"}])
        kept = json.loads(campaign.UNREACHABLE_PATH.read_text(encoding="utf-8"))
        self.assertNotIn(URL, kept)

    def test_a_row_without_a_url_and_an_unreadable_store_cost_nothing(self):
        campaign.remember_unreachable([{"why": "no url"}, {"url": "", "why": ""}])
        self.assertFalse(campaign.UNREACHABLE_PATH.exists())
        campaign.UNREACHABLE_PATH.write_text("{not json", encoding="utf-8")
        self.assertEqual(campaign._unreachable_read(), {})
        self.assertEqual(campaign.unreachable_today(URL), "")

    def test_the_store_is_read_once_per_run_and_passed_in(self):
        store = {URL: {"count": 2, "last": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}}
        self.assertTrue(campaign.unreachable_today(URL, store=store))
        self.assertEqual(campaign.unreachable_today(URL, store={}), "")


if __name__ == "__main__":
    unittest.main()
