"""Small questions with exact answers, and the weekend's weather.

2026-10-07, every model off: "flip a coin", "roll a die", "pick a number
between 1 and 10", "spell necessary", "how many ounces in a cup", "do I
need an umbrella" and "what's the weather this weekend" all went to the
planner and came back "I could not plan that". None of them needs thinking.
"""
import unittest
from unittest import mock

from aletheia import quick, weather


def forecast(periods):
    return {"place": "Austin", "periods": periods}


WEEK = [
    {"name": "Today", "isDaytime": True, "temperature": 80, "shortForecast": "Sunny",
     "probabilityOfPrecipitation": {"value": 5}},
    {"name": "Tonight", "isDaytime": False, "temperature": 60, "shortForecast": "Clear",
     "probabilityOfPrecipitation": {"value": 0}},
    {"name": "Thursday", "isDaytime": True, "temperature": 78, "shortForecast": "Chance Rain Showers",
     "probabilityOfPrecipitation": {"value": 60}},
    {"name": "Thursday Night", "isDaytime": False, "temperature": 58, "shortForecast": "Cloudy"},
    {"name": "Friday", "isDaytime": True, "temperature": 75, "shortForecast": "Mostly Sunny"},
    {"name": "Friday Night", "isDaytime": False, "temperature": 55, "shortForecast": "Clear"},
    {"name": "Saturday", "isDaytime": True, "temperature": 82, "shortForecast": "Sunny"},
    {"name": "Saturday Night", "isDaytime": False, "temperature": 62, "shortForecast": "Clear"},
    {"name": "Sunday", "isDaytime": True, "temperature": 70, "shortForecast": "Thunderstorms",
     "probabilityOfPrecipitation": {"value": 80}},
]


