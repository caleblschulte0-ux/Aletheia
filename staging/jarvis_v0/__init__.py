"""Jarvis-style orchestration staging area.

This package is intentionally disconnected from ``aletheia.core``.  It exists
to make the observe -> understand -> plan -> authorize -> act -> verify ->
remember loop concrete and testable before any production integration.
"""

from .contracts import (
    ActionReceipt,
    ActionStep,
    Intent,
    LoopOutcome,
    LoopPhase,
    MemoryCandidate,
    Observation,
    Plan,
    RiskLevel,
)
from .loop import JarvisLoop, LoopResult

__all__ = [
    "ActionReceipt",
    "ActionStep",
    "Intent",
    "JarvisLoop",
    "LoopOutcome",
    "LoopPhase",
    "LoopResult",
    "MemoryCandidate",
    "Observation",
    "Plan",
    "RiskLevel",
]
