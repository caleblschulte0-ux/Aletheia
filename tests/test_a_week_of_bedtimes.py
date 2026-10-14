""""I went to bed at 11", "I woke up at 7", then "how much sleep did I get
this week" said he had told her nothing (2026-10-14): only "I slept 7
hours" was counted for the week or the average."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, quick


def _rows(*pairs):
    out = []
    for at, text in pairs:
        out.append({"ts": at.isoformat(), "text": text})
    return list(reversed(out))     # newest first, as her notes are


class AWeekOfBedtimes(unittest.TestCase):
    def test_two_nights_add_up(self):
        tz = localtime.operator_tz()
        today = dt.datetime.now(tz).replace(hour=7, minute=5, second=0, microsecond=0)
        if today.weekday() == 0:
            self.skipTest("on a Monday only one morning of this week has happened")
        yesterday = today - dt.timedelta(days=1)
        rows = _rows((yesterday - dt.timedelta(hours=8), "i went to bed at 11"), (yesterday, "i woke up at 6"),
                     (today - dt.timedelta(hours=8), "i went to bed at midnight"), (today, "i woke up at 8"))
        with mock.patch.object(quick, "_notes", return_value=rows):
            self.assertEqual(quick.answer("how much sleep did i get this week"),
                             "15 hours over the 2 nights you told me about - about 7.5 a night.")

    def test_told_in_the_same_second(self):
        now = dt.datetime.now(dt.timezone.utc)
        self.assertEqual(list(quick._bed_woke_nights([(now, "i woke up at 7"), (now, "i went to bed at 11")]).values()), [8.0])

    def test_a_said_number_wins_its_night(self):
        now = dt.datetime.now(dt.timezone.utc)
        rows = _rows((now - dt.timedelta(seconds=10), "i went to bed at 11"), (now - dt.timedelta(seconds=5), "i woke up at 7"),
                     (now, "i slept 6 hours"))
        with mock.patch.object(quick, "_notes", return_value=rows):
            self.assertEqual(quick.answer("how much sleep did i get this week"), "You've told me about one night this week: 6 hours.")


if __name__ == "__main__":
    unittest.main()
