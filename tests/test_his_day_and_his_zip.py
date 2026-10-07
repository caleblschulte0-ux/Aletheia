"""His day asked the ways people ask, and the postcode the weather wants.

2026-10-07, every model off: "do I have any meetings today" was answered
"nothing coming up" - a different question; "how busy am I this week",
"what's my first meeting tomorrow" and "block off friday afternoon" went to
the planner; and "my zip code is 78701", which the weather asks him to say,
went to the planner too.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import calendar, localtime, profile, quick, speech, voice, weather


class HisDay(unittest.TestCase):
    def events(self):
        tz = localtime.operator_tz()
        tomorrow = dt.datetime.now(tz).date() + dt.timedelta(days=1)
        at = lambda h: dt.datetime.combine(tomorrow, dt.time(h), tzinfo=tz).isoformat()
        return [{"title": "Dentist", "start": at(14)}, {"title": "Standup", "start": at(9)}]

    def test_meetings_today_is_about_today(self):
        self.assertEqual(quick.match("do i have any meetings today"), ("agenda_more", "today"))
        self.assertEqual(quick.match("how busy am i this week"), ("agenda_more", "this week"))

    def test_the_first_meeting_is_the_earliest(self):
        with mock.patch.object(calendar, "all_events", return_value=self.events()):
            self.assertEqual(quick.answer("what's my first meeting tomorrow"), "Tomorrow, first up: Standup at 9 am.")

    def test_block_off_an_afternoon_is_a_busy_hold(self):
        got = voice.interpret("block off friday afternoon")["command"]
        self.assertEqual((got["kind"], got["title"], got["minutes"]), ("calendar_hold", "Busy", 180))
        self.assertIn("T14:00", got["start"])


class HisZip(unittest.TestCase):
    def test_said_is_remembered(self):
        self.assertEqual(voice.interpret("my zip code is 78701")["command"],
                         {"kind": "remember", "domain": "identity", "key": "zip_code", "value": "78701"})

    def test_the_weather_finds_it(self):
        from aletheia import memory
        with mock.patch.object(profile, "load", return_value={}), \
                mock.patch.object(memory, "everything", return_value={"identity": {"zip_code": {"value": "78701"}}}):
            self.assertEqual(weather.where_he_is()[0], "78701")

    def test_the_receipt_is_a_sentence(self):
        self.assertEqual(speech.spoken_receipt("remember", "remembered identity.zip_code"),
                         "Got it - I'll remember your zip code.")

    def test_no_network_is_not_a_wrong_zip(self):
        import urllib.error
        with mock.patch.object(weather, "_get", side_effect=urllib.error.URLError("down")):
            with self.assertRaises(weather.WeatherUnavailable) as caught:
                weather._point("78701")
        self.assertNotIn("may be wrong", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