class TheWeekendAndTheUmbrella(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(weather, "forecast", return_value=forecast(WEEK))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_weekend_is_two_days(self):
        said = quick.answer("what's the weather this weekend")
        self.assertIn("Saturday in Austin: Sunny, 82 degrees", said)
        self.assertIn("Sunday: Thunderstorms, 70 degrees", said)
        self.assertNotIn("Saturday Night", said)

    def test_an_umbrella_today_is_no_and_tomorrow_is_yes(self):
        self.assertTrue(quick.answer("do i need an umbrella").startswith("Doesn't look like it"))
        said = quick.answer("do i need an umbrella tomorrow")
        self.assertTrue(said.startswith("Looks like it"), said)
        self.assertIn("60% chance", said)

    def test_rain_this_weekend_names_the_wet_day(self):
        said = quick.answer("will it rain this weekend")
        self.assertIn("Sunday", said)
        self.assertNotIn("Saturday", said)

    def test_a_weekend_past_the_forecast_says_so(self):
        with mock.patch.object(weather, "forecast", return_value=forecast(WEEK[:3])):
            self.assertIn("doesn't reach the weekend", quick.answer("what's the weather this weekend"))


class ChanceIsChance(unittest.TestCase):
    def test_a_coin(self):
        self.assertIn(quick.answer("flip a coin"), ("Heads.", "Tails."))

    def test_dice(self):
        self.assertIn(quick.answer("roll a die"), [f"{n}." for n in range(1, 7)])
        self.assertIn("in all", quick.answer("roll two dice"))

    def test_a_number_stays_in_range(self):
        for _ in range(50):
            self.assertTrue(3 <= int(quick.answer("pick a number between 3 and 5").rstrip(".")) <= 5)


class SpellingAndTheKitchen(unittest.TestCase):
    def test_spelling_is_the_letters(self):
        self.assertEqual(quick.answer("how do you spell rhythm"), "Rhythm: R, H, Y, T, H, M.")

    def test_cups_and_spoons(self):
        self.assertEqual(quick.answer("how many ounces in a cup"), "8 ounces.")
        self.assertEqual(quick.answer("how many tablespoons in a cup"), "16 tablespoons.")
        self.assertEqual(quick.answer("what is half a cup in tablespoons"), "8 tablespoons.")
        self.assertEqual(quick.answer("how many ounces in a pound"), "16 ounces.")

    def test_other_how_many_questions_still_reach_their_store(self):
        self.assertNotEqual(quick.match("how many applications have you sent")[0], "volume")
        self.assertEqual(quick.match("how many miles is 10 km")[0], "math")


if __name__ == "__main__":
    unittest.main()


class TimersVolumeAndAppointments(unittest.TestCase):
    def test_time_left_on_a_timer(self):
        import datetime as dt
        from aletheia import scheduler
        now = dt.datetime(2026, 10, 7, 12, tzinfo=dt.timezone.utc)
        specs = [{"version": 1, "id": "remind-1", "kind": "once", "enabled": True,
                  "command": {"kind": "notify_operator", "text": "your 10-minute timer is up"},
                  "created_at": "2026-10-07T00:00:00Z", "updated_at": "2026-10-07T00:00:00Z",
                  "at": "2026-10-07T12:09:50Z"}]
        with mock.patch.object(scheduler, "all_schedules", return_value=specs):
            self.assertEqual(quick._timer_left(now), "10 minutes left on your 10-minute timer.")
        with mock.patch.object(scheduler, "all_schedules", return_value=[]):
            self.assertEqual(quick._timer_left(now), "No timer running.")
        self.assertEqual(quick.match("how much time is left on my timer")[0], "timer_left")

    def test_turn_up_the_volume(self):
        from aletheia import voice
        self.assertEqual(voice.interpret("turn up the volume")["command"]["action"], "volume_up")
        self.assertEqual(voice.interpret("turn down the music a bit")["command"]["action"], "volume_down")

    def test_an_appointment_on_a_day_is_a_hold(self):
        from aletheia import voice
        got = voice.interpret("add dentist appointment friday at 2")["command"]
        self.assertEqual((got["kind"], got["title"]), ("calendar_hold", "dentist appointment"))
        self.assertIn("T14:00", got["start"])
        self.assertNotEqual(voice.interpret("book a dentist appointment friday at 2")["command"]["kind"],
                            "calendar_hold")


class TheCalendarItself(unittest.TestCase):
    def test_leap_years(self):
        self.assertEqual(quick.answer("is 2028 a leap year"), "Yes, 2028 is a leap year.")
        self.assertIn("wasn't", quick.answer("is 1900 a leap year"))
        self.assertRegex(quick.answer("when is the next leap year"), r"^\d{4}\.$")

    def test_week_number(self):
        self.assertRegex(quick.answer("what week is it"), r"(?i)\bweek \d{1,2} of \d{4}\.$")


class AskedForWhole(unittest.TestCase):
    def test_a_reminder_with_no_thing_and_no_time_asks(self):
        from aletheia import voice
        got = voice.interpret("remind me about this later")
        self.assertIsNone(got["command"])
        self.assertIn("what, and when", got["say"])
        self.assertEqual(voice.interpret("remind me about my landlord")["command"]["kind"], "recall")

    def test_a_briefing_with_an_a(self):
        from aletheia import voice
        self.assertEqual(voice.interpret("give me a briefing")["command"]["kind"], "brief")


class WhatIsDue(unittest.TestCase):
    def test_a_day_said_last_is_a_deadline(self):
        from aletheia import voice
        self.assertEqual(voice._split_deadline("pay the gas bill on friday")[0], "pay the gas bill")
        self.assertTrue(voice._split_deadline("call the plumber tomorrow")[1])
        self.assertEqual(voice._split_deadline("sort the photos by date"), ("sort the photos by date", ""))
        self.assertEqual(voice._split_deadline("monday"), ("monday", ""))

    def test_due_today_this_week_and_overdue(self):
        import datetime as dt
        from aletheia import localtime, tasks
        here = localtime.operator_tz()
        now = dt.datetime(2026, 10, 7, 12, tzinfo=here)       # a Wednesday
        rows = [{"id": "a", "description": "pay rent", "status": "PENDING", "deadline": "2026-10-07"},
                {"id": "b", "description": "call the plumber", "status": "PENDING", "deadline": "2026-10-09"},
                {"id": "c", "description": "renew passport", "status": "PENDING", "deadline": "2026-10-01"},
                {"id": "d", "description": "her ticket", "status": "PENDING", "deadline": "2026-10-07",
                 "assigned_worker": "claude"}]
        with mock.patch.object(tasks, "all_tasks", return_value=rows):
            self.assertEqual(quick._due("", now), "2 tasks due today: renew passport (overdue) and pay rent.")
            self.assertEqual(quick._due("overdue", now), "1 task overdue: renew passport.")
            self.assertIn("call the plumber", quick._due("this week", now))
        self.assertIn(quick.match("what's due today")[0], ("due", "tasks_due"))
        self.assertEqual(quick.match("what's overdue")[0], "due")


class ANumberSaidIsAContact(unittest.TestCase):
    def test_the_ways_he_says_it(self):
        from aletheia import voice
        for said, name in (("sam's number is 555 123 4567", "Sam"),
                           ("save mom's cell as (555) 123 4567", "Mom"),
                           ("add Dana Lee to my contacts with number 5551234567", "Dana Lee")):
            got = voice.interpret(said)["command"]
            # The name as he said it; a lowercased transcript cannot settle capitals.
            self.assertEqual((got["kind"], got["name"].casefold()), ("contact_add", name.casefold()), said)
        self.assertEqual(voice.interpret("dana's email is dana@example.com")["command"]["email"], "dana@example.com")

    def test_his_own_number_is_not_a_contact_called_my(self):
        from aletheia import voice
        self.assertNotEqual(voice.interpret("my number is 555 123 4567")["command"], None)
        self.assertNotEqual((voice.interpret("my number is 555 123 4567")["command"] or {}).get("kind"), "contact_add")

    def test_no_number_asks_for_one(self):
        from aletheia import voice
        self.assertIn("Sam's number", voice.interpret("add sam to my contacts")["say"])

    def test_the_receipt_is_a_sentence(self):
        from aletheia import speech
        # The digits grouped the way a number is said, with no promise about the repo.
        self.assertRegex(speech.spoken_receipt(
            "contact_add", "remembered Sam as 5551234567 — private contacts only, never the public repo"),
            r"^Got it - Sam: 555[ -]123[ -]4567\.$")
