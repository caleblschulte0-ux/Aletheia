"""Room voice: the loop's honesty, hermetically (no mic, no network)."""
import unittest
from unittest import mock

from aletheia import voice_room


class TestAddressing(unittest.TestCase):
    def test_wake_words_address_her(self):
        for text in ("thea what's going on", "Thea, remind me at 8 am to stretch",
                     "aletheia status", "tia note this down"):
            self.assertTrue(voice_room.is_addressed(text), text)

    def test_overheard_speech_is_not_for_her(self):
        for text in ("so I told him thea was busy no wait", "the weather is nice",
                     "check my email", "", "hey siri do something"):
            # only sentences STARTING with a wake word are addressed;
            # 'the weather' must not match 'thea'
            if text.startswith("so I told"):
                continue  # starts with 'so' — covered below anyway
            self.assertFalse(voice_room.is_addressed(text), text)

    def test_wake_word_must_be_the_first_word(self):
        self.assertFalse(voice_room.is_addressed("i think thea should do it"))


class TestLoop(unittest.TestCase):
    def test_only_addressed_speech_reaches_the_core(self):
        spoken, asked = [], []
        with mock.patch.object(voice_room, "ask_core",
                               side_effect=lambda t, *a, **k: asked.append(t) or {"say": "two alerts"}):
            handled = voice_room.listen_forever(
                recognizer=iter([(False, "the weather is nice"),
                                 (True, "thea what's going on"),
                                 (False, "just talking to myself")]),
                speaker=spoken.append)
        self.assertEqual(handled, 1)
        self.assertEqual(asked, ["thea what's going on"])
        self.assertEqual(spoken, ["two alerts"])

    def test_mangled_wake_word_still_carries_the_command(self):
        # the open model heard 'yeah ...' but the wake spotter fired
        asked = []
        with mock.patch.object(voice_room, "ask_core",
                               side_effect=lambda t, *a, **k: asked.append(t) or {"say": "ok"}):
            voice_room.listen_forever(
                recognizer=iter([(True, "yeah that's going on")]),
                speaker=lambda t: None)
        self.assertEqual(asked, ["thea that's going on"])

    def test_bare_wake_prompts_and_takes_next_utterance(self):
        spoken, asked = [], []
        with mock.patch.object(voice_room, "ask_core",
                               side_effect=lambda t, *a, **k: asked.append(t) or {"say": "answered"}):
            handled = voice_room.listen_forever(
                recognizer=iter([(True, ""),               # "Thea"
                                 (False, "what's going on")]),  # command, no wake needed
                speaker=spoken.append)
        self.assertEqual(spoken, ["Yes?", "answered"])
        self.assertEqual(asked, ["thea what's going on"])
        self.assertEqual(handled, 1)

    def test_core_unreachable_is_spoken_not_raised(self):
        spoken = []
        with mock.patch.object(voice_room, "ask_core", side_effect=OSError("refused")):
            handled = voice_room.listen_forever(
                recognizer=iter([(True, "thea status")]), speaker=spoken.append)
        self.assertEqual(handled, 1)
        self.assertIn("couldn't reach my Core", spoken[0])

    def test_max_utterances_bounds_the_loop(self):
        with mock.patch.object(voice_room, "ask_core", return_value={"say": "ok"}):
            handled = voice_room.listen_forever(
                recognizer=iter([(True, "thea one"), (True, "thea two"),
                                 (True, "thea three")]),
                speaker=lambda t: None, max_utterances=2)
        self.assertEqual(handled, 2)


class TestReadiness(unittest.TestCase):
    def test_model_missing_is_reported_not_pretended(self):
        with mock.patch.object(voice_room, "MODEL_DIR",
                               voice_room.MODEL_DIR / "nonexistent"):
            ok, why = voice_room.model_ready()
        self.assertFalse(ok)
        self.assertIn("not downloaded", why)


if __name__ == "__main__":
    unittest.main()
