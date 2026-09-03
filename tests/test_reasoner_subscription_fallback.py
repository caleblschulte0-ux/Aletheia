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
        self.assertIn("both subscription reasoning paths are unavailable", degraded)
        self.assertIn("local reasoning disabled", degraded)
        self.assertNotIn("claude private detail", degraded)

    def test_subscription_timeout_is_one_shared_provider_budget(self):
        with mock.patch.object(reasoner, "infer_json",
                               side_effect=reasoner.ReasonerUnavailable("down")), \
             mock.patch.object(browser_reasoner, "infer_json",
                               return_value=VALID) as browser:
            reasoner.subscription_json("contract", "answer", timeout_s=5)
        self.assertGreater(browser.call_args.kwargs["timeout_s"], 0)
        self.assertLessEqual(browser.call_args.kwargs["timeout_s"], 5)

    def test_exhausted_claude_budget_does_not_start_browser(self):
        with mock.patch.object(reasoner.time, "monotonic",
                               side_effect=[0.0, 0.0, 6.0]), \
             mock.patch.object(reasoner, "infer_json",
                               side_effect=reasoner.ReasonerUnavailable("down")), \
             mock.patch.object(browser_reasoner, "infer_json") as browser:
            with self.assertRaises(reasoner.ReasonerUnavailable):
                reasoner.subscription_json("contract", "answer", timeout_s=5)
        browser.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class ProseHasTwoPathsToo(unittest.TestCase):
    """`infer_json` has had a second path since it was written; `infer_text`
    never did. That was harmless while the only text caller was a code
    generator, and stopped being harmless the moment CONVERSATION became
    one: an expired Claude login would have left her planning, filing,
    reminding and researching normally while every question he actually
    asked came back "I could not reach a model"."""

    def test_the_cli_answers_first_and_says_so(self):
        with mock.patch.object(reasoner, "infer_text", return_value="The moon."):
            said, provider = reasoner.subscription_text("sys", "why tides?")
        self.assertEqual(said, "The moon.")
        self.assertTrue(provider.startswith("claude.cli:"))

    def test_the_browser_answers_when_the_cli_cannot(self):
        with mock.patch.object(reasoner, "infer_text",
                               side_effect=reasoner.ReasonerUnavailable("no CLI")), \
             mock.patch.object(browser_reasoner, "infer_json",
                               return_value={"answer": "The moon, still."}):
            said, provider = reasoner.subscription_text("sys", "why tides?")
        self.assertEqual(said, "The moon, still.")
        self.assertEqual(provider, "chatgpt.browser")

    def test_the_browser_is_asked_for_the_one_field_it_can_return(self):
        seen = {}

        def fake(system, text, **kwargs):
            seen["system"] = system
            return {"answer": "ok"}
        with mock.patch.object(reasoner, "infer_text",
                               side_effect=reasoner.ReasonerUnavailable("no CLI")), \
             mock.patch.object(browser_reasoner, "infer_json", side_effect=fake):
            reasoner.subscription_text("sys", "q")
        self.assertIn('{"answer"', seen["system"])

    def test_both_paths_down_is_one_honest_error(self):
        with mock.patch.object(reasoner, "infer_text",
                               side_effect=reasoner.ReasonerUnavailable("no CLI")), \
             mock.patch.object(browser_reasoner, "infer_json",
                               side_effect=RuntimeError("no session")):
            with self.assertRaises(reasoner.ReasonerUnavailable) as caught:
                reasoner.subscription_text("sys", "q")
        self.assertIn("both subscription paths", str(caught.exception))

    def test_an_empty_cli_answer_falls_through_rather_than_shipping_blank(self):
        with mock.patch.object(reasoner, "infer_text", return_value="   "), \
             mock.patch.object(browser_reasoner, "infer_json",
                               return_value={"answer": "a real one"}):
            said, provider = reasoner.subscription_text("sys", "q")
        self.assertEqual(said, "a real one")

    def test_conversation_uses_the_chain_not_the_bare_cli(self):
        from aletheia.fleet import REPO_ROOT
        body = (REPO_ROOT / "aletheia" / "converse.py").read_text(encoding="utf-8")
        self.assertIn("reasoner.subscription_text", body)
        self.assertNotIn("think or reasoner.infer_text", body)


if __name__ == "__main__":
    unittest.main()
