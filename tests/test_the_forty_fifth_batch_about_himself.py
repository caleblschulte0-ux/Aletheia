"""Forty-fifth sandbox batch, 2026-10-05: facts about himself.

    > what's my zip                     [4.6s] a model
    > where do I work                   [4.6s] a model, twice
    > what's my job title               [3.5s] a model
    > my birthday is June 3 1998        [5.5s] a plan, an approval
    > how old am I / when's my birthday / how many days until my birthday
                                        a model each, every one saying "I haven't saved it yet"
    > do you know my name               "I have nothing about name on file"
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, memory, profile, quick, voice


class HisFields(unittest.TestCase):
    def test_zip_work_and_title_are_profile_questions(self):
        for said in ("what's my zip", "where do I work", "what's my job title", "do you know my name",
                     "what do I do for a living", "who do I work for", "what's my employer"):
            self.assertEqual(quick.match(said)[0], "mine", said)
        with mock.patch.object(profile, "answer", side_effect=lambda f: {"postal_code": "62704", "current_employer": "Acme",
                                                                         "current_title": "Analyst"}.get(f)):
            self.assertEqual(quick.answer("what's my zip"), "Your zip is 62704.")
            self.assertEqual(quick.answer("where do I work"), "You work at Acme.")
            self.assertEqual(quick.answer("what's my job title"), "Your job title is Analyst.")
            self.assertEqual(quick.answer("what do I do for a living"), "You're an Analyst at Acme.")
        with mock.patch.object(profile, "answer", return_value=None):
            self.assertIn("I don't have your employer", quick.answer("where do I work"))
            self.assertIn("I don't have your name", quick.answer("do you know my name"))


class HisBirthday(unittest.TestCase):
    def tearDown(self):
        memory.forget("identity", "birthday")

    def test_said_plainly_it_is_remembered(self):
        self.assertEqual(voice.interpret("thea my birthday is June 3 1998")["command"],
                         {"kind": "remember", "domain": "identity", "key": "birthday", "value": "June 3 1998",
                          "about": "your birthday"})
        self.assertEqual(voice.interpret("thea I was born on 3 June 1998")["command"]["value"], "3 June 1998")
        self.assertNotEqual(voice.interpret("thea my birthday is tomorrow")["command"].get("kind"), "remember")

    def test_and_then_read_back_counted_and_aged(self):
        self.assertIn("I don't have your birthday", quick.answer("how old am I"))
        today = localtime.today()
        born = today.replace(year=today.year - 30) + dt.timedelta(days=10)      # ten days from now, 30 years ago
        memory.remember("identity", "birthday", f"{born.strftime('%B')} {born.day} {born.year}", "test")
        self.assertEqual(quick.answer("when's my birthday"),
                         f"Your birthday is {born.strftime('%B')} {born.day}. You were born in {born.year}.")
        self.assertEqual(quick.answer("how old am I"), "You're 29.")
        self.assertTrue(quick.answer("how many days until my birthday").startswith("10 days - "), quick.answer("how many days until my birthday"))
        self.assertIn("when you turn 30", quick.answer("how long until my birthday"))
        memory.remember("identity", "birthday", "June 3", "test")
        self.assertIn("not the year", quick.answer("how old am I"))
        # the generic countdown is untouched
        self.assertEqual(quick.match("how many days until christmas")[0], "until")


if __name__ == "__main__":
    unittest.main()
