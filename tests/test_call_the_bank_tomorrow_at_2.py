""""Add a task to call the bank tomorrow at 2" (2026-10-12).

The whole sentence became the task and nothing was due, and "what's on my
list for tomorrow" went to a model.
"""
import datetime as dt
import unittest

from aletheia import localtime, quick, voice


def day(offset):
    return (dt.datetime.now(localtime.operator_tz()).date() + dt.timedelta(days=offset)).isoformat()


class DayThenTime(unittest.TestCase):
    def test_tomorrow_at_2_is_the_afternoon(self):
        self.assertEqual(voice._split_deadline("call the bank tomorrow at 2"), ("call the bank", f"{day(1)}T14:00:00"))

    def test_noon(self):
        rest, due = voice._split_deadline("pay rent tomorrow at noon")
        self.assertEqual((rest, due), ("pay rent", f"{day(1)}T12:00:00"))

    def test_a_time_with_no_day_stays_the_task(self):
        self.assertEqual(voice._split_deadline("meet sam at 5"), ("meet sam at 5", ""))

    def test_by_a_day_at_a_time_unchanged(self):
        self.assertEqual(voice._split_deadline("call mom by tomorrow at 3"), ("call mom", f"{day(1)}T15:00:00"))


class ListForADay(unittest.TestCase):
    def test_rewrites(self):
        for said, day_word in (("what's on my list for tomorrow", "tomorrow"), ("what's on my to do list today", "today"),
                               ("whats on my list for friday", "friday")):
            self.assertEqual(quick._direct(said), f"what's due {day_word}", said)


if __name__ == "__main__":
    unittest.main()
