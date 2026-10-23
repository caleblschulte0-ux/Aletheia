""""Make dinner with mom an hour later", "make it 2 hours" said by name, "how
long is dinner with mom" and "what's my last thing Sunday" (2026-10-23: to
the planner, a model and a memory search) - about a hold she pencilled in.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import calendar, localtime, quick, voice


class MakeDinnerAnHourLater(unittest.TestCase):
    def setUp(self):
        tz = localtime.operator_tz()
        today = dt.datetime.now(tz).date()
        self.sunday = today + dt.timedelta(days=2)  # never today or tomorrow, so it is said by name
        at = lambda h: dt.datetime.combine(self.sunday, dt.time(h, 0), tzinfo=tz)  # noqa: E731
        self.at = at
        self.events = [
            {"id": "c", "title": "church", "start": at(10).isoformat(), "end": at(11).isoformat(),
             "status": "TENTATIVE", "source": "hold:voice"},
            {"id": "d", "title": "dinner with mom", "start": at(18).isoformat(), "end": at(19).isoformat(),
             "status": "TENTATIVE", "source": "hold:voice"},
        ]
        patcher = mock.patch.object(calendar, "all_events", return_value=self.events)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _cmd(self, sentence):
        return voice.interpret(sentence).get("command") or {}

    def test_an_hour_later_moves_it(self):
        cmd = self._cmd("make dinner with mom an hour later")
        self.assertEqual(cmd.get("kind"), "calendar_hold", cmd)
        self.assertEqual(calendar.parse_time(cmd["start"]), self.at(19))
        self.assertEqual(cmd.get("minutes"), 60)

    def test_half_an_hour_earlier(self):
        cmd = self._cmd("make dinner with mom half an hour earlier")
        self.assertEqual(calendar.parse_time(cmd["start"]), self.at(17) + dt.timedelta(minutes=30))

    def test_a_length_keeps_the_start(self):
        for sentence, minutes in (("make dinner with mom 2 hours", 120),
                                  ("make dinner with mom an hour and a half", 90),
                                  ("set dinner with mom to 45 minutes", 45)):
            with self.subTest(sentence=sentence):
                cmd = self._cmd(sentence)
                self.assertEqual((cmd.get("kind"), cmd.get("minutes")), ("calendar_hold", minutes), cmd)
                self.assertEqual(calendar.parse_time(cmd["start"]), self.at(18))

    def test_how_long_is_read_back(self):
        said = voice.interpret("how long is dinner with mom").get("say") or ""
        self.assertIn("an hour", said)
        self.assertIn("6 pm to 7 pm", said)

    def test_nothing_of_hers_is_left_alone(self):
        self.assertNotEqual(self._cmd("make the timer 5 minutes").get("kind"), "calendar_hold")
        self.assertIsNone(voice.interpret("how long is the movie").get("say"))

    def test_last_thing_on_a_weekday(self):
        said = quick.answer("what's my last thing " + self.sunday.strftime("%A").lower()) or ""
        self.assertIn("dinner with mom, done at 7 pm", said)


if __name__ == "__main__":
    unittest.main()
