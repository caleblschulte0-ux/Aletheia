"""Two follow-ups that waited for a model with every answer on disk (2026-10-12).

"Remind me to water the plants every Sunday at 10", "move it to Saturday",
and "add eggs to the shopping list", "actually make that a dozen eggs" were
both queued "for when the big models are back".
"""
import unittest
from unittest import mock

from aletheia import voice

WEEKLY = {"id": "w1", "kind": "weekly", "time": "10:00", "weekdays": [6],
          "command": {"kind": "notify_operator", "text": "water the plants"}}


def said(sentence):
    return voice.interpret(f"thea {sentence}")


class MoveItToSaturday(unittest.TestCase):
    def test_the_weekly_reminder_just_set_moves_day_and_keeps_its_time(self):
        with mock.patch("aletheia.voice._recent_ask_of",
                        return_value={"kind": "remind_weekly", "days": ["sunday"], "time": "10:00",
                                      "text": "water the plants"}), \
                mock.patch("aletheia.intercom._one_reminder", return_value=(WEEKLY, "")):
            got = said("move it to saturday")["command"]
        self.assertEqual(got, {"kind": "remind_weekly", "days": ["saturday"], "time": "10:00",
                               "text": "water the plants", "replaces": "water the plants"})

    def test_with_no_weekly_reminder_just_set_it_is_not_this(self):
        with mock.patch("aletheia.voice._recent_ask_of", return_value={}):
            got = (said("move it to saturday") or {}).get("command") or {}
        self.assertNotEqual(got.get("kind"), "remind_weekly")

    def test_every_other_week_is_left_alone(self):
        with mock.patch("aletheia.voice._recent_ask_of",
                        return_value={"kind": "remind_weekly", "days": ["sunday"], "time": "10:00",
                                      "text": "water the plants", "every": 2}), \
                mock.patch("aletheia.intercom._one_reminder", return_value=(WEEKLY, "")):
            got = (said("move it to saturday") or {}).get("command") or {}
        self.assertNotEqual(got.get("kind"), "remind_weekly")


class MakeThatADozenEggs(unittest.TestCase):
    def test_the_thing_just_added_is_swapped(self):
        with mock.patch("aletheia.voice._previous_turn",
                        return_value=("add eggs to the shopping list", "Added to the shopping list: eggs.")):
            got = said("actually make that a dozen eggs")["command"]
        self.assertEqual(got, {"kind": "shopping_add", "item": "a dozen eggs", "replaces": "eggs"})

    def test_after_a_task_it_is_still_a_rename(self):
        with mock.patch("aletheia.voice._previous_turn",
                        return_value=("add a task to email sam", "Added a task: email sam.")), \
                mock.patch("aletheia.voice._the_task_just_added", return_value="email sam"):
            got = said("make that call sam")["command"]
        self.assertEqual(got["kind"], "task_change")


DAILY = {"id": "d1", "kind": "daily", "time": "08:00",
         "command": {"kind": "notify_operator", "text": "take your vitamins"}}


def asks(**by_kind):
    return lambda kind, needs, turns=4: by_kind.get(kind, {})


class MakeItNine(unittest.TestCase):
    def test_a_daily_reminder_just_set_stays_daily_at_the_new_time(self):
        with mock.patch("aletheia.voice._recent_ask_of",
                        side_effect=asks(remind_daily={"time": "08:00", "text": "take your vitamins"})), \
                mock.patch("aletheia.intercom._one_reminder", return_value=(DAILY, "")):
            got = said("make it 9")["command"]
        self.assertEqual(got, {"kind": "remind_daily", "time": "09:00", "text": "take your vitamins",
                               "replaces": "take your vitamins"})

    def test_a_weekly_reminder_keeps_its_days(self):
        with mock.patch("aletheia.voice._recent_ask_of",
                        side_effect=asks(remind_weekly={"days": ["sunday"], "time": "10:00",
                                                        "text": "water the plants"})), \
                mock.patch("aletheia.intercom._one_reminder", return_value=(WEEKLY, "")):
            got = said("actually make that 11")["command"]
        self.assertEqual(got, {"kind": "remind_weekly", "days": ["sunday"], "time": "11:00",
                               "text": "water the plants", "replaces": "water the plants"})

    def test_a_bare_hour_keeps_the_evening(self):
        evening = {**DAILY, "time": "20:00"}
        with mock.patch("aletheia.voice._recent_ask_of",
                        side_effect=asks(remind_daily={"time": "20:00", "text": "take your vitamins"})), \
                mock.patch("aletheia.intercom._one_reminder", return_value=(evening, "")):
            got = said("make it 9")["command"]
        self.assertEqual(got["time"], "21:00")


if __name__ == "__main__":
    unittest.main()
