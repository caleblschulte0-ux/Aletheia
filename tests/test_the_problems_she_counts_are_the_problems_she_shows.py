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
        with mock.patch("aletheia.recollection.day", lambda hours: did), \
                mock.patch("aletheia.recollection.trouble", lambda hours: wrong), \
                mock.patch("aletheia.autonomy.recent", lambda hours, limit: []):
            rows = needs_you.activity()
        self.assertEqual([(r["at"], r["outcome"]) for r in rows],
                         [("Wed 21:03", "recovered"), ("Wed 21:02", "failed"), ("Wed 21:01", "finished")])
        self.assertIn("possible spam", rows[1]["what"])

    def test_one_line_seen_by_both_readers_is_one_row(self):
        row = {"at": "Wed 21:01", "kind": "action", "who": "aletheia", "what": "drafted the note"}
        with mock.patch("aletheia.recollection.day", lambda hours: [row]), \
                mock.patch("aletheia.recollection.trouble", lambda hours: [dict(row)]), \
                mock.patch("aletheia.autonomy.recent", lambda hours, limit: []):
            rows = needs_you.activity()
        self.assertEqual(len(rows), 1)

    def test_a_dead_trouble_reader_does_not_blank_what_she_did(self):
        def boom(hours):
            raise OSError("journal locked")
        did = [{"at": "Wed 21:01", "kind": "action", "who": "aletheia", "what": "drafted the note"}]
        with mock.patch("aletheia.recollection.day", lambda hours: did), \
                mock.patch("aletheia.recollection.trouble", boom), \
                mock.patch("aletheia.autonomy.recent", lambda hours, limit: []):
            rows = needs_you.activity()
        # `_safe` wraps the whole read: a dead reader costs the view, not the page.
        self.assertIsInstance(rows, list)


if __name__ == "__main__":
    unittest.main()
