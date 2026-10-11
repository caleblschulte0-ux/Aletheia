"""A web errand whose object only points back is a question, not an errand.

2026-10-11, every model off: "sign me up for that" was taken literally and offered as a browser
errand to sign up for "that", with a yes to tap.
"""
import unittest
from unittest import mock

from aletheia import quick, rule_planner, voice


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



class EventsAreALook(unittest.TestCase):
    """The same evening: "find me free events this weekend" searched his Documents, and "how's the
    move going", with no pulse written, said "No fleet reading yet" as if the move were a repository."""

    def test_events_are_never_a_file(self):
        got = voice._interpret("find me free events this weekend")
        self.assertNotEqual((got.get("command") or {}).get("kind"), "file_find")

    def test_with_no_model_finding_events_is_a_look(self):
        kind, args, _ = rule_planner.match("find me free events this weekend")
        self.assertEqual((kind, args), ("research", {"question": "free events this weekend"}))
        self.assertEqual(rule_planner.match("find free events near me")[0], "web_task")

    def test_no_pulse_is_said_only_about_a_repository(self):
        with mock.patch.object(quick, "_no_pulse", return_value=True), \
                mock.patch("aletheia.current_state.repo_words", return_value=None), \
                mock.patch.object(quick, "_mission_named", return_value=None):
            self.assertNotIn("fleet", str(quick.answer("how's the move going")))
            self.assertIn("No fleet reading", str(quick.answer("how's the trader going")))


if __name__ == "__main__":
    unittest.main()
