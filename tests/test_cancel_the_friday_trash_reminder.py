""""Cancel the Friday trash reminder" (2026-10-12).

With trash every Tuesday and Friday at 7 pm, it stopped BOTH days, and
"stop the Friday one" went to the planner.
"""
import unittest
from unittest import mock

from aletheia import intercom, policy, voice

TRASH = {"id": "w1", "kind": "weekly", "weekdays": [1, 4], "time": "19:00", "enabled": True,
         "command": {"kind": "notify", "text": "take out the trash"}}
PLANTS = {"id": "w2", "kind": "weekly", "weekdays": [0, 4], "time": "08:00", "enabled": True,
          "command": {"kind": "notify", "text": "water the plants"}}
GYM = {"id": "w3", "kind": "weekly", "weekdays": [4], "time": "06:00", "enabled": True,
       "command": {"kind": "notify", "text": "go to the gym"}}


def said(sentence, rows):
    with mock.patch.object(policy, "all_approvals", return_value=[]), \
            mock.patch.object(intercom, "_reminder_schedules", return_value=rows):
        return voice.interpret(f"thea {sentence}")


class DropADay(unittest.TestCase):
    def test_the_friday_trash_reminder_keeps_tuesday(self):
        self.assertEqual(said("cancel the friday trash reminder", [TRASH])["command"],
                         {"kind": "remind_weekly", "days": ["tuesday"], "time": "19:00",
                          "text": "take out the trash", "replaces": "take out the trash"})

    def test_the_friday_one(self):
        got = said("stop the friday one", [TRASH])["command"]
        self.assertEqual(got["days"], ["tuesday"])

    def test_take_friday_off(self):
        got = said("take friday off the trash reminder", [TRASH])["command"]
        self.assertEqual(got["days"], ["tuesday"])

    def test_two_on_friday_asks_which(self):
        got = said("stop the friday one", [TRASH, PLANTS])
        self.assertIsNone(got["command"])
        self.assertIn("Which one?", got["say"])

    def test_one_that_is_only_on_friday_is_the_plain_cancel(self):
        got = said("cancel the friday gym reminder", [GYM])["command"]
        self.assertEqual(got["kind"], "reminder_off")


if __name__ == "__main__":
    unittest.main()
