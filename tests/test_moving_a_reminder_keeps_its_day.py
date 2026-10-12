""""Change the rent reminder to 2pm" keeps the reminder's day.

Said on a Monday about Tuesday's reminder (2026-10-12), it came back "I'll
remind you today at 2 pm": the new time was laid on the next time 2 pm
comes round, and the day he set it for was lost. A new time is not a new day.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, voice


def once(text, at):
    return {"id": "r1", "kind": "once", "at": at.isoformat(), "enabled": True,
            "command": {"kind": "notify_operator", "text": text}}


class MovingAReminder(unittest.TestCase):
    def _moved(self, sentence, at, text):
        with mock.patch("aletheia.intercom._one_reminder", return_value=(once(text, at), "")), \
                mock.patch("aletheia.converse.recent", return_value=[]):
            return voice.interpret(f"thea {sentence}")["command"]

    def _in_days(self, days, hour):
        tz = localtime.operator_tz()
        day = dt.datetime.now(tz).date() + dt.timedelta(days=days)
        return dt.datetime(day.year, day.month, day.day, hour, 0, tzinfo=tz)

    def test_a_new_time_stays_on_the_same_day(self):
        was = self._in_days(3, 12)
        got = self._moved("change the rent reminder to 2pm", was, "pay rent")
        self.assertEqual(got["kind"], "remind_at")
        self.assertEqual(got["replaces"], "pay rent")
        self.assertEqual(dt.datetime.fromisoformat(got["at"]), was.replace(hour=14))

    def test_a_bare_hour_keeps_the_half_of_the_day(self):
        was = self._in_days(2, 15)
        got = self._moved("move my call bob reminder to 4", was, "call bob")
        self.assertEqual(dt.datetime.fromisoformat(got["at"]), was.replace(hour=16))

    def test_an_unreadable_old_time_falls_back_to_the_next_one(self):
        with mock.patch("aletheia.intercom._one_reminder",
                        return_value=({"id": "r1", "kind": "once", "at": "soon",
                                       "command": {"text": "pay rent"}}, "")), \
                mock.patch("aletheia.converse.recent", return_value=[]):
            got = voice.interpret("thea change the rent reminder to 2pm")["command"]
        at = dt.datetime.fromisoformat(got["at"])
        self.assertGreater(at, dt.datetime.now(at.tzinfo))
        self.assertEqual((at.hour, at.minute), (14, 0))


if __name__ == "__main__":
    unittest.main()
