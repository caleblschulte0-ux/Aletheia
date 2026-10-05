"""Forty-second sandbox batch, 2026-10-05: two things in one breath, and
the corrections that follow an ask.

    > add milk and remind me at 4 to call the bank   [5.2s] a plan, an approval
    > actually make that the orthodontist            [5.1s] a plan, an approval
    > never mind the dentist thing                   [4.5s] a plan, an approval
    > what did I just ask you                        [4.0s] a model
    > my landlord is Dana                            [4.0s] a plan, an approval
"""
import unittest
from unittest import mock

from aletheia import converse, intercom, quick, tasks, voice


class OneBreath(unittest.TestCase):
    def test_two_instructions_split_only_where_both_halves_are_hers(self):
        d = voice.interpret("thea add milk and remind me at 4 to call the bank")
        self.assertEqual(d["command"]["kind"], "shopping_add")
        self.assertEqual(d["command"]["item"], "milk")
        self.assertEqual(d["and_then"], [{"ask": "remind me at 4 to call the bank"}])
        # the second half is HIS WORDS, read again after the first half ran
        d = voice.interpret("thea add eggs and what's on my list")
        self.assertEqual(d["command"]["item"], "eggs")
        self.assertEqual(d["and_then"][0]["ask"], "what's on my list")
        # a fact and a fact
        d = voice.interpret("thea remember my landlord is Dana and my dentist is Dr Lee")
        self.assertEqual(d["command"]["value"], "Dana")
        self.assertEqual(d["and_then"][0]["ask"], "my dentist is Dr Lee")

    def test_one_thing_with_an_and_in_it_stays_one_thing(self):
        for said, kind in (("add milk and eggs", "shopping_add"), ("add a task to call mom and dad", "task_new"),
                           ("add a task to call mom and text dad", "task_new"),
                           ("add a task to email Dana and call Sam", "task_new"),
                           ("note that Dana and Sam came by", "note"),
                           ("remind me at 4 to call the bank and the dentist", "remind_at")):
            d = voice.interpret(f"thea {said}")
            self.assertEqual(d["command"]["kind"], kind, said)
            self.assertNotIn("and_then", d, said)
        self.assertEqual(voice.interpret("thea add milk and eggs")["command"]["item"], "milk and eggs")
        self.assertEqual(voice.interpret("thea remind me at 4 to call the bank and the dentist")["command"]["text"],
                         "call the bank and the dentist")

    def test_the_core_runs_the_rest_after_the_first(self):
        from aletheia import core
        said = core._run_the_rest(None, "Added to the shopping list: milk.", ["what time is it"], "q")
        self.assertTrue(said.startswith("Added to the shopping list: milk. "))
        self.assertRegex(said, r"\d")
        self.assertFalse(core._half_needs_thinking("what time is it"))
        self.assertFalse(core._half_needs_thinking("add eggs"))
        self.assertTrue(core._half_needs_thinking("write me a poem about the sea"))


class Corrections(unittest.TestCase):
    def setUp(self):
        converse.forget()
        for t in tasks.all_tasks():
            if t.get("status") not in tasks.contracts.TASK_TERMINAL:
                tasks.set_status(t["id"], "CANCELLED", "test")

    def tearDown(self):
        self.setUp()

    def test_make_that_the_orthodontist_replaces_the_task_he_just_added(self):
        intercom.execute_command({"kind": "task_new", "id": "call-the-dentist", "description": "call the dentist"},
                                 "operator_quote")
        converse.remember_exchange("add a task to call the dentist", "Added a task: call the dentist.")
        d = voice.interpret("thea actually make that the orthodontist")
        self.assertEqual(d["command"]["kind"], "task_new")
        self.assertEqual(d["command"]["description"], "call the orthodontist")
        self.assertEqual(d["command"]["replaces"], "call the dentist")
        d = voice.interpret("thea change it to the orthodontist")
        self.assertEqual(d["command"]["description"], "call the orthodontist")

    def test_never_mind_the_dentist_thing_drops_it(self):
        intercom.execute_command({"kind": "task_new", "id": "call-the-dentist-2", "description": "call the dentist"},
                                 "operator_quote")
        d = voice.interpret("thea never mind the dentist thing")
        self.assertEqual(d["command"], {"kind": "task_done", "which": "dentist", "as": "cancelled"})
        said = intercom.execute_command(d["command"], "operator_quote")
        self.assertEqual(said, "Dropped your task: call the dentist.")
        self.assertEqual([t for t in tasks.all_tasks() if t.get("status") not in tasks.contracts.TASK_TERMINAL], [])
        # a reminder is not a task
        self.assertNotEqual(voice.interpret("thea never mind the reminder thing")["command"].get("kind"), "task_done")

    def test_never_mind_right_after_a_task_undoes_it(self):
        from aletheia import policy
        converse.remember_exchange("add a task to call the dentist", "Added a task: call the dentist.")
        # with nothing pending (another test's approval must not be what "never mind" denies)
        with mock.patch.object(policy, "all_approvals", return_value=[]):
            with mock.patch.object(voice, "_last_ask_is_undoable", return_value=True):
                self.assertEqual(voice.interpret("thea never mind")["command"], {"kind": "undo"})
            with mock.patch.object(voice, "_last_ask_is_undoable", return_value=False):
                self.assertIsNone(voice.interpret("thea never mind")["command"])

    def test_what_did_i_just_ask_you_is_read_from_the_thread(self):
        self.assertEqual(quick.match("what did I just ask you")[0], "just_asked")
        self.assertIn("empty", quick.answer("what did I just ask you"))
        converse.remember_exchange("add a task to call the dentist", "Added a task: call the dentist.")
        self.assertEqual(quick.answer("what did I just ask you"),
                         'You said "add a task to call the dentist", and I said: Added a task: call the dentist.')
        self.assertIn("Added a task: call the dentist.", quick.answer("what did you just say"))


class AFactSaidPlainly(unittest.TestCase):
    def test_my_landlord_is_dana_is_the_fact(self):
        d = voice.interpret("thea my landlord is Dana")
        self.assertEqual(d["command"], {"kind": "remember", "domain": "people", "key": "landlord",
                                        "value": "Dana", "about": "your landlord"})
        self.assertEqual(voice.interpret("thea my dentist is Dr Lee")["command"]["value"], "Dr Lee")
        for said in ("my boss is annoying", "my meeting is at 3", "my flight is tomorrow", "my landlord is late"):
            self.assertNotEqual(voice.interpret(f"thea {said}")["command"].get("kind"), "remember", said)


if __name__ == "__main__":
    unittest.main()
