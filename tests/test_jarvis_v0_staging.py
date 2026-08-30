"""Hermetic tests for the disconnected Jarvis staging package."""
from __future__ import annotations

import unittest

from staging.jarvis_v0.contracts import (
    ActionStep,
    LoopOutcome,
    Observation,
    Plan,
    RiskLevel,
)
from staging.jarvis_v0.fakes import (
    RecordingActions,
    RecordingVoice,
    ScriptedReasoner,
    StaticAuthority,
    StaticPerception,
    StaticVerification,
    demo_plan,
)
from staging.jarvis_v0.loop import JarvisLoop
from staging.jarvis_v0.memory import EphemeralMemory
from staging.jarvis_v0.perception import PerceptionHub, SensorSpec
from staging.jarvis_v0.supervisor import SupervisorModel
from staging.jarvis_v0.voice_contract import VoiceSession, VoiceState


class JarvisLoopTests(unittest.TestCase):
    def make_loop(self, *, allowed=True, fail_action=None, fail_verify=None, plan=None):
        actions = RecordingActions(fail_capability=fail_action)
        authority = StaticAuthority(allowed=allowed, reason="operator said no")
        verification = StaticVerification(fail_capability=fail_verify)
        memory = EphemeralMemory()
        voice = RecordingVoice()
        loop = JarvisLoop(
            perception=StaticPerception(),
            reasoning=ScriptedReasoner(plan or demo_plan()),
            authority=authority,
            actions=actions,
            verification=verification,
            memory=memory,
            voice=voice,
        )
        return loop, actions, authority, verification, memory, voice

    def test_authorized_plan_executes_and_verifies_in_order(self):
        loop, actions, authority, verification, memory, voice = self.make_loop()
        result = loop.run("Open Barkly")
        self.assertEqual(result.outcome, LoopOutcome.COMPLETE)
        self.assertEqual(
            [step.capability for _, step in actions.executed],
            ["computer.open_app", "browser.read"],
        )
        self.assertEqual(verification.checked, ["computer.open_app", "browser.read"])
        self.assertEqual(len(authority.seen), 1)
        self.assertEqual(len(memory.items), 1)
        self.assertEqual(voice.spoken[-1], result.summary)

    def test_refused_plan_never_reaches_action_adapter(self):
        loop, actions, *_ = self.make_loop(allowed=False)
        result = loop.run("Open Barkly")
        self.assertEqual(result.outcome, LoopOutcome.REFUSED)
        self.assertEqual(actions.executed, [])

    def test_failed_action_stops_before_later_steps(self):
        loop, actions, _, verification, *_ = self.make_loop(
            fail_action="computer.open_app"
        )
        result = loop.run("Open Barkly")
        self.assertEqual(result.outcome, LoopOutcome.FAILED)
        self.assertEqual(len(actions.executed), 1)
        self.assertEqual(verification.checked, [])

    def test_failed_verification_stops_before_later_steps_and_memory(self):
        loop, actions, _, verification, memory, _ = self.make_loop(
            fail_verify="computer.open_app"
        )
        result = loop.run("Open Barkly")
        self.assertEqual(result.outcome, LoopOutcome.FAILED)
        self.assertEqual(len(actions.executed), 1)
        self.assertEqual(verification.checked, ["computer.open_app"])
        self.assertEqual(memory.items, ())

    def test_empty_plan_is_no_action(self):
        plan = Plan(goal="answer a question", steps=(), rationale="Answer only.")
        loop, actions, *_ = self.make_loop(plan=plan)
        result = loop.run("What time is it?")
        self.assertEqual(result.outcome, LoopOutcome.NO_ACTION)
        self.assertEqual(actions.executed, [])

    def test_step_budget_fails_closed(self):
        steps = tuple(
            ActionStep(capability=f"read.{index}", risk=RiskLevel.READ_ONLY)
            for index in range(3)
        )
        loop, actions, authority, *_ = self.make_loop(
            plan=Plan(goal="too many", steps=steps)
        )
        loop.max_steps = 2
        result = loop.run("do a lot")
        self.assertEqual(result.outcome, LoopOutcome.FAILED)
        self.assertEqual(actions.executed, [])
        self.assertEqual(authority.seen, [])


class VoiceContractTests(unittest.TestCase):
    def test_wake_word_starts_followup_window(self):
        session = VoiceSession(followup_window_s=10)
        self.assertEqual(session.accept("Thea open Barkly", now=100), "open Barkly")
        self.assertEqual(session.state, VoiceState.THINKING)
        self.assertEqual(session.accept("and check the build", now=105), "and check the build")
        self.assertIsNone(session.accept("random room speech", now=116))

    def test_bare_wake_word_listens(self):
        session = VoiceSession()
        self.assertEqual(session.accept("Thea", now=100), "")
        self.assertEqual(session.state, VoiceState.LISTENING)


class PerceptionHubTests(unittest.TestCase):
    def test_optional_sensor_failure_does_not_hide_required_sensor(self):
        good = Observation(source="uia", kind="window", payload={"title": "Barkly"})

        def broken(_):
            raise RuntimeError("camera unplugged")

        hub = PerceptionHub(
            (
                SensorSpec("camera", broken, optional=True),
                SensorSpec("uia", lambda _: (good,), optional=False),
            )
        )
        self.assertEqual(hub.observe("look"), (good,))


class SupervisorTests(unittest.TestCase):
    def test_critical_stale_component_recommends_restart(self):
        supervisor = SupervisorModel(stale_after_s=10)
        core = supervisor.register("core", critical=True)
        core.beat(now=100)
        self.assertFalse(supervisor.snapshot(now=105)["core"]["restart_recommended"])
        self.assertTrue(supervisor.snapshot(now=111)["core"]["restart_recommended"])


if __name__ == "__main__":
    unittest.main()
