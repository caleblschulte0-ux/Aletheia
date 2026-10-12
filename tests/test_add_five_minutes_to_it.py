""""Add 5 minutes to it" after setting a timer, and a timer named after its
length (2026-10-12).

"Set a timer for 10 minutes" then "add 5 minutes to it" went to the planner;
"set a 10 minute eggs timer" did too; a timer with 5 more on it was still
cancelled as "your 10-minute timer"; and "cancel the eggs timer" with none
running said "You have no reminders set."
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import intercom, policy, voice

SOON = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=8)


def said(sentence, previous="", running=()):
    with mock.patch.object(policy, "all_approvals", return_value=[]), \
            mock.patch("aletheia.voice._previous_ask", return_value=previous), \
            mock.patch("aletheia.voice._running_once", return_value=list(running)):
        return voice.interpret(f"thea {sentence}")


class AddMinutesToIt(unittest.TestCase):
    def test_it_is_the_timer_just_set(self):
        got = said("add 5 minutes to it", "set a timer for 10 minutes",
                   [(SOON, "your 10-minute timer is up")])["command"]
        self.assertEqual(got["kind"], "remind_at")
        self.assertEqual(got["replaces"], "your 10-minute timer is up")
        self.assertEqual(got["text"], "your 15-minute timer is up")
        self.assertEqual(dt.datetime.fromisoformat(got["at"]), SOON + dt.timedelta(minutes=5))

    def test_a_named_timer_keeps_its_name_and_grows(self):
        got = said("add 2 minutes to the eggs timer", "",
                   [(SOON, "your 10 minute eggs timer is up")])["command"]
        self.assertEqual(got["text"], "your 12 minute eggs timer is up")

    def test_it_after_a_reminder_is_not_a_timer(self):
        got = said("add 5 minutes to it", "remind me at 5 to call bob",
                   [(SOON, "your 10-minute timer is up")])
        command = (got or {}).get("command") or {}
        self.assertNotIn("timer is up", str(command.get("text") or ""))


class LengthThenName(unittest.TestCase):
    def test_eggs_timer(self):
        got = said("set a 10 minute eggs timer")["command"]
        self.assertEqual(got["kind"], "remind_at")
        self.assertIn("eggs", got["text"])
        self.assertIn("timer is up", got["text"])

    def test_kitchen_is_just_a_timer(self):
        got = said("set a 5 minute kitchen timer")["command"]
        self.assertEqual(got["kind"], "remind_at")
        self.assertNotIn("kitchen", got["text"])


class NothingToCancel(unittest.TestCase):
    def test_timer_and_alarm_say_what_they_are(self):
        with mock.patch.object(intercom, "_reminder_schedules", return_value=[]):
            self.assertEqual(intercom._one_reminder("eggs timer"), (None, "You don't have a timer running."))
            self.assertEqual(intercom._one_reminder("wake up"), (None, "You have no alarms set."))
            self.assertEqual(intercom._one_reminder("call bob"), (None, "You have no reminders set."))


if __name__ == "__main__":
    unittest.main()
