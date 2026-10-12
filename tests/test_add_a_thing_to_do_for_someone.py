""""Add buy a birthday card for mom due Friday" is a task with a deadline.

It went to the planner (2026-10-12, every model off) and was "kept for when
the big models are back": the bare "add X" rule stopped at any preposition,
so "for mom" or "by Friday" sent a plain thing to do away. And once it was a
task, the first "for" swallowed the deadline: "for mom due Friday" was not a
day, so nothing came due.
"""
import unittest

from aletheia import voice


def command(sentence):
    return voice.interpret(f"thea {sentence}")["command"]


class AddAThingToDo(unittest.TestCase):
    def test_for_someone_with_a_day(self):
        got = command("add buy a birthday card for mom due friday")
        self.assertEqual(got["kind"], "task_new")
        self.assertEqual(got["description"], "buy a birthday card for mom")
        self.assertTrue(got.get("deadline"))

    def test_by_a_day(self):
        got = command("add buy stamps by friday")
        self.assertEqual((got["kind"], got["description"]), ("task_new", "buy stamps"))
        self.assertTrue(got.get("deadline"))

    def test_about_something_by_a_day(self):
        got = command("add email sam about the lease by thursday")
        self.assertEqual(got["description"], "email sam about the lease")

    def test_for_someone_without_a_day(self):
        self.assertEqual(command("add buy a birthday card for mom")["description"], "buy a birthday card for mom")

    def test_other_stores_and_clock_times_are_left_alone(self):
        self.assertNotEqual((command("add call mom at 3") or {}).get("kind"), "task_new")
        self.assertNotEqual((command("add call mom to my contacts") or {}).get("kind"), "task_new")
        self.assertEqual(command("add milk")["kind"], "shopping_add")


class TheDeadlineAfterTheLastWord(unittest.TestCase):
    def test_a_for_inside_the_thing_does_not_swallow_the_day(self):
        desc, due = voice._split_deadline("buy a birthday card for mom due friday")
        self.assertEqual(desc, "buy a birthday card for mom")
        self.assertTrue(due)

    def test_words_that_are_not_a_day_still_stay_in_the_thing(self):
        self.assertEqual(voice._split_deadline("sort the photos by date"), ("sort the photos by date", ""))
        self.assertEqual(voice._split_deadline("write a toast for the wedding"), ("write a toast for the wedding", ""))


if __name__ == "__main__":
    unittest.main()
