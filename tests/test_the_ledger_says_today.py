"""Two ways the demand ledger was lying about its own rows.

    14x  message.send   NOT_BUILT   last 2026-09-10

on the evening of the 9th, about a capability that had been EXPERIMENTAL
for two days. Both halves of that line were wrong and neither was
noticeable: the status is plausible, the date is off by one, and this is
the file CLAUDE.md says to read FIRST when deciding what to build.

**A remembered status.** `ranked` built its row with `setdefault`, so
whichever record came first froze the status for the whole group — and
`reasons` was sitting right underneath showing NOT_BUILT thirteen times
and EXPERIMENTAL once, which is the ledger disagreeing with itself in the
same dict. The registry is the only source of truth for what she can do;
a second copy that disagrees by Friday is what that rule exists to
prevent. The recorded statuses stay in `reasons`, because "thirteen of
these were asked when it did not exist" is a real fact about demand.

**A UTC day, read as his.** Records are stored in UTC, correctly, and
`row['last'][:10]` then read the UTC calendar date as if it were his. An
ask at 21:53 on the 9th in Hartford printed as tomorrow. Same shape as
the reminder confirmed back as "tomorrow at 8 am": correct arithmetic,
wrong day, plausible enough that only the calendar catches it.
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from aletheia import capabilities, demand


class TheStatusComesFromTheRegistryCase(unittest.TestCase):
    def test_a_promoted_capability_is_not_still_reported_as_missing(self):
        records = [
            {"capability": "message.send", "at": "2026-09-07T15:10:48Z",
             "status": "NOT_BUILT", "asked": "send a text"},
            {"capability": "message.send", "at": "2026-09-09T02:53:31Z",
             "status": "EXPERIMENTAL", "asked": "send a text"},
        ]
        with mock.patch.object(demand, "_load", lambda: records), \
             mock.patch.object(demand, "_fresh", lambda rows, **k: rows):
            rows = demand.ranked()
        self.assertEqual(rows[0]["status"],
                         capabilities.get("message.send")["status"])

    def test_the_recorded_statuses_are_kept_as_history(self):
        """"Thirteen were asked when it did not exist" is a real fact."""
        records = [
            {"capability": "message.send", "at": "2026-09-07T15:10:48Z",
             "status": "NOT_BUILT", "asked": "send a text"},
            {"capability": "message.send", "at": "2026-09-09T02:53:31Z",
             "status": "EXPERIMENTAL", "asked": "send a text"},
        ]
        with mock.patch.object(demand, "_load", lambda: records), \
             mock.patch.object(demand, "_fresh", lambda rows, **k: rows):
            rows = demand.ranked()
        self.assertEqual(rows[0]["reasons"],
                         {"NOT_BUILT": 1, "EXPERIMENTAL": 1})

    def test_a_capability_no_longer_in_the_registry_keeps_what_it_had(self):
        """Demand for something since removed still counts; do not invent."""
        records = [{"capability": "gone.forever", "at": "2026-09-07T15:10:48Z",
                    "status": "NOT_BUILT", "asked": "do the thing"}]
        with mock.patch.object(demand, "_load", lambda: records), \
             mock.patch.object(demand, "_fresh", lambda rows, **k: rows):
            rows = demand.ranked()
        self.assertEqual(rows[0]["status"], "NOT_BUILT")


class TheDayIsHisCase(unittest.TestCase):
    def test_an_evening_ask_is_not_listed_as_tomorrow(self):
        """21:53 on the 9th in Hartford is 02:53 UTC on the 10th."""
        from aletheia import localtime
        zone = localtime.operator_tz()
        evening = dt.datetime(2026, 9, 9, 21, 53, tzinfo=zone)
        stamp = evening.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertNotEqual(stamp[:10], "2026-09-09",
                            "fixture no longer crosses midnight UTC")
        self.assertEqual(demand._his_day(stamp), "2026-09-09")

    def test_a_stamp_it_cannot_parse_is_not_mangled(self):
        self.assertEqual(demand._his_day("not a date"), "not a date")

    def test_it_never_raises_inside_a_listing(self):
        for value in ("", None, "2026-13-45T99:99:99Z", 12345):
            with self.subTest(value=value):
                demand._his_day(value)


if __name__ == "__main__":
    unittest.main()
