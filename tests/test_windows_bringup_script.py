"""The operator's Windows entrypoint must stay short, safe and fail-closed."""
import re
import unittest

from aletheia.fleet import REPO_ROOT
from tests.test_ci_writes_where_she_reads import DEPLOY_BRANCH

SCRIPTS = REPO_ROOT / "scripts"
_RAW_URL = re.compile(r"raw\.githubusercontent\.com/caleblschulte0-ux/Aletheia/([^/\s]+)/")


class EveryScriptRunsOnHisShellCase(unittest.TestCase):
    """Windows PowerShell 5.1 reads a file with no byte-order mark as the ANSI
    code page. An em dash (E2 80 94) came out as 0x94, which is a closing
    quote, and the bring-up failed to PARSE on his PC on 2026-09-19 while CI,
    parsing under pwsh, stayed green. Pure ASCII is the one encoding every
    PowerShell reads the same way from disk, from `irm | iex`, and from a
    scheduled task; the CI parse step now runs under 5.1 as the live proof."""

    def test_there_are_scripts_to_check(self):
        self.assertGreaterEqual(len(list(SCRIPTS.glob("*.ps1"))), 5)

    def test_every_powershell_script_is_pure_ascii(self):
        for path in sorted(SCRIPTS.glob("*.ps1")):
            raw = path.read_bytes()
            bad = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
            with self.subTest(script=path.name):
                self.assertEqual(bad[:3], [],
                                 f"{path.name} has a non-ASCII byte at offset {bad[0][0] if bad else 0}: "
                                 "Windows PowerShell 5.1 will misread it. Use ASCII "
                                 "(a hyphen for an em dash, straight quotes).")

    def test_every_raw_url_names_the_branch_the_core_runs_from(self):
        """The one-liner he types fetched `main`, which is 300 commits behind
        `live`, where the Core runs. A script fixed on live never reached him."""
        for path in sorted(list(SCRIPTS.glob("*.ps1")) + [REPO_ROOT / "docs" / "SETUP.md"]):
            for branch in _RAW_URL.findall(path.read_text(encoding="utf-8")):
                with self.subTest(file=path.name, branch=branch):
                    self.assertEqual(branch, DEPLOY_BRANCH)

    def test_ci_parses_every_script_with_windows_powershell_5(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "chatgpt-windows-bringup.yml").read_text(encoding="utf-8")
        step = workflow[workflow.index("Parse every operator PowerShell script"):]
        step = step[:step.index("- name:", 10)]
        self.assertIn("shell: powershell", step)
        self.assertNotIn("shell: pwsh", step)
        self.assertIn("Get-ChildItem -Path scripts -Filter *.ps1", step)
        self.assertIn("PSVersion.Major -ne 5", step)


class WindowsBringupScriptCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bootstrap = (REPO_ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
        cls.bringup = (REPO_ROOT / "scripts" / "bringup_windows.ps1").read_text(encoding="utf-8")

    def test_nothing_is_stopped_before_the_tools_and_the_update_are_in_hand(self):
        """She was killed at the top and every later failure - no network, no
        Python - found her already dead. Git, Python, the fetched update and
        the continuity snapshot all come before the first Stop-ScheduledTask."""
        stop = self.bringup.index("Stop-ScheduledTask")
        self.assertLess(self.bringup.index("$script:PyExe = $python.Exe"), stop)
        self.assertLess(self.bringup.index("git -C $dest fetch origin " + DEPLOY_BRANCH), stop)
        self.assertLess(self.bringup.index("aletheia.continuity snapshot"), stop)
        self.assertIn("nothing was stopped and nothing changed", self.bringup)

    def test_the_update_is_held_to_what_it_was_given_before_core_up(self):
        verify = self.bringup.index("aletheia.continuity verify")
        self.assertGreater(verify, self.bringup.index("Invoke-RestMethod $recovery"))
        self.assertLess(verify, self.bringup.index('Write-Host "  Core: UP"'))
        self.assertIn("The update lost something", self.bringup)

    def test_local_ai_not_answering_is_a_warning_not_the_reason_she_stays_down(self):
        self.assertNotIn('Invoke-AletheiaPython -PyArgs @("-m","aletheia.local_ai","activate")', self.bringup)
        self.assertIn("aletheia.local_ai activate", self.bringup)
        self.assertIn("nothing was switched off", self.bringup)
        self.assertIn("$localAiOk", self.bringup)

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
        recover = self.bringup.index("Invoke-RestMethod $recovery")
        self.assertLess(stop, recover)

    def test_existing_checkout_uses_safe_recovery_not_a_force_checkout(self):
        self.assertIn("recover_operator_checkout.ps1", self.bringup)
        self.assertIn("ALETHEIA_RECOVERY_KEEP_STOPPED", self.bringup)
        self.assertNotIn("checkout -f", self.bringup.casefold())

    def test_one_command_bringup_installs_missing_prerequisites(self):
        self.assertIn("winget install --id Git.Git", self.bringup)
        self.assertIn("winget install --id Python.Python.3.12", self.bringup)
        self.assertIn("Refresh-Path", self.bringup)

    def test_unattended_browser_lease_is_removed(self):
        self.assertIn("Remove-Item Env:\\ALETHEIA_ALLOW_CHATGPT_BROWSER_REASONING", self.bringup)
        self.assertIn("operator_lease_enabled", self.bringup)

    def test_installer_never_lifts_the_kill_switch(self):
        self.assertNotIn('"aletheia.policy","resume"', self.bringup)
        self.assertNotIn("policy.resume(", self.bringup)
        self.assertIn("policy.halted()", self.bringup)

    def test_policy_is_checked_only_after_core_voice_and_final_health(self):
        core = self.bringup.index("Core: UP")
        voice = self.bringup.index("voice_repair.ps1")
        final = self.bringup.index("Final health checks")
        policy = self.bringup.index("policy.halted()")
        self.assertLess(core, voice)
        self.assertLess(voice, final)
        self.assertLess(final, policy)


if __name__ == "__main__":
    unittest.main()
