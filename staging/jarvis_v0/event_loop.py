"""Pure proactive-event proposal engine.

This is the staging answer to "Jarvis notices things first."  It evaluates
structured events and produces proposals only.  It cannot execute actions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Callable, Sequence

from .contracts import RiskLevel


@dataclass(frozen=True)
class SystemEvent:
    topic: str
    payload: dict[str, Any]
    source: str
    at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ProactiveProposal:
    rule_id: str
    summary: str
    suggested_capability: str | None = None
    suggested_arguments: dict[str, Any] = field(default_factory=dict)
    risk: RiskLevel = RiskLevel.READ_ONLY


Predicate = Callable[[SystemEvent], bool]
Builder = Callable[[SystemEvent], ProactiveProposal]


@dataclass(frozen=True)
class EventRule:
    rule_id: str
    topic: str
    when: Predicate
    build: Builder
    cooldown_s: float = 300.0


class ProactiveEngine:
    """Evaluates events, dedupes rules, and emits no side effects."""

    def __init__(self, rules: Sequence[EventRule]) -> None:
        self.rules = tuple(rules)
        self._last_fired: dict[str, float] = {}

    def evaluate(
        self, event: SystemEvent, *, now: float | None = None
    ) -> tuple[ProactiveProposal, ...]:
        now = event.at if now is None else now
        proposals: list[ProactiveProposal] = []
        for rule in self.rules:
            if rule.topic != event.topic:
                continue
            last = self._last_fired.get(rule.rule_id)
            if last is not None and now - last < rule.cooldown_s:
                continue
            if not rule.when(event):
                continue
            proposal = rule.build(event)
            if proposal.rule_id != rule.rule_id:
                raise ValueError("proposal rule_id must match originating rule")
            proposals.append(proposal)
            self._last_fired[rule.rule_id] = now
        return tuple(proposals)
