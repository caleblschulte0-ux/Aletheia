"""Optional neural speech providers stay optional, bounded, and local."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from aletheia import voice_quality


class QualityFallbackCase(unittest.TestCase):
    def test_default_voice_is_local_british_male(self):
        self.assertEqual(voice_quality.PIPER_VOICE, "en_GB-alan-medium")

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

    def test_piper_download_uses_dedicated_python_module(self):
        calls = []

        def runner(argv, **kwargs):
            calls.append(argv)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with mock.patch.object(voice_quality, "_piper_installed", return_value=True), \
             mock.patch.object(
                 voice_quality, "piper_ready",
                 side_effect=[(False, "missing"), (True, "Piper ready")],
             ):
            ok, why = voice_quality.ensure_piper_model(runner=runner)
        self.assertTrue(ok)
        self.assertEqual(why, "Piper ready")
        self.assertEqual(len(calls), 1)
        argv = calls[0]
        self.assertEqual(argv[:3], [sys.executable, "-m", "piper.download_voices"])
        self.assertIn("--data-dir", argv)
        self.assertEqual(argv[-1], voice_quality.PIPER_VOICE)

    def test_piper_requires_a_real_wave_before_playback(self):
        played = []
        proc = SimpleNamespace(returncode=0, stdout="", stderr="")
        with mock.patch.object(voice_quality, "piper_ready", return_value=(True, "ok")):
            ok = voice_quality.piper_speak(
                "hello", runner=lambda *a, **k: proc, player=lambda p: played.append(p)
            )
        self.assertFalse(ok)
        self.assertEqual(played, [])

    def test_piper_plays_verified_wave_and_removes_temp_file(self):
        played = []
        argv_seen = []

        def runner(argv, **kwargs):
            argv_seen.extend(argv)
            target = Path(argv[argv.index("--output-file") + 1])
            target.write_bytes(b"RIFF" + b"x" * 100)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with mock.patch.object(voice_quality, "piper_ready", return_value=(True, "ok")):
            ok = voice_quality.piper_speak(
                "hello", runner=runner,
                player=lambda p: played.append((p, p.exists())),
            )
        self.assertTrue(ok)
        self.assertEqual(len(played), 1)
        self.assertTrue(played[0][1])
        self.assertFalse(played[0][0].exists())
        self.assertEqual(argv_seen[:3], [sys.executable, "-m", "piper"])
        self.assertIn("--data-dir", argv_seen)
        self.assertIn("--output-file", argv_seen)
        self.assertIn("--", argv_seen)
        self.assertNotIn("--download-dir", argv_seen)

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
