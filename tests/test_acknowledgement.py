"""She says she is thinking, instead of going silent.

The operator, 2026-09-05: "if I give you an answer, like, right away,
you're doing stuff — even if it's just telling me that you have to think a
little harder." Every ask paid at least one ~3.6s model round trip in
total silence, and silence from something that is supposed to be listening
is indistinguishable from silence from something that is broken.

The design decision under test is that the trigger is ELAPSED TIME, not a
guess about the sentence. A request the fast lane answers out of a file
comes back in milliseconds and nothing is said; there is no classifier to
be wrong, and no case where she claims to be working on something she is
not.
"""
import unittest
from unittest import mock

from aletheia import speech, voice_room


class AckLineCase(unittest.TestCase):
    def test_a_question_and_an_instruction_get_different_lines(self):
        self.assertEqual(speech.ack_line("what did dana say"),
                         speech.ACK_QUESTION)
        self.assertEqual(speech.ack_line("How many emails are unread?"),
                         speech.ACK_QUESTION)
        self.assertEqual(speech.ack_line("apply to ten jobs with my resume"),
                         speech.ACK_ACTION)
        self.assertEqual(speech.ack_line("cancel my gym membership"),
                         speech.ACK_ACTION)

    def test_nothing_heard_still_gets_a_line(self):
        self.assertEqual(speech.ack_line(""), speech.ACK_ACTION)
        self.assertEqual(speech.ack_line(None), speech.ACK_ACTION)

    def test_both_lines_stay_true_whatever_the_answer_turns_out_to_be(self):
        """She may well come back with "that needs your approval". An
        acknowledgement that promised the outcome would be a lie by then."""
        for line in (speech.ACK_QUESTION, speech.ACK_ACTION, speech.ACK_STILL):
            with self.subTest(line=line):
                low = line.casefold()
                for outcome in ("sent", "booked", "bought", "approved",
                                "cancelled", "applied", "finished"):
                    self.assertNotIn(outcome, low)


class Clock:
    """A hand-wound monotonic clock, so the test never actually waits."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class WaitingCase(unittest.TestCase):
    """What she says depends on how long the Core actually took."""

    def ask(self, delay_s, command="apply to ten jobs"):
        """Run the waiter with the Core taking `delay_s` of the fake clock."""
        clock = Clock()
        said = []
        # A Core that "answers" once the fake clock has passed `delay_s`.
        # `done.wait` is the only thing that advances the clock, so the test
        # never sleeps; `set()` is inert because here the CLOCK decides when
        # the answer arrives, not the inline worker below.
        class FakeEvent:
            def wait(self, timeout):
                clock.now += timeout
                return clock.now >= delay_s

            def set(self):
                pass

        class FakeThread:
            def __init__(self, target=None, **kw):
                self.target = target

            def start(self):
                # Runs inline. The waiting loop is driven by the fake clock
                # below, not by this, so the ordering under test is intact.
                self.target()

        with mock.patch.object(voice_room.threading, "Event", FakeEvent), \
             mock.patch.object(voice_room.threading, "Thread", FakeThread), \
             mock.patch.object(voice_room, "ask_core",
                               lambda *a, **k: {"say": "the answer"}):
            out = voice_room._ask_with_acknowledgement(
                command, "http://core", said.append, monotonic=clock)
        return said, out

    def test_a_fast_answer_is_never_preceded_by_an_acknowledgement(self):
        """The whole point of the fast lane is that it feels instant. An
        "on it" in front of a 10ms answer would undo that."""
        said, _out = self.ask(0.3)
        self.assertEqual(said, [])

    def test_a_slow_answer_is_acknowledged_once(self):
        said, _out = self.ask(voice_room.ACK_AFTER_S + 1.0)
        self.assertEqual(said, [speech.ACK_ACTION])

    def test_a_slow_question_gets_the_question_line(self):
        said, _out = self.ask(voice_room.ACK_AFTER_S + 1.0,
                              command="what did dana say today")
        self.assertEqual(said, [speech.ACK_QUESTION])

    def test_a_very_long_wait_says_so_exactly_once(self):
        said, _out = self.ask(voice_room.STILL_AFTER_S * 3)
        self.assertEqual(said, [speech.ACK_ACTION, speech.ACK_STILL])

    def test_the_answer_still_comes_back(self):
        _said, out = self.ask(voice_room.ACK_AFTER_S + 1.0)
        self.assertEqual(out["say"], "the answer")


class RealThreadCase(unittest.TestCase):
    """One pass over the real threading path, so the fakes above cannot be
    the only thing that has ever run this code."""

    def test_a_core_error_becomes_a_spoken_reason_not_an_exception(self):
        def boom(*a, **kw):
            raise ConnectionRefusedError("nothing listening")

        said = []
        with mock.patch.object(voice_room, "ask_core", boom):
            out = voice_room._ask_with_acknowledgement(
                "anything", "http://core", said.append)
        self.assertIn("ConnectionRefusedError", out["say"])
        self.assertIsNone(out["followup_id"])

    def test_a_real_answer_comes_straight_back(self):
        said = []
        with mock.patch.object(voice_room, "ask_core",
                               lambda *a, **k: {"say": "yes", "followup_id": None}):
            out = voice_room._ask_with_acknowledgement(
                "are you there", "http://core", said.append)
        self.assertEqual(out["say"], "yes")
        self.assertEqual(said, [], "a fast answer must not be narrated")


class NoStutterCase(unittest.TestCase):
    """Two acknowledgements can land on the same ask; only one is said.

    The room says one when the Core is slow to answer, and the Core sends
    one back when it hands the work to a followup. Both are "Working on
    it.", and "Working on it. Working on it." is exactly how a thing sounds
    when it is stuck.
    """

    def test_the_cores_acknowledgement_is_not_repeated(self):
        """Driven deterministically: the waiter says the room's line, then
        hands back a Core reply that is the identical sentence."""
        def slow_and_acknowledged(command, core_url, say, **kw):
            say(speech.ACK_ACTION)          # the room, because the Core is slow
            return {"say": speech.ACK_ACTION, "followup_id": "fu-1"}

        spoken = []
        with mock.patch.object(voice_room, "_ask_with_acknowledgement",
                               slow_and_acknowledged), \
             mock.patch.object(voice_room, "collect_followup",
                               return_value="Here is the answer."):
            voice_room.listen_forever(
                recognizer=iter([(True, "thea sort my week")]),
                speaker=spoken.append, max_utterances=1)
        self.assertEqual(spoken, [speech.ACK_ACTION, "Here is the answer."])

    def test_a_real_answer_is_never_suppressed(self):
        """He asked twice; he gets two answers. Only the standing "still
        working" lines are de-duplicated."""
        spoken = []
        with mock.patch.object(
                voice_room, "ask_core",
                return_value={"say": "No, I'm running.", "followup_id": None}):
            voice_room.listen_forever(
                recognizer=iter([(True, "thea are you halted"),
                                 (True, "thea are you halted")]),
                speaker=spoken.append, max_utterances=2)
        self.assertEqual(spoken, ["No, I'm running.", "No, I'm running."])


if __name__ == "__main__":
    unittest.main()
