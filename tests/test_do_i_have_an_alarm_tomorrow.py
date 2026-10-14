""""Do I have an alarm tomorrow" went to a model (2026-10-14): the "do I
have class tomorrow" reader took it and found no note."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, quick


class AlarmTomorrow(unittest.TestCase):
    def test_yes_with_the_time_and_no(self):
        tz = localtime.operator_tz()
        tomorrow = (dt.datetime.now(tz) + dt.timedelta(days=1)).replace(hour=6, minute=30, second=0, microsecond=0)
        with mock.patch.object(quick, "_coming", return_value=[(tomorrow, "wake up", "reminder")]):
            self.assertEqual(quick.answer("do i have an alarm tomorrow"), "Yes - your alarm tomorrow is at 6:30 am.")
        with mock.patch.object(quick, "_coming", return_value=[]):
            self.assertEqual(quick.answer("do i have an alarm set for tomorrow"), "No alarm set for tomorrow.")

    def test_class_tomorrow_is_still_the_note_reader(self):
        self.assertEqual(quick.match("do i have class tomorrow")[0], "do_i_have")


if __name__ == "__main__":
    unittest.main()
