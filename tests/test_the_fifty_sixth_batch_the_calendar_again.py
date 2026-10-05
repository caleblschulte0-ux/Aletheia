"""Fifty-sixth sandbox batch, 2026-10-05: the calendar, asked sideways.

    > what's on friday                      [4.6s] a model
    > how long until my next meeting        the meeting, not the wait
    > do I have anything tomorrow morning   [4.0s] a model
    > what time works for a call on thursday [6.0s] a model
    > hold lunch every day at noon          [6.5s] a plan offering a reminder instead, for approval
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import presence, quick, voice


class TheCalendarAgain(unittest.TestCase):
    def test_a_day_on_its_own_is_the_agenda(self):
        for said in ("what's on friday", "anything friday", "what's happening on monday", "anything tomorrow"):
            self.assertEqual(quick.match(said)[0], "agenda", said)
        self.assertEqual(quick.match("what's on friday")[1], "friday")

    def test_how_long_until_the_next_meeting_is_a_wait(self):
        start = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2, minutes=1)
        appt = {"title": "dinner with Sam", "when": "tonight at 8 pm", "start": start.isoformat()}
        with mock.patch.object(presence, "_next_appointment", return_value=appt):
            self.assertEqual(quick.answer("what's my next meeting"), "dinner with Sam tonight at 8 pm.")
            said = quick.answer("how long until my next meeting")
            self.assertRegex(said, r"^2 hours(?: and \d+ minutes?)? - dinner with Sam")

    def test_free_time_said_three_more_ways(self):
        for said in ("do I have anything tomorrow morning", "what time works for a call on thursday", "when could I fit in a call friday"):
            d = voice.interpret(f"thea {said}")
            self.assertEqual(d["command"]["kind"], "free_time", said)

    def test_a_repeating_hold_is_refused_plainly(self):
        from aletheia import demand
        with mock.patch.object(demand, "record") as rec:
            d = voice.interpret("thea hold lunch every day at noon")
        self.assertIsNone(d["command"])
        self.assertIn("isn't built", d["say"])
        self.assertIn("remind me every day at noon", d["say"])
        rec.assert_called_once()
        self.assertEqual(voice.interpret("thea hold friday at noon for lunch")["command"]["kind"], "calendar_hold")


if __name__ == "__main__":
    unittest.main()
