"""A list he keeps can be renamed, and a line moved by part of its words.

2026-10-28, talking to her with the models off:

    > rename the gift ideas list to christmas gifts      (to the planner)
    > move scarf from gift ideas to the shopping list    (to the planner:
      the line was "a scarf for mom", and "gift ideas" had no "list")

A rename keeps every line and never deletes a file; a list he does not
have is said to be missing rather than sent to a model.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import intercom, lists, voice


class Renamed(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        p = mock.patch.object(lists, "private_dir", lambda name: self.tmp / name)
        p.start()
        self.addCleanup(p.stop)
        (self.tmp / "lists").mkdir()
        lists.add("gift ideas", ["a scarf for mom"])

    def test_the_lines_go_with_it(self):
        said = intercom.execute_command({"kind": "list_new", "list": "christmas gifts", "from": "gift ideas"}, {})
        self.assertEqual(said, "Renamed your gift ideas list to christmas gifts - 1 thing on it.")
        self.assertEqual(lists.items("christmas gifts"), ["a scarf for mom"])
        self.assertIsNone(lists.items("gift ideas"))
        self.assertTrue((self.tmp / "lists" / "gift-ideas.json").is_file())      # kept, marked deleted

    def test_two_lists_are_never_merged(self):
        from aletheia import act
        lists.add("christmas", ["socks"])
        with self.assertRaises(act.Refused):
            intercom.execute_command({"kind": "list_new", "list": "christmas", "from": "gift ideas"}, {})
        self.assertEqual(lists.items("gift ideas"), ["a scarf for mom"])

    def test_he_can_say_it(self):
        for said in ("rename the gift ideas list to christmas gifts", "rename gift ideas to christmas gifts",
                     "call the gift ideas list christmas gifts"):
            got = voice.interpret(said)["command"]
            self.assertEqual((got["kind"], got["list"], got["from"]),
                             ("list_new", "christmas gifts", "gift ideas"), said)

    def test_a_list_he_does_not_have_is_said_to_be_missing(self):
        got = voice.interpret("rename the costco list to sams")
        self.assertIsNone(got["command"])
        self.assertEqual(got["say"], "You don't have a costco list.")

    def test_a_line_moved_by_part_of_its_words(self):
        got = voice.interpret("move scarf from gift ideas to my packing list")["command"]
        self.assertEqual((got["kind"], got["list"], got["item"], got["moved_from"]),
                         ("list_add", "packing", "a scarf for mom", "gift ideas"))


if __name__ == "__main__":
    unittest.main()
