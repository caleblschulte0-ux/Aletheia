""""Move my dentist appointment to Wednesday", said on a Wednesday about next
Tuesday's, moved it to that same afternoon; and after "cancel my dentist
appointment", "when is my dentist appointment" went to a model (2026-10-14)."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import calendar as _calendar, localtime, quick, voice


class ABareWeekdayIsTheNearestOne(unittest.TestCase):
    def test_nearest_the_day_it_was_on(self):
        tz = localtime.operator_tz()
        today = dt.datetime.now(tz).date()
        was_day = today + dt.timedelta(days=13)        # well ahead, so no wrap into the past
        was = dt.datetime.combine(was_day, dt.time(14, 0), tzinfo=tz)
        hold = {"title": "dentist appointment", "start": was.isoformat(),
                "end": (was + dt.timedelta(hours=1)).isoformat()}
        after = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][(was_day.weekday() + 1) % 7]
        with mock.patch.object(voice, "_one_of_her_holds", return_value=(hold, "")), \
                mock.patch.object(voice, "_names_one_open_task", return_value=False):
            out = voice._interpret(f"move my dentist appointment to {after}")
        new = dt.datetime.fromisoformat(out["command"]["start"])
        self.assertEqual(new.date(), was_day + dt.timedelta(days=1))
        self.assertEqual((new.hour, new.minute), (14, 0))


class ACancelledHoldIsSaid(unittest.TestCase):
    def test_when_and_how_long(self):
        ahead = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=6)
        gone = [{"title": "dentist appointment", "status": "CANCELLED", "start": ahead.isoformat()}]
        with mock.patch.object(_calendar, "all_events", return_value=gone), \
                mock.patch.object(quick, "_coming", return_value=[]), \
                mock.patch.object(quick, "_notes", return_value=[]):
            for asked in ("when is my dentist appointment", "how long until my dentist appointment"):
                said = quick.answer(asked) or ""
                self.assertTrue(said.startswith("You don't have one now - your dentist appointment"), (asked, said))

    def test_a_past_or_other_cancelled_hold_is_not_it(self):
        past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)
        gone = [{"title": "dentist appointment", "status": "CANCELLED", "start": past.isoformat()}]
        with mock.patch.object(_calendar, "all_events", return_value=gone):
            self.assertIsNone(quick._cancelled_hold(["dentist"]))
            self.assertIsNone(quick._cancelled_hold(["haircut"]))


if __name__ == "__main__":
    unittest.main()
