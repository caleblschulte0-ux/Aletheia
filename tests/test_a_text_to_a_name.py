"""Sweep 25 (2026-10-07): sentences that went to the planner and need no model."""
import unittest
from unittest import mock

from aletheia import voice


class ATextToAName(unittest.TestCase):
    def test_a_name_then_a_sentence_is_a_text(self):
        self.assertEqual(voice._interpret("text dana i'm running late")["command"],
                         {"kind": "message_send", "to": "dana", "body": "i'm running late"})
        self.assertEqual(voice._interpret("message sam can you grab milk")["command"]["body"], "can you grab milk")

    def test_a_stranger_and_two_words_is_still_not_guessed(self):
        self.assertNotEqual((voice._interpret("text bob happy birthday").get("command") or {}).get("kind"),
                            "message_send")


class InMyCalendar(unittest.TestCase):
    def test_in_is_on(self):
        from aletheia import quick
        self.assertEqual(quick.match("what's in my calendar next week"), ("agenda", "next week"))


class DoneSaidEveryWay(unittest.TestCase):
    def test_done_with_it_ticks_the_one_task_it_names(self):
        with mock.patch.object(voice, "_names_one_open_task", return_value=True):
            for said, which in (("done with laundry", "laundry"), ("finish the dentist task", "dentist"),
                                ("the laundry task is done", "laundry"), ("i called the dentist", "called the dentist")):
                self.assertEqual(voice._interpret(said)["command"], {"kind": "task_done", "which": which}, said)

    def test_news_about_a_task_he_does_not_have_is_not_a_tick(self):
        with mock.patch.object(voice, "_names_one_open_task", return_value=False):
            got = voice._interpret("i called the plumber").get("command") or {}
            self.assertNotEqual(got.get("kind"), "task_done")

    def test_a_machine_finishing_is_not_his_task_done(self):
        with mock.patch.object(voice, "_names_one_open_task", return_value=True):
            got = voice._interpret("the dishwasher is done").get("command") or {}
            self.assertNotEqual(got.get("kind"), "task_done")


if __name__ == "__main__":
    unittest.main()
