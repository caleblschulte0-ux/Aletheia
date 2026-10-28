""""Next Friday" near a month end names the month of the later Friday.

2026-10-28, talking to her:

    > what's the date next friday
      Friday the 30th of October - or the 6th, if you mean the week after.

"The 6th" of what? Across a month end the second answer needs its month.
"""
import datetime
import unittest
from unittest import mock

from aletheia import quick

_REAL = datetime.datetime


class _Wed28Oct(_REAL):
    @classmethod
    def now(cls, tz=None):
        return _REAL(2026, 10, 28, 13, 0, tzinfo=tz or datetime.timezone.utc)


class _Wed7Oct(_REAL):
    @classmethod
    def now(cls, tz=None):
        return _REAL(2026, 10, 7, 13, 0, tzinfo=tz or datetime.timezone.utc)


class NextFridayAcrossAMonth(unittest.TestCase):
    def test_the_date_names_the_later_month(self):
        with mock.patch("datetime.datetime", _Wed28Oct):
            said = quick._date_of("next friday")
        self.assertEqual(said, "Friday the 30th of October - or the 6th of November, if you mean the week after.")

    def test_days_until_names_the_later_month(self):
        with mock.patch("datetime.datetime", _Wed28Oct):
            said = quick.answer("how many days until next friday")
        self.assertIn("the 6th of November", said or "")

    def test_the_same_month_stays_short(self):
        with mock.patch("datetime.datetime", _Wed7Oct):
            said = quick._date_of("next friday")
        self.assertEqual(said, "Friday the 9th of October - or the 16th, if you mean the week after.")


if __name__ == "__main__":
    unittest.main()
