"""Typed contracts for the isolated Jarvis orchestration loop.

These objects intentionally contain no Aletheia production imports.  They are
the proposed seam between perception, reasoning, authority, action,
verification, memory, and voice.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time
import uuid
from typing import Any


class RiskLevel(str, Enum):
    """How much authority an action step needs."""

    READ_ONLY = "read_only"
    LOW = "low"
    SENSITIVE = "sensitive"
    DESTRUCTIVE = "destructive"


class LoopPhase(str, Enum):
    IDLE = "idle"
    OBSERVING = "observing"
    UNDERSTANDING = "understanding"
    PLANNING = "planning"
    AWAITING_AUTHORITY = "awaiting_authority"
    ACTING = "acting"
    VERIFYING = "verifying"
    REMEMBERING = "remembering"
    COMPLETE = "complete"
    REFUSED = "refused"
    FAILED = "failed"


class LoopOutcome(str, Enum):
    COMPLETE = "complete"
    REFUSED = "refused"
    FAILED = "failed"
    NO_ACTION = "no_action"


@dataclass(frozen=True)
class Observation:
    source: str
    kind: str
    payload: dict[str, Any]
    confidence: float = 1.0
    observed_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("observation source is required")
        if not self.kind.strip():
            raise ValueError("observation kind is required")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("observation confidence must be between 0 and 1")


@dataclass(frozen=True)
class Intent:
    utterance: str
    goal: str
    context_refs: tuple[str, ...] = ()
    urgency: str = "normal"

    def __post_init__(self) -> None:
        if not self.utterance.strip():
            raise ValueError("intent utterance is required")
        if not self.goal.strip():
            raise ValueError("intent goal is required")


@dataclass(frozen=True)
class ActionStep:
    capability: str
    arguments: dict[str, Any] = field(default_factory=dict)
    expected_observation: str = ""
    risk: RiskLevel = RiskLevel.READ_ONLY
    reversible: bool = True

    def __post_init__(self) -> None:
        if not self.capability.strip():
            raise ValueError("action capability is required")


@dataclass(frozen=True)
class Plan:
    goal: str
    steps: tuple[ActionStep, ...]
    rationale: str = ""
    plan_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        if not self.goal.strip():
            raise ValueError("plan goal is required")
        if not self.plan_id.strip():
            raise ValueError("plan id is required")

    @property
    def highest_risk(self) -> RiskLevel:
        order = {
            RiskLevel.READ_ONLY: 0,
            RiskLevel.LOW: 1,
            RiskLevel.SENSITIVE: 2,
            RiskLevel.DESTRUCTIVE: 3,
        }
        return max((step.risk for step in self.steps),
                   key=lambda value: order[value],
                   default=RiskLevel.READ_ONLY)


@dataclass(frozen=True)
class ActionReceipt:
    capability: str
    ok: bool
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    action_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        if not self.capability.strip():
            raise ValueError("receipt capability is required")
        if not self.ok and not (self.error or "").strip():
            raise ValueError("failed receipt requires an error")


@dataclass(frozen=True)
class MemoryCandidate:
    kind: str
    key: str
    value: Any
    provenance: str
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not self.kind.strip() or not self.key.strip():
            raise ValueError("memory kind and key are required")
        if not self.provenance.strip():
            raise ValueError("memory provenance is required")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("memory confidence must be between 0 and 1")
