"""Nobody says the whole sentence twice.

    > add milk to the shopping list   [0.1s] Added to the shopping list: milk.
    > add bread too                   [4.6s] 1 step ready - Add bread to the
                                      shopping list. Say approve to run it.

The same act, one turn apart, with two completely different experiences —
and the slow one asks permission to do the thing the fast one had just
done for free. He is standing in a kitchen naming groceries; the second
one is not a new subject.

This is the hole CLAUDE.md describes under "her memory of the
conversation had a hole where she was fastest", one layer up: the thread
is populated correctly now, and the deterministic layer was not reading
it. Every "too", "also" and "and" fell through to a planner that then
asked to be allowed to do it.

Two rules hold the shape:

- It reads what HE SAID, never what SHE ANSWERED. Her wording is exactly
  the sort of thing that gets improved, and a pattern anchored to it
  drifts silently the moment somebody rewrites the sentence.
- It walks BACK through the run. Checking only the previous turn broke
  the chain after one item, because "and eggs" follows a continuation
  rather than a full sentence — so "add milk to the list / add bread too
  / and eggs" was fast, fast, four seconds.

And it stops at anything that is not a shopping add, which is what keeps
"add a task to call the plumber" followed by "add cheese too" out of the
groceries.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import voice


class _Threaded(unittest.TestCase):
    def thread(self, *said):
        """The last few turns, oldest first, as `converse.recent` gives them."""
        from aletheia import converse
        turns = [{"at": "", "he_asked": s, "she_answered": ""} for s in said]
        return mock.patch.object(converse, "recent", lambda limit=3: turns)

    def kind(self, said):
        return ((voice._interpret(said) or {}).get("command") or {}).get("kind")

    def item(self, said):
        return ((voice._interpret(said) or {}).get("command") or {}).get("item")


class TheSecondItemIsFreeTooCase(_Threaded):
    def test_a_follow_up_after_a_shopping_add_is_a_shopping_add(self):
        with self.thread("add milk to the shopping list"):
            for said in ("add bread too", "and eggs", "also add butter",
                         "add jam as well", "and also cheese"):
                with self.subTest(said=said):
                    self.assertEqual(self.kind(said), "shopping_add", said)

    def test_the_item_is_what_he_said(self):
        with self.thread("add milk to the shopping list"):
            self.assertEqual(self.item("add bread too"), "bread")
            self.assertEqual(self.item("and eggs"), "eggs")
            self.assertEqual(self.item("also add butter"), "butter")

    def test_a_run_keeps_going(self):
        """"and eggs" follows a continuation, not a full sentence."""
        with self.thread("add milk to the shopping list", "add bread too"):
            self.assertEqual(self.kind("and eggs"), "shopping_add")
        with self.thread("add milk to the shopping list", "add bread too",
                         "and eggs"):
            self.assertEqual(self.kind("also butter"), "shopping_add")

    def test_his_capitals_survive(self):
        with self.thread("add milk to the shopping list"):
            self.assertEqual(self.item("add Greek Yogurt too"), "Greek Yogurt")


class ItStopsWhereTheSubjectChangesCase(_Threaded):
    def test_a_task_is_not_a_grocery(self):
        with self.thread("add milk to the shopping list",
                         "add a task to call the plumber"):
            self.assertNotEqual(self.kind("add cheese too"), "shopping_add")

    def test_with_no_thread_at_all_it_does_not_guess(self):
        with self.thread():
            self.assertNotEqual(self.kind("add bread too"), "shopping_add")

    def test_an_unrelated_previous_turn_stops_it(self):
        with self.thread("what's the weather"):
            self.assertNotEqual(self.kind("add bread too"), "shopping_add")

    def test_it_does_not_reach_back_past_the_run(self):
        """"Too" means the thing just said, not the thing said before lunch."""
        with self.thread("add milk to the shopping list", "what's the weather",
                         "am i free tomorrow", "check my email"):
            self.assertNotEqual(self.kind("add bread too"), "shopping_add")

    def test_a_broken_thread_falls_back_rather_than_failing(self):
        from aletheia import converse
        with mock.patch.object(converse, "recent",
                               side_effect=RuntimeError("no thread")):
            self.assertNotEqual(self.kind("add bread too"), "shopping_add")


class TheFullSentenceStillWorksCase(_Threaded):
    def test_it_did_not_break_the_thing_it_extends(self):
        with self.thread():
            self.assertEqual(self.kind("add milk to the shopping list"),
                             "shopping_add")
            self.assertEqual(self.item("add milk to the shopping list"), "milk")

    def test_several_things_at_once_still_go_to_the_planner(self):
        """"Macaroni and cheese" is one thing; splitting would guess."""
        with self.thread("add milk to the shopping list"):
            self.assertNotEqual(self.kind("add eggs milk and bread too"),
                                "shopping_add")

    def test_a_task_said_mid_run_is_still_a_task(self):
        """The regression this caused: "add a task to call the plumber",
        said between two groceries, went ON the shopping list as "a task
        to call the plumber". A bare "add X" inside a run swallowed a
        change of subject whole, because the marker was required in the
        run-detector and not in the reader."""
        with self.thread("add milk to the shopping list", "add bread too"):
            self.assertEqual(self.kind("add a task to call the plumber"),
                             "task_new")

    def test_a_continuation_needs_a_marker(self):
        """One definition, matched the same way in both places."""
        self.assertEqual(voice._also_item("add bread too"), "bread")
        self.assertEqual(voice._also_item("also add butter"), "butter")
        self.assertEqual(voice._also_item("and eggs"), "eggs")
        self.assertEqual(voice._also_item("add a task to call the plumber"), "")
        self.assertEqual(voice._also_item("add milk to the shopping list"), "")


if __name__ == "__main__":
    unittest.main()
