"""Regression tests for the live room-voice failures found in real use."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import voice_room


class WakeGateCase(unittest.TestCase):
    def test_confident_wake_word_is_accepted(self):
        result = {"text": "thea", "result": [{"word": "thea", "conf": 0.91}]}
        self.assertTrue(voice_room._wake_detected(result))

    def test_low_confidence_nearest_word_is_not_a_wake(self):
        result = {"text": "thea", "result": [{"word": "thea", "conf": 0.32}]}
        self.assertFalse(voice_room._wake_detected(result))

    def test_unknown_room_speech_is_not_a_wake(self):
        result = {"text": "[unk]", "result": [{"word": "[unk]", "conf": 0.99}]}
        self.assertFalse(voice_room._wake_detected(result))

    def test_legitimate_the_first_word_is_not_deleted(self):
        self.assertEqual(
            voice_room._strip_leading_garbage("the weather tomorrow"),
            "the weather tomorrow",
        )


class ConversationWindowCase(unittest.TestCase):
    def test_bare_wake_expires_instead_of_stealing_later_room_speech(self):
        spoken, asked = [], []
        times = iter([0.0, 0.0, 0.0, 20.0])
        with mock.patch.object(
            voice_room, "ask_core",
            side_effect=lambda text, *a, **k: asked.append(text) or {"say": "wrong"},
        ):
            handled = voice_room.listen_forever(
                recognizer=iter([
                    (True, ""),
                    (False, "this conversation is not for thea"),
                ]),
                speaker=spoken.append,
                monotonic=lambda: next(times),
            )
        self.assertEqual(handled, 0)
        self.assertEqual(asked, [])
        self.assertEqual(spoken, ["Yes?"])

    def test_unaddressed_room_speech_never_makes_thea_talk(self):
        spoken = []
        handled = voice_room.listen_forever(
            recognizer=iter([
                (False, "normal conversation"),
                (False, "television dialogue"),
                (False, "someone says a random sentence"),
            ]),
            speaker=spoken.append,
        )
        self.assertEqual(handled, 0)
        self.assertEqual(spoken, [])

    def test_identical_failure_is_briefly_suppressed(self):
        spoken = []
        with mock.patch.object(
            voice_room, "ask_core", side_effect=OSError("offline")
        ):
            handled = voice_room.listen_forever(
                recognizer=iter([
                    (True, "thea status"),
                    (True, "thea status"),
                ]),
                speaker=spoken.append,
                monotonic=lambda: 1.0,
            )
        self.assertEqual(handled, 2)
        self.assertEqual(len(spoken), 1)
        self.assertIn("couldn't reach my Core", spoken[0])


class SingletonCase(unittest.TestCase):
    def test_second_listener_cannot_take_same_os_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "voice.lock"
            first = voice_room.VoiceInstanceLock(path)
            second = voice_room.VoiceInstanceLock(path)
            self.assertTrue(first.acquire())
            try:
                self.assertFalse(second.acquire())
            finally:
                first.release()
            self.assertTrue(second.acquire())
            second.release()


class MouthGateCase(unittest.TestCase):
    def test_real_speak_marks_an_output_generation_and_prefers_piper(self):
        before = voice_room._output_generation
        with mock.patch.object(voice_room.voice_quality, "piper_speak", return_value=True), \
             mock.patch.object(voice_room, "sapi_speak") as sapi:
            voice_room.speak("hello")
        self.assertEqual(voice_room._output_generation, before + 1)
        sapi.assert_not_called()
        self.assertGreater(voice_room._ignore_audio_until, 0)

    def test_sapi_is_only_the_fallback(self):
        with mock.patch.object(voice_room.voice_quality, "piper_speak", return_value=False), \
             mock.patch.object(voice_room, "sapi_speak") as sapi:
            voice_room.speak("hello")
        sapi.assert_called_once_with("hello")


if __name__ == "__main__":
    unittest.main()
