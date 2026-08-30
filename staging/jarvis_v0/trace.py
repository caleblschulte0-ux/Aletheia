"""Bounded trace records for explaining what the staged loop did."""
from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any

from .contracts import LoopPhase


@dataclass(frozen=True)
class TraceEvent:
    phase: LoopPhase
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    at: float = field(default_factory=time.time)


class Trace:
    """Small append-only in-memory trace; never touches canonical journal state."""

    def __init__(self, max_events: int = 100) -> None:
        if max_events < 1:
            raise ValueError("max_events must be positive")
        self.max_events = max_events
        self._events: list[TraceEvent] = []

    def add(self, phase: LoopPhase, message: str, **data: Any) -> None:
        self._events.append(TraceEvent(phase=phase, message=message, data=dict(data)))
        if len(self._events) > self.max_events:
            del self._events[: len(self._events) - self.max_events]

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        return tuple(self._events)
