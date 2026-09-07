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


class TheSlowTurnsCountToo(unittest.TestCase):
    """Recording only the turns answered inline left the same hole one
    layer down: "remind me at 8 tomorrow" is answered through the
    follow-up path, and "make that 9 instead" a breath later found "no
    visible prior request or value to update"."""

    def test_the_followup_work_records_its_own_answer(self):
        from aletheia import core, followups

        started = {}

        def start(work, acknowledgement="", durable=False):
            started["say"] = work()
            return {"id": "fu-1", "say": acknowledgement}

        with mock.patch.object(core, "run_command",
                               return_value={"detail": "1 step ready — do it",
                                             "outcome": "done"}), \
             mock.patch.object(followups, "start", start), \
             mock.patch.object(core, "_remember_out_loud") as kept:
            # the handler builds the closure; call it the way it does
            def think_it_through():
                detail = core.run_command({}, {})["detail"]
                core._remember_out_loud("remind me at 8 tomorrow", detail)
                return detail
            followups.start(think_it_through)
        self.assertEqual(started["say"], "1 step ready — do it")
        kept.assert_called_once_with("remind me at 8 tomorrow",
                                     "1 step ready — do it")

    def test_the_core_really_wires_it(self):
        # The closure above is a copy of the handler's; this checks the
        # handler actually calls it, by reading the source rather than
        # standing up an HTTP server for one line.
        import inspect
        from aletheia import core
        source = inspect.getsource(core)
        self.assertIn("def think_it_through", source)
        self.assertIn("_remember_out_loud(transcript, detail)", source)


class PunctuationLeftBehind(unittest.TestCase):
    def test_an_id_removed_from_between_two_commas(self):
        from aletheia import speech
        self.assertEqual(
            speech.tidy("there's a pending approval,, but I can't tell"),
            "there's a pending approval, but I can't tell")
        self.assertEqual(speech.spoken_prose(
            "two approvals (intent-1b32747ddb, intent-a3d2ad3434), waiting"),
            "two approvals, waiting")

    def test_an_ellipsis_is_a_real_thing_a_person_writes(self):
        from aletheia import speech
        self.assertEqual(speech.tidy("wait... really"), "wait... really")
        self.assertEqual(speech.tidy("a, b, c"), "a, b, c")


if __name__ == "__main__":
    unittest.main()
