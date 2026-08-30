"""Deterministic evidence rules for staged action verification.

No language model is allowed to declare its own action successful.  Rules consume
adapter receipts and structured observations.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .contracts import ActionReceipt, ActionStep, Observation


class EvidenceRule:
    def check(
        self,
        step: ActionStep,
        receipt: ActionReceipt,
        observations: Sequence[Observation],
    ) -> tuple[bool, str]:
        raise NotImplementedError


@dataclass(frozen=True)
class ReceiptFieldEquals(EvidenceRule):
    field: str
    expected: Any

    def check(
        self,
        step: ActionStep,
        receipt: ActionReceipt,
        observations: Sequence[Observation],
    ) -> tuple[bool, str]:
        actual = receipt.evidence.get(self.field)
        ok = actual == self.expected
        return ok, (
            f"receipt evidence {self.field} matched"
            if ok
            else f"receipt evidence {self.field}={actual!r}, expected {self.expected!r}"
        )


@dataclass(frozen=True)
class ObservationFieldEquals(EvidenceRule):
    kind: str
    field: str
    expected: Any
    source: str | None = None

    def check(
        self,
        step: ActionStep,
        receipt: ActionReceipt,
        observations: Sequence[Observation],
    ) -> tuple[bool, str]:
        for observation in observations:
            if observation.kind != self.kind:
                continue
            if self.source is not None and observation.source != self.source:
                continue
            if observation.payload.get(self.field) == self.expected:
                return True, "structured observation matched"
        return False, (
            f"no observation matched kind={self.kind!r} source={self.source!r} "
            f"{self.field}={self.expected!r}"
        )


class RuleVerifier:
    """VerificationPort backed by explicit per-capability rules."""

    def __init__(self, rules: dict[str, EvidenceRule], *, observer=None) -> None:
        self.rules = dict(rules)
        self.observer = observer

    def verify(
        self,
        step: ActionStep,
        receipt: ActionReceipt,
        *,
        before: Sequence[Observation],
    ) -> tuple[bool, str, Sequence[Observation]]:
        fresh = tuple(self.observer(step) if self.observer else before)
        rule = self.rules.get(step.capability)
        if rule is None:
            return False, f"no deterministic verification rule for {step.capability}", fresh
        ok, reason = rule.check(step, receipt, fresh)
        return ok, reason, fresh
