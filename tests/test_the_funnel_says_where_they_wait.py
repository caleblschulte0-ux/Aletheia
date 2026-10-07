"""The funnel says where filled-but-unsent applications are sitting.

Live 2026-10-06: 15 filled, 4 sent, and nothing said where the other
eleven were. Each place is a different fix, so each is its own count, and
the brief names them in words. Counts only: the file is public.
"""
import datetime as dt
import json
import unittest
from unittest import mock

from aletheia import hunt_funnel

NOW = dt.datetime(2026, 10, 7, 15, 0, tzinfo=dt.timezone.utc)


def row(state, **extra):
    base = {"id": f"r-{state}-{len(extra)}", "state": state, "staged_at": "2026-10-05T15:00:00Z"}
    base.update(extra)
    return base


class WhereTheyWait(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(hunt_funnel, "_waits_for_him",
                                    side_effect=lambda r: r.get("employment", ""))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_each_place_is_its_own_count(self):
        rows = [row("NEEDS_YOU"), row("NEEDS_YOU"), row("NEEDS_ACCOUNT"),
                row("AWAITING_YOU"), row("AWAITING_YOU", employment="part-time"),
                row("APPROVED", employment="contract"), row("FAILED"), row("SUBMITTED"),
                row("CLOSED", closed_because="not realistic: wants 5 years", closed_at="2026-10-06T10:00:00Z"),
                row("CLOSED", closed_because="an application already went to this form",
                    closed_at="2026-10-06T10:00:00Z"),
                row("CLOSED", closed_because="Acme said no", closed_at="2026-10-06T10:00:00Z")]
        held = hunt_funnel.counts(rows, now=NOW)["waiting"]
        self.assertEqual(held["needs_answer"], 2)
        self.assertEqual(held["needs_account"], 1)
        self.assertEqual(held["to_send"], 1)
        self.assertEqual(held["his_ok"], {"contract": 1, "part-time": 1})
        self.assertEqual(held["failed"], 1)
        self.assertEqual(held["closed"], {"duplicate": 1, "not_realistic": 1, "other": 1})
        self.assertEqual(held["oldest_days"], 2)

    def test_nothing_that_names_an_employer_is_published(self):
        rows = [row("CLOSED", closed_because="Acme Robotics said no", company="Acme Robotics",
                    closed_at="2026-10-06T10:00:00Z"),
                row("NEEDS_YOU", company="Acme Robotics", questions=["Why Acme?"])]
        text = json.dumps(hunt_funnel.counts(rows, now=NOW))
        self.assertNotIn("Acme", text)

    def test_closures_before_the_window_are_not_counted(self):
        rows = [row("CLOSED", closed_because="not realistic", closed_at="2026-08-01T10:00:00Z",
                    staged_at="2026-08-01T10:00:00Z")]
        self.assertEqual(hunt_funnel.counts(rows, now=NOW)["waiting"]["closed"], {})

    def test_the_brief_says_where_they_wait_and_what_clears_it(self):
        rows = [row("SUBMITTED"), row("NEEDS_YOU"), row("NEEDS_ACCOUNT"),
                row("AWAITING_YOU", employment="part-time")]
        lines = hunt_funnel.words(hunt_funnel.counts(rows, now=NOW), now=NOW)
        waiting = [line for line in lines if line.startswith("- **Waiting:**")]
        self.assertEqual(len(waiting), 1)
        self.assertIn("1 stopped on a question only you can answer", waiting[0])
        self.assertIn("1 need an account", waiting[0])
        self.assertIn("1 wait for your own OK", waiting[0])

    def test_nothing_waiting_is_no_line(self):
        lines = hunt_funnel.words(hunt_funnel.counts([row("SUBMITTED")], now=NOW), now=NOW)
        self.assertFalse([line for line in lines if "Waiting" in line])

    def test_an_old_funnel_without_the_block_still_reads(self):
        funnel = hunt_funnel.counts([row("SUBMITTED")], now=NOW)
        funnel.pop("waiting")
        self.assertTrue(hunt_funnel.words(funnel, now=NOW))


if __name__ == "__main__":
    unittest.main()
