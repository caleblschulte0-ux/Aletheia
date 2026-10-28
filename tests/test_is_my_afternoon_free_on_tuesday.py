""""Is my afternoon free on Tuesday": the part of the day said first.

2026-10-28, talking to her with the models off:

    > is my tuesday afternoon free
      Free Tuesday afternoon 12 pm to 5 pm. ...
    > is my afternoon free on tuesday
      I could not plan that: nothing could think just now ...
"""
import unittest

from aletheia import voice


class PartThenDay(unittest.TestCase):
    def test_the_same_question_both_ways(self):
        for said, part, day in (("is my afternoon free on tuesday", "afternoon", "tuesday"),
                                ("is my morning free tomorrow", "morning", "tomorrow"),
                                ("is the evening free on friday", "evening", "friday"),
                                ("is my afternoon free", "afternoon", "today"),
                                ("is this evening free", "evening", "today")):
            cmd = voice.interpret(said)["command"] or {}
            self.assertEqual(cmd.get("kind"), "free_time", said)
            self.assertEqual(cmd.get("part"), part, said)
            self.assertEqual(cmd.get("day"), voice._spoken_day(day), said)

    def test_day_first_is_unchanged(self):
        self.assertEqual(voice.interpret("is my tuesday afternoon free")["command"],
                         voice.interpret("is my afternoon free on tuesday")["command"])


if __name__ == "__main__":
    unittest.main()
