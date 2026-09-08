"""A machine that apologises to the television is broken.

His words: *"I don't want it to sit there and say thinking about that or
I'm sorry, I didn't catch that when I'm playing... every time I turn it
on so far, it sucks."*

From his own notification list, before this:

    You said "the" — what would you like me to do?
    Your message just says "the" — what did you mean?
    I didn't catch a clear request in "the injuries"

The wake word fired on room noise, the fragment went to the PLANNER —
most of a minute — and came back an apology, which she said out loud and
then filed as a chore.

The rule is silence, not a better apology. He loses nothing: if he
really did ask, he asks again, which he was going to do anyway.
"""
import unittest
from unittest import mock

from aletheia import places, voice, voice_room


class NoiseIsNotARequestCase(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(places, "resolve", side_effect=KeyError("none"))
        p.start()
        self.addCleanup(p.stop)

    def test_the_fragments_that_actually_happened_are_silent(self):
        """Taken verbatim from what his machine picked up."""
        for noise in ("the", "the injuries", "uh", "um the", "ok", "yeah",
                      "right", "er", "it", "that", "  "):
            with self.subTest(noise=noise):
                self.assertFalse(voice.worth_answering(noise), noise)

    def test_the_one_word_that_matters_most_is_never_silenced(self):
        """"Stop" is one word and it is the emergency stop.

        Anything the deterministic layer compiles is a request whatever
        its length — that is why this check asks the interpreter first
        and counts words second.
        """
        for said in ("stop", "halt", "resume", "approve", "deny",
                     "tasks", "brief", "never mind"):
            with self.subTest(said=said):
                self.assertTrue(voice.worth_answering(said), said)

    def test_the_fast_lane_makes_a_short_question_a_request(self):
        """"Are you halted" is one content word and I silenced it.

        It compiles to an `intent` — `quick` answers it, not the
        deterministic layer — so counting words treated the most basic
        question he can ask her as room noise. The counter is the LAST
        resort now, for sentences no lane recognises at all.
        """
        for said in ("are you halted", "you there", "are you ok",
                     "what time is it"):
            with self.subTest(said=said):
                self.assertTrue(voice.worth_answering(said), said)

    def test_a_real_request_is_never_silenced(self):
        for said in ("what time is it", "add milk to the shopping list",
                     "what is the capital of iceland",
                     "text brant that I'm on my way",
                     "remind me at 3 to call the dentist"):
            with self.subTest(said=said):
                self.assertTrue(voice.worth_answering(said), said)

    def test_something_broken_is_never_silent(self):
        """A silence caused by a bug would be the worst outcome here:
        indistinguishable from her being switched off."""
        with mock.patch.object(voice, "interpret",
                               side_effect=RuntimeError("boom")):
            self.assertTrue(voice.worth_answering("anything at all"))


class TheRoomStaysQuietCase(unittest.TestCase):
    """The room, and only the room. Typed into the Command Center "the"
    still gets an answer — he is looking at a screen he chose to type
    into, and silence there is a bug rather than a courtesy."""

    def room(self, heard):
        said, asked = [], []

        def ask(command, core_url, say, monotonic=None):
            asked.append(command)
            return {"say": "an answer", "followup_id": None}

        with mock.patch.object(voice_room, "_ask_with_acknowledgement", ask), \
             mock.patch.object(places, "resolve", side_effect=KeyError("none")):
            voice_room.listen_forever(
                recognizer=iter([(True, h) for h in heard]),
                speaker=said.append, max_utterances=len(heard))
        return said, asked

    def test_noise_reaches_neither_her_mouth_nor_the_core(self):
        """No try/except here on purpose.

        The first version wrapped this in one and skipped on any
        exception — and then swallowed a real NameError (`voice` was
        never imported into `voice_room`) into a green skip. A tolerant
        test is worse than no test: it reports success for a listener
        that crashes on every utterance.
        """
        said, asked = self.room(["thea the"])
        self.assertEqual(asked, [], "a fragment reached the planner")
        self.assertEqual(said, [], "she apologised to the room")

    def test_a_real_request_still_goes_all_the_way_through(self):
        """The other half: silence must not be the new default."""
        said, asked = self.room(["thea what is the capital of iceland"])
        self.assertEqual(asked, ["what is the capital of iceland"])
        self.assertEqual(said, ["an answer"])


if __name__ == "__main__":
    unittest.main()
