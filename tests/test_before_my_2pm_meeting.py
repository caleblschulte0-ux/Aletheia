"""'Remind me 10 minutes before my 2pm meeting' answered "I don't see 2pm
meeting on your calendar" (2026-10-28): the pattern ate his "my". And "an
hour before the plumber comes" looked for an event called "plumber comes"."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import calendar, voice


class BeforeMyMeeting(unittest.TestCase):
    def test_his_own_word_comes_back(self):
        with mock.patch.object(calendar, "all_events", return_value=[]):
            said = voice.interpret("remind me 10 minutes before my 2pm meeting")["say"]
        self.assertIn("your 2pm meeting", said)
        with mock.patch.object(calendar, "all_events", return_value=[]):
            said = voice.interpret("remind me 15 minutes before dinner with Dana")["say"]
        self.assertIn("dinner with Dana", said)

    def test_the_plumber_comes_is_the_plumber(self):
        start = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).replace(microsecond=0)
        event = {"start": start.isoformat(), "title": "Plumber", "status": "CONFIRMED"}
        with mock.patch.object(calendar, "all_events", return_value=[event]):
            cmd = voice.interpret("remind me an hour before the plumber comes")["command"]
        self.assertEqual(cmd["kind"], "remind_at")
        self.assertEqual(dt.datetime.fromisoformat(cmd["at"]), start - dt.timedelta(hours=1))


if __name__ == "__main__":
    unittest.main()
