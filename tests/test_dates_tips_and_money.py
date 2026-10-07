"""Weeks until a day, a tip, his birthday, money abroad, and the off switch.

2026-10-07, every model off: "how many weeks until christmas", "what's a
20% tip on 45", "how many days until my birthday", "how much is 50 euros in
dollars" and "how do I turn you off" all went to a model or the planner.
"""
import unittest
from unittest import mock

from aletheia import fx, memory, quick, voice


class WeeksAndTips(unittest.TestCase):
    def test_weeks_until(self):
        self.assertRegex(quick.answer("how many weeks until christmas"), r"^(\d+ weeks?( and \d+ days?)?|\d+ days?)(,| -) Friday 25 December\.$")

    def test_a_tip(self):
        said = quick.answer("what's a 20% tip on 45")
        self.assertIn("$9.00", said)
        self.assertIn("$54.00", said)
        self.assertEqual(quick.answer("tip on 80"), "On $80.00: 15% is $12.00, 18% is $14.40, and 20% is $16.00.")


class HisBirthday(unittest.TestCase):
    def test_said_is_remembered_not_a_form_field(self):
        got = voice.interpret("my birthday is march 3")["command"]
        self.assertEqual((got["kind"], got["key"], got["value"]), ("remember", "birthday", "march 3"))

    def test_days_until_it(self):
        with mock.patch.object(memory, "recall", return_value="march 3"), \
                mock.patch.object(memory, "everything", return_value={"identity": {"birthday": {"value": "march 3"}}}):
            self.assertRegex(quick.answer("how many days until my birthday"), r"\b3 March\b|\bMarch 3")
        with mock.patch.object(memory, "recall", return_value=None), \
                mock.patch.object(memory, "everything", return_value={}):
            self.assertIn("my birthday is", quick.answer("how many days until my birthday").lower())


class Money(unittest.TestCase):
    def test_at_the_published_rate(self):
        with mock.patch.object(fx, "rate", return_value=(1.0912, "2026-10-06")):
            said = quick.answer("how much is 50 euros in dollars")
        self.assertTrue(said.startswith("50 euros is about 54.56 dollars"), said)
        self.assertIn("European Central Bank", said)

    def test_no_service_is_no_number(self):
        with mock.patch.object(fx, "_cache_path", side_effect=OSError), \
                mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
            said = quick.answer("how much is 50 euros in dollars")
        self.assertIn("won't guess", said)
        self.assertNotRegex(said, r"\d+\.\d\d")

    def test_weight_is_still_weight(self):
        self.assertEqual(quick.match("how many pounds in 5 kg")[0], "math")


class TheOffSwitch(unittest.TestCase):
    def test_every_word_it_names_works(self):
        said = quick.answer("how do i turn you off")
        self.assertIn('"stop"', said)
        self.assertEqual(voice.interpret("stop")["command"]["kind"], "halt")
        self.assertEqual(voice.interpret("announcements off")["command"]["kind"], "announce_set")
        self.assertEqual(voice.interpret("turn off the microphone")["command"]["kind"], "mic_off")


if __name__ == "__main__":
    unittest.main()


class AlarmsListsAndSmallThings(unittest.TestCase):
    def test_an_alarm_every_day_and_on_weekdays(self):
        self.assertEqual(voice.interpret("set an alarm for 6am every day")["command"],
                         {"kind": "remind_daily", "time": "06:00", "text": "wake up"})
        self.assertEqual(voice.interpret("wake me up at 7 every weekday")["command"]["days"], ["weekdays"])

    def test_what_time_is_my_alarm(self):
        from aletheia import scheduler
        rows = [{"id": "r1", "kind": "daily", "enabled": True, "time": "06:00", "timezone": "America/Chicago",
                 "command": {"kind": "notify_operator", "text": "wake up"}}]
        with mock.patch.object(scheduler, "all_schedules", return_value=rows):
            self.assertEqual(quick.answer("what time is my alarm set for"), "1 alarm: every day at 6 am.")
        with mock.patch.object(scheduler, "all_schedules", return_value=[]):
            self.assertIn("No alarm set", quick.answer("what time is my alarm set for"))

    def test_remove_milk_only_when_milk_is_on_the_list(self):
        with mock.patch.object(voice, "_on_the_shopping_list", return_value=True):
            self.assertEqual(voice.interpret("remove milk")["command"], {"kind": "shopping_off", "item": "milk"})
        with mock.patch.object(voice, "_on_the_shopping_list", return_value=False):
            self.assertNotEqual((voice.interpret("remove milk")["command"] or {}).get("kind"), "shopping_off")

    def test_count_and_a_riddle(self):
        self.assertEqual(quick.answer("count to five"), "1, 2, 3, 4, 5.")
        self.assertIn("?", quick.answer("tell me a riddle"))


class GoodMorningMentionsTheWeather(unittest.TestCase):
    def test_when_she_can_read_it(self):
        from aletheia import weather
        with mock.patch("aletheia.quick._overnight", return_value="A quiet night."), \
                mock.patch("aletheia.quick._focus", return_value="the day is yours"), \
                mock.patch.object(weather, "where_he_is", return_value=("78701", "Austin")), \
                mock.patch.object(weather, "forecast", return_value={"periods": [
                    {"name": "Today", "temperature": 71, "shortForecast": "Mostly Sunny"}]}):
            self.assertEqual(quick.answer("good morning"),
                             "Good morning. A quiet night. Outside it's mostly sunny, 71 degrees.")

    def test_never_an_error_in_a_greeting(self):
        from aletheia import weather
        with mock.patch("aletheia.quick._overnight", return_value="A quiet night."), \
                mock.patch("aletheia.quick._focus", return_value="the day is yours"), \
                mock.patch.object(weather, "where_he_is", return_value=("78701", "Austin")), \
                mock.patch.object(weather, "forecast", side_effect=weather.WeatherUnavailable("down")):
            self.assertEqual(quick.answer("good morning"), "Good morning. A quiet night.")
