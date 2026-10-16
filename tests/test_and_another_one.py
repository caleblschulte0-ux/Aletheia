"""Three follow-ups found 2026-10-16 in the sandbox with every model off.

"Add a task to email the landlord", "and another to fix the sink" went to a
model; so did "make it 7pm tomorrow" after a reminder (while "make it
tomorrow at 7pm" moved it), and "what's open on my task list".
"""
import unittest
from unittest import mock

from aletheia import converse, quick, voice


def _after(answer):
    return mock.patch.object(converse, "recent", return_value=[
        {"he_asked": "earlier", "she_answered": answer}])


class AnotherTask(unittest.TestCase):
    def test_after_a_task_another_is_another_task(self):
        with _after("Added a task: email the landlord."):
            for said, what in (("and another to fix the sink", "fix the sink"),
                               ("another one to call Mom", "call Mom"),
                               ("add another task to mow", "mow")):
                with self.subTest(said=said):
                    cmd = voice._interpret(said)["command"]
                    self.assertEqual((cmd["kind"], cmd["description"]), ("task_new", what))

    def test_after_anything_else_it_is_not_a_task(self):
        with _after("I'll remind you tomorrow at 5 pm: call jen."):
            self.assertNotEqual(voice._interpret("and another to fix the sink")["command"].get("kind"), "task_new")

    def test_more_time_is_never_a_task(self):
        with _after("Added a task: email the landlord."):
            for said in ("another 5 minutes", "another hour", "another one minute"):
                with self.subTest(said=said):
                    self.assertNotEqual((voice._interpret(said)["command"] or {}).get("kind"), "task_new")


class TimeThenDay(unittest.TestCase):
    def test_it_moves_the_reminder_like_day_then_time(self):
        turn = [{"he_asked": "remind me at 5 to call jen", "she_answered": "I'll remind you tomorrow at 5 pm: call jen."}]
        with mock.patch.object(converse, "recent", return_value=turn):
            for said, same in (("make it 7pm tomorrow", "make it tomorrow at 7pm"),
                               ("no, make it 7 on friday", "make it friday at 7"),
                               ("change it to 8:30 am monday", "make it monday at 8:30 am")):
                with self.subTest(said=said):
                    got, want = voice._interpret(said)["command"], voice._interpret(same)["command"]
                    self.assertNotEqual(want.get("kind"), "intent")
                    self.assertEqual(got, want)


class OpenTasks(unittest.TestCase):
    def test_what_is_open_reaches_the_task_list(self):
        for said in ("what's open on my task list", "what tasks are open", "what's still open on my to do list"):
            with self.subTest(said=said):
                tidy = quick._tidy(said)
                self.assertIn("tasks", [name for name, pattern in quick.PATTERNS if pattern.search(tidy)])
