"""Sweep 23 (2026-10-07): "email mom happy birthday", "don't bother me for
an hour", "how are my projects going" and "what's Barkly doing"."""
import unittest

from aletheia import quick, voice


class APersonThenTheWords(unittest.TestCase):
    def test_email_a_relation(self):
        self.assertEqual(voice._interpret("email mom happy birthday")["command"],
                         {"kind": "email_draft", "to": "mom", "body": "happy birthday"})

    def test_about_is_still_a_conversation(self):
        self.assertEqual(voice._interpret("email mom about the party")["command"]["kind"], "thread_draft")

    def test_saying_is_still_the_body(self):
        self.assertEqual(voice._interpret("email dana saying hi")["command"]["body"], "hi")

    def test_a_stranger_is_not_guessed(self):
        self.assertEqual(voice._known_person_first("zork happy birthday"), None)


class QuietForASpanInWords(unittest.TestCase):
    def test_an_hour_in_words(self):
        self.assertEqual(voice._interpret("don't bother me for an hour")["command"],
                         {"kind": "notify_snooze", "minutes": 60})
        self.assertEqual(voice._interpret("quiet for half an hour")["command"]["minutes"], 30)


class HisProjects(unittest.TestCase):
    def test_how_are_they_going(self):
        self.assertEqual(quick.match("how are my projects going")[0], "projects")

    def test_what_one_is_doing(self):
        self.assertEqual(quick.match("what's barkly doing")[0], "status_of")
        self.assertEqual(quick.match("what's the trader up to")[0], "status_of")
        self.assertEqual(quick.match("what's the weather doing")[0], "weather")
