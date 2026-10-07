""""Text mom happy birthday" - the person and the message with no "that".

Found 2026-10-07: "I don't have a phone number for mom happy." The send
still goes through the same approval as every message.
"""
import unittest
from unittest import mock

from aletheia import contacts, quick, voice


class TheNameEndsWhereTheMessageStarts(unittest.TestCase):
    def test_a_relation(self):
        with mock.patch.object(contacts, "all_contacts", return_value=[]):
            self.assertEqual(voice._interpret("text mom happy birthday")["command"],
                             {"kind": "message_send", "to": "mom", "body": "happy birthday"})

    def test_a_contact_with_two_words(self):
        dana = {"id": "dana-cole", "display_name": "Dana Cole", "aliases": [], "emails": [],
                "phones": ["+16055550123"]}
        with mock.patch.object(contacts, "all_contacts", return_value=[dana]), \
                mock.patch.object(contacts, "validate"):
            self.assertEqual(voice._interpret("text dana cole running late")["command"]["to"], "dana cole")

    def test_a_stranger_is_not_guessed(self):
        with mock.patch.object(contacts, "all_contacts", return_value=[]):
            self.assertEqual(voice._interpret("text bob happy birthday")["command"]["kind"], "intent")

    def test_what_version(self):
        self.assertEqual(quick.match("what version are you")[0], "version")


if __name__ == "__main__":
    unittest.main()


class TheWeatherAskedSideways(unittest.TestCase):
    def test_each_reads_the_forecast_for_the_day_he_said(self):
        from aletheia import weather
        with mock.patch.object(weather, "spoken", side_effect=lambda when="": f"[{when}]"):
            for said, day in (("what's the weather on saturday", "saturday"), ("will it snow", ""),
                              ("how hot will it be today", "today"), ("what should i wear tomorrow", "tomorrow"),
                              ("do i need a jacket", ""), ("what's the forecast", "")):
                with self.subTest(said=said):
                    self.assertEqual(quick.answer(said), f"[{day}]")


class ANeedIsAListLine(unittest.TestCase):
    def test_needs_go_on_the_list_and_buying_stays_his(self):
        for said, item in (("we're out of coffee", "coffee"), ("we need paper towels", "paper towels"),
                           ("i need to buy batteries", "batteries"), ("we're running low on dish soap", "dish soap"),
                           ("add milk", "milk")):
            with self.subTest(said=said):
                self.assertEqual(voice._interpret(said)["command"], {"kind": "shopping_add", "item": item})

    def test_a_need_that_is_not_a_thing_to_buy(self):
        for said in ("i need a break", "i need to call mom", "i need help", "we need to talk",
                     "i need a doctor", "add a task", "add it"):
            with self.subTest(said=said):
                self.assertNotEqual((voice._interpret(said)["command"] or {}).get("kind"), "shopping_add")

    def test_a_bare_add_with_a_verb_is_a_task(self):
        self.assertEqual(voice._interpret("add call the bank")["command"]["kind"], "task_new")

    def test_take_it_off_only_when_it_is_on_the_list(self):
        with mock.patch.object(voice, "_on_the_shopping_list", return_value=True):
            self.assertEqual(voice._interpret("take eggs off")["command"], {"kind": "shopping_off", "item": "eggs"})
        with mock.patch.object(voice, "_on_the_shopping_list", return_value=False):
            self.assertNotEqual(voice._interpret("take eggs off")["command"]["kind"], "shopping_off")


class SmallTreats(unittest.TestCase):
    def test_a_fact_and_a_quote_from_her_own_lists(self):
        self.assertIn(quick.answer("tell me a fun fact"), quick.FUN_FACTS)
        self.assertIn(quick.answer("give me a quote"), quick.QUOTES)
