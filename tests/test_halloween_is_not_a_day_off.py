""""Is tomorrow a holiday" answered "No. The next one is Halloween"
(2026-10-21, every model off): the question is about a day off."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, quick


class ADayOff(unittest.TestCase):
    def ask(self, said, halloween_in, veterans_in=10):
        today = dt.datetime.now(localtime.operator_tz()).date()
        days = {"Halloween": halloween_in, "Veterans Day": veterans_in}
        named = lambda name, _today: today + dt.timedelta(days=days[name]) if name in days else None
        with mock.patch.object(quick, "_named_date", side_effect=named):
            return quick._holiday_next(said)

    def test_the_next_one_is_a_day_off(self):
        said = self.ask("tomorrow", halloween_in=3)
        self.assertTrue(said.startswith("No. The next holiday is Veterans Day"), said)
        self.assertIn("Halloween is", said)
        self.assertIn("isn't a day off", said)

    def test_on_the_day_itself(self):
        said = self.ask("tomorrow", halloween_in=1)
        self.assertTrue(said.startswith("Tomorrow is Halloween, but it isn't a day off."), said)

    def test_a_real_holiday_is_still_yes(self):
        self.assertEqual(self.ask("tomorrow", halloween_in=5, veterans_in=1), "Yes - tomorrow is Veterans Day.")


if __name__ == "__main__":
    unittest.main()
