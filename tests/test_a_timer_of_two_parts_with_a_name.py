""""Set a timer for an hour and a half", then "how long is left" said "1 hour
and 30 minutes left on the 30 minute timer"; and "set a roast timer for 1 hour
15 minutes" went to the planner (2026-10-15, every model off)."""
import datetime as dt
import re
import unittest
from unittest import mock

from aletheia import intercom, speech, voice


class TheLengthIsNotTheName(unittest.TestCase):
    def test_two_part_length_has_no_name(self):
        self.assertIsNone(re.fullmatch(speech.TIMER_CALLED, "1 hour 30 minute"))
        self.assertEqual(re.fullmatch(speech.TIMER_CALLED, "1 hour 15 minute roast").group(1), "roast")
        self.assertEqual(re.fullmatch(speech.TIMER_CALLED, "10 minute eggs").group(1), "eggs")

    def test_how_long_is_left(self):
        at = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=90)).isoformat()
        rows = [{"kind": "once", "at": at, "command": {"kind": "notify", "text": "your 1 hour 30 minute timer is up"}}]
        with mock.patch.object(intercom, "_reminder_schedules", return_value=rows):
            said = voice._timer_left()
        self.assertNotIn("the 30 minute timer", said)


class ANameOnATwoPartTimer(unittest.TestCase):
    def test_every_way_he_names_it(self):
        for said in ("set a timer for 1 hour 15 minutes called roast", "set a timer for 1 hour and 15 minutes for the roast",
                     "set a roast timer for 1 hour 15 minutes"):
            with self.subTest(said=said):
                cmd = voice._interpret(said)["command"]
                self.assertEqual(cmd["kind"], "remind_at")
                self.assertEqual(cmd["text"], "your 1 hour 15 minute roast timer is up")

    def test_unnamed_is_unchanged(self):
        self.assertEqual(voice._interpret("set a timer for an hour and a half")["command"]["text"],
                         "your 1 hour 30 minute timer is up")
        self.assertEqual(voice._interpret("set a new timer for an hour and a half")["command"]["text"],
                         "your 1 hour 30 minute timer is up")


if __name__ == "__main__":
    unittest.main()
