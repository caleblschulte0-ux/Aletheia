"""Three sentences that reached a door to the outside world (2026-10-12).

"Remind me to call mom tomorrow at 6", "and text dad too" became a TEXT to
Dad saying "too". "Cancel the one for dad" was prepared as cancelling a
subscription called "one for dad". And "clear my list" with an empty
shopping list and two tasks said "The shopping list was already empty", so
he believed his tasks were gone. None of it needed a model.
"""
import unittest
from unittest import mock

from aletheia import voice

JUST_SET = {"at": "2026-10-13T18:00:00-05:00", "command": {"text": "call mom"}}


def said(sentence):
    return voice.interpret(f"thea {sentence}")


class AndTextDadToo(unittest.TestCase):
    def test_after_a_reminder_it_is_another_reminder_at_that_time(self):
        with mock.patch("aletheia.voice._the_reminder_just_set", return_value=JUST_SET):
            got = said("and text dad too")["command"]
        self.assertEqual(got, {"kind": "remind_at", "at": JUST_SET["at"], "text": "text dad"})

    def test_with_no_reminder_just_set_too_is_not_a_message(self):
        with mock.patch("aletheia.voice._the_reminder_just_set", return_value=None), \
                mock.patch("aletheia.converse.recent", return_value=[]):
            got = said("text dad too")
        self.assertIsNone(got["command"])
        self.assertTrue(got["say"].startswith("What should it say?"), got["say"])

    def test_a_real_message_still_goes(self):
        with mock.patch("aletheia.converse.recent", return_value=[]):
            got = said("text mom happy birthday")["command"]
        self.assertEqual((got["kind"], got["to"]), ("message_send", "mom"))


class CancelTheOneForDad(unittest.TestCase):
    def test_one_is_one_of_her_reminders(self):
        with mock.patch("aletheia.intercom._one_reminder", return_value=({"id": "r1"}, "")), \
                mock.patch("aletheia.voice._one_of_her_holds", return_value=(None, "")):
            got = said("cancel the one for dad")["command"]
        self.assertEqual(got, {"kind": "reminder_off", "which": "dad"})

    def test_one_is_never_a_subscription(self):
        with mock.patch("aletheia.intercom._one_reminder", return_value=(None, "none")), \
                mock.patch("aletheia.voice._names_one_open_task", return_value=False), \
                mock.patch("aletheia.voice._one_of_her_holds", return_value=(None, "")):
            got = said("cancel the netflix one")
        self.assertIsNone(got["command"])
        self.assertIn("I don't see a reminder or a task about netflix", got["say"])


class ClearMyList(unittest.TestCase):
    def test_an_empty_shopping_list_does_not_hide_his_tasks(self):
        with mock.patch("aletheia.intercom._shopping_items", return_value=[]), \
                mock.patch("aletheia.intercom._open_tasks", return_value=[{"id": "t1"}, {"id": "t2"}]), \
                mock.patch("aletheia.voice._other_lists", return_value=[]):
            got = said("clear my list")
        self.assertIsNone(got["command"])
        self.assertIn("task list has 2 things", got["say"])

    def test_with_things_to_buy_it_is_still_the_shopping_list(self):
        with mock.patch("aletheia.intercom._shopping_items", return_value=[{"id": "s1", "need": "milk"}]), \
                mock.patch("aletheia.intercom._open_tasks", return_value=[{"id": "t1"}]), \
                mock.patch("aletheia.voice._other_lists", return_value=[]):
            got = said("clear the list")["command"]
        self.assertEqual(got, {"kind": "shopping_off", "item": "everything"})


if __name__ == "__main__":
    unittest.main()
