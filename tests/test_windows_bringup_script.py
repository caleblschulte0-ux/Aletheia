"""The operator's Windows entrypoint must stay short, safe and fail-closed."""
import unittest
from pathlib import Path

from aletheia.fleet import REPO_ROOT


class WindowsBringupScriptCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bootstrap = (REPO_ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
        cls.bringup = (REPO_ROOT / "scripts" / "bringup_windows.ps1").read_text(encoding="utf-8")

    def test_bootstrap_delegates_to_bounded_bringup(self):
        self.assertIn("bringup_windows.ps1", self.bootstrap)
        self.assertNotIn("unittest discover", self.bootstrap)
        self.assertNotIn("-s tests", self.bootstrap)

    def test_bringup_never_runs_the_full_development_suite(self):
        low = self.bringup.casefold()
        self.assertNotIn("unittest discover", low)
        self.assertNotIn("-s tests", low)
        self.assertNotIn("1210", low)

    def test_stale_background_tasks_are_stopped_before_repo_repair(self):
        stop = self.bringup.index("Stop-ScheduledTask")
        fetch = self.bringup.index("git -C $dest fetch")
        self.assertLess(stop, fetch)

    def test_unattended_browser_lease_is_removed(self):
        self.assertIn("Remove-Item Env:\\ALETHEIA_ALLOW_CHATGPT_BROWSER_REASONING", self.bringup)
        self.assertIn("operator_lease_enabled", self.bringup)

    def test_resume_happens_only_after_core_voice_and_final_health(self):
        core = self.bringup.index("Core: UP")
        voice = self.bringup.index("voice_repair.ps1")
        final = self.bringup.index("Final health checks")
        resume = self.bringup.index('"aletheia.policy","resume"')
        self.assertLess(core, voice)
        self.assertLess(voice, final)
        self.assertLess(final, resume)


if __name__ == "__main__":
    unittest.main()
