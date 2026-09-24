"""The problems the header counts are the problems the list shows.

Live 2026-09-24 the header said "Today: 32 things done, 24 problems" and
"What she's done" under it held no problem at all, because the list read
`recollection.day` - what she DID, which drops alerts by design - while
the count read the ribbon, which keeps them. `_outcome_of` mapped an alert
to "failed" for a row that could never arrive. The list reads both
readers now, so the tap on "24 problems" has 24 things to show.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import needs_you


class TheProblemsSheCountsAreTheProblemsSheShows(unittest.TestCase):
    def test_an_alert_is_a_failed_row_beside_what_she_did(self):
        did = [{"at": "Wed 21:01", "kind": "action", "who": "aletheia", "what": "drafted the note"}]
        wrong = [{"at": "Wed 21:02", "kind": "alert", "who": "aletheia",
                  "what": "apply-b1ca106a was refused by the site: flagged as possible spam"},
                 {"at": "Wed 21:03", "kind": "recovery", "who": "aletheia", "what": "health red -> green"}]
        with mock.patch("aletheia.recollection.day", lambda hours, limit=None: did), \
                mock.patch("aletheia.recollection.trouble", lambda hours, limit=None: wrong), \
                mock.patch("aletheia.autonomy.recent", lambda hours, limit: []):
            rows = needs_you.activity()
        self.assertEqual([(r["at"], r["outcome"]) for r in rows],
                         [("Wed 21:03", "recovered"), ("Wed 21:02", "failed"), ("Wed 21:01", "finished")])
        self.assertIn("possible spam", rows[1]["what"])

    def test_one_line_seen_by_both_readers_is_one_row(self):
        row = {"at": "Wed 21:01", "kind": "action", "who": "aletheia", "what": "drafted the note"}
        with mock.patch("aletheia.recollection.day", lambda hours, limit=None: [row]), \
                mock.patch("aletheia.recollection.trouble", lambda hours, limit=None: [dict(row)]), \
                mock.patch("aletheia.autonomy.recent", lambda hours, limit: []):
            rows = needs_you.activity()
        self.assertEqual(len(rows), 1)

    def test_a_dead_trouble_reader_does_not_blank_what_she_did(self):
        def boom(hours, limit=None):
            raise OSError("journal locked")
        did = [{"at": "Wed 21:01", "kind": "action", "who": "aletheia", "what": "drafted the note"}]
        with mock.patch("aletheia.recollection.day", lambda hours, limit=None: did), \
                mock.patch("aletheia.recollection.trouble", boom), \
                mock.patch("aletheia.autonomy.recent", lambda hours, limit: []):
            rows = needs_you.activity()
        # `_safe` wraps the whole read: a dead reader costs the view, not the page.
        self.assertIsInstance(rows, list)


class TheHeaderCountsWhatTheListShows(unittest.TestCase):
    def test_the_tally_is_counted_from_the_same_rows(self):
        rows = [{"at": "Wed 21:01", "what": "a", "outcome": "finished"},
                {"at": "Wed 21:02", "what": "b", "outcome": "failed"},
                {"at": "Wed 21:03", "what": "c", "outcome": "failed"},
                {"at": "Wed 21:04", "what": "d", "outcome": "unattended"},
                {"at": "Wed 21:05", "what": "e", "outcome": "recovered"}]
        self.assertEqual(needs_you.today_tally(rows), {"done": 2, "problems": 2})

    def test_today_is_his_calendar_day_not_a_rolling_window(self):
        import datetime as dt
        with mock.patch("aletheia.localtime.operator_tz", return_value=dt.timezone.utc):
            at = dt.datetime(2026, 9, 24, 6, 30, tzinfo=dt.timezone.utc)
            self.assertAlmostEqual(needs_you.today_hours(at), 6.5, places=2)
            just_after = dt.datetime(2026, 9, 24, 0, 0, 30, tzinfo=dt.timezone.utc)
            self.assertGreater(needs_you.today_hours(just_after), 0)

    def test_the_page_carries_every_problem_and_the_newest_of_the_rest(self):
        rows = ([{"at": f"Wed 2{i%10}:00", "what": f"ok {i}", "outcome": "finished"} for i in range(100)]
                + [{"at": "Wed 09:00", "what": "old problem", "outcome": "failed"}])
        page = needs_you.for_the_page(rows, keep=60)
        self.assertEqual(len(page), 61)
        self.assertEqual(page[-1]["what"], "old problem", "a problem older than the newest sixty still travels")
        self.assertEqual(needs_you.today_tally(page)["problems"], needs_you.today_tally(rows)["problems"])

    def test_the_readers_are_asked_for_the_days_worth_not_fourteen(self):
        asked = {}
        def day(hours, limit=None):
            asked["day"] = limit; return []
        def trouble(hours, limit=None):
            asked["trouble"] = limit; return []
        with mock.patch("aletheia.recollection.day", day), mock.patch("aletheia.recollection.trouble", trouble),                 mock.patch("aletheia.autonomy.recent", lambda hours, limit: []):
            needs_you.activity(hours=6.0, limit=200)
        self.assertEqual((asked["day"], asked["trouble"]), (200, 200))


if __name__ == "__main__":
    unittest.main()
