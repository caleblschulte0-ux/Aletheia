"""A repeating reminder moved by name still repeats (2026-10-12).

"Change the trash reminder to 8" turned the weekly one into a one-off at 8
and switched the weekly one off; "change the trash reminder to Wednesday"
and "move the grandma reminder to Saturday" waited for a model.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import intercom, voice

WEEKLY = {"id": "w", "kind": "weekly", "time": "21:00", "weekdays": [1],
          "command": {"text": "take out the trash"}}
MONTHLY = {"id": "m", "kind": "monthly", "time": "09:00", "monthday": 1, "command": {"text": "pay rent"}}


def said(sentence, found):
    with mock.patch.object(intercom, "_one_reminder", return_value=(found, "")), \
            mock.patch("aletheia.voice._one_of_her_holds", return_value=(None, "")), \
            mock.patch("aletheia.voice._names_one_open_task", return_value=False), \
            mock.patch("aletheia.converse.recent", return_value=[]):
        return voice.interpret(f"thea {sentence}")["command"]


class StillRepeats(unittest.TestCase):
    def test_a_new_time_keeps_its_days_and_its_evening(self):
        self.assertEqual(said("change the trash reminder to 8", WEEKLY),
                         {"kind": "remind_weekly", "days": ["tuesday"], "time": "20:00",
                          "text": "take out the trash", "replaces": "take out the trash"})

    def test_a_new_day_keeps_its_time(self):
        self.assertEqual(said("change the trash reminder to wednesday", WEEKLY),
                         {"kind": "remind_weekly", "days": ["wednesday"], "time": "21:00",
                          "text": "take out the trash", "replaces": "take out the trash"})

    def test_a_monthly_one_keeps_its_date(self):
        self.assertEqual(said("change the rent reminder to 10", MONTHLY),
                         {"kind": "remind_monthly", "day": 1, "time": "10:00", "text": "pay rent",
                          "replaces": "pay rent"})


class AOneOffToAnotherDay(unittest.TestCase):
    def test_saturday_at_the_same_time(self):
        from aletheia import localtime
        tz = localtime.operator_tz()
        soon = (dt.datetime.now(tz) + dt.timedelta(days=1)).replace(hour=14, minute=0, second=0, microsecond=0)
        once = {"id": "o", "kind": "once", "at": soon.isoformat(), "command": {"text": "call grandma"}}
        got = said("move the grandma reminder to saturday", once)
        at = dt.datetime.fromisoformat(got["at"]).astimezone(tz)
        self.assertEqual((got["kind"], at.strftime("%A"), at.hour, got["replaces"]),
                         ("remind_at", "Saturday", 14, "call grandma"))


if __name__ == "__main__":
    unittest.main()
