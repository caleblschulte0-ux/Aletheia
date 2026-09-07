"""'What can't you do' travelled with no registry at all.

`_BROAD` matched every positive phrasing and not one negative one, so the
single most important honesty question anybody asks this system was
answered from whatever the model remembered of the turn before. It
hedged, out loud: "Two things flat out don't exist yet — I don't have the
exact names of those two in front of me right now, so I won't guess."

Which is the §104 hazard exactly: a question about her own limits,
answered without reading her own registry.

And an audit tool that leaves state no real client leaves invents its own
bugs. `talk` polled the follow-up slot and never acknowledged it, so
every answer stayed an UNREAD notification and "what's waiting on me"
came back "Aletheia finished thinking: 100 out of 128 things fully
work..." — her own replies, read back as things needing his attention.
The wall acks; the audit tool has to ack.
"""
import unittest
from unittest import mock

from aletheia import followups, self_knowledge, talk


class TheNegativeFormIsTheSameQuestion(unittest.TestCase):
    def test_it_carries_the_whole_picture(self):
        for said in ("what can't you do", "what cannot you do",
                     "what are you unable to do", "what don't you support",
                     "what's not built"):
            got = self_knowledge.for_question(said)
            self.assertEqual(got.get("asked_about"), "everything", said)

    def test_it_names_the_things_that_do_not_exist(self):
        got = self_knowledge.for_question("what can't you do")
        named = {row["capability"] for row in got["not_built_yet"]}
        self.assertTrue(named, "nothing NOT_BUILT travelled with the question")
        for row in got["not_built_yet"]:
            self.assertTrue(row["what_it_is"], row)

    def test_the_positive_form_is_unchanged(self):
        self.assertEqual(
            self_knowledge.for_question("what can you do").get("asked_about"),
            "everything")

    def test_a_question_about_one_thing_is_still_specific(self):
        got = self_knowledge.for_question("can you read a pdf")
        self.assertNotEqual(got.get("asked_about"), "everything")


class TheAuditToolBehavesLikeTheWall(unittest.TestCase):
    def test_it_acknowledges_the_answer_it_just_said(self):
        slot = {"state": followups.READY, "say": "the answer"}
        with mock.patch.object(followups, "poll", return_value=slot), \
             mock.patch.object(followups, "acknowledge") as ack, \
             mock.patch.object(talk, "_post",
                               return_value={"say": "One moment.",
                                             "followup_id": "f1"}):
            _elapsed, said = talk.ask("http://x", "hello", "secret")
        self.assertEqual(said, "the answer")
        ack.assert_called_once_with("f1")

    def test_a_failed_ack_never_swallows_the_answer(self):
        slot = {"state": followups.READY, "say": "the answer"}
        with mock.patch.object(followups, "poll", return_value=slot), \
             mock.patch.object(followups, "acknowledge", side_effect=OSError("gone")), \
             mock.patch.object(talk, "_post",
                               return_value={"say": "One moment.",
                                             "followup_id": "f1"}):
            _elapsed, said = talk.ask("http://x", "hello", "secret")
        self.assertEqual(said, "the answer")


if __name__ == "__main__":
    unittest.main()
