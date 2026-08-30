import unittest

from aletheia.fleet import REPO_ROOT


class FinishOperatorScriptCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (REPO_ROOT / "scripts" / "finish_operator.ps1").read_text(encoding="utf-8")

    def test_skips_full_suite_and_login_flows(self):
        self.assertNotIn('"unittest","discover"', self.text)
        self.assertNotIn("gh auth login", self.text)
        self.assertNotIn("aletheia.browse login", self.text)

    def test_checks_existing_auth_before_enabling_standing_grants(self):
        first_github = self.text.index('"aletheia.github_auth","status"')
        first_chatgpt = self.text.index('"aletheia.chatgpt_session"')
        work = self.text.index('"aletheia.work_trust","on"')
        code = self.text.index('"aletheia.code_trust","on"')
        self.assertLess(first_github, work)
        self.assertLess(first_chatgpt, work)
        self.assertLess(first_github, code)
        self.assertLess(first_chatgpt, code)

    def test_installs_and_rechecks_persistent_components(self):
        for needle in (
            '"aletheia.autostart","install","--only","core"',
            '"aletheia.project_autostart","install"',
            '"aletheia.work_trust","status"',
            '"aletheia.code_trust","status"',
            '"aletheia.autostart","doctor","--only","core"',
            '"aletheia.autostart","doctor","--only","voice"',
            '"aletheia.project_autostart","status"',
        ):
            self.assertIn(needle, self.text)
        self.assertIn("scripts\\voice_repair.ps1", self.text)

    def test_uses_python_312_and_refuses_empty_args(self):
        self.assertIn("& py -3.12 @PyArgs", self.text)
        self.assertIn("refusing empty Python arguments", self.text)


if __name__ == "__main__":
    unittest.main()
