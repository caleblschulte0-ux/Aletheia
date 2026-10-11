"""A web errand whose object only points back is a question, not an errand.

2026-10-11, every model off: "sign me up for that" was taken literally and offered as a browser
errand to sign up for "that", with a yes to tap.
"""
import unittest

from aletheia import rule_planner


class ThatIsNotAThing(unittest.TestCase):
    def test_a_pointing_word_asks_which_one(self):
        for said in ("sign me up for that", "register me for it", "book that one", "fill out the form"):
            kind, args, _ = rule_planner.match(said)
            self.assertEqual(kind, rule_planner.ANSWER, said)
            self.assertIn("Which one", args["say"], said)

    def test_a_named_thing_is_still_the_errand(self):
        kind, args, _ = rule_planner.match("sign me up for the sioux falls job fair")
        self.assertEqual(kind, "web_task")
        self.assertEqual(args["goal"], "sign me up for the sioux falls job fair")


if __name__ == "__main__":
    unittest.main()
