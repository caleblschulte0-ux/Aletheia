"""Direct ChatGPT work envelopes stay quote-bound, public-safe, and Claude-independent."""
import unittest
from unittest import mock

from aletheia import intents, work_direct, work_session


class DirectEnvelopeCase(unittest.TestCase):
    def setUp(self):
        self.quote = "Open the project dashboard and refresh it"

    def envelope(self, actions=None):
        return work_direct.encode(
            quote=self.quote,
            summary="Open and refresh the dashboard",
            actions=actions or [{
                "type": "computer",
                "steps": [
                    {"action": "open_app", "app": "notepad.exe", "arguments": []},
                    {"action": "list_windows", "max_results": 10},
                ],
            }],
        )

    def test_quote_hash_binds_plan_to_operator_words(self):
        text = self.envelope()
        plan = work_direct.parse(text, quote=self.quote)
        self.assertEqual(plan["summary"], "Open and refresh the dashboard")
        with self.assertRaises(work_direct.DirectWorkRefused):
            work_direct.parse(text, quote="different operator request")

    def test_public_bus_refuses_arbitrary_computer_typing(self):
        text = self.envelope([{
            "type": "computer",
            "steps": [{"action": "set_text", "window": {"title": "Notes"},
                       "control": {"control_type": "Document"}, "text": "private"}],
        }])
        with self.assertRaises(work_direct.DirectWorkRefused):
            work_direct.parse(text, quote=self.quote)

    def test_public_bus_refuses_open_app_arguments(self):
        text = self.envelope([{
            "type": "computer",
            "steps": [{"action": "open_app", "app": "notepad.exe",
                       "arguments": [r"C:\Users\Caleb\Private\notes.txt"]}],
        }])
        with self.assertRaises(work_direct.DirectWorkRefused):
            work_direct.parse(text, quote=self.quote)

    def test_public_bus_refuses_browser_typing(self):
        text = self.envelope([{
            "type": "browser", "url": "https://example.com",
            "steps": [{"action": "type", "selector": "#q", "value": "private text"}],
        }])
        with self.assertRaises(work_direct.DirectWorkRefused):
            work_direct.parse(text, quote=self.quote)

    def test_sensitive_click_is_refused_before_work_session(self):
        text = self.envelope([{
            "type": "browser", "url": "https://example.com/account",
            "steps": [{"action": "click", "selector": "button.delete-account"}],
        }])
        with self.assertRaises(work_direct.DirectWorkRefused):
            work_direct.parse(text, quote=self.quote)

    def test_safe_navigation_plan_executes_through_active_work_session(self):
        text = self.envelope([{
            "type": "browser", "url": "https://example.com/project",
            "steps": [{"action": "click", "selector": "button.refresh"},
                      {"action": "wait_for", "selector": "main"}],
        }])
        with mock.patch.object(work_direct.work_session, "active", return_value={"id": "ws"}), \
             mock.patch.object(
                 work_direct.work_session, "run_browser",
                 return_value={"url": "https://example.com/project", "steps_done": ["click", "wait"]},
             ) as run:
            result = work_direct.execute(text, quote=self.quote)
        self.assertEqual(result["state"], "EXECUTED")
        run.assert_called_once()

    def test_no_active_session_refuses_before_any_action(self):
        text = self.envelope()
        with mock.patch.object(work_direct.work_session, "active", return_value=None), \
             mock.patch.object(work_direct.work_session, "run_computer") as run:
            with self.assertRaises(work_session.WorkSessionRequired):
                work_direct.execute(text, quote=self.quote)
        run.assert_not_called()

    def test_intent_direct_route_never_calls_claude_planner(self):
        text = self.envelope()
        fake = {
            "direct_work": True, "state": "EXECUTED", "summary": "done",
            "receipts": [], "spoken": "done",
        }
        with mock.patch("aletheia.work_direct.execute", return_value=fake) as execute, \
             mock.patch.object(intents.planner, "compile") as compile_plan:
            record = intents.propose(text, quote=self.quote)
        self.assertIs(record, fake)
        execute.assert_called_once_with(text, quote=self.quote)
        compile_plan.assert_not_called()
        self.assertEqual(intents.spoken(record), "done")

    def test_non_direct_intents_still_use_existing_planner(self):
        self.assertFalse(work_direct.is_direct("remind me tomorrow"))


if __name__ == "__main__":
    unittest.main()
