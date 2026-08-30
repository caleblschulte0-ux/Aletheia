"""Staging capability catalog.

The reasoner may name only capabilities present in this catalog.  The catalog is
metadata only; it contains no callable and therefore grants no authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .contracts import Plan, RiskLevel


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    risk: RiskLevel
    requires_verification: bool = True
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("capability name is required")


class CapabilityCatalog:
    def __init__(self, specs: Iterable[CapabilitySpec] = ()) -> None:
        self._specs: dict[str, CapabilitySpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: CapabilitySpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"duplicate capability: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> CapabilitySpec | None:
        return self._specs.get(name)

    def validate_plan(self, plan: Plan) -> list[str]:
        problems: list[str] = []
        for index, step in enumerate(plan.steps):
            spec = self.get(step.capability)
            if spec is None:
                problems.append(f"steps[{index}]: unknown capability {step.capability!r}")
                continue
            if step.risk != spec.risk:
                problems.append(
                    f"steps[{index}]: risk {step.risk.value!r} does not match "
                    f"catalog risk {spec.risk.value!r}"
                )
            if spec.requires_verification and not step.expected_observation.strip():
                problems.append(
                    f"steps[{index}]: {step.capability!r} requires expected verification evidence"
                )
        return problems

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))
