"""Optional neural speech providers stay optional, bounded, and local."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from aletheia import voice_quality


class QualityFallbackCase(unittest.TestCase):
    def test_unprepared_whisper_returns_none_without_loading_a_model(self):
        with mock.patch.object(voice_quality, "whisper_ready", return_value=(False, "no")), \
             mock.patch.object(voice_quality, "_load_whisper") as load:
            self.assertIsNone(voice_quality.transcribe_pcm(b"\x00\x00" * 100))
        load.assert_not_called()

    def test_unprepared_piper_returns_false_without_running_anything(self):
        runner = mock.Mock()
        with mock.patch.object(voice_quality, "piper_ready", return_value=(False, "no")):
            self.assertFalse(voice_quality.piper_speak("hello", runner=runner, player=lambda p: None))
        runner.assert_not_called()

    def test_piper_requires_a_real_wave_before_playback(self):
        played = []
        proc = SimpleNamespace(returncode=0, stdout="", stderr="")
        with mock.patch.object(voice_quality, "piper_ready", return_value=(True, "ok")), \
             mock.patch.object(voice_quality, "_piper_exe", return_value="piper"):
            ok = voice_quality.piper_speak(
                "hello", runner=lambda *a, **k: proc, player=lambda p: played.append(p)
            )
        self.assertFalse(ok)
        self.assertEqual(played, [])

    def test_piper_plays_verified_wave_and_removes_temp_file(self):
        played = []

        def runner(argv, **kwargs):
            target = Path(argv[argv.index("--output_file") + 1])
            target.write_bytes(b"RIFF" + b"x" * 100)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with mock.patch.object(voice_quality, "piper_ready", return_value=(True, "ok")), \
             mock.patch.object(voice_quality, "_piper_exe", return_value="piper"):
            ok = voice_quality.piper_speak(
                "hello", runner=runner,
                player=lambda p: played.append((p, p.exists())),
            )
        self.assertTrue(ok)
        self.assertEqual(len(played), 1)
        self.assertTrue(played[0][1])
        self.assertFalse(played[0][0].exists())

    def test_setup_does_not_pretend_quality_is_ready_when_install_fails(self):
        with mock.patch.object(
            voice_quality, "install_quality_packages", return_value=(False, "pip failed")
        ), mock.patch.object(voice_quality, "ensure_piper_model") as piper, \
             mock.patch.object(voice_quality, "ensure_whisper_model") as whisper:
            result = voice_quality.setup_quality(install=True)
        self.assertFalse(result["packages"]["ok"])
        self.assertIsNone(result["piper"])
        self.assertIsNone(result["whisper"])
        piper.assert_not_called()
        whisper.assert_not_called()


if __name__ == "__main__":
    unittest.main()
