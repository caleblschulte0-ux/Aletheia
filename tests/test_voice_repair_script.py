"""Static guardrails for the operator-invoked Windows voice repair script."""
import unittest

from aletheia.fleet import REPO_ROOT


class VoiceRepairScriptCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (REPO_ROOT / "scripts" / "voice_repair.ps1").read_text(encoding="utf-8")

    def test_it_refuses_to_restart_always_on_voice_from_a_review_branch(self):
        self.assertIn('$branch -ne "main"', self.source)
        self.assertIn("refusing to restart always-on voice", self.source)

    def test_it_prepares_models_before_stopping_current_listener(self):
        setup = self.source.index("-m aletheia.voice_room --setup")
        stop = self.source.index('Stop-ScheduledTask -TaskName "AletheiaVoice"')
        self.assertLess(setup, stop)

    def test_it_requires_neural_quality_before_stopping_the_old_listener(self):
        piper = self.source.index("p=q.piper_ready()")
        whisper = self.source.index("w=q.whisper_ready()")
        refusal = self.source.index("neural speech setup is incomplete")
        stop = self.source.index('Stop-ScheduledTask -TaskName "AletheiaVoice"')
        self.assertLess(piper, refusal)
        self.assertLess(whisper, refusal)
        self.assertLess(refusal, stop)

    def test_it_waits_for_old_listener_to_stop_before_starting_a_new_one(self):
        stop = self.source.index('Stop-ScheduledTask -TaskName "AletheiaVoice"')
        guard = self.source.index("old AletheiaVoice listener did not stop")
        start = self.source.index('Start-ScheduledTask -TaskName "AletheiaVoice"')
        self.assertLess(stop, guard)
        self.assertLess(guard, start)

    def test_it_runs_an_honest_readiness_check_after_restart(self):
        self.assertIn("-m aletheia.voice_room --check", self.source)


if __name__ == "__main__":
    unittest.main()
