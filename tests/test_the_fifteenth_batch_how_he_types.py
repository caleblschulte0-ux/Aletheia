"""Fifteenth sandbox batch, 2026-10-05: the way he types on a phone.

    > whats waitin on me       [4.6s] a model (the fast lane knew "what's waiting on me")
    > add task call mom        [4.0s] a plan and an approval
    > remind me 3pm dentist    [4.6s] a plan and an approval
    > shopping list add eggs   [4.0s] a plan and an approval
    > remind me tmrw 9am gym   [4.5s] a plan and an approval
    > notes                    [5.5s] a model asking which he meant
    > yes                      [4.0s] after her own question, a NEW plan
    > no                       [11.5s] a model

Each of the first five does for free what its tidy spelling does.
"""
import unittest
from unittest import mock

from aletheia import quick, voice


class ShorthandIsReadAtBothDoors(unittest.TestCase):
    def test_longhand(self):
        self.assertEqual(voice._longhand("whats waitin on me rn"), "whats waiting on me right now")
        self.assertEqual(voice._longhand("remind me tmrw 9am gym"), "remind me tomorrow 9am gym")
        self.assertEqual(voice._longhand("wats my next mtg"), "what's my next meeting")
        self.assertEqual(voice._longhand("corn and urn"), "corn and urn", "inside a word is not shorthand")

    def test_the_fast_lane_sees_the_longhand(self):
        with mock.patch("aletheia.quick._needs", return_value="Nothing needs you right now.", create=True):
            self.assertIsNotNone(quick.answer("whats waitin on me"))


class TerseShapes(unittest.TestCase):
    def test_a_task_without_the_small_words(self):
        for said in ("add task call mom", "new task: buy stamps", "create a task to water the plants"):
            cmd = voice.interpret(said)["command"]
            self.assertEqual(cmd["kind"], "task_new", said)

    def test_a_list_add_said_list_first(self):
        self.assertEqual(voice.interpret("shopping list add eggs")["command"],
                         {"kind": "shopping_add", "item": "eggs"})

    def test_a_reminder_with_the_time_bare(self):
        for said, text in (("remind me 3pm dentist", "dentist"), ("remind me tmrw 9am gym", "gym"),
                           ("remind me tonight at 8pm bins", "bins")):
            cmd = voice.interpret(said)["command"]
            self.assertEqual(cmd["kind"], "remind_at", said)
            self.assertEqual(cmd["text"], text, said)

    def test_a_bare_notes_reads_them(self):
        with mock.patch("aletheia.quick._notes_answer", return_value="2 notes: a; b.", create=True):
            self.assertIsNotNone(quick.answer("notes"))


class ABareYesAndNo(unittest.TestCase):
    def test_yes_is_the_approve_path(self):
        one = {"id": "ap-1", "state": "PENDING", "requested_at": "2026-10-05T00:00:00Z"}
        with mock.patch("aletheia.policy.all_approvals", return_value=[one]), \
             mock.patch("aletheia.voice._asked_recently", return_value=True), \
             mock.patch("aletheia.voice._approve_by_voice", return_value={"command": {"kind": "approve", "id": "ap-1"},
                                                                          "say": None}):
            for said in ("yes", "yeah", "sure", "do it"):
                self.assertEqual(voice.interpret(said)["command"], {"kind": "approve", "id": "ap-1"}, said)

    def test_yes_with_nothing_pending_says_so(self):
        with mock.patch("aletheia.policy.all_approvals", return_value=[]):
            out = voice.interpret("yes")
        self.assertIsNone(out["command"])
        self.assertIn("Nothing is waiting", out["say"])

    def test_no_denies_the_one_pending(self):
        one = {"id": "ap-1", "state": "PENDING"}
        with mock.patch("aletheia.policy.all_approvals", return_value=[one]):
            cmd = voice.interpret("no")["command"]
        self.assertEqual(cmd["kind"], "deny")
        self.assertEqual(cmd["id"], "ap-1")


if __name__ == "__main__":
    unittest.main()
