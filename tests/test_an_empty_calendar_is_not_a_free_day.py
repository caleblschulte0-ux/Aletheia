"""An empty calendar and the WRONG calendar give the same answer.

    > am i free tomorrow afternoon
      [0.1s] Free tomorrow afternoon 12 pm to 5 pm.

Said with no hedge at all, from a connected feed holding ZERO events in
either direction for two months. If his real schedule lives on a
different calendar than the one wired up — a second Google account, a
work calendar, a shared one — that sentence is confidently wrong every
single time, and there is nothing in it for him to catch.

His own setup audit already says it:

    1 feed(s) read live, and it is EMPTY (0 events in the next 60 days) -
    'am I free?' will answer yes to every hour. If that is wrong, the
    schedule lives on a different calendar than the feed given

which is exactly right and reaches the wrong person. The one who needs
that sentence is not reading a checklist; he is standing in a room being
told he is free.

Only when it is COMPLETELY empty, and only near the day in question. A
quiet week is a fact about his week and needs no apology; nothing at all,
for weeks either side, is a fact about the connection.
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from aletheia import intercom

TOMORROW = dt.date.today() + dt.timedelta(days=1)


def _event(day, hour=10):
    """A REAL event. The first version of this fixture had three fields
    and `calendar.validate` rejected it — a made-up shape would have made
    every assertion here a test of the fixture."""
    stamp = f"{day.isoformat()}T{hour:02d}:00:00+00:00"
    return {"version": 1, "id": f"e-{day.isoformat()}", "title": "a thing",
            "start": stamp, "end": f"{day.isoformat()}T{hour + 1:02d}:00:00+00:00",
            "created_at": stamp, "updated_at": stamp, "status": "CONFIRMED"}


class TheCaveatCase(unittest.TestCase):
    def _ask(self, events):
        from aletheia import calendar as cal
        with mock.patch.object(cal, "all_events", lambda: events):
            return intercom.free_time_answer(
                {"day": TOMORROW.isoformat(), "part": "afternoon"})

    def test_a_completely_empty_calendar_says_so(self):
        said = self._ask([])
        self.assertIn("Free", said)
        self.assertIn("different calendar", said)

    def test_a_calendar_with_anything_on_it_does_not_apologise(self):
        """A quiet week is a fact about his week."""
        said = self._ask([_event(TOMORROW + dt.timedelta(days=9))])
        self.assertNotIn("different calendar", said)

    def test_an_event_far_outside_the_window_does_not_count(self):
        far = TOMORROW + dt.timedelta(days=intercom.EMPTY_CALENDAR_DAYS + 10)
        self.assertIn("different calendar", self._ask([_event(far)]))

    def test_an_event_behind_him_still_counts(self):
        """A calendar he stopped putting things in is still HIS calendar."""
        past = TOMORROW - dt.timedelta(days=5)
        self.assertNotIn("different calendar", self._ask([_event(past)]))

    def test_the_answer_itself_is_unchanged(self):
        """The hedge is added to the sentence, never instead of it."""
        with_caveat = self._ask([])
        without = self._ask([_event(TOMORROW + dt.timedelta(days=2))])
        self.assertTrue(with_caveat.startswith(without.rstrip()))


class ItNeverBreaksTheSentenceCase(unittest.TestCase):
    """The caveat's own edges, tested where they live.

    Driving these through `free_time_answer` does not reach them:
    `calendar.free_slots` validates every row and raises first, so a
    malformed calendar breaks the answer long before the hedge is
    considered. Asserting through the front door would have proved
    something about `validate` and nothing about this.
    """

    def _caveat(self, **patch):
        from aletheia import calendar as cal
        with mock.patch.object(cal, "all_events", **patch):
            return intercom._nothing_on_it_at_all(cal, TOMORROW)

    def test_a_calendar_that_will_not_read_says_nothing_extra(self):
        """A hedge that breaks the sentence it hedges is worse than none."""
        self.assertEqual(self._caveat(side_effect=RuntimeError("down")), "")

    def test_an_unparseable_row_is_not_treated_as_empty(self):
        """Unreadable is not empty; claiming bare on one bad row is a lie."""
        self.assertEqual(
            self._caveat(return_value=[{"id": "e", "start": "not a date"}]), "")

    def test_a_row_with_no_start_at_all(self):
        self.assertEqual(self._caveat(return_value=[{"id": "e"}]), "")

    def test_genuinely_nothing_is_the_only_thing_that_speaks(self):
        self.assertIn("different calendar", self._caveat(return_value=[]))
        self.assertEqual(self._caveat(return_value=[_event(TOMORROW)]), "")


if __name__ == "__main__":
    unittest.main()
