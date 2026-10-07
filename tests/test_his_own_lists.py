"""He keeps lists that are not shopping and not tasks.

    > make a list called packing
    > add socks to my packing list
    > what's on my packing list

All three went to the planner, and with no frontier model they were queued
for later or compiled into a shopping item called "socks to my packing".
A packing list, a movies list, a gift list is a list of his with a NAME,
kept in its own small file, read back in his words, and never mistaken for
the shopping list or the tasks, which keep their own stores and verbs.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import intercom, lists, voice


def heard(said):
    return voice.interpret(said)["command"]


class HeSaysIt(unittest.TestCase):
    def test_making_a_list(self):
        for said in ("make a list called packing", "start a packing list",
                     "create a new list named Packing"):
            cmd = heard(said)
            self.assertEqual(cmd["kind"], "list_new", said)
            self.assertEqual(cmd["list"].lower(), "packing", said)

    def test_a_list_with_no_name_asks_for_one(self):
        out = voice.interpret("start a list")
        self.assertIsNone(out["command"])
        self.assertIn("call it", out["say"])

    def test_adding_reading_and_taking_off(self):
        self.assertEqual(heard("add Dune to my movies list"),
                         {"kind": "list_add", "list": "movies", "item": "Dune"})
        self.assertEqual(heard("what's on my movies list"),
                         {"kind": "list_read", "list": "movies"})
        self.assertEqual(heard("take Dune off my movies list"),
                         {"kind": "list_off", "list": "movies", "item": "Dune"})
        self.assertEqual(heard("clear my movies list"),
                         {"kind": "list_off", "list": "movies", "item": "everything"})
        self.assertEqual(heard("what lists do I have"), {"kind": "list_read"})

    def test_the_lists_that_have_their_own_stores_keep_them(self):
        self.assertEqual(heard("add milk to my shopping list")["kind"], "shopping_add")
        self.assertEqual(heard("what's on my shopping list")["kind"], "shopping_list")
        self.assertEqual(heard("add milk to the list")["kind"], "shopping_add")
        for name in ("shopping", "grocery", "to-do", "tasks", "reminders"):
            self.assertFalse(lists.is_named_list(name), name)

    def test_reading_is_read_only_and_writing_is_routine(self):
        self.assertIn("list_read", intercom.READ_ONLY_KINDS)
        for kind in ("list_new", "list_add", "list_off"):
            self.assertIn(kind, intercom.ROUTINE_KINDS, kind)
        self.assertIn("list_add", intercom.UNDOES_HIS_ASK)


class TheStoreAnswers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        patcher = mock.patch.object(lists, "private_dir",
                                    side_effect=lambda name: (root / name).mkdir(
                                        parents=True, exist_ok=True) or root / name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def run_it(self, **cmd):
        return intercom.execute_command(cmd, {})

    def test_the_round_trip(self):
        self.assertIn("Started your packing list", self.run_it(kind="list_new", list="packing"))
        self.assertEqual(self.run_it(kind="list_add", list="packing", item="socks, a charger"),
                         "Added to your packing list: socks and a charger.")
        self.assertEqual(self.run_it(kind="list_read", list="packing"),
                         "2 things on your packing list: socks and a charger.")
        self.assertIn("socks", self.run_it(kind="list_off", list="packing", item="socks"))
        self.assertEqual(lists.items("packing"), ["a charger"])

    def test_adding_to_a_list_that_does_not_exist_yet_starts_it(self):
        self.run_it(kind="list_add", list="movies", item="Dune")
        self.assertEqual(lists.items("movies"), ["Dune"])
        self.assertIn("movies", self.run_it(kind="list_read"))

    def test_clearing_says_cleared_and_an_empty_list_says_empty(self):
        self.run_it(kind="list_add", list="gifts", item="a scarf, a book")
        self.assertEqual(self.run_it(kind="list_off", list="gifts", item="everything"),
                         "Cleared your gifts list - 2 things off it.")
        self.assertEqual(self.run_it(kind="list_off", list="gifts", item="everything"),
                         "Your gifts list is already empty.")
        self.assertEqual(self.run_it(kind="list_read", list="gifts"),
                         "Your gifts list is empty.")

    def test_a_list_he_never_made_is_not_denied_it_is_offered(self):
        out = self.run_it(kind="list_read", list="camping")
        self.assertIn("make a list called camping", out)


if __name__ == "__main__":
    unittest.main()
