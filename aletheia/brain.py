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


class BrainOutputError(ValueError):
    pass


def validate_output(value: dict) -> dict:
    if not isinstance(value, dict):
        raise BrainOutputError("brain output must be an object")
    allowed = {"intent", "summary", "command", "required_capabilities", "references", "confidence"}
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
