"""Six from the second sweep with every frontier off (2026-09-22): "what's my
schedule this week" and "how many tasks do I have left" paid a model for
stores the fast lane already reads; "what's the last thing you did" paid
one to read the newest journal line; "remind me to call mom when I get
home" waited two minutes (a place is not a time); "add milk and eggs" made
ONE row called "milk and eggs"; "clear the shopping list" planned two steps
for two minutes on her own model."""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import intercom, quick, rule_planner, voice


class TheFastLaneReadsThemCase(unittest.TestCase):
    def test_schedule_this_week_is_the_calendar_shape(self):
        with mock.patch("aletheia.quick._agenda", return_value="Nothing on your calendar this week.") as agenda:
            self.assertEqual(quick.answer("what's my schedule this week"), "Nothing on your calendar this week.")
            self.assertEqual(agenda.call_args[0][0], "this week")

    def test_tasks_left_is_the_tasks_shape(self):
        with mock.patch("aletheia.quick._tasks", return_value="2 tasks open.") as tasks:
            for said in ("how many tasks do I have left", "what tasks do I have open", "what's left to do"):
                with self.subTest(said=said):
                    self.assertEqual(quick.answer(said), "2 tasks open.")
            self.assertTrue(tasks.called)

    def test_the_last_thing_she_did_is_the_newest_journal_line(self):
        rows = [{"what": "Added a task: call the plumber"}, {"what": "Set a reminder for 3 pm"}]
        with mock.patch("aletheia.quick._on_day", side_effect=lambda d: rows if d == 0 else []):
            self.assertEqual(quick.answer("what's the last thing you did"),
                             "The last thing I did today: Set a reminder for 3 pm.")
        with mock.patch("aletheia.quick._on_day", side_effect=lambda d: [] if d == 0 else rows[:1]):
            self.assertIn("yesterday", quick.answer("what did you just do"))
        with mock.patch("aletheia.quick._on_day", return_value=[]):
            self.assertIn("Nothing in my journal", quick.answer("what was the last thing you did"))


class APlaceIsNotATimeCase(unittest.TestCase):
    def test_when_i_get_home_is_said_not_guessed(self):
        for said in ("thea remind me to call mom when I get home", "thea remind me to take the bins out when I'm home",
                     "thea remind me that the oven is on when I get back"):
            with self.subTest(said=said):
                out = voice.interpret(said)
                self.assertIsNone(out["command"])
                self.assertIn("where you are", out["say"])
        self.assertEqual(voice.interpret("thea remind me to call mom at 6")["command"]["kind"], "remind_at")


class TheShoppingListCase(unittest.TestCase):
    def test_milk_and_eggs_are_two_rows_and_a_named_thing_is_one(self):
        self.assertEqual(intercom.shopping_items_of("milk and eggs"), ["milk", "eggs"])
        self.assertEqual(intercom.shopping_items_of("milk, eggs and bread"), ["milk", "eggs", "bread"])
        self.assertEqual(intercom.shopping_items_of("salt and vinegar chips"), ["salt and vinegar chips"])
        self.assertEqual(intercom.shopping_items_of("milk"), ["milk"])

    def test_adding_two_makes_two_rows(self):
        made = []
        with mock.patch("aletheia.shopping.create",
                        side_effect=lambda wid, need, budget=None: made.append(need) or {"need": need}):
            said = intercom.execute_command({"kind": "shopping_add", "item": "milk and eggs"}, {})
        self.assertEqual(made, ["milk", "eggs"])
        self.assertEqual(said, "Added to the shopping list: milk and eggs.")

    def test_clear_takes_everything_off_and_says_what(self):
        kind, args, summary = rule_planner.match("clear the shopping list")
        self.assertEqual((kind, args), ("shopping_off", {"item": "everything"}))
        rows = [{"id": "shop-1", "need": "milk"}, {"id": "shop-2", "need": "eggs"}]
        with mock.patch("aletheia.intercom._shopping_items", return_value=rows), \
             mock.patch("aletheia.shopping.cancel") as cancel:
            said = intercom.execute_command({"kind": "shopping_off", "item": "everything"}, {})
        self.assertEqual([c.args[0] for c in cancel.call_args_list], ["shop-1", "shop-2"])
        self.assertEqual(said, "Took 2 things off the shopping list: milk and eggs.")
        with mock.patch("aletheia.intercom._shopping_items", return_value=[]):
            self.assertIn("already empty", intercom.execute_command({"kind": "shopping_off", "item": "everything"}, {}))
        self.assertEqual(rule_planner.match("take eggs off the shopping list")[1], {"item": "eggs"})


if __name__ == "__main__":
    unittest.main()
