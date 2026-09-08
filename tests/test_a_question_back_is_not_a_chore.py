"""Her own confusion, filed as six things waiting on him.

Found on his machine rather than in a test: `what's waiting on me` read
back six IMPORTANT unread notifications, every one of them her own reply
to something she had not understood —

    "Aletheia finished thinking: I didn't catch a clear request in
     'the injuries' — the last few messages came through..."

He asked, she did not follow, and the not-following became a chore with
his name on it. Days later nothing could answer it, because the
conversation that would have was over.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import followups, journal, notifications, stateio


class QuestionBackCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d)})
        env.start()
        self.addCleanup(env.stop)
        p = mock.patch.object(journal, "JOURNAL_PATH", d / "j.jsonl")
        p.start()
        self.addCleanup(p.stop)
        self.published = []
        pub = mock.patch.object(
            notifications, "publish",
            side_effect=lambda *a, **k: self.published.append((a, k)) or {"id": "n1"})
        pub.start()
        self.addCleanup(pub.stop)

    def terminal(self, said, state=followups.READY):
        record = {"id": "fu-test", "state": state, "say": said}
        return followups._publish_terminal(record)


class ItTellsAnAnswerFromAQuestionCase(QuestionBackCase):
    def test_the_six_real_ones_are_not_filed_as_waiting_on_him(self):
        """Taken verbatim from his machine."""
        for said in (
            "I didn't catch a clear request in \"the injuries\" — could you "
            "say again what you'd like me to do?",
            "I couldn't make out a clear request from that — could you say "
            "what you'd like me to do?",
            "What would you like me to do?",
        ):
            with self.subTest(said=said[:40]):
                self.published.clear()
                self.assertIsNone(self.terminal(said))
                self.assertEqual(self.published, [], "still a chore")

    def test_a_real_answer_is_still_delivered(self):
        self.assertIsNotNone(self.terminal("Reykjavik."))
        self.assertEqual(len(self.published), 1)

    def test_a_failure_still_reaches_him(self):
        """"I could not finish" is a fact about her, not a question for him."""
        self.assertIsNotNone(
            self.terminal("That didn't work: RuntimeError: no CLI",
                          state=followups.FAILED))
        self.assertEqual(len(self.published), 1)

    def test_a_failure_that_ends_in_a_question_still_reaches_him(self):
        self.assertIsNotNone(
            self.terminal("I could not reach a model. Is the CLI installed?",
                          state=followups.FAILED))
        self.assertEqual(len(self.published), 1)

    def test_nothing_is_lost_only_the_demand_on_his_attention(self):
        self.terminal("What would you like me to do?")
        written = journal.JOURNAL_PATH.read_text(encoding="utf-8")
        self.assertIn("not filed as waiting on him", written)

    def test_the_test_itself_is_not_the_whole_rule(self):
        for answer in ("Reykjavik.", "Three tasks are open.", ""):
            self.assertFalse(followups._is_a_question_back(answer), answer)
        for question in ("Which one?", "  Say again?  "):
            self.assertTrue(followups._is_a_question_back(question), question)


class TheRoomAcknowledgesWhatItSaidCase(unittest.TestCase):
    """The root cause of the eighty.

    `/api/voice/followup` is a pure READ on purpose — consuming on GET
    would let a response lost in transit destroy the only copy of an
    answer — and the listener is meant to POST the ack once it has
    really spoken. The wall does. The audit tool does. The ROOM, the
    surface he actually uses, never did, so every answer she said out
    loud stayed an unread IMPORTANT notification for ever.
    """

    def run_one(self, collected):
        from aletheia import voice_room
        said, acked = [], []
        thread = voice_room.launch_followup(
            "fu-1", "http://core", said.append,
            collector=lambda fid, url: collected,
            acknowledge=lambda fid, url: acked.append(fid))
        thread.join(2)
        return said, acked

    def test_an_answer_it_spoke_is_acknowledged(self):
        said, acked = self.run_one("Reykjavik.")
        self.assertEqual(said, ["Reykjavik."])
        self.assertEqual(acked, ["fu-1"])

    def test_an_answer_it_never_got_is_NOT_acknowledged(self):
        """Acknowledging a failed collection consumes an answer nobody
        heard — the exact loss the pure-read GET exists to prevent."""
        said, acked = self.run_one(None)
        self.assertEqual(acked, [], "consumed an answer it never said")
        self.assertTrue(said, "and it still told him something")

    def test_a_failing_acknowledgement_never_takes_the_room_down(self):
        from aletheia import voice_room
        said = []
        thread = voice_room.launch_followup(
            "fu-2", "http://core", said.append,
            collector=lambda fid, url: "Reykjavik.",
            acknowledge=lambda fid, url: (_ for _ in ()).throw(OSError("no core")))
        thread.join(2)
        self.assertEqual(said, ["Reykjavik."])


if __name__ == "__main__":
    unittest.main()
