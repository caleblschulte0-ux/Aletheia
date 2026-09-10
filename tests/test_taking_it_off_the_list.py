""""Add milk to the list" was free. "Take milk off the list" was not.

    > add milk to the shopping list   [0.1s] Added to the shopping list: milk.
    > take milk off the list          [4.6s] 1 step ready - Take milk off
                                      the shopping list. Say approve to
                                      run it.

`shopping_off` existed. It required the words "shopping list" IN FULL,
while the add pattern sitting six lines above it has always accepted a
bare "the list". So one direction was instant and the other cost four and
a half seconds and then asked permission to undo it.

Third instance of one class tonight — the reminder cancel and the second
shopping item were the others — and it is worth naming: THE WRITER IS
INSTANT AND THE UN-DOER IS NOT. A thing she can do in one call should be
undoable in one call, or the asymmetry quietly teaches him to be careful
about asking.

And "got the milk" is what a person says in a shop. It is also how "I got
the job" and "got it" are said, so this asks the STORE instead of
guessing: it is a removal only if that thing is on his list right now. A
pattern that swallows too much answers a DIFFERENT question, which is the
failure he cannot detect.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import voice


class _WithAList(unittest.TestCase):
    def list_holds(self, *items):
        from aletheia import intercom
        rows = [{"id": i.replace(" ", "-"), "need": i} for i in items]
        return mock.patch.object(intercom, "_shopping_items", lambda: rows)

    def cmd(self, said):
        return (voice._interpret(said) or {}).get("command") or {}


class BothDirectionsAreOneCallCase(_WithAList):
    def test_the_short_way_of_saying_it(self):
        for said, item in (("take milk off the list", "milk"),
                           ("remove bread from the list", "bread"),
                           ("delete eggs from the list", "eggs"),
                           ("take milk off the shopping list", "milk"),
                           ("remove milk from my grocery list", "milk")):
            with self.subTest(said=said):
                got = self.cmd(said)
                self.assertEqual(got.get("kind"), "shopping_off", said)
                self.assertEqual(got.get("item"), item)

    def test_adding_still_works_both_ways(self):
        """The pair has to stay symmetrical, which is the whole point."""
        for said in ("add milk to the list", "add milk to the shopping list"):
            with self.subTest(said=said):
                self.assertEqual(self.cmd(said).get("kind"), "shopping_add")


class GotTheMilkCase(_WithAList):
    def test_it_comes_off_when_it_is_on_the_list(self):
        with self.list_holds("milk", "bread"):
            for said in ("got the milk", "i got the milk",
                         "i've got the milk", "bought the milk",
                         "picked up the bread"):
                with self.subTest(said=said):
                    self.assertEqual(self.cmd(said).get("kind"),
                                     "shopping_off", said)

    def test_i_got_the_job_is_not_a_grocery(self):
        """The sentence is identical. Only the store can tell them apart."""
        with self.list_holds("milk", "bread"):
            for said in ("i got the job", "got it", "i got a call",
                         "got the message"):
                with self.subTest(said=said):
                    self.assertNotEqual(self.cmd(said).get("kind"),
                                        "shopping_off", said)

    def test_an_empty_list_takes_nothing_off(self):
        with self.list_holds():
            self.assertNotEqual(self.cmd("got the milk").get("kind"),
                                "shopping_off")

    def test_a_store_that_will_not_read_does_not_guess(self):
        from aletheia import intercom
        with mock.patch.object(intercom, "_shopping_items",
                               side_effect=RuntimeError("gone")):
            self.assertNotEqual(self.cmd("got the milk").get("kind"),
                                "shopping_off")

    def test_it_matches_the_way_he_said_it(self):
        """"Got the milk" against a list holding "milk, 2 litres"."""
        with self.list_holds("milk 2 litres"):
            self.assertEqual(self.cmd("got the milk").get("kind"),
                             "shopping_off")


class ThePredicateCase(_WithAList):
    def test_it_asks_the_store(self):
        with self.list_holds("milk"):
            self.assertTrue(voice._on_the_shopping_list("milk"))
            self.assertFalse(voice._on_the_shopping_list("a job"))

    def test_nothing_named_is_never_on_it(self):
        with self.list_holds("milk"):
            self.assertFalse(voice._on_the_shopping_list(""))
            self.assertFalse(voice._on_the_shopping_list("   "))


if __name__ == "__main__":
    unittest.main()
