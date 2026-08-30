"""Ephemeral memory model for staging.

This deliberately does not read or write ``memory/`` or ``state/``.  It gives
the orchestration loop a realistic recall/propose/commit seam while keeping all
experiments disposable.
"""
from __future__ import annotations

from collections import deque
from typing import Sequence

from .contracts import ActionReceipt, Intent, MemoryCandidate, Observation, Plan


def _tokens(text: str) -> set[str]:
    return {piece for piece in "".join(
        char.lower() if char.isalnum() else " " for char in text
    ).split() if len(piece) > 2}


class EphemeralMemory:
    def __init__(self, *, max_items: int = 200) -> None:
        if max_items < 1:
            raise ValueError("max_items must be positive")
        self.max_items = max_items
        self._items: deque[MemoryCandidate] = deque(maxlen=max_items)

    def recall(self, utterance: str, *, limit: int = 8) -> Sequence[MemoryCandidate]:
        if limit < 1:
            return ()
        query = _tokens(utterance)
        scored: list[tuple[int, int, MemoryCandidate]] = []
        for recency, item in enumerate(reversed(self._items)):
            haystack = _tokens(f"{item.kind} {item.key} {item.value}")
            overlap = len(query & haystack)
            if overlap:
                scored.append((overlap, -recency, item))
        scored.sort(reverse=True, key=lambda row: (row[0], row[1]))
        return tuple(item for _, _, item in scored[:limit])

    def propose(
        self,
        intent: Intent,
        plan: Plan,
        receipts: Sequence[ActionReceipt],
        final_observations: Sequence[Observation],
    ) -> Sequence[MemoryCandidate]:
        if not receipts:
            return ()
        return (
            MemoryCandidate(
                kind="episode",
                key=f"verified-plan:{plan.plan_id}",
                value={
                    "goal": intent.goal,
                    "capabilities": [receipt.capability for receipt in receipts],
                    "verified": True,
                },
                provenance="jarvis-v0 verified action loop",
                confidence=1.0,
            ),
        )

    def commit(self, candidates: Sequence[MemoryCandidate]) -> None:
        for candidate in candidates:
            self._items.append(candidate)

    @property
    def items(self) -> tuple[MemoryCandidate, ...]:
        return tuple(self._items)
