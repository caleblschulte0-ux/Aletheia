""""Add coffee with Jo Saturday at 8" is a diary entry (2026-10-23: to the planner).

The noun list that keeps "add X <day> at <time>" a calendar hold knew
appointments and dinners but not coffee, the gym, church or date night, so the
everyday ones fell to a model. A wish ("I want coffee tomorrow at 8") and a
game he only watches ("the game is tomorrow at 7") stay what they were.
"""
import unittest

from aletheia import voice


def _cmd(sentence):
    return voice.interpret(sentence).get("command") or {}


class AddCoffeeWithJoSaturday(unittest.TestCase):
    def test_everyday_plans_become_holds(self):
        for sentence, title in (("add coffee with jo saturday at 8", "coffee with jo"),
                                ("add drinks with mike friday at 6", "drinks with mike"),
                                ("add gym tomorrow at 6", "gym"),
                                ("add date night saturday at 7", "date night"),
                                ("add church sunday at 10", "church"),
                                ("add yoga tomorrow at 7am", "yoga"),
                                ("add the game sunday at noon", "the game")):
            with self.subTest(sentence=sentence):
                cmd = _cmd(sentence)
                self.assertEqual(cmd.get("kind"), "calendar_hold", cmd)
                self.assertEqual(cmd.get("title"), title)

    def test_the_hour_is_read_the_way_he_means_it(self):
        self.assertIn("T18:00", _cmd("add gym tomorrow at 6")["start"])
        self.assertIn("T07:00", _cmd("add yoga tomorrow at 7am")["start"])
        self.assertIn("T10:00", _cmd("add church sunday at 10")["start"])

    def test_a_wish_is_not_a_hold(self):
        for sentence in ("i want coffee tomorrow at 8", "i need coffee tomorrow at 8",
                         "i want lunch tomorrow at noon"):
            with self.subTest(sentence=sentence):
                self.assertNotEqual(_cmd(sentence).get("kind"), "calendar_hold")

    def test_a_game_he_watches_is_still_a_note(self):
        self.assertEqual(_cmd("the game is tomorrow at 7").get("kind"), "note")


if __name__ == "__main__":
    unittest.main()
