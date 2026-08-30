"""Hermetic adapters for exercising the staged loop."""
from __future__ import annotations

from typing import Sequence

from .contracts import (
    ActionReceipt,
    ActionStep,
    Intent,
    MemoryCandidate,
    Observation,
    Plan,
    RiskLevel,
)
from .memory import EphemeralMemory


class StaticPerception:
    def __init__(self, observations: Sequence[Observation] = ()) -> None:
        self.observations = tuple(observations)

    def observe(self, utterance: str) -> Sequence[Observation]:
        return self.observations


class ScriptedReasoner:
    def __init__(self, plan: Plan | None = None) -> None:
        self._plan = plan

    def understand(
        self, utterance: str, observations: Sequence[Observation], memories: Sequence[MemoryCandidate]
    ) -> Intent:
        return Intent(utterance=utterance, goal=utterance.strip())

    def plan(
        self, intent: Intent, observations: Sequence[Observation], memories: Sequence[MemoryCandidate]
    ) -> Plan:
        return self._plan or Plan(
            goal=intent.goal,
            rationale="Nothing to do in the staging demo.",
            steps=(),
        )


class StaticAuthority:
    def __init__(self, allowed: bool = True, reason: str = "staging authorization granted") -> None:
        self.allowed = allowed
        self.reason = reason
        self.seen: list[Plan] = []

    def authorize(self, plan: Plan) -> tuple[bool, str]:
        self.seen.append(plan)
        return self.allowed, self.reason


class RecordingActions:
    def __init__(self, *, fail_capability: str | None = None) -> None:
        self.fail_capability = fail_capability
        self.executed: list[tuple[str, ActionStep]] = []

    def execute(self, step: ActionStep, *, plan_id: str) -> ActionReceipt:
        self.executed.append((plan_id, step))
        if step.capability == self.fail_capability:
            return ActionReceipt(
                capability=step.capability,
                ok=False,
                error="scripted staging failure",
            )
        return ActionReceipt(
            capability=step.capability,
            ok=True,
            evidence={"simulated": True, "arguments": step.arguments},
        )


class StaticVerification:
    def __init__(self, *, fail_capability: str | None = None) -> None:
        self.fail_capability = fail_capability
        self.checked: list[str] = []

    def verify(
        self,
        step: ActionStep,
        receipt: ActionReceipt,
        *,
        before: Sequence[Observation],
    ) -> tuple[bool, str, Sequence[Observation]]:
        self.checked.append(step.capability)
        if step.capability == self.fail_capability:
            return False, "scripted verification failure", before
        return True, "verified in staging", before


class RecordingVoice:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    def say(self, text: str) -> None:
        self.spoken.append(text)


def demo_plan() -> Plan:
    return Plan(
        goal="Open the Barkly project and inspect its current state",
        rationale="Simulated only: open, inspect, then report.",
        steps=(
            ActionStep(
                capability="computer.open_app",
                arguments={"app": "browser"},
                expected_observation="browser window exists",
                risk=RiskLevel.LOW,
            ),
            ActionStep(
                capability="browser.read",
                arguments={"target": "Barkly"},
                expected_observation="project page is readable",
                risk=RiskLevel.READ_ONLY,
            ),
        ),
    )


def demo_stack(*, allowed: bool = True):
    return {
        "perception": StaticPerception(),
        "reasoning": ScriptedReasoner(demo_plan()),
        "authority": StaticAuthority(allowed=allowed),
        "actions": RecordingActions(),
        "verification": StaticVerification(),
        "memory": EphemeralMemory(),
        "voice": RecordingVoice(),
    }
