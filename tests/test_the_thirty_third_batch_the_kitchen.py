"""Thirty-third sandbox batch, 2026-10-05: the shopping list and the chores the
way a person says them in a kitchen.

    > add milk / I need eggs / we're out of bread / put milk back on
                                        four planner turns and four approvals,
                                        for what "add milk to the list" does free
    > how many things are on the list   [6.5s] a model
    > mark everything done              the planner: one step per task, an approval
"""
import unittest
from unittest import mock

from aletheia import intercom, quick, voice


class TheKitchen(unittest.TestCase):
    def test_the_bare_shapes_are_the_list(self):
        for said, item in (("add milk", "milk"), ("I need eggs", "eggs"), ("we're out of bread", "bread"),
                           ("put milk back on", "milk"), ("add milk and eggs", "milk and eggs")):
            self.assertEqual(voice.interpret(said)["command"], {"kind": "shopping_add", "item": item}, said)

    def test_a_thing_to_do_and_a_role_are_not_groceries(self):
        self.assertNotEqual(voice.interpret("I need to call the bank")["command"].get("kind"), "shopping_add")
        self.assertEqual(voice.interpret("add a task to mow the lawn")["command"]["kind"], "task_new")
        self.assertEqual(voice.interpret("add Sales Engineer to the roles")["command"]["kind"], "preference_set")
        self.assertNotEqual(voice.interpret("add it")["command"].get("kind"), "shopping_add")

    def test_the_count_is_the_list(self):
        self.assertEqual(quick.match("how many things are on the list")[0], "shopping")

    def test_everything_done_is_the_whole_open_list(self):
        self.assertEqual(voice.interpret("mark everything done")["command"], {"kind": "task_done", "which": "everything"})
        rows = [{"id": "mow", "description": "mow the lawn"}, {"id": "fence", "description": "fix the fence"}]
        with mock.patch("aletheia.intercom._open_tasks", return_value=rows), \
             mock.patch("aletheia.tasks.set_status") as done:
            said = intercom.execute_command({"kind": "task_done", "which": "everything"}, {"repos": {}}, quote="mark everything done")
        self.assertEqual(said, "marked done — mow the lawn and fix the fence")
        self.assertEqual([c.args[0] for c in done.call_args_list], ["mow", "fence"])
        with mock.patch("aletheia.intercom._open_tasks", return_value=[]):
            self.assertEqual(intercom.execute_command({"kind": "task_done", "which": "everything"}, {"repos": {}}), "Nothing open on your task list.")


if __name__ == "__main__":
    unittest.main()


class MyListNamesNoList(unittest.TestCase):
    def test_both_stores_answer(self):
        with mock.patch("aletheia.intercom._tasks_answer", return_value="Nothing on your list."), \
             mock.patch("aletheia.intercom.shopping_answer", return_value="3 things on your shopping list: bread, eggs and milk."):
            self.assertEqual(intercom.my_list_answer(), "3 things on your shopping list: bread, eggs and milk.")
            self.assertEqual(voice.interpret("what's on my list")["say"], "3 things on your shopping list: bread, eggs and milk.")
        with mock.patch("aletheia.intercom._tasks_answer", return_value="2 things on your list: a and b."), \
             mock.patch("aletheia.intercom.shopping_answer", return_value="1 thing on your shopping list: milk."):
            self.assertEqual(intercom.my_list_answer(), "Tasks: 2 things on your task list: a and b. Shopping: 1 thing on your shopping list: milk.")
        with mock.patch("aletheia.intercom._tasks_answer", return_value="Nothing on your list."), \
             mock.patch("aletheia.intercom.shopping_answer", return_value="Nothing on your shopping list."):
            self.assertEqual(quick.answer("what's on my list"), "Nothing on your task list or your shopping list.")

    def test_cross_off_asks_the_shopping_list_first(self):
        with mock.patch.object(voice, "_on_the_shopping_list", return_value=True):
            self.assertEqual(voice.interpret("cross off milk")["command"], {"kind": "shopping_off", "item": "milk"})
        with mock.patch.object(voice, "_on_the_shopping_list", return_value=False):
            self.assertEqual(voice.interpret("cross off milk")["command"], {"kind": "task_done", "which": "milk"})
