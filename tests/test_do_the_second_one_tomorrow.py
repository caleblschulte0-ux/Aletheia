""""Add call the plumber", "add pay the water bill too", "do the second one
tomorrow" (2026-10-14: the second was saved as "pay the water bill too", the
third went to a model and came back as an approval, and the list read back
afterwards left the day out).
"""
import unittest
from unittest import mock

from aletheia import policy, quick, tasks, voice


def said(sentence):
    with mock.patch.object(policy, "all_approvals", return_value=[]):
        return voice.interpret(f"thea {sentence}")["command"]


class ThePhrasings(unittest.TestCase):
    def test_a_place_on_the_list_and_a_day(self):
        got = said("do the second one tomorrow")
        self.assertEqual((got["kind"], got["which"]), ("task_change", "the second one"))
        self.assertTrue(got["deadline"])
        self.assertEqual(said("make the first one due friday")["which"], "the first one")
        self.assertEqual(said("move the top one to monday")["which"], "the first one")

    def test_too_is_not_part_of_the_task(self):
        self.assertEqual(voice._new_task("pay the water bill too")["command"]["description"], "pay the water bill")
        self.assertEqual(voice._new_task("call mom as well")["command"]["description"], "call mom")


class TheListSaysTheDay(unittest.TestCase):
    def test_a_short_list_names_each_deadline(self):
        rows = [{"id": "a", "description": "call the plumber", "status": "OPEN"},
                {"id": "b", "description": "pay the water bill", "status": "OPEN", "deadline": "2026-10-15"}]
        with mock.patch.object(tasks, "all_tasks", return_value=rows), \
                mock.patch.object(tasks, "is_his", return_value=True), \
                mock.patch.object(tasks, "is_ready", return_value=True):
            got = quick._tasks()
        self.assertTrue(got.startswith("2 tasks open: call the plumber and pay the water bill due "), got)


if __name__ == "__main__":
    unittest.main()
