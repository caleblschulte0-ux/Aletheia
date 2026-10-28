""""I'm going on vacation next week", then "when am I on vacation" read
"next week" back as said (2026-10-28) - true for a week, wrong after. The
relative day is counted from the day he said it."""
import unittest
from unittest import mock

from aletheia import localtime, quick

import datetime as dt

TZ = dt.timezone(dt.timedelta(hours=-5))
SAID = "2026-10-27T22:00:00-05:00"  # a Tuesday


class CountedFromTheDayHeSaidIt(unittest.TestCase):
    def read(self, said):
        with mock.patch.object(localtime, "operator_tz", return_value=TZ):
            return quick._days_from(said, SAID)

    def test_each_relative_day(self):
        self.assertEqual(self.read("I'm going on vacation next week"), " - the week of November 2")
        self.assertEqual(self.read("my sister is coming this weekend"), " - the weekend of October 31")
        self.assertEqual(self.read("the party is next weekend"), " - the weekend of November 7")
        self.assertEqual(self.read("I'm moving next month"), " - so in November")
        self.assertEqual(self.read("the dentist is tomorrow"), " - so Wednesday, October 28")
        self.assertEqual(self.read("my check comes in two weeks"), " - so around November 10")

    def test_days_still_count_as_before(self):
        self.assertEqual(self.read("my package arrives in 3 days"), " - so around October 30")

    def test_nothing_relative_adds_nothing(self):
        self.assertEqual(self.read("my locker is 42"), "")
        self.assertEqual(quick._days_from("I'm moving next month", "not a time"), "")


if __name__ == "__main__":
    unittest.main()
