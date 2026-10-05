"""Twenty-third sandbox batch, 2026-10-05: the calendar itself.

    > do I have anything on sunday     "I could not find anything matching
                                       anything on sunday. I looked in Documents"
    > cancel the dentist               a SUBSCRIPTION called dentist
    > move the dentist to 4            [6.0s] a model, "I can't find a dentist"
    > am I free this weekend           [4.0s] a model
    > what day is the 20th             [3.5s] a model
    > what week is it / is it a leap year / when is daylight saving
                                       [7.5s] [3.5s] [5.5s] three models
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import calendar as cal, calendar_reasoning, intercom, localtime, quick, voice

TOMORROW = localtime.today() + dt.timedelta(days=1)


def _hold(title="Dentist", hour=10):
    start = dt.datetime.combine(TOMORROW, dt.time(hour, 0), tzinfo=localtime.operator_tz())
    end = start + dt.timedelta(hours=1)
    held = calendar_reasoning.hold(title, start.isoformat(), end.isoformat())
    return held["event"]


class TheTwoVerbs(unittest.TestCase):
    def setUp(self):
        for e in cal.all_events():
            if e.get("status") != "CANCELLED":
                cal.cancel(e["id"])

    def test_release_takes_it_off_and_names_it(self):
        _hold()
        said = intercom.execute_command({"kind": "calendar_release", "title": "the dentist"}, {"repos": {}})
        self.assertTrue(said.startswith("Taken off your calendar: Dentist "), said)
        self.assertFalse(intercom.calendar_events_named("dentist"))
        with self.assertRaises(Exception) as caught:
            intercom.execute_command({"kind": "calendar_release", "title": "dentist"}, {"repos": {}})
        self.assertIn("no dentist on your calendar", str(caught.exception))

    def test_move_keeps_the_length_and_journals(self):
        event = _hold()
        new_start = dt.datetime.combine(TOMORROW, dt.time(16, 0), tzinfo=localtime.operator_tz())
        with mock.patch("aletheia.journal.append") as journaled:
            said = intercom.execute_command({"kind": "calendar_move", "title": "dentist", "start": new_start.isoformat()}, {"repos": {}})
        self.assertTrue(said.startswith("Moved Dentist to "), said)
        moved = cal.load(event["id"])
        self.assertEqual(cal.parse_time(moved["start"]).astimezone(localtime.operator_tz()).hour, 16)
        self.assertEqual(cal.parse_time(moved["end"]).astimezone(localtime.operator_tz()).hour, 17)
        self.assertTrue(any("moved Dentist" in str(c.args) for c in journaled.call_args_list))

    def test_the_grammar_knows_them(self):
        self.assertEqual(intercom.KIND_ARGS["calendar_release"], ({"title"}, set()))
        self.assertIn("calendar_move", intercom.ROUTINE_KINDS)
        self.assertIn("calendar_release", intercom.ROUTINE_KINDS)


class TheVoiceAsksTheStores(unittest.TestCase):
    def test_cancel_is_the_calendar_when_the_calendar_says_so(self):
        with mock.patch.object(voice, "_tracks_a_subscription", return_value=False), \
             mock.patch.object(voice, "_on_the_calendar", return_value=True):
            self.assertEqual(voice.interpret("cancel the dentist")["command"], {"kind": "calendar_release", "title": "dentist"})
        with mock.patch.object(voice, "_tracks_a_subscription", return_value=True), \
             mock.patch.object(voice, "_on_the_calendar", return_value=False):
            self.assertEqual(voice.interpret("cancel netflix")["command"]["kind"], "subscription_cancel")
        with mock.patch.object(voice, "_tracks_a_subscription", return_value=False), \
             mock.patch.object(voice, "_on_the_calendar", return_value=False):
            out = voice.interpret("cancel the dentist appointment")
        self.assertIsNone(out["command"])
        self.assertEqual(out["say"], "There's no dentist on your calendar.")

    def test_move_reads_the_hour_against_the_events_own_day(self):
        start = dt.datetime.combine(TOMORROW, dt.time(10, 0), tzinfo=localtime.operator_tz())
        event = {"id": "e1", "title": "Dentist", "start": start.isoformat(), "end": (start + dt.timedelta(hours=1)).isoformat(), "status": "TENTATIVE"}
        with mock.patch("aletheia.intercom.calendar_events_named", return_value=[event]):
            out = voice.interpret("move the dentist to 4")["command"]
            self.assertEqual(out["kind"], "calendar_move")
            self.assertEqual(out["start"][:16], f"{TOMORROW.isoformat()}T16:00")
            friday = voice._spoken_day("friday")
            self.assertEqual(voice.interpret("move the dentist to friday at 9 am")["command"]["start"][:16], f"{friday}T09:00")

    def test_a_day_question_is_never_a_file(self):
        self.assertEqual(quick.match("do i have anything on sunday"), ("agenda", "sunday"))
        self.assertNotEqual(voice.interpret("do i have anything on sunday")["command"].get("kind"), "file_find")


class TheCalendarItself(unittest.TestCase):
    def test_the_weekend(self):
        with mock.patch("aletheia.quick._agenda", side_effect=lambda d: "Nothing on your calendar Saturday." if d == "saturday" else "Sunday: Lunch at 1 pm."):
            self.assertEqual(quick.answer("am i free this weekend"), "Saturday is clear and Sunday: Lunch at 1 pm.")
        with mock.patch("aletheia.quick._agenda", return_value="Nothing on your calendar Saturday."):
            self.assertTrue(quick.answer("what's on this weekend").startswith("Nothing on your calendar this weekend"))

    def test_which_day_a_date_is(self):
        said = quick.answer("what day is the 20th")
        self.assertRegex(said, r"^The 20th is a \w+day, 20 \w+ - (today|tomorrow|\d+ days away)\.$")
        self.assertRegex(quick.answer("what day is christmas"), r"^Christmas is a \w+day, 25 December - ")
        self.assertEqual(quick.match("what day is it tomorrow")[0], "date")

    def test_the_week_the_leap_year_and_the_clocks(self):
        self.assertRegex(quick.answer("what week is it"), r"^Week \d{1,2} of the year, the one that started Monday \d{1,2} \w+\.$")
        self.assertEqual(quick.answer("is 2028 a leap year"), "Yes, 2028 is a leap year - February has 29 days.")
        self.assertEqual(quick.answer("is 2026 a leap year"), "No, 2026 isn't a leap year. The next one is 2028.")
        with mock.patch("aletheia.localtime.operator_tz", return_value=__import__("zoneinfo").ZoneInfo("America/Chicago")):
            said = quick.answer("when is daylight saving")
        self.assertRegex(said, r"The clocks go (back|forward) an hour .* \d+ days from now\.$")
        with mock.patch("aletheia.localtime.operator_tz", return_value=__import__("zoneinfo").ZoneInfo("Asia/Tokyo")):
            self.assertEqual(quick.answer("when do the clocks change"), "Your time zone doesn't change its clocks.")


if __name__ == "__main__":
    unittest.main()
