""""Remind me the day before Halloween to buy candy" (2026-10-16, every model
off) said "I don't see halloween on your calendar", one turn after she had
said which day Halloween is. A named day is a day; "a week before Christmas
to mail the cards" is Christmas, not an event called "christmas to mail the
cards"; and "the morning of Christmas Eve" is the morning of it."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import calendar as cal, localtime, voice


def _said(sentence):
    with mock.patch.object(cal, "all_events", return_value=[]), \
            mock.patch.object(voice, "_event_from_notes", return_value=None):
        return voice.interpret(sentence)


class ANamedDayIsADay(unittest.TestCase):
    def _at(self, got):
        self.assertIsNotNone(got["command"], got)
        self.assertEqual(got["command"]["kind"], "remind_at")
        return dt.datetime.fromisoformat(got["command"]["at"]).astimezone(localtime.operator_tz())

    def _next(self, month, day):
        today = dt.datetime.now(localtime.operator_tz()).date()
        when = dt.date(today.year, month, day)
        return when if when >= today else dt.date(today.year + 1, month, day)

    def test_the_day_before_halloween(self):
        got = _said("remind me the day before halloween to buy candy")
        at = self._at(got)
        self.assertEqual(at.date(), self._next(10, 31) - dt.timedelta(days=1))
        self.assertEqual(at.hour, 9)
        self.assertTrue(got["command"]["text"].startswith("buy candy - Halloween is "), got)

    def test_a_week_before_christmas_keeps_the_errand(self):
        got = _said("remind me a week before christmas to mail the cards")
        at = self._at(got)
        self.assertEqual(at.date(), self._next(12, 25) - dt.timedelta(days=7))
        self.assertIn("mail the cards", got["command"]["text"])

    def test_the_morning_of_christmas_eve(self):
        got = _said("remind me the morning of christmas eve to call grandma")
        at = self._at(got)
        self.assertEqual((at.date(), at.hour), (self._next(12, 24), 8))
        self.assertIn("call grandma", got["command"]["text"])

    def test_something_not_on_the_calendar_still_says_so(self):
        got = _said("remind me the day before the dentist")
        self.assertIsNone(got["command"])
        self.assertIn("calendar", got["say"])


if __name__ == "__main__":
    unittest.main()
