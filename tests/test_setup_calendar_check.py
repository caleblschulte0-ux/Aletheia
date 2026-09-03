"""The calendar step FETCHES. Configured is not read (§30).

2026-09-02: the operator pasted his secret iCal URL, the feed was
connected, and the checklist reported "1 secret-ICS feed(s) configured" —
the count of a config entry, never a request. The calendar turned out to
hold nothing, and "ok" would have let him believe availability reasoning
was live when it would answer "you are free" to every hour of every day.
"""
from __future__ import annotations

import unittest
from unittest import mock

import aletheia
from aletheia import setup


def _as_submodules(**fakes):
    """Patch aletheia.<name> as ATTRIBUTES of the package, not sys.modules.

    `from aletheia import ics` reads the package attribute when the
    submodule has already been imported anywhere in the process — so a
    sys.modules patch works alone and is bypassed in the full suite,
    which is exactly how these six tests passed in isolation and failed
    together.
    """
    return [mock.patch.object(aletheia, name, fake, create=True)
            for name, fake in fakes.items()]


class IcsBranchCase(unittest.TestCase):
    def check(self, *, feeds=(("primary", "https://x/basic.ics"),), refresh=None):
        ics = mock.MagicMock()
        ics._config.return_value = {"feeds": [{"id": i, "url": u} for i, u in feeds]}
        if isinstance(refresh, Exception):
            ics.refresh.side_effect = refresh
        else:
            ics.refresh.return_value = refresh
        live = mock.MagicMock()
        live.available.return_value = (False, "no official provider configured")
        for patch in _as_submodules(ics=ics, calendar_live=live):
            patch.start(); self.addCleanup(patch.stop)
        return setup._calendar(), ics

    def test_a_feed_with_events_reports_how_many_were_read(self):
        (state, detail), ics = self.check(refresh={"feeds": 1, "mirrored": 12})
        self.assertEqual(state, setup.OK)
        self.assertIn("12 event(s) mirrored", detail)
        ics.refresh.assert_called_once()      # it really fetched

    def test_an_empty_feed_is_said_out_loud_not_passed_off_as_working(self):
        (state, detail), _ = self.check(refresh={"feeds": 1, "mirrored": 0})
        self.assertEqual(state, setup.OK)
        self.assertIn("EMPTY", detail)
        self.assertIn("different calendar", detail)

    def test_a_dead_url_is_broken_not_ok(self):
        (state, detail), _ = self.check(refresh=OSError("403 Forbidden"))
        self.assertEqual(state, setup.BROKEN)
        self.assertIn("fetch failed", detail)
        self.assertIn("OSError", detail)

    def test_unexpandable_recurrences_are_named(self):
        (state, detail), _ = self.check(
            refresh={"feeds": 1, "mirrored": 3, "unsupported": 2})
        self.assertEqual(state, setup.OK)
        self.assertIn("2 recurrence(s)", detail)

    def test_no_feed_at_all_is_still_missing(self):
        (state, _), ics = self.check(feeds=())
        self.assertEqual(state, setup.MISSING)
        ics.refresh.assert_not_called()


class OfficialProviderBranchCase(unittest.TestCase):
    def check(self, refresh):
        live = mock.MagicMock()
        live.available.return_value = (True, "configured")
        live.config.return_value = {"provider": "google"}
        if isinstance(refresh, Exception):
            live.refresh.side_effect = refresh
        else:
            live.refresh.return_value = refresh
        for patch in _as_submodules(calendar_live=live, ics=mock.MagicMock()):
            patch.start(); self.addCleanup(patch.stop)
        return setup._calendar()

    def test_a_live_provider_reports_what_it_read(self):
        state, detail = self.check({"mirrored": 7})
        self.assertEqual(state, setup.OK)
        self.assertIn("google", detail)
        self.assertIn("7 event(s)", detail)

    def test_an_empty_official_calendar_says_so_too(self):
        state, detail = self.check({"mirrored": 0})
        self.assertEqual(state, setup.OK)
        self.assertIn("EMPTY", detail)

    def test_a_failing_provider_is_broken(self):
        state, detail = self.check(RuntimeError("token expired"))
        self.assertEqual(state, setup.BROKEN)
        self.assertIn("configured but failing", detail)


if __name__ == "__main__":
    unittest.main()
