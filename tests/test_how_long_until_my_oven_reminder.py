""""How long until my oven reminder" (2026-10-12).

"When is my oven reminder" answered from her store; "how long until my
oven reminder" went to a model and, with none running, answered nothing.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import intercom, quick, scheduler

AT = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=20, seconds=5)
OVEN = {"id": "r1", "kind": "once", "enabled": True, "at": AT.isoformat(),
        "command": {"kind": "notify", "text": "check the oven"}}


class HowLongUntil(unittest.TestCase):
    def test_named_reminder_says_how_long(self):
        with mock.patch.object(intercom, "_one_reminder", return_value=(OVEN, "")), \
                mock.patch.object(scheduler, "next_occurrence", return_value=AT), \
                mock.patch.object(intercom, "_reminder_words", return_value="check the oven — today"):
            got = quick._until("my oven reminder")
        self.assertTrue(got.startswith("Your oven reminder goes off in 20 minutes"), got)
        self.assertTrue(got.endswith(": check the oven."), got)

    def test_goes_off_is_the_same_question(self):
        with mock.patch.object(quick, "_reminder_until", return_value="x") as asked:
            quick._until("the oven reminder goes off")
        asked.assert_called_once_with("oven")

    def test_none_about_that_is_said(self):
        with mock.patch.object(intercom, "_one_reminder", return_value=(None, "None of your reminders is about dentist.")):
            self.assertEqual(quick._until("my dentist reminder"), "None of your reminders is about dentist.")

    def test_next_reminder_keeps_its_own_reader(self):
        with mock.patch.object(quick, "_reminder_until") as asked:
            quick._until("my next reminder")
        asked.assert_not_called()


if __name__ == "__main__":
    unittest.main()
