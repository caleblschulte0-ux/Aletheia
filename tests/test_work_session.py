"""Work-session autonomy stays useful and fails closed at sensitive boundaries."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, policy, work_session


class WorkSessionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        patches = [
            mock.patch.object(work_session, "SESSION_PATH", root / "session.json"),
            mock.patch.object(work_session, "CLAIMS_DIR", root / "claims"),
            mock.patch.object(journal, "JOURNAL_PATH", root / "journal.jsonl"),
            mock.patch.object(policy, "APPROVALS_DIR", root / "approvals"),
            mock.patch.object(policy, "HALT_PATH", root / "halt.json"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.now = dt.datetime(2026, 8, 29, 20, 0, tzinfo=dt.timezone.utc)

    def open(self, **kw):
        return work_session.open_session(now=self.now, via="test", **kw)

    def test_operator_can_open_and_close_bounded_session(self):
        session = self.open(hours=4, max_actions=7)
        self.assertTrue(policy.is_approved(session["approval_id"]))
        state = work_session.status(now=self.now)
        self.assertTrue(state["active"])
        self.assertEqual(state["actions_left"], 7)
        self.assertTrue(work_session.close_session(via="test"))
        self.assertFalse(work_session.status(now=self.now)["active"])

    def test_expired_session_authorizes_nothing(self):
        self.open(hours=1)
        later = self.now + dt.timedelta(hours=2)
        self.assertIsNone(work_session.active(now=later))

    def test_safe_computer_plan_gets_exact_one_shot_approval(self):
        self.open()
        steps = [
            {"action": "open_app", "app": "notepad.exe", "arguments": []},
            {"action": "wait_window", "window": {"title_re": ".*Notepad.*"}, "timeout_s": 5},
            {"action": "set_text", "window": {"title_re": ".*Notepad.*"},
             "control": {"control_type": "Document"}, "text": "routine project note", "timeout_s": 5},
        ]
        aid = work_session.authorize_computer(steps)
        approval = policy.load(aid)
        self.assertEqual(approval["state"], "APPROVED")
        from aletheia import computer
        self.assertEqual(approval["requested_action"], computer.approval_action(steps))
        self.assertEqual(work_session.status(now=self.now)["used"], 1)

    def test_shell_is_never_auto_authorized(self):
        self.open()
        with self.assertRaises(work_session.WorkSessionRefused):
            work_session.authorize_computer([
                {"action": "open_app", "app": "powershell.exe", "arguments": ["-Command", "whoami"]}
            ])

    def test_closing_windows_is_not_routine_because_unsaved_work_can_be_lost(self):
        self.open()
        steps = [{"action": "close_window", "window": {"title": "Notes"}, "timeout_s": 5}]
        with self.assertRaises(work_session.WorkSessionRefused):
            work_session.authorize_computer(steps)

    def test_sensitive_desktop_controls_force_handoff(self):
        self.open()
        steps = [{"action": "set_text", "window": {"title": "Account Security"},
                  "control": {"auto_id": "password"}, "text": "hello", "timeout_s": 5}]
        problems = work_session.computer_problems(steps)
        self.assertTrue(any("sensitive" in p for p in problems), problems)

    def test_safe_browser_navigation_gets_bounded_approval(self):
        self.open(max_actions=2)
        steps = [
            {"action": "type", "selector": "#search", "value": "Aletheia documentation"},
            {"action": "click", "selector": "button.search"},
            {"action": "wait_for", "selector": "main"},
        ]
        aid = work_session.authorize_browser("https://example.com/docs", steps)
        self.assertTrue(policy.is_approved(aid))
        self.assertEqual(work_session.status(now=self.now)["used"], 1)

    def test_browser_password_payment_and_send_surfaces_force_handoff(self):
        self.open()
        cases = [
            ("https://example.com/account/security", [{"action": "type", "selector": "#password", "value": "x"}]),
            ("https://example.com/checkout", [{"action": "click", "selector": "#pay"}]),
            ("https://mail.example.com/inbox", [{"action": "click", "selector": "button.send"}]),
        ]
        for url, steps in cases:
            with self.subTest(url=url):
                with self.assertRaises(work_session.WorkSessionRefused):
                    work_session.authorize_browser(url, steps)

    def test_api_key_like_text_is_never_auto_typed(self):
        self.open()
        problems = work_session.browser_problems(
            "https://example.com/settings",
            [{"action": "type", "selector": "#value", "value": "sk-1234567890abcdefghijkl"}],
        )
        self.assertTrue(any("credential" in p for p in problems), problems)

    def test_enter_key_is_not_auto_pressed_because_it_can_submit_unknown_form(self):
        self.open()
        problems = work_session.browser_problems(
            "https://example.com/search", [{"action": "press", "value": "Enter"}],
        )
        self.assertTrue(any("submit/trigger" in p for p in problems), problems)

    def test_action_budget_is_hard_cap(self):
        self.open(max_actions=1)
        work_session.authorize_browser(
            "https://example.com", [{"action": "wait_for", "selector": "body"}]
        )
        with self.assertRaises(work_session.WorkSessionRequired):
            work_session.authorize_browser(
                "https://example.com", [{"action": "wait_for", "selector": "main"}]
            )

    def test_kill_switch_beats_live_work_session(self):
        self.open()
        policy.halt("test stop", via="test")
        with self.assertRaises(policy.Halted):
            work_session.authorize_browser(
                "https://example.com", [{"action": "wait_for", "selector": "body"}]
            )


if __name__ == "__main__":
    unittest.main()
