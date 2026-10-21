""""Plan tacos for dinner Tuesday" put "Plan tacos" on the meal plan, and
"what do I need to do today" read the task list and left out tonight's
reminder (2026-10-19, every model off)."""
import unittest
from unittest import mock

from aletheia import quick, voice


class TheVerbIsNotTheDish(unittest.TestCase):
    def test_plan_and_lets_have(self):
        for said, item in (("plan tacos for dinner tuesday", "Tuesday: tacos"),
                           ("let's have chili for dinner friday", "Friday: chili"),
                           ("pizza for dinner saturday", "Saturday: pizza")):
            with self.subTest(said=said):
                cmd = voice.interpret(said)["command"]
                self.assertEqual((cmd["kind"], cmd["list"], cmd["item"]), ("list_add", "meal plan", item))


class TodayHasItsReminders(unittest.TestCase):
    def test_tonights_reminder_is_said(self):
        with mock.patch.object(quick, "_tasks", return_value="1 task open. Next: pick up dry cleaning."), \
                mock.patch.object(quick, "_agenda", return_value="Nothing on your calendar today."), \
                mock.patch.object(quick, "_reminders_on", return_value="1 reminder: today at 9 pm, defrost the chicken."), \
                mock.patch("aletheia.needs_you.items", return_value=[]):
            said = voice.interpret("what do I need to do today")
        self.assertIsNone(said["command"])
        self.assertIn("pick up dry cleaning", said["say"])
        self.assertIn("defrost the chicken", said["say"])

    def test_a_reminder_already_in_the_day_is_not_said_twice(self):
        day = "Nothing on your calendar today. You do have 1 reminder: today at 9 pm, defrost the chicken."
        with mock.patch.object(quick, "_tasks", return_value="Nothing on your list."), \
                mock.patch.object(quick, "_agenda", return_value=day), \
                mock.patch.object(quick, "_reminders_on", return_value="1 reminder: today at 9 pm, defrost the chicken."), \
                mock.patch("aletheia.needs_you.items", return_value=[]):
            said = quick._focus()
        self.assertEqual(said.count("defrost the chicken"), 1)

    def test_without_today_it_is_still_the_list(self):
        self.assertEqual(voice.interpret("what's left to do")["command"], {"kind": "tasks"})


if __name__ == "__main__":
    unittest.main()
