import os
import unittest
from unittest import mock

from aletheia import browser_reasoner, local_model_pool, reasoner


VALID = {
    "intent": "clarify",
    "summary": "need one detail",
    "required_capabilities": [],
    "confidence": 0.8,
}


class SubscriptionFallbackCase(unittest.TestCase):
    def setUp(self):
        self.shadow = mock.patch.dict(
            os.environ, {"ALETHEIA_LOCAL_AI_SHADOW": "0"}, clear=False,
        )
        self.shadow.start()

    def tearDown(self):
        self.shadow.stop()

    def test_claude_success_does_not_touch_browser(self):
        adapter = reasoner.CliReasoner(
            model=reasoner.PLAN_MODEL, system_prompt="contract",
        )
        with mock.patch.object(reasoner, "infer_json", return_value=VALID) as cli, \
             mock.patch.object(browser_reasoner, "infer_json") as browser:
            result = adapter.provider("claude.cli.plan").run("do something", {})
        self.assertEqual(result["summary"], "need one detail")
        cli.assert_called_once()
        browser.assert_not_called()

    def test_claude_failure_uses_chatgpt_browser_without_api_key(self):
        adapter = reasoner.CliReasoner(
            model=reasoner.PLAN_MODEL, system_prompt="contract",
        )
        with mock.patch.object(reasoner, "infer_json",
                               side_effect=reasoner.ReasonerUnavailable("subscription down")), \
             mock.patch.object(browser_reasoner, "infer_json", return_value=VALID) as browser:
            provider = adapter.provider("claude.cli.plan")
            result = provider.run("do something", {"now": "fact"})
        self.assertEqual(provider.id, "reasoning.hybrid.standard.plan")
        self.assertEqual(result["intent"], "clarify")
        browser.assert_called_once()

    def test_malformed_claude_output_also_falls_through(self):
        bad = {"intent": "made-up-intent", "summary": "bad"}
        adapter = reasoner.CliReasoner(
            model=reasoner.PLAN_MODEL, system_prompt="contract",
        )
        with mock.patch.object(reasoner, "infer_json", return_value=bad), \
             mock.patch.object(browser_reasoner, "infer_json", return_value=VALID) as browser:
            result = adapter.provider().run("do something", {})
        self.assertEqual(result, VALID)
        browser.assert_called_once()

    def test_custom_schema_validator_participates_in_fallback(self):
        def validate(value):
            if value.get("approved") is not True:
                raise ValueError("wrong review schema")
            return value
        with mock.patch.object(reasoner, "infer_json", return_value={"approved": False}), \
             mock.patch.object(browser_reasoner, "infer_json",
                               return_value={"approved": True, "findings": []}) as browser:
            result = reasoner.subscription_json(
                "contract", "review this", validator=validate
            )
        self.assertTrue(result["approved"])
        browser.assert_called_once()

    def test_both_unavailable_degrades_honestly(self):
        adapter = reasoner.CliReasoner(
            model=reasoner.PLAN_MODEL, system_prompt="contract",
        )
        provider = adapter.provider()
        with mock.patch.object(local_model_pool, "auto_json",
                               side_effect=local_model_pool.LocalPoolUnavailable("offline")), \
             mock.patch.object(reasoner, "infer_json",
                               side_effect=reasoner.ReasonerUnavailable("claude private detail")), \
             mock.patch.object(browser_reasoner, "infer_json",
                               side_effect=browser_reasoner.BrowserReasonerUnavailable("login needed")):
            output, degraded = reasoner.infer_or_fallback(provider, "do something", {})
        self.assertEqual(output["intent"], "clarify")
        self.assertIn("subscription reasoning and both local reasoning roles are unavailable", degraded)
        self.assertNotIn("claude private detail", degraded)


if __name__ == "__main__":
    unittest.main()
