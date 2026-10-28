"""Taking back a change to one of his own lists.

2026-10-28, talking to her with the models off:

    > take towels off my packing list
    > undo that
      Nothing to undo: ...
    > delete my packing list
    > undo that
      Nothing to undo: ...
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import converse, intercom, lists


class UndoOnHisLists(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        self.patch = mock.patch.object(lists, "private_dir", lambda name: root / name)
        self.patch.start()
        (root / "lists").mkdir()
        lists.add("packing", ["towels", "sunscreen"])

    def tearDown(self):
        self.patch.stop()
        self.dir.cleanup()

    def undo_after(self, answer):
        with mock.patch.object(converse, "recent", return_value=[{"he_asked": "x", "she_answered": answer}]):
            return intercom._undo_his_last_ask()

    def test_a_line_taken_off_goes_back(self):
        lists.take_off("packing", "towels")
        self.assertEqual(self.undo_after("Took it off your packing list: towels."),
                         "Undone - back on your packing list: towels.")
        self.assertEqual(sorted(lists.items("packing")), ["sunscreen", "towels"])

    def test_a_deleted_list_comes_back(self):
        lists.drop("packing")
        self.assertEqual(self.undo_after("Deleted your packing list and the 2 things on it."),
                         "Undone: your packing list is back, with 2 things on it.")
        self.assertEqual(sorted(lists.items("packing")), ["sunscreen", "towels"])

    def test_a_cleared_list_fills_again(self):
        lists.take_off("packing", "everything")
        self.undo_after("Cleared your packing list - 2 things off it.")
        self.assertEqual(sorted(lists.items("packing")), ["sunscreen", "towels"])


if __name__ == "__main__":
    unittest.main()
