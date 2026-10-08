"""A page that does not respond before anything is filled gets one more look.

Live 2026-10-08, four of three days' closed applications were postings that
did not respond on the first load ("the page did not respond to what I
tried") and were closed for good. Before anything of his is on the page a
fresh page costs nothing. Once anything was filled or pressed, the stop
stands as before.
"""
import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import browser_loop, browser_mission as bm, power

GOAL = "apply for this job"
URL = "https://jobs.example.com/acme/123"


class PageTimeout(Exception):
    pass


PageTimeout.__module__ = "playwright._impl._errors"


class FakeSession:
    def __init__(self):
        self.pages = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def new_page(self):
        self.pages += 1
        return mock.Mock(url=URL)


class OneMoreLookBeforeFilling(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for target, name, value in ((bm, "missions_dir", lambda: Path(tmp.name)),
                                    (power, "keep_awake",
                                     lambda *a, **k: contextlib.nullcontext())):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.session = FakeSession()

    def pursue(self, drive):
        with mock.patch.object(browser_loop, "_drive", side_effect=drive):
            return browser_loop.pursue(GOAL, URL, session=lambda: self.session)

    def test_a_first_load_that_fails_is_tried_once_more(self):
        calls = []

        def drive(ctx, page, record, *a, **k):
            calls.append(record["id"])
            if len(calls) == 1:
                raise PageTimeout("Timeout 30000ms exceeded")
            return {**record, "state": "AWAITING_APPROVAL"}

        out = self.pursue(drive)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.session.pages, 2)
        self.assertEqual(out["state"], "AWAITING_APPROVAL")
        self.assertTrue(any("looking once more" in h["did"] for h in bm.load(out["id"])["history"]))

    def test_twice_is_a_stop(self):
        def drive(*a, **k):
            raise PageTimeout("Timeout 30000ms exceeded")

        out = self.pursue(drive)
        self.assertEqual(out["state"], bm.NEEDS_YOU)
        self.assertEqual(out["boundary"]["kind"], "ERROR")
        self.assertEqual(self.session.pages, 2)

    def test_once_something_is_filled_it_stops_at_once(self):
        calls = []

        def drive(ctx, page, record, *a, **k):
            calls.append(1)
            bm.checkpoint(bm.load(record["id"]), bm.FILLED, url=URL)
            raise PageTimeout("Timeout 30000ms exceeded")

        out = self.pursue(drive)
        self.assertEqual(len(calls), 1)
        self.assertEqual(out["boundary"]["kind"], "ERROR")


if __name__ == "__main__":
    unittest.main()
