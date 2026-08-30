import unittest

from aletheia.fleet import REPO_ROOT


class OperatorActivationV2Case(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (REPO_ROOT / "scripts" / "activate_operator_v2.ps1").read_text(encoding="utf-8")
        cls.lower = cls.text.casefold()

    def test_never_uses_powershell_automatic_args_as_parameter(self):
        self.assertNotIn("[string[]]$args", self.lower)
        self.assertIn("[string[]]$pyargs", self.lower)
        self.assertIn("invoke-aletheiapython -pyargs", self.lower)

    def test_helper_refuses_empty_python_argv(self):
        self.assertIn("refusing to launch python with an empty argument list", self.lower)

    def test_first_runtime_command_is_explicit_python_m_pip(self):
        self.assertIn('invoke-aletheiapython -pyargs @("-m","pip","install"', self.lower)
        self.assertIn('invoke-aletheiapython -pyargs @("-m","unittest","discover"', self.lower)

    def test_tests_run_before_standing_grants(self):
        tests = self.lower.index('invoke-aletheiapython -pyargs @("-m","unittest","discover"')
        work = self.lower.index('invoke-aletheiapython -pyargs @("-m","aletheia.work_trust","on"')
        code = self.lower.index('invoke-aletheiapython -pyargs @("-m","aletheia.code_trust","on"')
        self.assertLess(tests, work)
        self.assertLess(tests, code)

    def test_auth_stays_off_public_repo_and_environment(self):
        self.assertIn("gh auth login --hostname github.com --web", self.lower)
        self.assertIn('"aletheia.github_auth","import-cli"', self.lower)
        self.assertIn("aletheia.browse login https://chatgpt.com/", self.lower)
        self.assertNotIn("setx ", self.lower)
        self.assertNotIn("fleet_token=", self.lower)
        self.assertNotIn("github_token=", self.lower)


if __name__ == "__main__":
    unittest.main()
