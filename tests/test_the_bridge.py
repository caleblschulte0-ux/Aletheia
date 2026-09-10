"""The bridge: when the subscriptions run out, she keeps thinking.

    "the whole point of building this LLM on my own was the bridge ... I can
    have something that technically will always be able to fix something.
    That'll never run out even if it's not the best."   — 2026-09-10

    ...and in the same breath: the only things he wants changing his
    repositories are Claude and the best of ChatGPT.

What was true that morning, and what these hold against:

- Claude says exactly when its window comes back ("You've hit your session
  limit · resets 4:40pm (UTC)") and Aletheia heard "Claude CLI exited 1".
- The standard policy's local fallback asked only the deep model, which
  needs ~19 GB on a 16 GB laptop: 31 recorded attempts, 31 failures. The
  bridge had never carried a single request.
- Conversation had Claude, then ChatGPT, then nothing.
- qwen3:8b drafted a sound charter in 100 seconds whose only fault was
  counting `needs` from zero.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (brief, charters, converse, local_model_pool, reasoner,
                      reasoning_gateway)
from aletheia.fleet import load_fleet
from tests.test_projects_are_carried import NOW
from tests.test_projects_by_saying_so import think_returning

SAID = "You've hit your session limit · resets 4:40pm (UTC)"


def utc(*args):
    return dt.datetime(*args, tzinfo=dt.timezone.utc)


class ClearRest(unittest.TestCase):
    """The rest marker lives in (the suite's temporary) private state, so a
    test that sets it must leave nothing behind for the next module."""

    def setUp(self):
        self.addCleanup(self._clear)
        self._clear()

    @staticmethod
    def _clear():
        try:
            reasoner._rest_path().unlink()
        except OSError:
            pass


class ItHearsWhenClaudeIsOutCase(unittest.TestCase):
    def test_the_words_it_actually_prints(self):
        self.assertEqual(reasoner.limit_reset(SAID, now=utc(2026, 9, 10, 15, 35)),
                         utc(2026, 9, 10, 16, 40))

    def test_a_reset_earlier_in_the_day_is_tomorrow(self):
        self.assertEqual(reasoner.limit_reset(SAID, now=utc(2026, 9, 10, 17, 0)),
                         utc(2026, 9, 11, 16, 40))

    def test_his_own_zone(self):
        said = "You've hit your session limit · resets 4pm (America/Chicago)"
        self.assertEqual(reasoner.limit_reset(said, now=utc(2026, 9, 10, 15, 0)),
                         utc(2026, 9, 10, 21, 0))

    def test_a_weekly_limit_with_a_date(self):
        said = "You've hit your weekly limit · resets Sep 12, 4pm (UTC)"
        self.assertEqual(reasoner.limit_reset(said, now=utc(2026, 9, 10, 15, 0)),
                         utc(2026, 9, 12, 16, 0))

    def test_a_limit_that_does_not_say_when_is_tried_again_soon(self):
        now = utc(2026, 9, 10, 15, 0)
        self.assertEqual(reasoner.limit_reset("You've hit your usage limit", now=now),
                         now + reasoner.REST_FALLBACK)

    def test_other_failures_are_not_a_limit(self):
        for said in ("bad login", "Claude CLI exited 1", "network unreachable"):
            with self.subTest(said=said):
                self.assertIsNone(reasoner.limit_reset(said))


class ItStopsAskingUntilTheResetCase(ClearRest):
    def completed(self, stdout="", code=0, stderr=""):
        return subprocess.CompletedProcess(["claude"], code, stdout, stderr)

    def test_a_spent_window_is_remembered_and_not_asked_again(self):
        with mock.patch.object(reasoner, "cli_path", return_value="claude.exe"), \
             mock.patch.object(reasoner.subprocess, "run",
                               return_value=self.completed(SAID, 1)) as run:
            with self.assertRaises(reasoner.ClaudeResting):
                reasoner._run_cli("s", "u", "haiku")
            self.assertIsNotNone(reasoner.resting_until())
            with self.assertRaises(reasoner.ClaudeResting):
                reasoner._run_cli("s", "u", "haiku")
        self.assertEqual(run.call_count, 1)

    def test_the_error_envelope_carries_it_too(self):
        envelope = json.dumps({"is_error": True, "result": SAID})
        with mock.patch.object(reasoner, "cli_path", return_value="claude.exe"), \
             mock.patch.object(reasoner.subprocess, "run", return_value=self.completed(envelope)):
            with self.assertRaises(reasoner.ClaudeResting):
                reasoner._run_cli("s", "u", "haiku")

    def test_an_answer_that_mentions_a_limit_is_an_answer(self):
        envelope = json.dumps({"result": "People say they've hit your session limit when..."})
        with mock.patch.object(reasoner, "cli_path", return_value="claude.exe"), \
             mock.patch.object(reasoner.subprocess, "run", return_value=self.completed(envelope)):
            self.assertIn("limit", reasoner._run_cli("s", "u", "haiku"))
        self.assertIsNone(reasoner.resting_until())

    def test_once_the_reset_passes_claude_is_asked_again(self):
        reasoner._rest(utc(2020, 1, 1), SAID)
        self.assertIsNone(reasoner.resting_until())
        envelope = json.dumps({"result": "back"})
        with mock.patch.object(reasoner, "cli_path", return_value="claude.exe"), \
             mock.patch.object(reasoner.subprocess, "run", return_value=self.completed(envelope)) as run:
            self.assertEqual(reasoner._run_cli("s", "u", "haiku"), "back")
        run.assert_called_once()

    def test_resting_is_still_unavailable_to_everything_that_already_handles_that(self):
        self.assertTrue(issubclass(reasoner.ClaudeResting, reasoner.ReasonerUnavailable))


class TheBridgeUsesTheModelThatFitsCase(unittest.TestCase):
    def test_standard_falls_to_whatever_local_model_fits(self):
        run = local_model_pool.LocalRun("fast", "qwen3:8b", False, {"summary": "plain"}, None, 1)
        with mock.patch.object(reasoning_gateway.model_pool_config, "enabled", return_value=True), \
             mock.patch.object(local_model_pool, "reachable", return_value=True), \
             mock.patch.object(reasoner, "subscription_json",
                               side_effect=reasoner.ClaudeResting(utc(2030, 1, 1))), \
             mock.patch.object(local_model_pool, "auto_json", return_value=run) as local:
            result = reasoning_gateway.reason_json("sys", "plan it", policy="standard")
        self.assertEqual(result.provider, "ollama:qwen3:8b")
        self.assertTrue(local.call_args.kwargs["allow_failover"])

    def test_critical_work_never_falls_to_the_local_model(self):
        """His rule: only Claude and the best of ChatGPT change his repos."""
        with mock.patch.object(reasoner, "subscription_json",
                               side_effect=reasoner.ClaudeResting(utc(2030, 1, 1))), \
             mock.patch.object(local_model_pool, "auto_json") as local:
            with self.assertRaises(reasoner.ReasonerUnavailable):
                reasoning_gateway.reason_json("sys", "review", policy="critical")
        local.assert_not_called()

    def test_the_code_worker_and_the_merge_review_stay_on_the_subscriptions(self):
        from aletheia.fleet import REPO_ROOT
        for rel in ("aletheia/code_worker.py", "aletheia/project_merge.py"):
            body = (REPO_ROOT / rel).read_text(encoding="utf-8")
            self.assertNotIn("local_model_pool", body, rel)
            self.assertNotIn("reasoning_gateway", body, rel)


class HerOwnVoiceCase(ClearRest):
    def test_her_own_model_answers_in_the_one_field(self):
        run = local_model_pool.LocalRun("fast", "qwen3:8b", False, {"answer": "The moon."}, None, 1)
        with mock.patch("aletheia.model_pool_config.enabled", return_value=True), \
             mock.patch.object(local_model_pool, "reachable", return_value=True), \
             mock.patch.object(local_model_pool, "auto_json", return_value=run) as local:
            said, provider = reasoner.local_text("sys", "why tides?")
        self.assertEqual((said, provider), ("The moon.", "ollama:qwen3:8b"))
        self.assertIn('{"answer"', local.call_args.args[0])
        self.assertEqual(local.call_args.kwargs["preferred_role"], "fast")

    def test_switched_off_is_said_not_pretended(self):
        with mock.patch("aletheia.model_pool_config.enabled", return_value=False):
            with self.assertRaises(reasoner.ReasonerUnavailable):
                reasoner.local_text("sys", "q")

    def test_conversation_keeps_answering_and_says_whose_answer_it_is(self):
        reasoner._rest(utc(2030, 1, 1, 16, 40), SAID)
        with mock.patch.object(reasoner, "subscription_text",
                               side_effect=reasoner.ClaudeResting(utc(2030, 1, 1, 16, 40))), \
             mock.patch.object(reasoner, "local_text", return_value=("The moon.", "ollama:qwen3:8b")):
            out = converse.answer("why are there tides", include_thread=False, read_files=False)
        self.assertIn("The moon.", out["answer"])
        self.assertIn("from my own model", out["answer"])
        self.assertIn("Claude's out until", out["answer"])
        self.assertEqual(out["provider"], "ollama:qwen3:8b")

    def test_nothing_at_all_is_still_an_honest_error(self):
        with mock.patch.object(reasoner, "subscription_text",
                               side_effect=reasoner.ReasonerUnavailable("down")), \
             mock.patch.object(reasoner, "local_text",
                               side_effect=reasoner.ReasonerUnavailable("off")):
            with self.assertRaises(converse.ConverseError):
                converse.answer("why are there tides", include_thread=False, read_files=False)


class DraftingAcrossTheBridgeCase(unittest.TestCase):
    def test_a_smaller_model_counting_from_zero_is_forgiven(self):
        steps = [{"text": "Write the product brief", "owner": "thea", "needs": []},
                 {"text": "Design three organizer models", "owner": "thea", "needs": [0]},
                 {"text": "Print the first batch", "owner": "caleb", "needs": [1]}]
        value = {"title": "Desk Organizers", "goal": "An Etsy shop selling printed desk organizers",
                 "repo": "Money_Machine", "why": "x", "steps": steps}
        fixed = charters._validator({"Money_Machine"})(copy.deepcopy(value))
        self.assertEqual([s["needs"] for s in fixed["steps"]], [[], [1], [2]])

    def test_a_draft_by_her_own_model_says_so(self):
        output = {"title": "Pocket Chef",
                  "goal": "A recipe app that plans a week of dinners from what is in the fridge",
                  "repo": "Money_Machine", "why": "because he asked",
                  "steps": [{"text": "Write the product brief in the repository", "owner": "thea", "needs": []},
                            {"text": "Pick the three recipes to launch with", "owner": "caleb", "needs": []},
                            {"text": "Build the first screen from the brief", "owner": "thea", "needs": [2]}]}
        result = reasoning_gateway.GatewayResult(output, "ollama:qwen3:8b", "standard")
        with mock.patch.object(reasoning_gateway, "reason_json", return_value=result) as gateway:
            plan = charters.draft("a recipe app", fleet=load_fleet(), existing=[], now=NOW)
        self.assertEqual(gateway.call_args.kwargs["policy"], "standard")
        self.assertEqual(plan["project"]["drafted_by"], "ollama:qwen3:8b")
        self.assertIn("own model", plan["project"]["why"])
        self.assertIn("closer look", brief._confirm_text(plan))

    def test_nobody_able_to_think_costs_an_ask_nothing(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        from tests.test_projects_by_saying_so import FakeContents, fleet_as
        with mock.patch.object(charters, "QUEUE_PATH", Path(tmp.name) / "asks.json"):
            charters.ask("new", text="a recipe app", via="test")

            def nobody(*_a, **_kw):
                raise reasoner.ClaudeResting(utc(2030, 1, 1))
            for _ in range(charters.MAX_ATTEMPTS + 1):
                charters.drain(request=FakeContents(), think=nobody, fleet=fleet_as("me"), now=NOW)
            row = charters.pending()[0]
        self.assertEqual((row["state"], row["attempts"]), ("pending", 0))


if __name__ == "__main__":
    unittest.main()
