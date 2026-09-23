"""From the 2026-09-23 night sweep: "set the volume to 50" planned for a
minute and was refused with "steps[0].action: 'set_volume' not in
['close_window', 'focus_window', ...]" read out in the room; "how many days
until christmas" paid a model for calendar arithmetic."""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from aletheia import intents, quick, voice


class ARefusalInWordsCase(unittest.TestCase):
    def test_an_unknown_hands_action_is_said_not_listed(self):
        said = intents._hands_refused({"n": 1, "detail": "ValueError: steps[0].action: 'set_volume' not in "
                                                         "['close_window', 'focus_window', 'hotkey', 'invoke']"})
        self.assertIn("my hands can't set volume", said)
        self.assertNotIn("[", said)
        self.assertNotIn("close_window", said)

    def test_a_volume_level_is_answered_by_voice(self):
        for said in ("thea set the volume to 50", "thea turn the volume to 20%", "thea put the sound at half"):
            with self.subTest(said=said):
                out = voice.interpret(said)
                self.assertIsNone(out["command"])
                self.assertIn("only up, down and mute", out["say"])
        self.assertEqual(voice.interpret("thea volume up")["command"]["action"], "volume_up")


class DaysUntilCase(unittest.TestCase):
    TODAY = dt.date(2026, 9, 22)

    def test_named_days_weekdays_and_dates(self):
        self.assertEqual(quick._named_date("christmas", self.TODAY), dt.date(2026, 12, 25))
        self.assertEqual(quick._named_date("new year's", self.TODAY), dt.date(2027, 1, 1))
        self.assertEqual(quick._named_date("thanksgiving", self.TODAY), dt.date(2026, 11, 26))
        self.assertEqual(quick._named_date("friday", self.TODAY), dt.date(2026, 9, 25))
        self.assertEqual(quick._named_date("tuesday", self.TODAY), dt.date(2026, 9, 29))
        self.assertEqual(quick._named_date("the 3rd of october", self.TODAY), dt.date(2026, 10, 3))
        self.assertEqual(quick._named_date("march 1", self.TODAY), dt.date(2027, 3, 1))
        self.assertIsNone(quick._named_date("the meeting", self.TODAY))

    def test_the_sentence(self):
        fixed = dt.datetime(2026, 9, 22, 12, 0, tzinfo=dt.timezone.utc)
        with mock.patch("aletheia.localtime.operator_tz", return_value=dt.timezone.utc), \
             mock.patch("aletheia.quick.dt", create=True) as _:
            pass
        with mock.patch("aletheia.quick._named_date", return_value=dt.date(2026, 12, 25)), \
             mock.patch("datetime.datetime") as now:
            now.now.return_value = fixed
            said = quick.answer("how many days until christmas")
        self.assertEqual(said, "94 days, Friday 25 December.")
        with mock.patch("aletheia.quick._named_date", return_value=None):
            self.assertIsNone(quick.answer("how many days until the meeting"))


if __name__ == "__main__":
    unittest.main()
