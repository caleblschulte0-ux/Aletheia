"""Side-effect-free scripted providers for end-to-end scenario testing.

Aletheia needs to test orchestration without sending real mail, changing a real
calendar, clicking the desktop, or touching hardware. Scripts are plain data;
there is no eval/exec and an unscripted call fails closed.
"""
from __future__ import annotations

import copy


class SimulationError(RuntimeError):
    pass


class ScriptedProvider:
    """A deterministic fake transport with queued per-operation outcomes."""

    def __init__(self, provider_id: str, scripts: dict[str, list[dict]]):
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError("provider_id is required")
        if not isinstance(scripts, dict):
            raise ValueError("scripts must be an object")
        self.provider_id = provider_id
        self._scripts: dict[str, list[dict]] = {}
        for operation, outcomes in scripts.items():
            if not isinstance(operation, str) or not operation or not isinstance(outcomes, list):
                raise ValueError("simulation operations require list scripts")
            checked = []
            for outcome in outcomes:
                self._validate_outcome(outcome)
                checked.append(copy.deepcopy(outcome))
            self._scripts[operation] = checked
        self.calls: list[dict] = []

    @staticmethod
    def _validate_outcome(outcome: dict) -> None:
        if not isinstance(outcome, dict) or outcome.get("kind") not in {"success", "failure"}:
            raise ValueError("simulation outcome kind must be success or failure")
        allowed = {"kind", "result", "code", "message"}
        unknown = set(outcome) - allowed
        if unknown:
            raise ValueError(f"unknown simulation outcome fields {sorted(unknown)}")
        if outcome["kind"] == "failure" and (not isinstance(outcome.get("code"), str) or not outcome["code"]):
            raise ValueError("failure outcome requires code")

    def remaining(self, operation: str) -> int:
        return len(self._scripts.get(operation, []))

    def call(self, operation: str, payload: dict | None = None) -> dict:
        if not isinstance(operation, str) or not operation:
            raise ValueError("operation is required")
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        queue = self._scripts.get(operation)
        if not queue:
            raise SimulationError(f"unscripted simulated call {self.provider_id}.{operation}")
        outcome = queue.pop(0)
        self.calls.append({"operation": operation, "payload": copy.deepcopy(payload or {}),
                           "outcome": copy.deepcopy(outcome)})
        return copy.deepcopy(outcome)


def run_steps(provider: ScriptedProvider, steps: list[dict], *, stop_on_failure: bool = True) -> dict:
    """Run data-only simulated operations. No real capability is invoked."""
    if not isinstance(steps, list):
        raise ValueError("steps must be a list")
    results = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or set(step) - {"operation", "payload"}:
            raise ValueError(f"invalid simulation step {index}")
        outcome = provider.call(step.get("operation", ""), step.get("payload", {}))
        results.append({"index": index, "operation": step["operation"], "outcome": outcome})
        if stop_on_failure and outcome["kind"] == "failure":
            return {"completed": False, "results": results, "stopped_at": index}
    return {"completed": True, "results": results}
