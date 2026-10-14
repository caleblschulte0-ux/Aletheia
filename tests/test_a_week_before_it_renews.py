""""My car insurance renews December 1", then "remind me a week before"
(2026-10-14: to a model, which offered the reminder as an approval); and
"snooze it 10 minutes" on a reminder that had not gone off told him to say
"move it to" instead of pushing it, while "push it back 30 minutes" did.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, notifications, policy, quick, voice


class AWeekBefore(unittest.TestCase):
    def setUp(self):
        self.tz = localtime.operator_tz()
        self.on = dt.datetime.now(self.tz).date() + dt.timedelta(days=30)
        self.said = f"my car insurance renews {self.on.strftime('%B').lower()} {self.on.day}"

    def test_the_date_his_note_just_gave(self):
        with mock.patch.object(quick, "_noted_dates", return_value=[(self.on, self.said)]):
            got = voice._before_a_noted_date("remind me a week before", self.said)
        cmd = got["command"]
        self.assertEqual(cmd["kind"], "remind_at")
        at = dt.datetime.fromisoformat(cmd["at"])
        self.assertEqual((at.date(), at.hour), (self.on - dt.timedelta(days=7), 9))
        self.assertEqual(cmd["text"], f"your car insurance renews {self.on.strftime('%B')} {self.on.day} - in a week")

    def test_the_day_before_and_a_number_of_days(self):
        with mock.patch.object(quick, "_noted_dates", return_value=[(self.on, self.said)]):
            day = voice._before_a_noted_date("remind me the day before", f"note that {self.said}")
            two = voice._before_a_noted_date("remind me 2 days before", self.said)
        self.assertEqual(dt.datetime.fromisoformat(day["command"]["at"]).date(), self.on - dt.timedelta(days=1))
        self.assertTrue(day["command"]["text"].endswith("- tomorrow"))
        self.assertEqual(dt.datetime.fromisoformat(two["command"]["at"]).date(), self.on - dt.timedelta(days=2))

    def test_a_day_already_gone_is_said_and_another_sentence_is_nothing(self):
        soon = dt.datetime.now(self.tz).date() + dt.timedelta(days=2)
        with mock.patch.object(quick, "_noted_dates", return_value=[(soon, "my lease ends soon")]):
            gone = voice._before_a_noted_date("remind me a week before", "my lease ends soon")
            other = voice._before_a_noted_date("remind me a week before", "what's the weather")
        self.assertIsNone(gone["command"])
        self.assertIn("already gone by", gone["say"])
        self.assertIsNone(other)


class SnoozeWhatHasNotGoneOff(unittest.TestCase):
    def test_a_named_interval_pushes_it(self):
        pushed = {"command": {"kind": "remind_at", "at": "x", "text": "call mom"}, "say": None}
        real = voice._interpret

        def interp(sentence, *a, **k):
            return pushed if sentence == "push it back 10 minutes" else real(sentence, *a, **k)
        with mock.patch.object(notifications, "all_notifications", return_value=[]), \
                mock.patch.object(policy, "all_approvals", return_value=[]), \
                mock.patch.object(voice, "_interpret", side_effect=interp):
            got = real("snooze it 10 minutes")
        self.assertEqual(got, pushed)

    def test_something_that_went_off_is_still_snoozed(self):
        with mock.patch.object(notifications, "all_notifications", return_value=[{"id": "n1"}]), \
                mock.patch.object(policy, "all_approvals", return_value=[]):
            got = voice.interpret("thea snooze it 10 minutes")["command"]
        self.assertEqual((got["kind"], got["minutes"]), ("notify_snooze", 10))


if __name__ == "__main__":
    unittest.main()
