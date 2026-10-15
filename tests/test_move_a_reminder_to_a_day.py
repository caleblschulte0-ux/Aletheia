"""2026-10-15, every model off: "change my rent reminder to saturday at noon"
and "push my dentist reminder back a day" went to the planner, and "move my
plumber reminder to friday" - with no plumber reminder - did too, instead of
saying there is none. A named reminder moves to a day as readily as to a time."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, voice


def _in_days(n, hour):
    tz = localtime.operator_tz()
    day = dt.datetime.now(tz).date() + dt.timedelta(days=n)
    return dt.datetime.combine(day, dt.time(hour, 0), tzinfo=tz)


class MovedToADay(unittest.TestCase):
    def setUp(self):
        self.dentist = _in_days(3, 14)
        patch = mock.patch.object(voice, "_running_once", return_value=[(self.dentist, "call the dentist")])
        patch.start()
        self.addCleanup(patch.stop)

    def moved(self, which, to):
        return voice._reminder_moved_to(which, to)

    def test_a_day_keeps_its_own_time(self):
        target = _in_days(5, 14)
        got = self.moved("dentist", target.strftime("%A").lower())["command"]
        self.assertEqual(got["kind"], "remind_at")
        self.assertEqual(got["replaces"], "call the dentist")
        at = dt.datetime.fromisoformat(got["at"]).astimezone(localtime.operator_tz())
        self.assertEqual((at.date(), at.hour), (target.date(), 14))

    def test_a_day_and_a_time(self):
        target = _in_days(5, 12)
        got = self.moved("dentist", target.strftime("%A").lower() + " at noon")["command"]
        at = dt.datetime.fromisoformat(got["at"]).astimezone(localtime.operator_tz())
        self.assertEqual((at.date(), at.hour), (target.date(), 12))

    def test_nothing_by_that_name_is_said_plainly(self):
        got = self.moved("plumber", "friday")
        self.assertIsNone(got["command"])
        self.assertIn("I don't see a reminder for plumber", got["say"])

    def test_a_time_still_moves_it_on_its_own_day(self):
        got = self.moved("dentist", "4pm")["command"]
        at = dt.datetime.fromisoformat(got["at"]).astimezone(localtime.operator_tz())
        self.assertEqual((at.date(), at.hour), (self.dentist.date(), 16))


class PushedBackADay(unittest.TestCase):
    def test_a_day_later(self):
        dentist = _in_days(3, 14)
        with mock.patch.object(voice, "_running_once", return_value=[(dentist, "call the dentist")]):
            got = voice._shift_named_reminder("my dentist reminder", dt.timedelta(days=1))["command"]
        at = dt.datetime.fromisoformat(got["at"])
        self.assertEqual(at, dentist + dt.timedelta(days=1))

    def test_the_sentence_reaches_it(self):
        with mock.patch.object(voice, "_shift_named_reminder",
                               return_value={"command": {"kind": "remind_at"}, "say": None}) as shift, \
                mock.patch.object(voice, "_one_of_her_holds", return_value=(None, "")):
            voice._interpret("push my dentist reminder back a day")
        self.assertEqual(shift.call_args[0][1], dt.timedelta(days=1))


if __name__ == "__main__":
    unittest.main()
