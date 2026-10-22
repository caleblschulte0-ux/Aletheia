""""Am I free Saturday morning" said "9 am to 12:15 pm" (2026-10-22).

The last half hour that STARTED in the morning ran past noon, and merged
into the stretch it moved where the morning ends.
"""
import datetime as dt
import unittest

from aletheia import calendar as cal, quick


class AMorningEndsAtNoon(unittest.TestCase):
    def slots(self):
        return cal.free_slots(dt.date(2026, 10, 24), duration_minutes=30,
                              timezone="America/Chicago", events=[])

    def test_the_free_morning_ends_at_noon(self):
        merged = cal.merge_slots(cal.in_part(self.slots(), "morning"))
        self.assertEqual(len(merged), 1, merged)
        self.assertTrue(merged[0][1].startswith("2026-10-24T12:00"), merged)

    def test_the_afternoon_still_starts_at_noon_and_ends_with_the_day(self):
        merged = cal.merge_slots(cal.in_part(self.slots(), "afternoon"))
        self.assertTrue(merged[0][0].startswith("2026-10-24T12:00"), merged)
        self.assertTrue(merged[-1][1].startswith("2026-10-24T17:00"), merged)



class OnTapIsTheCalendar(unittest.TestCase):
    """"What's on tap for Friday" went to a model (2026-10-22)."""

    def test_the_idioms_read_the_calendar(self):
        for said, meant in (("what's on tap for friday", "what's on my calendar friday"),
                            ("what's on deck tomorrow", "what's on my calendar tomorrow"),
                            ("what's on the docket", "what's on my calendar today")):
            self.assertEqual(quick._direct(quick._tidy(said)), meant, said)


if __name__ == "__main__":
    unittest.main()
