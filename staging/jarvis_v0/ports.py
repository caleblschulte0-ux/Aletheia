"""Dependency-injection ports for the isolated Jarvis loop."""
from __future__ import annotations

from typing import Protocol, Sequence

from .contracts import (
    ActionReceipt,
    ActionStep,
    Intent,
    MemoryCandidate,
    Observation,
    Plan,
)


class PerceptionPort(Protocol):
    def observe(self, utterance: str) -> Sequence[Observation]:
        """Return current bounded observations relevant to this turn."""


class ReasoningPort(Protocol):
    def understand(
        self, utterance: str, observations: Sequence[Observation], memories: Sequence[MemoryCandidate]
    ) -> Intent:
        """Convert the operator turn and context into an explicit goal."""

    def plan(
        self, intent: Intent, observations: Sequence[Observation], memories: Sequence[MemoryCandidate]
    ) -> Plan:
        """Return a typed plan.  Empty steps means the turn needs no action."""


class AuthorityPort(Protocol):
    def authorize(self, plan: Plan) -> tuple[bool, str]:
        """Approve/refuse exactly this plan and explain the decision."""


class ActionPort(Protocol):
    def execute(self, step: ActionStep, *, plan_id: str) -> ActionReceipt:
        """Execute one already-authorized step and return evidence."""


class VerificationPort(Protocol):
    def verify(
        self,
        step: ActionStep,
        receipt: ActionReceipt,
        *,
        before: Sequence[Observation],
    ) -> tuple[bool, str, Sequence[Observation]]:
        """Verify the requested effect and optionally return fresh observations."""


class MemoryPort(Protocol):
    def recall(self, utterance: str, *, limit: int = 8) -> Sequence[MemoryCandidate]:
        """Retrieve a bounded set of relevant memories."""

    def propose(
        self,
        intent: Intent,
        plan: Plan,
        receipts: Sequence[ActionReceipt],
        final_observations: Sequence[Observation],
    ) -> Sequence[MemoryCandidate]:
        """Create memory candidates from a completed turn without persisting them."""

    def commit(self, candidates: Sequence[MemoryCandidate]) -> None:
        """Persist only already-approved memory candidates."""


class VoicePort(Protocol):
    def say(self, text: str) -> None:
        """Speak or otherwise surface a sentence to the operator."""
