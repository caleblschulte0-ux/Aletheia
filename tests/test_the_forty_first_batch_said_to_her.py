"""Forty-first sandbox batch, 2026-10-05: what is said TO her.

    > REMIND ME AT 3 TO CALL MOM          "I'll remind you ...: CALL MOM."
    > remind me at three thirty to call dad   [6.1s] the planner, an approval
    > is thea awake / can she set a timer / tell her to add eggs
                                           a model, a model, the planner
    > thea, hey thea, what time is it      [7.5s] a model
    > hello there                          [9.5s] a model
"""
import unittest

from aletheia import quick, voice


class SaidToHer(unittest.TestCase):
    def test_capitals_wake_words_and_the_third_person(self):
        self.assertEqual(voice._as_said_to_her("REMIND ME AT 3 TO CALL MOM"), "remind me at 3 to call mom")
        self.assertEqual(voice._as_said_to_her("thea, hey thea, what time is it"), "what time is it")
        self.assertEqual(voice._as_said_to_her("tell her to add eggs"), "add eggs")
        self.assertEqual(voice._as_said_to_her("can she set a timer"), "can you set a timer")
        self.assertEqual(voice._as_said_to_her("is thea awake"), "are you awake")
        self.assertEqual(voice._as_said_to_her("what does she do"), "what do you do")
        self.assertEqual(voice._as_said_to_her("remember Dana is my landlord"), "remember Dana is my landlord")

    def test_the_sentences_then_reach_their_rules(self):
        self.assertEqual(voice.interpret("REMIND ME AT 3 TO CALL MOM")["command"]["text"], "call mom")
        self.assertEqual(voice.interpret("thea REMIND ME AT 3 TO CALL MOM")["command"]["text"], "call mom")
        self.assertEqual(voice.interpret("tell her to add eggs")["command"], {"kind": "shopping_add", "item": "eggs"})
        self.assertEqual(voice.interpret("thea, hey thea, what time is it")["command"]["text"], "what time is it")
        self.assertEqual(quick.match("hello there")[0], "greeting")
        self.assertIsNotNone(quick.match(voice._as_said_to_her("is thea awake")))

    def test_minutes_in_words(self):
        self.assertEqual(voice._spoken_time("three thirty"), "03:30")
        self.assertEqual(voice._spoken_time("four fifteen pm"), "16:15")
        self.assertEqual(voice._spoken_time("six oh five"), "06:05")
        self.assertEqual(voice.interpret("remind me at three thirty to call dad")["command"]["at"][11:16], "15:30")


if __name__ == "__main__":
    unittest.main()
