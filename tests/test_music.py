"""Play, pause and skip with no API key — and the half that needs one.

He has Spotify Premium and offered to get an API key. He should not have
to for this half: the transport controls are Windows media keys, which
every player on the machine already listens for.

The other half is real and is kept separate. Media keys control what is
ALREADY QUEUED; "play the Rolling Stones" needs his account, and
answering it by resuming whatever was paused on Thursday is a different
promise from the one he made.

No keys are pressed in this file and no player is launched.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import capabilities, intercom, journal, music, places, voice


class MusicCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d)})
        env.start()
        self.addCleanup(env.stop)
        for p in (mock.patch.object(journal, "JOURNAL_PATH", d / "j.jsonl"),
                  mock.patch.object(places, "resolve",
                                    side_effect=KeyError("none"))):
            p.start()
            self.addCleanup(p.stop)

    def said(self, sentence):
        return voice.interpret(sentence) or {}


class TransportNeedsNoKeyCase(MusicCase):
    def test_the_ordinary_words_reach_the_right_button(self):
        for sentence, action in (("play some music", "play"),
                                 ("play something", "play"),
                                 ("pause", "pause"),
                                 ("stop the music", "pause"),
                                 ("skip", "next"),
                                 ("next song", "next"),
                                 ("go back", "previous")):
            with self.subTest(sentence=sentence):
                got = self.said(sentence).get("command") or {}
                self.assertEqual(got.get("kind"), "music", sentence)
                self.assertEqual(got.get("action"), action, sentence)

    def test_it_claims_only_what_it_did(self):
        """A media key is fire-and-forget: Windows gives no acknowledgement
        that any application acted on it. "Play." is honest; "it's
        playing" is the sentence he cannot check."""
        with mock.patch.object(music, "press", return_value=True), \
             mock.patch.object(music, "player_running", return_value=True):
            for action, expected in (("play", "Play."), ("pause", "Paused."),
                                     ("next", "Skipped."),
                                     ("previous", "Back one.")):
                with self.subTest(action=action):
                    said = music.control(action)
                    self.assertEqual(said, expected)
                    self.assertNotIn("playing", said.lower())

    def test_pressing_play_at_a_shut_player_opens_it_first(self):
        """Pressing play at nothing does nothing, and reporting success
        would be unverifiable."""
        with mock.patch.object(music, "press", return_value=True), \
             mock.patch.object(music, "player_running", return_value=False), \
             mock.patch.object(music, "open_player", return_value=(True, "opened")):
            said = music.control("play", sleep=lambda s: None)
        self.assertIn("Opening Spotify", said)

    def test_a_player_that_will_not_open_is_admitted(self):
        with mock.patch.object(music, "player_running", return_value=False), \
             mock.patch.object(music, "open_player",
                               return_value=(False, "could not open Spotify")):
            with self.assertRaises(music.MusicUnavailable):
                music.control("play", sleep=lambda s: None)

    def test_keys_that_do_not_arrive_are_not_reported_as_pressed(self):
        with mock.patch.object(music, "press", return_value=False), \
             mock.patch.object(music, "player_running", return_value=True):
            with self.assertRaises(music.MusicUnavailable):
                music.control("pause")

    def test_asking_for_something_it_has_no_button_for(self):
        with self.assertRaises(music.MusicUnavailable):
            music.control("shuffle")

    def test_neither_probe_ever_raises(self):
        """The rule is in the name: they RETURN, they do not throw.

        This pinned "could not open", which is what Windows says. CI runs
        on Linux, where the probe honours the rule and says something
        else - equally true - so the suite was green on his PC and red in
        CI for a sentence neither of them was wrong about.
        """
        with mock.patch("subprocess.run", side_effect=OSError("no shell")):
            self.assertFalse(music.player_running())
        with mock.patch("subprocess.Popen", side_effect=OSError("no explorer")), \
             mock.patch.object(music, "player_running", return_value=False):
            ok, why = music.open_player()
        self.assertFalse(ok)
        # A reason worth reading, whichever platform gave it.
        self.assertTrue(str(why).strip(), "refused without saying why")
        self.assertNotIn("Traceback", str(why))


class ChoosingIsADifferentPromiseCase(MusicCase):
    def test_naming_something_says_what_it_would_take(self):
        for sentence in ("play the rolling stones", "put on some jazz",
                         "play my discover weekly"):
            with self.subTest(sentence=sentence):
                got = self.said(sentence)
                self.assertIsNone(got.get("command"), sentence)
                self.assertIn("can't pick a particular song",
                              got.get("say", ""), sentence)

    def test_the_signal_is_the_noun_not_the_word_some(self):
        """"Play some MUSIC" is transport; "put on some JAZZ" is a choice.
        Written against the word "some" it got this backwards."""
        self.assertEqual((self.said("play some music").get("command") or {})
                         .get("action"), "play")
        self.assertIsNone(self.said("put on some jazz").get("command"))

    def test_it_does_not_swallow_its_neighbours(self):
        for sentence in ("play devils advocate", "resume"):
            with self.subTest(sentence=sentence):
                got = (self.said(sentence).get("command") or {}).get("kind")
                self.assertNotEqual(got, "music", sentence)

    def test_the_registry_keeps_them_apart(self):
        """One entry for both would say AVAILABLE about a capability that
        cannot do what its own description promises."""
        self.assertEqual(capabilities.get("media.play")["status"], "AVAILABLE")
        self.assertEqual(capabilities.get("media.choose")["status"], "NOT_BUILT")


class ThroughTheGrammarCase(MusicCase):
    def test_the_verb_runs_the_transport(self):
        with mock.patch.object(music, "press", return_value=True), \
             mock.patch.object(music, "player_running", return_value=True):
            said = intercom.execute_command({"kind": "music", "action": "pause"},
                                            {}, quote="pause")
        self.assertEqual(said, "Paused.")

    def test_it_is_routine_because_pausing_is_as_easy_to_undo(self):
        self.assertEqual(intercom.tier("music"), intercom.TIER_ROUTINE)


if __name__ == "__main__":
    unittest.main()
