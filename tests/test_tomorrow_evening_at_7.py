"""A part of the day settles which half a bare hour is in (2026-10-12).

"Remind me to call mom tomorrow evening at 7" was set for seven in the
MORNING, "tomorrow night at 9" for nine in the morning, "remind me about
the dry cleaning tomorrow at noon" for TODAY with "tomorrow" in the words,
and "tonight at 8" said with "about" for eight tomorrow morning.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, voice


def when(sentence):
    with mock.patch("aletheia.converse.recent", return_value=[]):
        cmd = voice.interpret(f"thea {sentence}")["command"]
    at = dt.datetime.fromisoformat(cmd["at"]).astimezone(localtime.operator_tz())
    return at, cmd["text"]


TOMORROW = lambda: localtime.today() + dt.timedelta(days=1)  # noqa: E731


def this_evening_at_7(case, sentence, text=None):
    """Seven this evening, or - once seven has gone by on his clock - her
    saying so rather than quietly moving it (CI ran these at 7:10 pm
    Central on 2026-10-14 and the clock, not the code, failed them)."""
    if dt.datetime.now(localtime.operator_tz()).hour >= 19:
        with mock.patch("aletheia.converse.recent", return_value=[]):
            out = voice.interpret(f"thea {sentence}")
        case.assertIsNone(out["command"], sentence)
        case.assertIn("already past 7 pm today", out["say"], sentence)
        return
    at, said = when(sentence)
    case.assertEqual(at.hour, 19, sentence)
    if text is not None:
        case.assertEqual(said, text, sentence)


class APartOfTheDay(unittest.TestCase):
    def test_tomorrow_evening_at_7_is_the_evening(self):
        at, text = when("remind me to call mom tomorrow evening at 7")
        self.assertEqual((at.date(), at.hour, text), (TOMORROW(), 19, "call mom"))

    def test_tomorrow_night_at_9_is_the_night(self):
        at, _ = when("remind me to call mom tomorrow night at 9")
        self.assertEqual((at.date(), at.hour), (TOMORROW(), 21))

    def test_tomorrow_morning_at_8_stays_the_morning(self):
        at, _ = when("remind me tomorrow morning at 8 to call mom")
        self.assertEqual(at.hour, 8)

    def test_this_evening_at_7_either_way_round(self):
        for sentence in ("remind me this evening at 7 to call mom", "remind me to call mom this evening at 7",
                         "remind me to call mom at 7 this evening"):
            this_evening_at_7(self, sentence, "call mom")


class AboutWithADay(unittest.TestCase):
    def test_tomorrow_at_noon_is_tomorrow(self):
        at, text = when("remind me about the dry cleaning tomorrow at noon")
        self.assertEqual((at.date(), at.hour, text), (TOMORROW(), 12, "the dry cleaning"))

    def test_tonight_at_8_is_tonight(self):
        at, text = when("remind me about the dry cleaning tonight at 8")
        self.assertEqual((at.hour, text), (20, "the dry cleaning"))

    def test_this_evening_at_7(self):
        this_evening_at_7(self, "remind me about the dry cleaning this evening at 7")


if __name__ == "__main__":
    unittest.main()
