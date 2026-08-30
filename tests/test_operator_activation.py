import unittest
from unittest import mock

from aletheia import chatgpt_session, project_autostart
from aletheia.fleet import REPO_ROOT


class FakeEditor:
    pass


class FakePage:
    def __init__(self, url="https://chatgpt.com/"):
        self.url = url
        self.closed = False
    def goto(self, url, wait_until=None):
        del url, wait_until
    def close(self):
        self.closed = True


class FakeContext:
    def __init__(self, page): self.page = page
    def new_page(self): return self.page


class FakeSession:
    def __init__(self, page): self.ctx = FakeContext(page)
    def __enter__(self): return self.ctx
    def __exit__(self, *args): pass


class ChatGPTSessionCase(unittest.TestCase):
    def test_status_is_read_only_and_accepts_prompt_box(self):
        page = FakePage()
        profile_type = type(chatgpt_session.browse.PROFILE_DIR)
        with mock.patch.object(chatgpt_session.browse, "available", return_value=(True, "ready")), \
             mock.patch.object(profile_type, "exists", return_value=True), \
             mock.patch.object(chatgpt_session.browse, "_Session", return_value=FakeSession(page)), \
             mock.patch.object(chatgpt_session.browser_reasoner, "_host_ok", return_value=True), \
             mock.patch.object(chatgpt_session.browser_reasoner, "_editor", return_value=FakeEditor()) as editor:
            result = chatgpt_session.status()
        self.assertTrue(result["ready"])
        editor.assert_called_once_with(page)
        self.assertTrue(page.closed)

    def test_auth_redirect_is_not_ready(self):
        page = FakePage("https://auth.openai.com/login")
        profile_type = type(chatgpt_session.browse.PROFILE_DIR)
        with mock.patch.object(chatgpt_session.browse, "available", return_value=(True, "ready")), \
             mock.patch.object(profile_type, "exists", return_value=True), \
             mock.patch.object(chatgpt_session.browse, "_Session", return_value=FakeSession(page)), \
             mock.patch.object(chatgpt_session.browser_reasoner, "_host_ok", return_value=False):
            result = chatgpt_session.status()
        self.assertFalse(result["ready"])


class ProjectAutostartCase(unittest.TestCase):
    def test_registration_is_30m_non_overlapping_batch(self):
        script = project_autostart.register_script(
            r"C:\Py\pythonw.exe", r"C:\Users\operator\Aletheia"
        )
        self.assertIn("'-m aletheia.project_loop once'", script)
        self.assertIn("'AletheiaProjects'", script)
        self.assertIn("New-TimeSpan -Minutes 30", script)
        self.assertIn("-MultipleInstances IgnoreNew", script)
        self.assertIn("-ExecutionTimeLimit (New-TimeSpan -Minutes 20)", script)

    def test_wrong_target_or_slow_repeat_fails_audit(self):
        actual = {
            "exists": True, "state": "Ready", "arguments": "-m something.else",
            "multiple_instances": "Parallel", "allow_start_on_batteries": True,
            "keeps_running_on_batteries": True, "start_when_available": True,
            "repetition_intervals": ["PT1H"],
        }
        problems = " | ".join(project_autostart.audit(actual))
        self.assertIn("wrong module", problems)
        self.assertIn("IgnoreNew", problems)
        self.assertIn("<= 30m", problems)


class ActivationScriptCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (REPO_ROOT / "scripts" / "activate_operator.ps1").read_text(encoding="utf-8")

    def test_script_runs_tests_before_enabling_standing_grants(self):
        tests = self.text.index('"unittest","discover"')
        work = self.text.index('"aletheia.work_trust","on"')
        code = self.text.index('"aletheia.code_trust","on"')
        self.assertLess(tests, work)
        self.assertLess(tests, code)

    def test_script_uses_official_login_flows_and_dpapi_import(self):
        self.assertIn("gh auth login --hostname github.com --web", self.text)
        self.assertIn('"aletheia.github_auth","import-cli"', self.text)
        self.assertIn("aletheia.browse login https://chatgpt.com/", self.text)
        self.assertNotIn("setx ", self.text.casefold())
        self.assertNotIn("FLEET_TOKEN=", self.text)
        self.assertNotIn("GITHUB_TOKEN=", self.text)

    def test_script_installs_and_verifies_every_persistent_piece(self):
        for needle in (
            '"aletheia.autostart","install","--only","core"',
            '"aletheia.project_autostart","install"',
            '"aletheia.github_auth","status"',
            '"aletheia.chatgpt_session"',
            '"aletheia.work_trust","status"',
            '"aletheia.code_trust","status"',
            '"aletheia.project_autostart","status"',
        ):
            self.assertIn(needle, self.text)
        self.assertIn("scripts\\voice_repair.ps1", self.text)


if __name__ == "__main__":
    unittest.main()
