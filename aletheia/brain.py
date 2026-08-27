"""Model-independent reasoning contract.

Aletheia's orchestration/policy/state are the system; an LLM is a replaceable
reasoning provider. This module defines the narrow output contract a future
ChatGPT, Claude, local model, or trained model adapter must satisfy before its
proposal can reach deterministic planners/gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

ALLOWED_INTENTS = {"answer", "command", "plan", "clarify", "gap"}
MAX_TEXT = 16_000
# A plan long enough to be useful and short enough to read before it runs.
# Unbounded step lists are how a reasoning provider turns one sentence into
# an afternoon of unreviewed actions.
MAX_STEPS = 12
STEP_KEYS = {"kind", "gap", "manual"}


class BrainOutputError(ValueError):
    pass


def validate_output(value: dict) -> dict:
    if not isinstance(value, dict):
        raise BrainOutputError("brain output must be an object")
    allowed = {"intent", "summary", "command", "steps", "required_capabilities",
               "references", "confidence"}
    unknown = set(value) - allowed
    if unknown:
        raise BrainOutputError(f"brain output has unknown fields {sorted(unknown)}")
    if value.get("intent") not in ALLOWED_INTENTS:
        raise BrainOutputError("invalid brain intent")
    summary = value.get("summary", "")
    if not isinstance(summary, str) or len(summary) > MAX_TEXT:
        raise BrainOutputError("summary must be bounded text")
    if "command" in value and not isinstance(value["command"], dict):
        raise BrainOutputError("command must be an object")
    if "steps" in value:
        _validate_steps(value["steps"])
    caps = value.get("required_capabilities", [])
    if not isinstance(caps, list) or any(not isinstance(x, str) or not x for x in caps):
        raise BrainOutputError("required_capabilities must be capability ids")
    refs = value.get("references", [])
    if not isinstance(refs, list) or any(not isinstance(x, str) or not x for x in refs):
        raise BrainOutputError("references must be strings")
    confidence = value.get("confidence")
    if confidence is not None and (not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1):
        raise BrainOutputError("confidence must be 0..1")
    return value


def _validate_steps(steps) -> list[dict]:
    """A proposed multi-step plan, structurally only.

    Structure is ALL this checks. Whether `kind` names a real command,
    whether its args are right, whether the operator has authorized it —
    none of that is knowable here and none of it is trusted from a model.
    `aletheia.planner` puts every step through `intercom.validate_kind_args`
    and the policy gates before anything can execute (§70).
    """
    if not isinstance(steps, list):
        raise BrainOutputError("steps must be a list")
    if len(steps) > MAX_STEPS:
        raise BrainOutputError(f"steps: at most {MAX_STEPS}, got {len(steps)}")
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise BrainOutputError(f"step {i} must be an object")
        present = STEP_KEYS & set(step)
        if len(present) != 1:
            raise BrainOutputError(
                f"step {i} must have exactly one of {sorted(STEP_KEYS)}, "
                f"got {sorted(present)}")
        for key, val in step.items():
            if isinstance(val, str) and len(val) > MAX_TEXT:
                raise BrainOutputError(f"step {i}: {key} is unbounded text")
    return steps


@dataclass(frozen=True)
class Provider:
    id: str
    infer: Callable[[str, dict], dict]

    def run(self, text: str, context: dict | None = None) -> dict:
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            raise ValueError("input text must be non-empty and bounded")
        result = self.infer(text, context or {})
        return validate_output(result)


def deterministic(text: str, context: dict | None = None) -> dict:
    """Safe fallback provider: does not pretend to understand arbitrary intent."""
    del context
    return {"intent": "clarify", "summary": f"No reasoning provider interpreted: {text[:200]}",
            "required_capabilities": [], "references": [], "confidence": 0.0}


FALLBACK = Provider("aletheia.deterministic", deterministic)
