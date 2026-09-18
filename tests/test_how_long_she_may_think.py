"""How long her own model may think, and why it depends on what the work is.

His ruling, 2026-09-18, asked how long her own model should get to think about
background work: *"I don't know, like a while."*

One Ollama queue on a CPU-only 16 GB laptop serves two situations that are
nothing alike: a sentence he is standing in the room waiting for, and a repair
draft nobody is looking at. Measured on this machine, a Node repair DRAFT takes
217-270 s with the queue free and failed at the old single 300 s ceiling
whenever the live Core was also talking to him. So:

- ATTENDED keeps 300 s and is the DEFAULT everywhere,
- BACKGROUND gets 1200 s and has to be asked for by name,
- and conversation still wins: background work in flight is put down at a
  checkpoint the moment a conversation starts waiting.

These hold the three rules that make that safe. The numbers themselves live in
`work_states.LOCAL_CEILING_S` and are not restated here.
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (local_brain, local_lease, local_model_pool,
                      reasoning_gateway, work_states)

ATTENDED = work_states.ATTENDED
BACKGROUND = work_states.BACKGROUND


class TheCeilingIsTheClassOfWork(unittest.TestCase):
    def test_the_two_classes_and_nothing_else(self):
        self.assertEqual(work_states.ATTENTION, {ATTENDED, BACKGROUND})
        with self.assertRaises(ValueError):
            work_states.local_ceiling_s("whenever")

    def test_background_gets_more_time_than_attended(self):
        self.assertGreater(work_states.local_ceiling_s(BACKGROUND),
                           work_states.local_ceiling_s(ATTENDED))

    def test_attended_is_the_ceiling_conversation_always_had(self):
        self.assertEqual(work_states.local_ceiling_s(ATTENDED), 300.0)

    def test_background_is_about_twenty_minutes(self):
        # "like a while", and about four times the longest measured draft.
        self.assertEqual(work_states.local_ceiling_s(BACKGROUND), 1_200.0)

    def test_the_hard_validation_cap_can_express_the_long_one(self):
        # It was 300 s, which made his ruling inexpressible: a background call
        # could not even be constructed.
        self.assertGreaterEqual(local_brain.MAX_TIMEOUT_S,
                                work_states.local_ceiling_s(BACKGROUND))
        local_brain.OllamaConfig(model="m", timeout_s=1_200.0).validated()

    def test_the_cap_is_still_a_cap(self):
        with self.assertRaises(ValueError):
            local_brain.OllamaConfig(model="m", timeout_s=local_brain.MAX_TIMEOUT_S + 1).validated()
        with self.assertRaises(ValueError):
            local_brain.OllamaConfig(model="m", timeout_s=0.1).validated()

    def test_the_gateway_reads_the_same_numbers(self):
        self.assertEqual(reasoning_gateway.local_ceiling_s(ATTENDED),
                         work_states.local_ceiling_s(ATTENDED))
        self.assertEqual(reasoning_gateway.local_ceiling_s(BACKGROUND),
                         work_states.local_ceiling_s(BACKGROUND))
        self.assertEqual(reasoning_gateway.LOCAL_MAX_TIMEOUT_S,
                         work_states.local_ceiling_s(ATTENDED))


class NothingGetsTheLongBudgetByDefault(unittest.TestCase):
    """The opt-in. A caller that does not SAY background is attended."""

    def configured(self, **kwargs) -> local_brain.OllamaConfig:
        with mock.patch.object(local_model_pool.model_pool_config, "resolve",
                               return_value={"model": "qwen3:8b", "think": False}):
            return local_model_pool._config("fast", **kwargs)

    def test_a_big_request_without_the_opt_in_is_cut_to_the_attended_ceiling(self):
        self.assertEqual(self.configured(timeout_s=1_200.0).timeout_s,
                         work_states.local_ceiling_s(ATTENDED))

    def test_the_same_request_with_the_opt_in_keeps_it(self):
        self.assertEqual(
            self.configured(timeout_s=1_200.0, attention=BACKGROUND).timeout_s, 1_200.0)

    def test_background_is_a_ceiling_not_a_floor(self):
        self.assertEqual(self.configured(timeout_s=30.0, attention=BACKGROUND).timeout_s, 30.0)

    def test_an_attention_nobody_recognises_is_refused_rather_than_guessed(self):
        with self.assertRaises(ValueError):
            local_model_pool.run_json("s", "t", attention="eventually")
        with self.assertRaises(ValueError):
            reasoning_gateway.reason_json("s", "t", attention="eventually")

    def test_the_gateway_work_budget_ceiling_follows_the_class(self):
        self.assertEqual(reasoning_gateway.work_budget_ceiling_s(ATTENDED),
                         reasoning_gateway.MAX_WORK_BUDGET_S)
        self.assertGreater(reasoning_gateway.work_budget_ceiling_s(BACKGROUND),
                           reasoning_gateway.work_budget_ceiling_s(ATTENDED))

    def test_an_attended_caller_cannot_claim_a_background_budget(self):
        with self.assertRaises(ValueError) as said:
            reasoning_gateway.reason_json("s", "t", policy="standard", work_budget_s=1_200.0)
        self.assertIn("work budget", str(said.exception))

    def test_the_long_local_slice_reaches_the_pool_only_when_asked_for(self):
        seen = {}

        def fake_auto(system, text, **kwargs):
            seen.update(kwargs)
            raise local_model_pool.LocalPoolUnavailable("not today")

        for attention, expected in ((ATTENDED, 300.0), (BACKGROUND, 1_200.0)):
            budget = reasoning_gateway.work_budget_ceiling_s(attention)
            with mock.patch.object(reasoning_gateway.model_pool_config, "enabled", return_value=True), \
                    mock.patch.object(reasoning_gateway.local_model_pool, "reachable", return_value=True), \
                    mock.patch.object(reasoning_gateway, "_subscription_json",
                                      side_effect=reasoning_gateway.reasoner.ReasonerUnavailable("out")), \
                    mock.patch.object(reasoning_gateway.local_model_pool, "auto_json", side_effect=fake_auto):
                with self.assertRaises(reasoning_gateway.reasoner.ReasonerUnavailable):
                    reasoning_gateway.reason_json("s", "t", policy="standard", attention=attention,
                                                  timeout_s=budget, work_budget_s=budget)
            self.assertEqual(seen["attention"], attention)
            self.assertAlmostEqual(seen["timeout_s"], expected, delta=5.0)

    def test_the_callers_that_opted_in_say_so(self):
        # Rule zero: a capability nothing calls is not a capability. These are
        # the background paths his brief names - repair drafts and reviews,
        # work-session items, program and study drafting.
        from aletheia import local_repair, program_shaping, study_reason, work_runners
        for module in (local_repair, program_shaping, study_reason, work_runners):
            source = Path(module.__file__).read_text(encoding="utf-8")
            self.assertIn("attention=reasoning_gateway.BACKGROUND", source,
                          f"{module.__name__} never asks for the background ceiling")

    def test_a_repair_draft_may_take_about_twenty_minutes(self):
        from aletheia import local_repair
        self.assertEqual(local_repair.WORK_BUDGET_S, work_states.local_ceiling_s(BACKGROUND))


class ConversationStillWins(unittest.TestCase):
    """The lease already puts conversation first. A twenty minute call needs
    more than that: the call ALREADY RUNNING is the one in front of him."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="lease-ceiling-")
        self.patch = mock.patch.dict(os.environ, {local_lease.LEASE_ENV: self.dir})
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_nobody_waiting_is_not_a_yield(self):
        self.assertFalse(local_lease.conversation_waiting())

    def test_a_conversation_waiting_is_seen_by_the_checkpoint(self):
        started = threading.Event()
        let_go = threading.Event()
        seen = {}

        def talk():
            with local_lease.purpose(local_lease.CONVERSATION):
                with local_lease.hold(what="he asked something", max_wait_s=8.0):
                    seen["got_it_after"] = time.monotonic() - seen["work_started"]
                    started.set()

        with local_lease.purpose(local_lease.WORK):
            with local_lease.hold(what="a repair draft", hold_s=1_230.0) as held:
                self.assertTrue(held["held"])
                seen["work_started"] = time.monotonic()
                # Nobody is waiting yet, so the draft carries on.
                self.assertFalse(local_lease.conversation_waiting())
                room = threading.Thread(target=talk, daemon=True)
                room.start()
                # ... and the moment one is, the checkpoint says so.
                deadline = time.monotonic() + 5.0
                while not local_lease.conversation_waiting() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(local_lease.conversation_waiting(),
                                "a waiting conversation was invisible to a long background call")
                let_go.set()
            room.join(timeout=10.0)
        self.assertTrue(started.is_set(), "the conversation never got her own model")
        # It got it within a poll of the draft putting it down, not 20 minutes later.
        self.assertLess(seen["got_it_after"], 5.0)

    def test_a_background_call_is_put_down_at_a_checkpoint(self):
        # A model that would otherwise think for a very long time.
        def slow_stream(config, payload, should_yield):
            return local_brain._stream_chat(config, payload, should_yield)

        calls = {"n": 0}

        def waiting_after_a_moment():
            calls["n"] += 1
            return calls["n"] > 2

        config = local_brain.OllamaConfig(model="m", timeout_s=60.0)
        with mock.patch.object(local_brain.urllib.request, "urlopen", side_effect=_never_answers):
            with self.assertRaises(local_brain.LocalBrainYielded):
                slow_stream(config, {"model": "m", "messages": []}, waiting_after_a_moment)

    def test_a_yield_is_not_a_failure_of_the_work(self):
        self.assertTrue(issubclass(local_model_pool.LocalPoolYielded,
                                   local_model_pool.LocalPoolUnavailable))
        self.assertTrue(issubclass(local_brain.LocalBrainYielded,
                                   local_brain.LocalBrainUnavailable))

    def test_a_yield_never_fails_over_to_the_other_role(self):
        # Failing over would take the queue straight back off him.
        tried = []

        def run(system, text, *, role, **kwargs):
            tried.append(role)
            raise local_model_pool.LocalPoolYielded("he started talking")

        with mock.patch.object(local_model_pool, "run_json", side_effect=run):
            with self.assertRaises(local_model_pool.LocalPoolYielded):
                local_model_pool.auto_json("s", "t", preferred_role="deep", allow_failover=True)
        self.assertEqual(tried, ["deep"])

    def test_only_background_carries_a_checkpoint(self):
        seen = {}

        def fake_infer(system, text, *, context=None, config=None, should_yield=None):
            seen[config.timeout_s] = should_yield
            return {"ok": True}

        with mock.patch.object(local_model_pool, "room_for_role", return_value={"fits": True}), \
                mock.patch.object(local_model_pool.model_pool_config, "enabled", return_value=True), \
                mock.patch.object(local_model_pool.model_pool_config, "resolve",
                                  return_value={"model": "m", "think": False}), \
                mock.patch.object(local_brain, "infer_json", side_effect=fake_infer), \
                mock.patch.object(local_model_pool.training_data, "record_turn", return_value="t"):
            local_model_pool.run_json("s", "t", role="fast", timeout_s=11.0)
            local_model_pool.run_json("s", "t", role="fast", timeout_s=13.0, attention=BACKGROUND)
        self.assertIsNone(seen[11.0])
        self.assertIs(seen[13.0], local_lease.conversation_waiting)


class _Hanging:
    """A response that never sends a line: the prompt-evaluation phase."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        while not self.closed:
            time.sleep(0.05)
        return iter(())

    closed = False

    def close(self):
        self.closed = True


def _never_answers(*args, **kwargs):
    return _Hanging()


if __name__ == "__main__":
    unittest.main()
