"""Speaking over her stops her, and the sentence he cut in with is heard.

The room hard-muted its own ears for as long as she was speaking, which
made a forty-word answer forty seconds he could not get a word into. That
is not a wording bug and no amount of shorter sentences fixes it: the
only way to stop her was to wait, or to leave.

These tests drive the room's real path with a fake mouth, because the
whole point of the design is that nothing about it needs a microphone:
the decision is a pure function over what the constrained recognizer
heard, the stopping is an event the mouth checks between breaths, and
the "his next sentence is for me" flag is consumed exactly once.
"""
from __future__ import annotations

import unittest

from aletheia import speech, voice_room


def _words(*pairs) -> dict:
    return {"result": [{"word": w, "conf": c} for w, c in pairs]}


class WhatCountsAsTalkingOverHer(unittest.TestCase):
    def test_his_name_for_her_said_over_her_is_an_interruption(self):
        self.assertTrue(voice_room.barge_in_heard(_words(("thea", 0.99))))

    def test_stop_and_wait_are_enough_on_their_own(self):
        self.assertTrue(voice_room.barge_in_heard(_words(("stop", 0.95))))
        self.assertTrue(voice_room.barge_in_heard(_words(("wait", 0.9))))

    def test_her_own_voice_coming_back_is_not_him(self):
        """The echo guard, and it is the whole safety argument.

        Her loudspeaker is in the same room as the microphone, so anything
        she says can be re-heard as though he said it. A word that is in
        her mouth this second is evidence the microphone works, not
        evidence he spoke.
        """
        self.assertFalse(voice_room.barge_in_heard(
            _words(("stop", 0.99)), "I'll stop the campaign now."))
        self.assertFalse(voice_room.barge_in_heard(
            _words(("thea", 0.99)), "My name is Thea."))

    def test_a_quiet_guess_does_not_cut_her_off(self):
        self.assertFalse(voice_room.barge_in_heard(_words(("stop", 0.4))))

    def test_room_noise_forced_into_the_grammar_is_not_an_interruption(self):
        self.assertFalse(voice_room.barge_in_heard(_words(("[unk]", 0.99))))
        self.assertFalse(voice_room.barge_in_heard({"text": ""}))

    def test_half_a_phrase_is_not_a_word_that_may_interrupt(self):
        """"on", "never" and "mind" are in the grammar so "never mind" can
        be transcribed at all; none of them may stop her by itself."""
        for word in ("on", "never", "mind", "hold"):
            self.assertFalse(voice_room.barge_in_heard(_words((word, 0.99))),
                             word)

    def test_a_whole_sentence_is_not_a_barge_in(self):
        """Without per-word confidence the only guard left is length: a
        long utterance is the room talking, not him cutting in."""
        self.assertFalse(voice_room.barge_in_heard(
            {"text": "stop by the shop on the way home tomorrow"}))
        self.assertTrue(voice_room.barge_in_heard({"text": "stop"}))


class SheStopsMidAnswer(unittest.TestCase):
    def setUp(self):
        voice_room._INTERRUPT.clear()
        voice_room.take_interrupt()

    tearDown = setUp

    def test_the_rest_of_a_long_answer_is_never_said(self):
        said: list[str] = []

        def mouth(text: str) -> None:
            said.append(text)
            if len(said) == 1:
                voice_room.interrupt_speech()

        long_answer = " ".join(f"This is sentence number {n}." for n in range(40))
        voice_room.speak(long_answer, chunk=mouth)
        self.assertEqual(len(said), 1,
                         "she carried on talking after he cut in")

    def test_an_ordinary_answer_is_one_breath_and_not_chopped(self):
        said: list[str] = []
        voice_room.speak("Added a task to call the plumber.", chunk=said.append)
        self.assertEqual(said, ["Added a task to call the plumber."])

    def test_the_sentence_he_cut_in_with_is_taken_without_his_wake_word(self):
        """He already said her name — to stop her. Making him say it again
        to finish the thought is the machine winning."""
        def mouth(text: str) -> None:
            voice_room.interrupt_speech()

        voice_room.speak("A long answer. " * 30, chunk=mouth)
        self.assertTrue(voice_room.take_interrupt())
        self.assertFalse(voice_room.take_interrupt(),
                         "the flag must be consumed once, not stay open")

    def test_nothing_to_interrupt_opens_no_command_window(self):
        self.assertFalse(voice_room.interrupt_speech())
        self.assertFalse(voice_room.take_interrupt())

    def test_she_is_not_deaf_for_the_usual_tail_after_being_cut_off(self):
        """The half-second tail exists so her own echo cannot wake her.
        After an interruption he is MID-SENTENCE, and half a second of
        politeness there eats the first words of what he stopped her for.
        """
        voice_room._ignore_audio_until = 0.0
        voice_room.speak("A long answer. " * 30,
                         chunk=lambda text: voice_room.interrupt_speech())
        self.assertEqual(voice_room._ignore_audio_until, 0.0)

        voice_room.speak("Done.", chunk=lambda text: None)
        self.assertGreater(voice_room._ignore_audio_until, 0.0)


class NothingTechnicalIsEverSaidOutLoud(unittest.TestCase):
    """The room's mouth is the one place that can promise this.

    Each of these reached a room verbatim at some point, on a path nobody
    expected, and each was fixed at its own source. This is the backstop.
    """

    def test_a_link_is_said_as_a_place_not_as_characters(self):
        said: list[str] = []
        voice_room.speak("Open http://127.0.0.1:8777/ and click the button.",
                         chunk=said.append)
        self.assertNotIn("http", " ".join(said))
        self.assertIn("your Aletheia page", " ".join(said))

    def test_an_identifier_and_a_traceback_never_reach_the_mouth(self):
        said: list[str] = []
        voice_room.speak("That failed: KeyError: intent-7aed1b5dcd is gone.",
                         chunk=said.append)
        self.assertNotIn("intent-7aed1b5dcd", " ".join(said))

    def test_a_windows_path_is_said_as_its_file(self):
        self.assertEqual(speech.say_path(r"C:\Users\caleb\Documents\notes.md"),
                         "notes.md")
        self.assertIn("notes.md", speech.without_links(
            r"I saved it at C:\Users\caleb\Documents\notes.md for you."))
        self.assertNotIn("Users", speech.without_links(
            r"I saved it at C:\Users\caleb\Documents\notes.md for you."))

    def test_an_ordinary_sentence_is_left_exactly_alone(self):
        plain = "I set a reminder for tomorrow at 3 pm to call the dentist."
        self.assertEqual(speech.for_the_room(plain), plain)


class BreathsAreWhereAPersonWouldPause(unittest.TestCase):
    def test_a_short_answer_is_one_breath(self):
        self.assertEqual(speech.breaths("Yes, I'm running."),
                         ["Yes, I'm running."])

    def test_nothing_is_lost_when_a_long_answer_is_broken_up(self):
        answer = " ".join(f"Sentence number {n} is here." for n in range(40))
        parts = speech.breaths(answer)
        self.assertGreater(len(parts), 1)
        self.assertEqual(" ".join(parts), answer)

    def test_every_breath_ends_at_a_full_stop(self):
        answer = " ".join(f"Sentence number {n} is here." for n in range(40))
        for part in speech.breaths(answer)[:-1]:
            self.assertTrue(part.endswith("."), part)

    def test_silence_is_silence(self):
        self.assertEqual(speech.breaths("   "), [])


if __name__ == "__main__":
    unittest.main()
