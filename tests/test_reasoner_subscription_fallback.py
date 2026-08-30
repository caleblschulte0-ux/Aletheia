import unittest
from unittest import mock

from aletheia import browser_reasoner, reasoner


VALID = {
    "intent": "clarify",
    "summary": "need one detail",
    "required_capabilities": [],
    "confidence": 0.8,
}


class SubscriptionFallbackCase(unittest.TestCase):
    def test_claude_success_does_not_touch_browser(self):
        adapter = reasoner.CliReasoner(system_prompt="contract")
        with mock.patch.object(reasoner, "infer_json", return_value=VALID) as cli, \
             mock.patch.object(browser_reasoner, "infer_json") as browser:
            result = adapter.provider("claude.cli.plan").run("do something", {})
        self.assertEqual(result["summary"], "need one detail")
        cli.assert_called_once()
        browser.assert_not_called()

    def test_claude_failure_uses_chatgpt_browser_without_api_key(self):
        adapter = reasoner.CliReasoner(system_prompt="contract")
        with mock.patch.object(reasoner, "infer_json",
                               side_effect=reasoner.ReasonerUnavailable("subscription down")), \
             mock.patch.object(browser_reasoner, "infer_json", return_value=VALID) as browser:
            provider = adapter.provider("claude.cli.plan")
            result = provider.run("do something", {"now": "fact"})
        self.assertEqual(provider.id, "subscription.auto.plan")
        self.assertEqual(result["intent"], "clarify")
        browser.assert_called_once()

    def test_malformed_claude_output_also_falls_through(self):
        bad = {"intent": "made-up-intent", "summary": "bad"}
        adapter = reasoner.CliReasoner(system_prompt="contract")
        with mock.patch.object(reasoner, "infer_json", return_value=bad), \
             mock.patch.object(browser_reasoner, "infer_json", return_value=VALID) as browser:
            result = adapter.provider().run("do something", {})
        self.assertEqual(result, VALID)
        browser.assert_called_once()

    def test_both_unavailable_degrades_honestly(self):
        adapter = reasoner.CliReasoner(system_prompt="contract")
        provider = adapter.provider()
        with mock.patch.object(reasoner, "infer_json",
                               side_effect=reasoner.ReasonerUnavailable("claude private detail")), \
             mock.patch.object(browser_reasoner, "infer_json",
                               side_effect=browser_reasoner.BrowserReasonerUnavailable("login needed")):
            output, degraded = reasoner.infer_or_fallback(provider, "do something", {})
        self.assertEqual(output["intent"], "clarify")
        self.assertIn("both subscription reasoning paths are unavailable", degraded)
        self.assertNotIn("claude private detail", degraded)


if __name__ == "__main__":
    unittest.main()
