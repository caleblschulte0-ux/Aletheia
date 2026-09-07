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


class AskingWhatBrokeReachesTheAlerts(unittest.TestCase):
    """The same blind spot, one store over.

    `_PAST` matches "did you" and "what happened"; it matched none of
    "what went wrong", "did anything fail", "what broke" — so the most
    natural way to ask what is broken travelled with no journal at all.
    """

    def test_the_failure_shaped_questions_carry_the_journal(self):
        from aletheia import recollection
        for said in ("what went wrong", "did anything fail", "what broke",
                     "is anything broken", "any errors"):
            got = recollection.for_question(said)
            self.assertEqual(got.get("asked_about"), "what went wrong", said)

    def test_it_carries_faults_rather_than_everything_she_did(self):
        from aletheia import recollection
        rows = [{"ts": "2026-09-07T09:00:00Z", "kind": "alert",
                 "subject": "pulse", "actor": "aletheia", "text": "trader is red"},
                {"ts": "2026-09-07T09:05:00Z", "kind": "action",
                 "subject": "task", "actor": "aletheia", "text": "did a thing"}]
        with mock.patch.object(recollection, "_read_journal",
                               return_value=(rows, True)):
            got = recollection.for_question("what went wrong")
        said = " ".join(row["what"] for row in got["journal"])
        self.assertIn("trader is red", said)
        self.assertNotIn("did a thing", said)

    def test_an_empty_list_is_not_an_invitation_to_invent_one(self):
        from aletheia import recollection
        with mock.patch.object(recollection, "_read_journal", return_value=([], True)):
            got = recollection.for_question("what went wrong")
        self.assertEqual(got["journal"], [])
        self.assertIn("never invent a failure", got["note"])

    def test_the_window_is_words_and_not_a_number_of_hours(self):
        # "The last 168 hours show no alerts or recoveries logged" was a
        # real answer, out loud.
        from aletheia import recollection
        self.assertEqual(recollection.window_words(168), "the last week")
        self.assertEqual(recollection.window_words(24), "the last day")
        self.assertEqual(recollection.window_words(72), "the last 3 days")
        self.assertEqual(recollection.window_words(5), "the last 5 hours")
        for said in ("what went wrong", "what did you do today", "did you send it"):
            got = recollection.for_question(said)
            self.assertTrue(got.get("window"), said)
            self.assertNotIn(str(int(got.get("hours", 0))), got["window"], said)

    def test_an_unreadable_journal_says_that_instead(self):
        from aletheia import recollection
        with mock.patch.object(recollection, "_read_journal", return_value=([], False)):
            got = recollection.for_question("what broke")
        self.assertIn("could not be READ", got["note"])


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
