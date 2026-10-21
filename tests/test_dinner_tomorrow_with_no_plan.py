""""What's for dinner tomorrow" with no meal plan kept went to a model, and
"clear the meal plan" went to the planner (2026-10-21, every model off)."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, quick, voice


class DinnerWithNoPlan(unittest.TestCase):
    def ask(self, said, events=()):
        with mock.patch("aletheia.lists.items", return_value=None), \
                mock.patch("aletheia.calendar.all_events", return_value=list(events)):
            return quick._meal_plan(quick._tidy(said))

    def test_nothing_planned_is_said(self):
        said = self.ask("what's for dinner tomorrow")
        self.assertIn("Nothing's planned for dinner tomorrow", said)
        self.assertIn("meal plan", said)

    def test_the_calendars_dinner_is_said(self):
        start = (dt.datetime.now(localtime.operator_tz()) + dt.timedelta(days=1)).replace(hour=19, minute=0, second=0, microsecond=0)
        said = self.ask("what's for dinner tomorrow", [{"title": "Dinner with Sam", "start": start.isoformat()}])
        self.assertEqual(said, "Tomorrow you have Dinner with Sam at 7 pm.")

    def test_the_suggestion_is_a_sentence_she_understands(self):
        said = self.ask("what am I having for lunch friday")
        suggestion = said.split('"')[1]
        cmd = voice.interpret(suggestion)["command"]
        self.assertEqual((cmd["kind"], cmd["list"]), ("list_add", "meal plan"))


class ClearTheMealPlan(unittest.TestCase):
    def test_without_the_word_list(self):
        for said in ("clear the meal plan", "clear my meal plan", "empty the meal plan", "reset our meal plan"):
            with self.subTest(said=said):
                self.assertEqual(voice.interpret(said)["command"],
                                 {"kind": "list_off", "list": "meal plan", "item": "everything"})


if __name__ == "__main__":
    unittest.main()
