"""The faster she got, the less she remembered of the conversation.

Four turns in — two tasks added, both answered in 0.0s — "actually cancel
that" came back:

    I don't have anything in the recent conversation to know what 'that'
    refers to — checked the conversation history (empty)

It was empty because the thread lived inside `converse` and only a turn a
MODEL answered was ever written to it. Everything the deterministic layer
answers instantly — which is most of what she says now — left no trace,
so the memory had a hole exactly where she was fastest.
"""
import unittest
from unittest import mock

from aletheia import converse


class EveryTurnIsRemembered(unittest.TestCase):
    def setUp(self):
        self.turns = []

        def read(_path):
            return {"turns": list(self.turns)}

        def write(_path, value):
            self.turns = list(value["turns"])

        p1 = mock.patch.object(converse.stateio, "read_json", read)
        p2 = mock.patch.object(converse.stateio, "write_json_atomic", write)
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)

    def test_a_turn_no_model_touched_is_kept(self):
        converse.remember_exchange("add a task to call the plumber",
                                   "Added a task: call the plumber.")
        self.assertEqual(self.turns[-1]["you"], "add a task to call the plumber")
        self.assertEqual(self.turns[-1]["her"], "Added a task: call the plumber.")

    def test_the_same_exchange_is_not_recorded_twice(self):
        # `converse` records its own turns and the Core records every
        # turn; the two must not double up on a model-answered one.
        for _ in range(3):
            converse.remember_exchange("what time is it", "9 pm.")
        self.assertEqual(len(self.turns), 1)

    def test_two_different_turns_both_land(self):
        converse.remember_exchange("one", "first")
        converse.remember_exchange("two", "second")
        self.assertEqual([t["you"] for t in self.turns], ["one", "two"])

    def test_an_empty_half_is_not_a_turn(self):
        converse.remember_exchange("", "something")
        converse.remember_exchange("something", "")
        self.assertEqual(self.turns, [])

    def test_it_never_raises_whatever_the_store_does(self):
        with mock.patch.object(converse.stateio, "write_json_atomic",
                               side_effect=OSError("read-only")):
            converse.remember_exchange("said", "replied")  # must not raise

    def test_the_core_records_without_the_wake_word(self):
        # "thea add a task to call the plumber" is not how he would refer
        # to it a turn later.
        from aletheia import core
        with mock.patch.object(converse, "remember_exchange") as kept:
            core._remember_out_loud("thea add a task to call the plumber",
                                    "Added a task: call the plumber.")
        kept.assert_called_once_with("add a task to call the plumber",
                                     "Added a task: call the plumber.")


if __name__ == "__main__":
    unittest.main()
